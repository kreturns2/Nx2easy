"""A built port put on a console's card: its NRO, the game's RomFS and its add-on content's.

  python tools/install.py <name> --sd <drive or folder>     the card in this computer (I:, /media/card)
  python tools/install.py <name> --ftp <host[:port]>        or over the network, to an FTP server on the console (port 5000)
  python tools/install.py <name> --sw2t <host[:port]>       or to SW2Transfer open on the console (port 6967; faster than FTP)
      --target switch | switch2    which NRO: out/<name>.nro (default) or out/<name>-switch2.nro
      --sd-format fat32 | exfat | auto
                                   fat32: a RomFS of 4 GB or more goes in 2 GB parts (<name>.romfs.00, .01, ...), which the port
                                   reads as one; exfat: always one file. auto (default): asked of the drive with --sd, and fat32
                                   with --ftp or --sw2t, where it can't be asked (parts are read from either kind of card).
      --from <folder>              where tools/nsp.py left the game: build/<name>_nsp by default
      --nro-only                   the NRO only: the game's files are on the card already (after building a port again).
                                   --no-romfs is the same
      --no-shaders                 not the translated shaders (a Switch 2's; they are on the card already)
      --long-log                   the file "debug" is put in the port's folder: its detailed log, from its first run

A Switch 2 game (built from a NUP container or a folder of loose files, tools/build.py) has no RomFS image on this computer: it
is made from the dump as it is sent (tools/game2.py: the game's files with its updates' laid over them), 9 GB of it for one game,
so nothing that size is written here. Its port is for a Switch 2 alone.

On the card, a port is its program, in the homebrew menu's folder, and a folder of its name at the card's root with everything
else of it, both under the tool's name:
    /switch/nx2-relink/<name>.nro  a Switch 2's port: an entry of the folder "nx2-relink" in the homebrew menu, which has
                                   nothing but the ports' programs in it
    /nx2-relink/<name>/            what it reads and writes    (/switch/nx-relink/ and /nx-relink/ for a Switch's)
        romfs.bin                  the game's files (or romfs.bin.00, .01, ...: parts of 2 GB for a FAT32 card)
        aoc<index>.romfs           its add-on content's
        save/                      the game's saved data, written by the port as the game saves
        log.txt, crash.txt         the last run's log; the report of the last run that ended badly
A port installed by an earlier version of this tool had its files in /nx2/ and its program in /switch/ (before 0.1.0), or all
of it in /switch/<tool>/<name>/ (0.1.0 and 0.1.1): its saved data, its RomFS and the rest are moved to the new folder (not copied
again), and the old program is removed.
A RomFS left there in the other form (one file where parts are being written, or the reverse) is removed: the port would read it
instead. Every file is read back and compared after it is written (--sd), or its size and three samples of it are (--ftp,
--sw2t).
"""
import ctypes
import ftplib
import glob
import hashlib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from progress import progress  # noqa: E402
PART = 2 << 30
LIMIT = (4 << 30) - 1  # a FAT32 file's most


def option(args, name, default=None):
    if name in args:
        i = args.index(name)
        v = args[i + 1]
        del args[i:i + 2]
        return v
    return default


def drive_format(path):
    """The file system of the drive a path is on ('FAT32', 'exFAT', ...), or None where it can't be asked."""
    if os.name != 'nt':
        return None
    root = os.path.splitdrive(os.path.abspath(path))[0] + '\\'
    name = ctypes.create_unicode_buffer(64)
    ok = ctypes.windll.kernel32.GetVolumeInformationW(root, None, 0, None, None, None, name, 64)
    return name.value if ok else None


def pieces(size, split):
    """(suffix, offset, length) of each file an image of this size is written as."""
    if not split or size <= LIMIT:
        return [('', 0, size)]
    return [(f'.{k:02d}', k * PART, min(PART, size - k * PART)) for k in range((size + PART - 1) // PART)]


class Slice:
    """A stretch of a file, read as a file (for ftplib)."""

    def __init__(self, f, n, said=None):
        self.f, self.left, self.all, self.said = f, n, n, said

    def read(self, n):
        n = min(n, self.left)
        self.left -= n
        if self.said:
            progress('copy', self.said, self.all - self.left, self.all)
        return self.f.read(n) if n else b''


class Card:
    """The card: a folder of this computer's."""

    def __init__(self, root):
        self.root = root if root.endswith(('/', '\\')) else root + '/'
        if not os.path.isdir(self.root):
            sys.exit(f'{root} isn\'t a folder or a drive.')

    def mkdir(self, d):
        os.makedirs(self.root + d.lstrip('/'), exist_ok=True)

    def listing(self, d):
        try:
            return os.listdir(self.root + d.lstrip('/'))
        except OSError:
            return []

    def remove(self, path):
        os.remove(self.root + path.lstrip('/'))

    def move(self, old, new):
        os.replace(self.root + old.lstrip('/'), self.root + new.lstrip('/'))

    def rmdir(self, d):
        try:
            os.rmdir(self.root + d.lstrip('/'))
        except OSError:
            pass

    def put(self, src, off, n, path):
        dst = self.root + path.lstrip('/')
        a = hashlib.sha256()
        with open(src, 'rb') as f, open(dst, 'wb') as o:
            f.seek(off)
            left = n
            while left:
                blk = f.read(min(1 << 22, left))
                if not blk:
                    break
                o.write(blk)
                a.update(blk)
                left -= len(blk)
                progress('copy', path, n - left, n)
            o.flush()
            os.fsync(o.fileno())  # (on the card, not in this computer's memory, before it is read back)
        b = hashlib.sha256()
        read = 0
        with open(dst, 'rb') as f:
            for blk in iter(lambda: f.read(1 << 22), b''):
                b.update(blk)
                read += len(blk)
                progress('verify', path, read, n)
        return os.path.getsize(dst) == n and a.digest() == b.digest()


class Ftp:
    """The card: an FTP server on the console."""

    def __init__(self, where):
        host, _, port = where.partition(':')
        self.ftp = ftplib.FTP()
        try:
            self.ftp.connect(host, int(port or 5000), timeout=60)
            self.ftp.login()
        except (OSError, ftplib.all_errors) as e:
            sys.exit(f'No FTP server answers at {where} ({e}). Is it open on the console?')

    def mkdir(self, d):
        try:
            self.ftp.mkd(d)
        except ftplib.all_errors:
            pass

    def listing(self, d):
        try:
            return [os.path.basename(x) for x in self.ftp.nlst(d)]
        except ftplib.all_errors:
            return []

    def remove(self, path):
        self.ftp.delete(path)

    def move(self, old, new):
        self.ftp.rename(old, new)

    def rmdir(self, d):
        try:
            self.ftp.rmd(d)
        except Exception:  # noqa: BLE001
            pass

    def sample(self, path, off, n):
        got = bytearray()
        conn = self.ftp.transfercmd('RETR ' + path, rest=off)
        while len(got) < n:
            b = conn.recv(1 << 16)
            if not b:
                break
            got += b
        conn.close()
        try:
            self.ftp.voidresp()
        except ftplib.all_errors:
            pass
        return bytes(got[:n])

    def put(self, src, off, n, path):
        with open(src, 'rb') as f:
            f.seek(off)
            self.ftp.storbinary('STOR ' + path, Slice(f, n, path), blocksize=1 << 18)
            self.ftp.voidcmd('TYPE I')
            if self.ftp.size(path) != n:
                return False
            for at in sorted({0, max(0, n // 2 - (1 << 19)), max(0, n - (1 << 20))}):
                want_n = min(1 << 20, n - at)
                f.seek(off + at)
                if self.sample(path, at, want_n) != f.read(want_n):
                    return False
        return True


def main():
    args = sys.argv[1:]
    target = option(args, '--target', 'switch')
    fmt = option(args, '--sd-format', 'auto').lower()
    sd, ftp, ttx, sw2t = option(args, '--sd'), option(args, '--ftp'), option(args, '--ttx'), option(args, '--sw2t')
    src_dir = option(args, '--from')
    no_romfs = '--no-romfs' in args or '--nro-only' in args
    for a in ('--no-romfs', '--nro-only'):
        if a in args:
            args.remove(a)
    no_shaders = '--no-shaders' in args
    if no_shaders:
        args.remove('--no-shaders')
    long_log = '--long-log' in args
    if long_log:
        args.remove('--long-log')
    if len(args) != 1 or [bool(sd), bool(ftp), bool(sw2t)].count(True) != 1 or target not in ('switch', 'switch2') or fmt not in ('fat32', 'exfat', 'auto'):
        sys.exit(__doc__)
    name = args[0]
    src_dir = src_dir or f'{ROOT}/build/{name}_nsp'
    info = json.load(open(f'{src_dir}/info.json', encoding='utf-8')) if os.path.isfile(f'{src_dir}/info.json') else {}
    if info.get('switch2') and target != 'switch2':
        print(f'{name}: its port is for its own console alone')
        target = 'switch2'
    nro = f'{ROOT}/out/{name}{"-switch2" if target == "switch2" else ""}.nro'
    if not os.path.isfile(nro):
        sys.exit(f'{nro} isn\'t there: build it first (tools/build.py).')
    if sw2t:
        from sw2t import Sw2t
        card = Sw2t(sw2t)
    else:
        card = Card(sd) if sd else Ftp(ftp)
    if fmt == 'auto':
        found = drive_format(sd) if sd else None
        fmt = 'exfat' if found and found.lower() == 'exfat' else 'fat32'
        print(f'the card: {found or "its format can\'t be asked"}; a large RomFS goes {"as one file" if fmt == "exfat" else "in 2 GB parts"}')
    split = fmt == 'fat32'

    tool = 'nx2-relink' if target == 'switch2' else 'nx-relink'
    home = f'/{tool}/{name}'  # (the port's folder: runtime/nx2.h has the same)
    card.mkdir('/switch')
    card.mkdir(f'/switch/{tool}')
    card.mkdir(f'/{tool}')
    card.mkdir(home)
    # what an earlier version of this tool left for this port, moved to the folder: 0.1.0 and 0.1.1 had it in the menu's folder
    before = f'/switch/{tool}/{name}'
    for entry in card.listing(before):
        if entry == f'{name}.nro':
            card.remove(f'{before}/{entry}')
        elif entry not in card.listing(home):
            card.move(f'{before}/{entry}', f'{home}/{entry}')
            print(f'  {before}/{entry}: moved to {home}/{entry}')
    if before.rsplit('/', 1)[1] in card.listing(f'/switch/{tool}') and not card.listing(before):
        card.rmdir(before)
    there, old = card.listing(home), card.listing('/nx2')
    for was, now in [(f'{name}.romfs', 'romfs.bin')] + [(o, 'romfs.bin' + o[-3:]) for o in old if re.fullmatch(re.escape(name) + r'\.romfs\.\d\d', o)] + \
            [(o, o[len(name) + 1:]) for o in old if re.fullmatch(re.escape(name) + r'\.aoc\d+\.romfs', o)] + [(f'{name}.shaders', 'shaders.bin'), (f'{name}.spv', 'shaders.spv')]:
        if was in old and now not in there:
            card.move(f'/nx2/{was}', f'{home}/{now}')
            print(f'  /nx2/{was}: moved to {home}/{now}')
    if name in card.listing('/nx2/save') and 'save' not in there:
        card.move(f'/nx2/save/{name}', f'{home}/save')
        print(f'  /nx2/save/{name}: the saved data, moved to {home}/save')
    program = f'/switch/{tool}/{name}.nro'  # (alone in the menu's folder: the homebrew menu shows the tool's folder's programs in one list)
    if f'nx2-{name}.nro' in card.listing('/switch'):
        card.remove(f'/switch/nx2-{name}.nro')
        print(f'  /switch/nx2-{name}.nro: removed (the port is {program} now)')
    if f'{name}.nro' in there:
        card.remove(f'{home}/{name}.nro')
        print(f'  {home}/{name}.nro: removed (the port is {program} now)')
    jobs = [(nro, program, False)]
    if not no_romfs:
        if info.get('switch2'):
            pass  # (a Switch 2 game's: made from its dump as it is sent, below)
        elif os.path.isfile(f'{src_dir}/romfs.bin'):
            jobs.append((f'{src_dir}/romfs.bin', f'{home}/romfs.bin', True))
        else:
            print(f'{src_dir}/romfs.bin isn\'t there: no RomFS sent (tools/nsp.py --romfs writes it)')
        for a in sorted(glob.glob(f'{src_dir}/aoc*.romfs')):
            index = re.search(r'aoc(\d+)\.romfs$', a).group(1)
            jobs.append((a, f'{home}/aoc{index}.romfs', True))
    # a Switch 2's port of a game with compiled shaders draws with their translations (tools/shaderpack.py)
    if target == 'switch2' and not no_shaders and os.path.isfile(f'{src_dir}/shaders.bin'):
        jobs.append((f'{src_dir}/shaders.bin', f'{home}/shaders.bin', False))
    # the font a game is given on a Switch 2 in place of the system's, which a homebrew program isn't let have there (runtime/gl2.c):
    # a free one from devkitPro's examples, if the card has none yet
    if target == 'switch2' and not info.get('switch2') and 'font.ttf' not in card.listing(home):
        for d in (os.environ.get('DEVKITPRO', ''), 'C:/devkitPro', '/opt/devkitpro'):
            font = f'{d}/examples/3ds/graphics/printing/custom-font/gfx/liberationitalic.ttf'
            if d and os.path.isfile(font):
                jobs.append((font, f'{home}/font.ttf', False))
                break
        else:
            print(f'  no font found to put at {home}/font.ttf (devkitPro\'s examples have one): a game that asks for the system\'s font will end')
    if long_log:
        open(f'{src_dir}/debug', 'w').write('the port writes its detailed log while this file is in its folder\n')
        jobs.append((f'{src_dir}/debug', f'{home}/debug', False))
    wrong = 0
    for src, dst, image in jobs:
        size = os.path.getsize(src)
        parts = pieces(size, split and image)
        if image:  # the same image in the other form, from an earlier time
            base = os.path.basename(dst)
            mine = {base + suffix for suffix, _, _ in parts}
            for other in card.listing(home):
                if (other == base or re.fullmatch(re.escape(base) + r'\.\d\d', other)) and other not in mine:
                    card.remove(f'{home}/{other}')
                    print(f'  {home}/{other}: removed (the image is written in another form now)')
        for suffix, off, n in parts:
            ok = card.put(src, off, n, dst + suffix)
            wrong += not ok
            print(f'  {dst + suffix}: {n} bytes, {"the same as here" if ok else "DIFFERENT from the one here"}', flush=True)
    if not no_romfs and info.get('switch2'):
        # a Switch 2 game's files: one RomFS image made from the dump as it goes (the game's, its updates' over them)
        import game2
        import nup as container
        for where in [info.get('dump') or info.get('nup')] + list(info.get('updates') or []):
            if not where or not os.path.exists(where):
                sys.exit(f'{where} isn\'t there any more: the game\'s files are read from it (--no-romfs if they are on the card already)')
        image = game2.image_of(info, print)
    else:
        image = None
    if image:
        base = 'romfs.bin'
        in_parts = split and image.size > LIMIT
        mine = {f'{base}.{k:02d}' for k in range(-(-image.size // PART))} if in_parts else {base}
        for other in card.listing(home):
            if (other == base or re.fullmatch(re.escape(base) + r'\.\d\d', other)) and other not in mine:
                card.remove(f'{home}/{other}')
                print(f'  {home}/{other}: removed (the image is written in another form now)')
        to = f'ttx://{ttx}{home}/{base}' if ttx else f'sw2t://{sw2t}{home}/{base}' if sw2t else f'ftp://{ftp}{home}/{base}' if ftp else card.root + home.lstrip('/') + '/' + base
        if ttx:
            print('  (through Toronja Transfer: it must be open on the console)')
        wrong += not container.send_image(image, to, parts=in_parts)
    if wrong:
        sys.exit(f'{wrong} file(s) didn\'t arrive right: don\'t run the port until they do.')
    print('done')


if __name__ == '__main__':
    main()
