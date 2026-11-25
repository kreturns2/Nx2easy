"""A game dump in the NUP container ("NX Package", github.com/a55uka/nup: a public, unencrypted container of a game's loose files,
each compressed on its own with zstd), read for a port: what it holds, and its files written out.

    python tools/nup.py info <file.nup>                      the packages in it, and each one's folders
    python tools/nup.py list <file.nup> [package] [folder]   the files of a package (0 by default) under a folder ("exefs", "romfs/...")
    python tools/nup.py extract <file.nup> <out> [package] [folder]   those files, written under <out>
    python tools/nup.py romfs <file.nup> <package> <to> [--parts]
                                                             the package's romfs folder as one RomFS image, as a port reads it:
                                                             to a file, or to a console (ftp://host:port/nx2-relink/<name>/romfs.bin, or
                                                             ttx://host/nx2-relink/<name>/romfs.bin with Toronja Transfer open on it);
                                                             --parts: in 2 GB parts if it is 4 GB or more (a FAT32 card)

A port is made from a container by tools/game2.py (tools/build.py and nxrelink.py call it), which reads a folder of loose files as well
and lays a game's updates over it.

The layout (all little-endian): a superblock of 0x80 bytes ("NUP\\x01", where the table of contents is and how long, where the
files' bytes begin, how many packages); the table of contents ("TOC\\x01": packages of 0x40 bytes, folders of 0x18, files of
0x50, a list of each folder's children, the names); then the files' bytes. A package: its title's number, its root folder, its
exefs and romfs folders, its version, its kind (0 the game, 1 an update, 2 added content), and a block of facts about it.
"""
import hashlib
import os
import struct
import sys

try:
    import zstandard
except ImportError:  # (Python 3.14 has it in its own library)
    zstandard = None

KINDS = {0: 'the game', 1: 'an update', 2: 'added content'}
# A package's facts, in their order. They are numbered from 0 in one container seen (0 an NPDM, 6 a build id's 32 bytes, 7 the
# dump's name) and from 1 in another (1 an NPDM, 3 a JPEG, 4 "1.1.1", 5 the title, 8 the dump's name): two versions of what makes
# them. Which it is, is told by where the NPDM is (Nup.facts).
FACTS = ['NPDM', 'NACP', 'icon', 'display version', 'title', 'publisher', 'build id', 'dump name', 'titles by language', 'icons by language']


class Nup:
    def __init__(self, path):
        self.f = open(path, 'rb')
        head = self.f.read(0x80)
        if head[:4] != b'NUP\x01':
            raise SystemExit(f'{path} isn\'t a NUP container')
        self.toc_at, self.toc_size = struct.unpack_from('<QQ', head, 8)
        self.blob_at, self.size, self.npackages = struct.unpack_from('<QQI', head, 0x38)
        self.f.seek(self.toc_at)
        toc = self.f.read(self.toc_size)
        if toc[:4] != b'TOC\x01':
            raise SystemExit('its table of contents isn\'t one this reads')
        if hashlib.sha256(toc).digest() != head[0x18:0x38]:
            print('  (the table of contents doesn\'t match the sum the file gives for it)')
        n, self.ndirs, self.nfiles, pool_at, pool_size = struct.unpack_from('<IQQQQ', toc, 4)
        at = 0x30
        self.packages = []
        for k in range(n):
            title, root, exefs, romfs, version, kind, flags = struct.unpack_from('<QIIIIBB', toc, at)
            meta_at, meta_size = struct.unpack_from('<QI', toc, at + 0x20)
            self.packages.append(dict(title=title, root=root, exefs=exefs, romfs=romfs, version=version, kind=kind, flags=flags, meta_at=meta_at, meta_size=meta_size))
            at += 0x40
        self.dirs = [struct.unpack_from('<IIII', toc, at + 0x18 * k) for k in range(self.ndirs)]
        at += 0x18 * self.ndirs
        self.files_at, self.toc = at, toc
        at += 0x50 * self.nfiles
        self.children_at = at
        self.pool = toc[pool_at:pool_at + pool_size]

    def name(self, off, length):
        return self.pool[off:off + length].decode('utf-8', 'replace')

    def file(self, k):
        """(its name, its size, where its bytes are, how many are kept, its sum, how they are kept: 0 as they are, 1 zstd)"""
        name_off, name_len, size, at, kept = struct.unpack_from('<IIQQQ', self.toc, self.files_at + 0x50 * k)
        digest = self.toc[self.files_at + 0x50 * k + 0x20:self.files_at + 0x50 * k + 0x40]
        return self.name(name_off, name_len), size, at, kept, digest, self.toc[self.files_at + 0x50 * k + 0x40]

    def walk(self, d, path=''):
        """Every file under a folder: (its path from there, its number)."""
        _, _, first, count = self.dirs[d]
        for node in struct.unpack_from(f'<{count}I', self.toc, self.children_at + 4 * first):
            if node < self.ndirs:
                name_off, name_len, _, _ = self.dirs[node]
                yield from self.walk(node, f'{path}{self.name(name_off, name_len)}/')
            else:
                yield path + self.file(node - self.ndirs)[0], node - self.ndirs

    def folder(self, package, sub):
        """The folder of a package that a path names ('' its root)."""
        d = self.packages[package]['root']
        for part in [x for x in sub.replace('\\', '/').split('/') if x]:
            _, _, first, count = self.dirs[d]
            for node in struct.unpack_from(f'<{count}I', self.toc, self.children_at + 4 * first):
                if node < self.ndirs and self.name(*self.dirs[node][:2]) == part:
                    d = node
                    break
            else:
                raise SystemExit(f'no folder "{part}" there')
        return d

    def read(self, k):
        name, size, at, kept, digest, codec = self.file(k)
        self.f.seek(at)
        data = self.f.read(kept)
        if codec == 1:
            if not zstandard:
                raise SystemExit('this file is compressed with zstd: pip install zstandard')
            data = zstandard.ZstdDecompressor().decompress(data, max_output_size=size)
        elif codec:
            raise SystemExit(f'{name} is kept in a way this doesn\'t read ({codec})')
        return data

    def facts(self, package):
        """A package's facts by name (FACTS): {'title': b'...', 'icon': b'...', ...}."""
        if not hasattr(self, 'first_fact'):
            # the number the facts begin at: the one an NPDM has, in any package of this container (0 if none has one)
            self.first_fact = next((kind for k in range(len(self.packages)) for kind, v in self.meta(k).items() if v[:4] == b'META'), 0)
        return {FACTS[kind - self.first_fact]: v for kind, v in self.meta(package).items() if 0 <= kind - self.first_fact < len(FACTS)}

    def meta(self, package):
        p = self.packages[package]
        self.f.seek(p['meta_at'])
        block, at, out = self.f.read(p['meta_size']), 0, {}
        while at + 8 <= len(block):
            kind, _, size = struct.unpack_from('<HHI', block, at)
            out[kind] = block[at + 8:at + 8 + size]
            at += 8 + size
        return out


def name_hash(parent, name):
    h = parent ^ 123456789
    for c in name:
        h = ((h >> 5) | (h << 27)) & 0xFFFFFFFF
        h ^= c
    return h


def buckets(n):
    if n < 3:
        return 3
    if n < 19:
        return n | 1
    while any(n % p == 0 for p in (2, 3, 5, 7, 11, 13, 17)):
        n += 1
    return n


def package_files(nup, package):
    """A package's romfs folder as RomFS takes files: {path: (size, a function that gives the file's bytes, in pieces)}."""
    root = nup.packages[package]['romfs']
    if root == 0xFFFFFFFF:
        raise SystemExit('that package has no romfs folder')
    return {path: (nup.file(i)[1], lambda i=i: (nup.read(i),)) for path, i in nup.walk(root)}


class RomFS:
    """Loose files as one RomFS image, made as it is read: the header, the files' bytes (each at a multiple of 16), then the four
    tables (folders and files by hash, and their entries). Its size is known before a byte of a file is read, so it can be sent to
    a console without being written here first.
    files: {path, its parts joined by "/": (size, a function that gives the file's bytes in pieces)}, from a container's package
    (package_files) or from folders of this computer, one set laid over another (tools/game2.py)."""
    NONE = 0xFFFFFFFF

    def __init__(self, files):
        tree = {}
        for path, entry in files.items():
            d = tree
            parts = path.split('/')
            for p in parts[:-1]:
                d = d.setdefault(p, {})
                if not isinstance(d, dict):
                    raise SystemExit(f'{path}: a file and a folder have the same name there')
            d[parts[-1]] = entry
        # folders in the order met: [name, parent's number, its folders, its files (name, (size, its bytes' function))]
        folders, at = [[b'', 0, [], []]], 0
        todo = [(tree, 0)]
        while todo:
            d, mine = todo.pop(0)
            for name in sorted(d):
                if isinstance(d[name], dict):
                    folders.append([name.encode(), mine, [], []])
                    folders[mine][2].append(len(folders) - 1)
                    todo.append((d[name], len(folders) - 1))
                else:
                    folders[mine][3].append((name.encode(), d[name]))
        pad4 = lambda n: (n + 3) & ~3  # noqa: E731
        folder_at, at = [], 0
        for f in folders:
            folder_at.append(at)
            at += 0x18 + pad4(len(f[0]))
        folders_size = at
        self.order, file_at, at, data = [], {}, 0, 0  # the files in the image's order: ((size, bytes' function), offset in the data, size, name)
        for k, f in enumerate(folders):
            for name, i in f[3]:
                size = i[0]
                data = (data + 15) & ~15
                file_at[(k, name)] = (at, data, size)
                self.order.append((i, data, size, name))
                at, data = at + 0x20 + pad4(len(name)), data + size
        files_size = at
        folder_hash, file_hash = [self.NONE] * buckets(len(folders)), [self.NONE] * buckets(len(self.order))
        folder_table, file_table = bytearray(folders_size), bytearray(files_size)
        for k, f in enumerate(folders):
            name, parent, subs, files = f
            if k:
                sibs = folders[parent][2]
                sibling = folder_at[sibs[sibs.index(k) + 1]] if sibs.index(k) + 1 < len(sibs) else self.NONE
            else:
                sibling = self.NONE
            h = name_hash(folder_at[parent], name) % len(folder_hash)
            struct.pack_into('<6I', folder_table, folder_at[k], folder_at[parent], sibling, folder_at[subs[0]] if subs else self.NONE,
                             file_at[(k, files[0][0])][0] if files else self.NONE, folder_hash[h], len(name))
            folder_table[folder_at[k] + 0x18:folder_at[k] + 0x18 + len(name)] = name
            folder_hash[h] = folder_at[k]
            for j, (fname, i) in enumerate(files):
                at, off, size = file_at[(k, fname)]
                h = name_hash(folder_at[k], fname) % len(file_hash)
                struct.pack_into('<IIQQII', file_table, at, folder_at[k], file_at[(k, files[j + 1][0])][0] if j + 1 < len(files) else self.NONE,
                                 off, size, file_hash[h], len(fname))
                file_table[at + 0x20:at + 0x20 + len(fname)] = fname
                file_hash[h] = at
        self.data_size = data
        tables_at = (0x200 + data + 15) & ~15
        parts = [struct.pack(f'<{len(folder_hash)}I', *folder_hash), bytes(folder_table), struct.pack(f'<{len(file_hash)}I', *file_hash), bytes(file_table)]
        head, at = [0x50], tables_at
        for p in parts:
            head += [at, len(p)]
            at += len(p)
        self.head = struct.pack('<10Q', *head, 0x200).ljust(0x200, b'\0')
        self.tail = bytes(tables_at - 0x200 - data) + b''.join(parts)
        self.size = at
        self.pieces, self.held, self.at, self.sent = self.make(), b'', 0, 0

    def make(self):
        yield self.head
        at = 0
        for (_, pieces), off, size, name in self.order:
            if off > at:
                yield bytes(off - at)
            got = 0
            for piece in pieces() if size else ():
                got += len(piece)
                yield piece
            if got != size:
                raise SystemExit(f'{name.decode("utf-8", "replace")}: {got} bytes read where {size} were said')
            at = off + size
        yield self.tail

    def read(self, n=-1):
        out = bytearray()
        while n < 0 or len(out) < n:
            if self.at >= len(self.held):
                self.held, self.at = next(self.pieces, None), 0
                if self.held is None:
                    self.held = b''
                    break
            take = len(self.held) - self.at if n < 0 else min(n - len(out), len(self.held) - self.at)
            out += memoryview(self.held)[self.at:self.at + take]
            self.at += take
        self.sent += len(out)
        return bytes(out)


class Part:
    """So many of a stream's next bytes, read as a file of their own: an image sent in parts."""

    def __init__(self, stream, n):
        self.stream, self.left = stream, n

    def read(self, n=-1):
        data = self.stream.read(self.left if n < 0 else min(n, self.left))
        self.left -= len(data)
        return data


PART = 2 << 30  # an image too large for a FAT32 card's file goes in parts of this size (<name>.romfs.00, .01, ...), as tools/install.py's do
LIMIT = (4 << 30) - 1


def send(stream, size, to, tell):
    """A stream's bytes to a file here, to a console's FTP server (ftp://host:port/path) or to Toronja Transfer open on the console
    (ttx://host/path; its README has the protocol, port 28302) or to SW2Transfer open on it (sw2t://host/path: tools/sw2t.py). True if
    what arrived is what was sent."""
    if to.startswith('sw2t://'):
        from sw2t import send_to
        return send_to(stream, size, to, tell)
    if to.startswith('ttx://'):
        import socket
        import zlib
        host, path = to[6:].split('/', 1)
        path = ('/' + path).encode()
        s = socket.create_connection((host.split(':')[0], int(host.split(':')[1]) if ':' in host else 28302), timeout=120)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 1 << 20)

        def take(n):
            got = b''
            while len(got) < n:
                more = s.recv(n - len(got))
                if not more:
                    raise SystemExit('the console hung up')
                got += more
            return got

        def status():
            code = s.recv(1)
            if code != b'\0':
                n = struct.unpack('<H', take(2))[0]
                raise SystemExit('the console refused: ' + take(n).decode('utf-8', 'replace'))
        s.sendall(b'TTX1' + struct.pack('<BH', 2, len(path)) + path + struct.pack('<Q', size))
        status()
        crc = 0
        while True:
            block = stream.read(2 << 20)
            if not block:
                break
            crc = zlib.crc32(block, crc)
            s.sendall(block)
            tell()
        status()
        there = struct.unpack('<I', take(4))[0]
        s.close()
        print(f'  {to}: {size} bytes; the sum of what the card holds ' + ('matches' if there == crc else f'DOES NOT match ({there:08x}, {crc:08x} here)'), flush=True)
        return there == crc
    if to.startswith('ftp://'):
        import ftplib
        host, path = to[6:].split('/', 1)
        ftp = ftplib.FTP()
        ftp.connect(host.split(':')[0], int(host.split(':')[1]) if ':' in host else 5000, timeout=120)
        ftp.login()
        ftp.storbinary('STOR /' + path, stream, blocksize=1 << 20, callback=tell)
        ftp.voidcmd('TYPE I')
        there = ftp.size('/' + path)
        ftp.quit()
        print(f'  {to}: {there} bytes there' + ('' if there == size else f', NOT the {size} sent'), flush=True)
        return there == size
    os.makedirs(os.path.dirname(os.path.abspath(to)), exist_ok=True)
    with open(to, 'wb') as o:
        while True:
            block = stream.read(4 << 20)
            if not block:
                break
            o.write(block)
            tell()
    there = os.path.getsize(to)
    print(f'  {to}: {there} bytes written' + ('' if there == size else f', NOT the {size} of the image'), flush=True)
    return there == size


def send_image(image, to, parts=False):
    """A RomFS image (RomFS) sent: to a file here, to a console's FTP server (ftp://host:port/nx2-relink/<name>/romfs.bin) or to Toronja
    Transfer open on it (ttx://host/nx2-relink/<name>/romfs.bin). With parts, an image of 4 GB or more goes as <to>.00, .01, ... of 2 GB each,
    which a port reads as one (a FAT32 card can't hold it otherwise). True if all of it arrived."""
    import time
    split = parts and image.size > LIMIT
    print(f'{len(image.order)} files, an image of {image.size >> 20} MB, to {to}' + (f' in {-(-image.size // PART)} parts' if split else ''), flush=True)
    start, said = time.time(), [0]
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from progress import progress
    shown = '/' + to.split('://', 1)[1].split('/', 1)[1] if '://' in to else to  # (where it goes on the card, for the window)

    def tell(_=None):
        progress('copy', f"{shown} (the game's files)", image.sent, image.size)  # (all of the image, across its parts)
        if image.sent - said[0] >= 256 << 20:
            said[0] = image.sent
            print(f'  {image.sent >> 20} of {image.size >> 20} MB, {(image.sent >> 20) / max(time.time() - start, 1):.1f} MB/s', flush=True)
    if not split:
        return send(image, image.size, to, tell)
    ok = True
    for k in range(-(-image.size // PART)):
        n = min(PART, image.size - k * PART)
        ok = send(Part(image, n), n, f'{to}.{k:02d}', tell) and ok
    return ok


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ('info', 'list', 'extract', 'romfs'):
        sys.exit(__doc__)
    nup = Nup(sys.argv[2])
    if sys.argv[1] == 'romfs':
        return sys.exit(0 if send_image(RomFS(package_files(nup, int(sys.argv[3]))), sys.argv[4], '--parts' in sys.argv) else 1)
    if sys.argv[1] == 'info':
        print(f'{sys.argv[2]}: {nup.size >> 20} MB, {len(nup.packages)} packages, {nup.ndirs} folders, {nup.nfiles} files')
        for k, p in enumerate(nup.packages):
            facts = nup.facts(k)
            text = lambda n: facts.get(n, b'').decode('utf-8', 'replace').strip(chr(0))  # noqa: E731
            files = list(nup.walk(p['root']))
            total = sum(nup.file(i)[1] for _, i in files)
            print(f'  package {k}: {KINDS.get(p["kind"], p["kind"])}, title {p["title"]:016x}, version {p["version"]} ("{text('display version')}"), "{text('title') or text('dump name')}" by "{text('publisher')}"')
            print(f'    {len(files)} files, {total >> 20} MB as they are; exefs {"yes" if p["exefs"] != 0xFFFFFFFF else "no"}, romfs {"yes" if p["romfs"] != 0xFFFFFFFF else "no"}; '
                  f'build id {facts.get("build id", b"").hex()}; facts: {", ".join(facts)}')
            if p['exefs'] != 0xFFFFFFFF:
                for path, i in nup.walk(p['exefs']):
                    print(f'      exefs/{path}: {nup.file(i)[1]} bytes')
        return
    package = int(sys.argv[4 if sys.argv[1] == 'extract' else 3]) if len(sys.argv) > (4 if sys.argv[1] == 'extract' else 3) else 0
    sub = sys.argv[5 if sys.argv[1] == 'extract' else 4] if len(sys.argv) > (5 if sys.argv[1] == 'extract' else 4) else ''
    d = nup.folder(package, sub)
    if sys.argv[1] == 'list':
        for path, i in nup.walk(d):
            print(f'{nup.file(i)[1]:12d}  {path}')
        return
    out, count, total = sys.argv[3], 0, 0
    for path, i in nup.walk(d):
        data = nup.read(i)
        if hashlib.sha256(data).digest() != nup.file(i)[4]:
            print(f'  {path}: its bytes don\'t match the sum the file gives for them')
        to = os.path.join(out, path)
        os.makedirs(os.path.dirname(to) or '.', exist_ok=True)
        with open(to, 'wb') as o:
            o.write(data)
        count, total = count + 1, total + len(data)
    print(f'{count} files, {total >> 20} MB, written under {out}')


if __name__ == '__main__':
    main()
