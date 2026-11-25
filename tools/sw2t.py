"""A port sent over Wi-Fi to SW2Transfer open on the console (https://github.com/Rodpad/SW2Transfer): its app, or its background
plugin. Its HTTP API, on port 6967; several connections at once, which is faster than FTP.

  host[:port]         the address SW2Transfer shows on the console's screen (default port 6967)
  SW2T_PASSWORD       the password, if one is set in SW2Transfer (otherwise it is asked for in a terminal)

Every file is checked after it is written: its size, and three samples of it read back (as with --ftp).
"""
import getpass
import http.client
import json
import os
import queue
import sys
import threading
import time
import urllib.parse

PORT = 6967
CONNECTIONS = 4       # (near the speed of 8 in SW2Transfer's tests, and leaves its background plugin room for others)
CHUNK = 2 << 20
SAMPLE = 1 << 20


def q(path):
    return urllib.parse.quote(path, safe='/')


class Sw2t:
    """The card: SW2Transfer on the console."""

    def __init__(self, where):
        host, _, port = where.partition(':')
        self.host, self.port = host, int(port or PORT)
        self.token = None
        self.local = threading.local()
        self.lock = threading.Lock()
        try:
            info = self.api('GET', '/api/info')
        except (OSError, http.client.HTTPException, RuntimeError) as e:
            sys.exit(f'SW2Transfer doesn\'t answer at {self.host}:{self.port} ({e}). Is it open on the console?')
        print(f'SW2Transfer {info.get("version", "?")} at {self.host}:{self.port}'
              + (' (its background plugin)' if info.get('background') else ''), flush=True)

    # ---- HTTP
    def conn(self):
        c = getattr(self.local, 'c', None)
        if c is None:
            c = self.local.c = http.client.HTTPConnection(self.host, self.port, timeout=120)
        return c

    def drop(self):
        c = getattr(self.local, 'c', None)
        if c:
            c.close()
        self.local.c = None

    def login(self, seen):
        with self.lock:
            if self.token != seen:
                return  # (another connection signed in meanwhile)
            pw = os.environ.get('SW2T_PASSWORD')
            if not pw:
                if not (sys.stdin and sys.stdin.isatty()):
                    sys.exit('SW2Transfer has a password: give it (SW2T_PASSWORD, or the password box in the window).')
                pw = getpass.getpass('SW2Transfer password: ')
            c = http.client.HTTPConnection(self.host, self.port, timeout=30)
            try:
                c.request('POST', '/api/login', headers={'X-SW2-Password': urllib.parse.quote(pw, safe=''), 'User-Agent': 'nx2-relink'})
                r = c.getresponse()
                j = json.loads(r.read() or b'{}')
            finally:
                c.close()
            if r.status != 200 or not j.get('ok'):
                sys.exit('SW2Transfer: ' + (j.get('error') or 'wrong password'))
            self.token = j.get('token')

    def request(self, method, path, body=None, headers=None):
        last, logins = None, 0
        for attempt in range(4):
            try:
                h = dict(headers or {}, **{'User-Agent': 'nx2-relink'})
                seen = self.token
                if seen:
                    h['Authorization'] = 'Bearer ' + seen
                c = self.conn()
                c.request(method, path, body=body, headers=h)
                r = c.getresponse()
                data = r.read()
                if r.status == 401 and logins < 2:
                    self.drop()
                    self.login(seen)
                    logins += 1
                    continue
                if r.status == 410:
                    sys.exit('cancelled on the console (Cancel all)')
                if r.getheader('Connection', '').lower() == 'close':
                    self.drop()
                return r, data
            except (OSError, http.client.HTTPException) as e:
                last = e
                self.drop()
                time.sleep(0.5 * (attempt + 1))
        raise RuntimeError(f'{method} {path}: {last}')

    def api(self, method, endpoint, **params):
        r, data = self.request(method, endpoint + '?' + urllib.parse.urlencode(params))
        try:
            j = json.loads(data or b'{}')
        except ValueError:
            j = {}
        if r.status >= 300 or j.get('ok') is False:
            raise RuntimeError(j.get('error') or f'HTTP {r.status}')
        return j

    # ---- what tools/install.py asks of a card
    def mkdir(self, d):
        try:
            self.api('POST', '/api/mkdir', path=d)
        except RuntimeError:
            pass

    def entries(self, d):
        try:
            return self.api('GET', '/api/list', path=d)['entries']
        except RuntimeError:
            return []

    def listing(self, d):
        return [e['name'] for e in self.entries(d)]

    def size(self, path):
        d, _, name = path.rpartition('/')
        return next((e['size'] for e in self.entries(d or '/') if e['name'] == name), None)

    def remove(self, path):
        self.api('POST', '/api/delete', path=path)

    def move(self, old, new):
        self.api('POST', '/api/rename', **{'from': old, 'to': new})

    def rmdir(self, d):
        try:
            self.api('POST', '/api/delete', path=d)
        except RuntimeError:
            pass

    def sample(self, path, off, n):
        r, data = self.request('GET', f'/dl{q(path)}', headers={'Range': f'bytes={off}-{off + n - 1}'})
        return data if r.status in (200, 206) else b''

    def put(self, src, off, n, path):
        with open(src, 'rb') as f:
            f.seek(off)
            return self.send(f, n, path, lambda: None, label=path)

    def send(self, stream, size, path, tell, label=None):
        """size bytes read from stream (in order, once) written to path, over several connections. True if the console has them."""
        xid = os.urandom(8).hex()
        self.api('POST', '/api/create', path=path, size=size, x=xid)
        keep = {at: None for at in sorted({0, max(0, size // 2 - SAMPLE // 2), max(0, size - SAMPLE)})} if size else {}
        work, failed, sent = queue.Queue(CONNECTIONS * 2), [], [0]
        count = threading.Lock()

        def worker():
            while True:
                job = work.get()
                if job is None:
                    self.drop()  # (closed now, not whenever the thread is collected: the console holds a slot for each)
                    return
                at, data = job
                if failed:
                    continue
                try:
                    r, body = self.request('PUT', f'/ul{q(path)}?offset={at}&total={size}&x={xid}', body=data,
                                           headers={'Content-Length': str(len(data)), 'Content-Type': 'application/octet-stream'})
                    if r.status != 200:
                        raise RuntimeError(f'HTTP {r.status} {body[:200]!r}')
                except BaseException as e:  # noqa: BLE001 (SystemExit too: it is said once, below)
                    failed.append(e)
                    continue
                with count:
                    sent[0] += len(data)
                    if label:
                        from progress import progress
                        progress('copy', label, sent[0], size)
        threads = [threading.Thread(target=worker, daemon=True) for _ in range(CONNECTIONS)]
        for t in threads:
            t.start()
        at, pending = 0, b''
        try:
            while at < size and not failed:
                data = stream.read(min(CHUNK, size - at))
                if not data:
                    break
                for k in keep:  # (the samples checked afterwards, kept as they go by: the stream can't be read again)
                    lo, hi = max(k, at), min(k + SAMPLE, at + len(data))
                    if lo < hi:
                        keep[k] = (keep[k] or b'') + data[lo - at:hi - at]
                work.put((at, data))
                at += len(data)
                tell()
        finally:
            for _ in threads:
                work.put(None)
            for t in threads:
                t.join()
        if failed:
            e = failed[0]
            if isinstance(e, SystemExit):
                raise e
            print(f'  {path}: {e}', flush=True)
            return False
        if at != size:
            print(f'  {path}: only {at} of {size} bytes were there to send', flush=True)
            return False
        there = self.size(path)
        if there != size:
            print(f'  {path}: {there} bytes there, NOT the {size} sent', flush=True)
            return False
        for k, want in keep.items():
            if want and self.sample(path, k, len(want)) != want:
                print(f'  {path}: what was read back at {k} isn\'t what was sent', flush=True)
                return False
        return True


_clients = {}


def send_to(stream, size, to, tell):
    """For tools/nup.py: sw2t://host[:port]/path. One client per console for all of an image's parts (one sign-in)."""
    host, path = to[len('sw2t://'):].split('/', 1)
    if host not in _clients:
        _clients[host] = Sw2t(host)
    ok = _clients[host].send(stream, size, '/' + path, tell)
    print(f'  {to}: {size} bytes; ' + ('the size and samples read back match' if ok else 'DID NOT arrive right'), flush=True)
    return ok
