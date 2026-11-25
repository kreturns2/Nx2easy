#!/usr/bin/env python3
"""
nx2-relink Easy - une interface simple et animée pour nx2-relink.

Placez ce fichier dans le dossier de nx2-relink (à côté de nxrelink.py), puis :
    python nx2_easy.py

Une page s'ouvre dans votre navigateur. Rien n'est envoyé sur Internet :
le serveur n'écoute que sur votre propre ordinateur (127.0.0.1).
Aucune dépendance en plus de nx2-relink lui-même (bibliothèque standard Python).
"""
import html
import json
import locale
import mimetypes
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

APP_DIR = Path(__file__).resolve().parent
CONFIG = APP_DIR / "nx2-easy.json"  # à côté du programme (ignoré par git)


# --------------------------------------------------------------------------- config
def load_cfg():
    try:
        return json.loads(CONFIG.read_text("utf-8"))
    except Exception:
        return {}


def save_cfg(cfg):
    try:
        CONFIG.write_text(json.dumps(cfg, indent=2), "utf-8")
    except Exception:
        pass


# --------------------------------------------------------------------------- languages
# One file per language in locales/ : add a file to add a language (missing texts are shown in English).
def load_locales():
    found = {}
    for f in sorted((APP_DIR / "locales").glob("*.json")):
        try:
            found[f.stem] = json.loads(f.read_text("utf-8"))
        except Exception as e:
            print(f"locales/{f.name}: {e}", file=sys.stderr)
    if "en" not in found:
        sys.exit("locales/en.json is missing or damaged.")
    return {k: {**found["en"], **v} for k, v in found.items()}


LOCALES = load_locales()
LANG = "en"


def set_lang(lang):
    global LANG
    if lang in LOCALES:
        LANG = lang


def choose_lang(wanted=None):
    """The language chosen in the page; else the browser's (Accept-Language), or the system's; else English."""
    saved = load_cfg().get("lang")
    if saved in LOCALES:
        return set_lang(saved)
    if wanted is None:
        wanted = locale.getlocale()[0] or ""
        if os.name == "nt":
            import ctypes
            wanted = locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage(), wanted)
    for part in wanted.split(","):
        code = re.split(r"[-_;]", part.strip().lower())[0]
        if code in LOCALES:
            return set_lang(code)
    set_lang("en")


def t(key):
    return LOCALES[LANG].get(key, key)


def page():
    texts = LOCALES[LANG]
    out = re.sub(r"\{\{(\w+)\}\}", lambda m: texts.get(m[1], m[1]), PAGE)
    options = "".join(f'<option value="{k}"{" selected" if k == LANG else ""}>{html.escape(v.get("_name", k))}</option>'
                      for k, v in LOCALES.items())
    return (out.replace("%%LANGS%%", options).replace("%%LANGJS%%", json.dumps(LANG)).replace("%%LANG%%", LANG)
            .replace("%%L10N%%", json.dumps(texts, ensure_ascii=False).replace("</", "<\\/")))


choose_lang()


def find_repo():
    cands = []
    cfg = load_cfg()
    cands.append(APP_DIR)  # toujours sa propre copie d'abord
    if cfg.get("repo"):
        cands.append(Path(cfg["repo"]))
    cands += [Path.cwd(), APP_DIR / "nx2-relink", Path.cwd() / "nx2-relink"]
    for c in cands:
        if (c / "nxrelink.py").is_file():
            return c.resolve()
    return None


REPO = find_repo()

# --------------------------------------------------------------------------- pickers
PICKER = r"""
import sys
try:
    import tkinter as tk
    from tkinter import filedialog
except Exception:
    print("__NOTK__"); sys.exit(0)
r = tk.Tk(); r.withdraw()
try: r.attributes('-topmost', True)
except Exception: pass
k, title = sys.argv[1:3]
if k == 'folder':
    p = filedialog.askdirectory(title=title)
elif k == 'image':
    p = filedialog.askopenfilename(title=title,
        filetypes=[(sys.argv[3], '*.png *.jpg *.jpeg *.bmp *.webp'), (sys.argv[4], '*.*')])
elif k == 'nup':
    p = filedialog.askopenfilename(title=title,
        filetypes=[('Dump NUP', '*.nup'), (sys.argv[4], '*.*')])
else:
    p = filedialog.askopenfilename(title=title)
print(p or '')
"""


def pick(kind):
    try:
        out = subprocess.run([sys.executable, "-c", PICKER, kind, t({"folder": "dlg_folder", "image": "choose_icon", "nup": "dlg_nup"}.get(kind, "dlg_file")),
                              t("images"), t("all_files")],
                             capture_output=True, text=True, timeout=600).stdout.strip()
    except Exception:
        return {"path": "", "notk": True}
    if out == "__NOTK__":
        return {"path": "", "notk": True}
    return {"path": os.path.normpath(out) if out else ""}


def drives():
    found = []
    if os.name == "nt":
        try:
            import ctypes
            k32 = ctypes.windll.kernel32
            mask = k32.GetLogicalDrives()
            for i in range(26):
                if not mask & (1 << i):
                    continue
                root = f"{chr(65 + i)}:\\"
                t = k32.GetDriveTypeW(root)
                if t not in (2, 3) or root.upper().startswith("C:"):
                    continue
                buf = ctypes.create_unicode_buffer(261)
                k32.GetVolumeInformationW(root, buf, 261, None, None, None, None, 0)
                found.append((root, buf.value or t("disk"), t == 2))
        except Exception:
            pass
    else:
        user = os.environ.get("USER", "")
        bases = ["/Volumes", f"/media/{user}", f"/run/media/{user}", "/media", "/mnt"]
        for b in bases:
            if not os.path.isdir(b):
                continue
            for e in sorted(os.listdir(b)):
                p = os.path.join(b, e)
                if not os.path.ismount(p) or e in ("Macintosh HD", "Recovery", user):
                    continue
                if any(p == f[0] for f in found):
                    continue
                found.append((p, e, True))
    res = []
    for path, label, removable in found:
        try:
            du = shutil.disk_usage(path)
            free, total = du.free, du.total
        except Exception:
            free = total = 0
        res.append({"path": path, "label": label, "removable": removable,
                    "free": free, "total": total,
                    "used": round(100 * (1 - free / total)) if total else 0,
                    "hasSwitch": os.path.isdir(os.path.join(path, "switch"))})
    return res


def ports():
    if not REPO or not (REPO / "out").is_dir():
        return []
    res = []
    for f in sorted((REPO / "out").glob("*.nro"), key=lambda p: -p.stat().st_mtime):
        st = f.stat()
        res.append({"file": f.name, "name": re.sub(r"-switch2$", "", f.stem),
                    "size": st.st_size, "date": st.st_mtime})
    return res


def deps():
    """The Python to run nx2-relink with, and what it misses (tools/fetch.py); a copy without fetch.py: this Python, unknown."""
    code = ("import sys, json; sys.path[:0] = [sys.argv[1] + '/tools', sys.argv[1]]; import fetch, nxrelink; "
            "print(json.dumps([fetch.python(), fetch.todo(nxrelink.dkp())]))")
    try:
        r = subprocess.run([sys.executable, "-c", code, str(REPO)], capture_output=True, text=True, timeout=30)
        return json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return sys.executable, []


# --------------------------------------------------------------------------- job runner
class Job:
    def __init__(self):
        self.lock = threading.Lock()
        self.events = []
        self.progress = None
        self.proc = None
        self.code = None
        self.running = False
        self.action = ""

    def add(self, ev):
        with self.lock:
            self.events.append(ev)

    def start(self, args, action, extra_env=None):
        if self.running:
            return False
        self.events, self.progress, self.code, self.running, self.action = [], None, None, True, action
        env = dict(os.environ, NX2_GUI="1", PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", **(extra_env or {}))
        # (setup --auto is run by this Python: the tool's own may be what it replaces)
        py = sys.executable if "--auto" in args else deps()[0]
        cmd = [py, "-u", str(REPO / "nxrelink.py")] + args
        self.add({"t": "log", "s": "$ nxrelink.py " + " ".join(
            f'"{a}"' if " " in a else a for a in args)})
        try:
            self.proc = subprocess.Popen(cmd, cwd=str(REPO), env=env, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        except Exception as e:
            self.add({"t": "log", "s": t("e_launch").format(e=e)})
            self.code, self.running = 1, False
            return True
        threading.Thread(target=self._read, daemon=True).start()
        return True

    def _line(self, line):
        line = line.strip("\x1b").rstrip()
        if not line:
            return
        if line.startswith("@@progress|"):
            parts = line.split("|")
            if len(parts) >= 5:
                try:
                    done, total = float(parts[-2]), float(parts[-1])
                except ValueError:
                    return
                with self.lock:
                    self.progress = {"kind": parts[1], "detail": "|".join(parts[2:-2]),
                                     "done": done, "total": total, "at": time.time()}
            return
        if line.startswith("@@phase|"):
            p = line.split("|", 3)
            if len(p) == 4:
                self.add({"t": "phase", "i": int(p[1]), "n": int(p[2]), "title": p[3]})
                with self.lock:
                    self.progress = None
            return
        m = re.match(r"^== step (\d+) of (\d+): (.*)$", line)
        if m:
            self.add({"t": "phase", "i": int(m[1]), "n": int(m[2]), "title": m[3], "soft": True})
            return
        if line.startswith("@@"):
            return
        self.add({"t": "log", "s": line})

    def _read(self):
        buf = b""
        while True:
            chunk = self.proc.stdout.read1(4096) if hasattr(self.proc.stdout, "read1") \
                else self.proc.stdout.read(1)
            if not chunk:
                break
            buf += chunk
            parts = re.split(rb"[\r\n]", buf)
            buf = parts.pop()
            for p in parts:
                self._line(p.decode("utf-8", "replace"))
        if buf:
            self._line(buf.decode("utf-8", "replace"))
        self.code = self.proc.wait()
        self.running = False
        self.add({"t": "end", "code": self.code})

    def cancel(self):
        if self.proc and self.running:
            try:
                self.proc.terminate()
            except Exception:
                pass


JOB = Job()


def make_args(d):
    game = (d.get("game") or "").strip()
    if not game or not os.path.exists(game):
        raise ValueError(t("e_game"))
    a = ["make", game]
    if d.get("update"):
        if not os.path.exists(d["update"]):
            raise ValueError(t("e_update"))
        a += ["--update", d["update"]]
    for key in ("name", "title", "version", "icon"):
        v = (d.get(key) or "").strip()
        if v:
            a += [f"--{key}", v]
    dest = d.get("dest")
    if dest == "sd":
        if not d.get("sd") or not os.path.isdir(d["sd"]):
            raise ValueError(t("e_sd"))
        a += ["--sd", d["sd"]]
    elif dest == "ftp":
        host = (d.get("ftp") or "").strip()
        if not re.match(r"^[\w.\-]+(:\d+)?$", host):
            raise ValueError(t("e_ftp"))
        if ":" not in host:
            host += ":5000"
        a += ["--ftp", host]
    elif dest == "sw2t":
        a += ["--sw2t", sw2t_host(d)]
    if d.get("nroOnly"):
        a.append("--nro-only")
    return a


def install_args(d):
    name = (d.get("name") or "").strip()
    if not re.match(r"^[\w.\-]+$", name):
        raise ValueError(t("e_name"))
    if d.get("dest") == "sd" and d.get("sd"):
        return ["install", name, "--sd", d["sd"]]
    if d.get("dest") == "ftp" and d.get("ftp"):
        h = d["ftp"].strip()
        return ["install", name, "--ftp", h if ":" in h else h + ":5000"]
    if d.get("dest") == "sw2t" and d.get("sw2t"):
        return ["install", name, "--sw2t", sw2t_host(d)]
    raise ValueError(t("e_dest"))


def sw2t_host(d):
    """SW2Transfer's address on the console (its port 6967 when none is given)."""
    host = (d.get("sw2t") or "").strip()
    if not re.match(r"^[\w.\-]+(:\d+)?$", host):
        raise ValueError(t("e_sw2t"))
    return host if ":" in host else host + ":6967"


def run_env(d):
    """SW2Transfer's password goes to the tool in its environment, never in its arguments (which the log shows)."""
    return {"SW2T_PASSWORD": d["sw2tPw"]} if d.get("dest") == "sw2t" and d.get("sw2tPw") else {}


# --------------------------------------------------------------------------- http
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, obj, code=200, ctype="application/json"):
        body = obj if isinstance(obj, bytes) else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return {}

    def _local(self):
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def do_GET(self):
        if not self._local():
            return self.send({"error": "forbidden"}, 403)
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/":
            choose_lang(self.headers.get("Accept-Language"))
            return self.send(page().encode(), ctype="text/html; charset=utf-8")
        if u.path == "/api/info":
            return self.send({"repo": str(REPO) if REPO else None,
                              "python": sys.version.split()[0], "os": sys.platform})
        if u.path == "/api/missing":
            return self.send(deps()[1] if REPO and os.name == "nt" else [])
        if u.path == "/api/drives":
            return self.send(drives())
        if u.path == "/api/ports":
            return self.send(ports())
        if u.path == "/api/status":
            since = int(q.get("since", ["0"])[0])
            with JOB.lock:
                return self.send({"running": JOB.running, "code": JOB.code, "action": JOB.action,
                                  "events": JOB.events[since:], "next": len(JOB.events),
                                  "progress": JOB.progress, "now": time.time()})
        if u.path == "/api/thumb":
            p = q.get("path", [""])[0]
            t = mimetypes.guess_type(p)[0] or ""
            if t.startswith("image/") and os.path.isfile(p) and os.path.getsize(p) < 20_000_000:
                return self.send(Path(p).read_bytes(), ctype=t)
            return self.send({"error": "no"}, 404)
        self.send({"error": "not found"}, 404)

    def do_POST(self):
        global REPO
        if not self._local() or self.headers.get("X-Nx2") != "1":
            return self.send({"error": "forbidden"}, 403)
        u = urlparse(self.path).path
        d = self.body()
        if u == "/api/pick":
            return self.send(pick(d.get("kind", "file")))
        if u == "/api/repo":
            p = Path(d.get("path", "")).expanduser()
            if p.is_file():
                p = p.parent
            if (p / "nxrelink.py").is_file():
                REPO = p.resolve()
                cfg = load_cfg(); cfg["repo"] = str(REPO); save_cfg(cfg)
                return self.send({"ok": True, "repo": str(REPO)})
            return self.send({"ok": False, "error": t("e_repo")})
        if u == "/api/lang":
            if d.get("lang") not in LOCALES:
                return self.send({"ok": False}, 400)
            cfg = load_cfg(); cfg["lang"] = d["lang"]; save_cfg(cfg)
            set_lang(d["lang"])
            return self.send({"ok": True})
        if u == "/api/exists":
            p = d.get("path", "")
            return self.send({"exists": os.path.exists(p), "dir": os.path.isdir(p),
                              "name": os.path.basename(p.rstrip("/\\")) or p})
        if u == "/api/cancel":
            JOB.cancel()
            return self.send({"ok": True})
        if u == "/api/run":
            if not REPO:
                return self.send({"ok": False, "error": t("e_norepo")})
            try:
                act = d.get("action")
                if act == "make":
                    args = make_args(d)
                elif act == "setup":
                    args = ["setup"]
                elif act == "auto":
                    args = ["setup", "--auto"]
                elif act == "install":
                    args = install_args(d)
                else:
                    raise ValueError(t("e_action"))
            except ValueError as e:
                return self.send({"ok": False, "error": str(e)})
            if not JOB.start(args, act, run_env(d)):
                return self.send({"ok": False, "error": t("e_busy")})
            return self.send({"ok": True})
        self.send({"error": "not found"}, 404)


def free_port(pref=8765):
    for p in [pref] + list(range(pref + 1, pref + 40)):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return 0


def main():
    port = free_port()
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    port = srv.server_address[1]
    url = f"http://127.0.0.1:{port}/"
    print(f"\n  {t('con_ready')}  {url}\n  {t('con_quit')}\n")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        JOB.cancel()
        print(f"\n  {t('con_bye')}")


# --------------------------------------------------------------------------- page
PAGE = r"""<!DOCTYPE html>
<html lang="%%LANG%%"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>nx2-relink Easy</title>
<style>
:root{
  --bg:#07070e; --fg:#f3f3fa; --mute:#9a9ab3; --line:rgba(255,255,255,.09);
  --card:rgba(20,20,36,.62); --card2:rgba(255,255,255,.04);
  --a1:#ff3d6e; --a2:#22d3ee; --a3:#8b5cf6; --ok:#34d399; --bad:#f87171;
  --r:20px; --ease:cubic-bezier(.2,.8,.2,1);
}
*{box-sizing:border-box;margin:0;padding:0}
[hidden]{display:none!important}
html,body{min-height:100%;background:var(--bg);color:var(--fg);
  font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,Ubuntu,sans-serif;-webkit-font-smoothing:antialiased}
button,input{font:inherit;color:inherit}
button{cursor:pointer;border:0;background:none}
::selection{background:var(--a3)}

/* ---------- animated background ---------- */
.bg{position:fixed;inset:0;overflow:hidden;z-index:0;pointer-events:none}
header,main{position:relative;z-index:1}
body{background:transparent!important}
.blob{position:absolute;width:55vmax;height:55vmax;border-radius:50%;filter:blur(90px);opacity:.38;
  animation:float 22s var(--ease) infinite alternate}
.blob.b1{background:var(--a1);top:-25vmax;left:-15vmax}
.blob.b2{background:var(--a2);bottom:-30vmax;right:-20vmax;animation-delay:-7s;animation-duration:26s}
.blob.b3{background:var(--a3);top:30%;left:40%;width:35vmax;height:35vmax;opacity:.25;animation-delay:-13s}
@keyframes float{0%{transform:translate(0,0) scale(1)}50%{transform:translate(6vmax,4vmax) scale(1.12)}
  100%{transform:translate(-4vmax,7vmax) scale(.92)}}
.grid{position:absolute;inset:0;background-image:linear-gradient(var(--line) 1px,transparent 1px),
  linear-gradient(90deg,var(--line) 1px,transparent 1px);background-size:56px 56px;
  mask-image:radial-gradient(ellipse at 50% 30%,#000 10%,transparent 70%);opacity:.5}
body.busy .blob{animation-duration:6s}

/* ---------- layout ---------- */
header{display:flex;align-items:center;gap:14px;padding:22px 28px;max-width:1000px;margin:0 auto}
.logo{display:flex;align-items:center;gap:12px;font-weight:750;font-size:18px;letter-spacing:-.01em}
.mark{width:38px;height:38px;border-radius:12px;position:relative;
  background:linear-gradient(135deg,var(--a1),var(--a3) 60%,var(--a2));box-shadow:0 8px 30px -8px var(--a1)}
.mark::before,.mark::after{content:"";position:absolute;top:8px;bottom:8px;width:9px;border-radius:6px;background:#0b0b14}
.mark::before{left:8px}.mark::after{right:8px}
.mark i{position:absolute;inset:0;border-radius:inherit;background:inherit;filter:blur(12px);opacity:.6;animation:pulse 3s infinite}
@keyframes pulse{50%{opacity:.15}}
.logo small{display:block;font-size:12px;color:var(--mute);font-weight:500}
.spacer{flex:1}
.ghost{padding:9px 14px;border-radius:12px;border:1px solid var(--line);background:var(--card2);color:var(--mute);
  transition:.25s var(--ease)}
select.ghost{font:inherit;appearance:auto;cursor:pointer}
select.ghost option{background:#0e0e1a;color:var(--fg)}
@media (max-width:640px){header{flex-wrap:wrap;padding:16px}.spacer{display:none}}
.ghost:hover{color:var(--fg);border-color:rgba(255,255,255,.22);transform:translateY(-1px)}
main{max-width:760px;margin:0 auto;padding:8px 20px 80px}
.view{display:none}.view.on{display:block}
.hero{text-align:center;margin:18px 0 30px}
.hero h1{font-size:clamp(28px,5vw,42px);line-height:1.1;letter-spacing:-.03em;font-weight:800}
.grad{background:linear-gradient(90deg,var(--a1),var(--a3),var(--a2),var(--a1));background-size:300% 100%;
  -webkit-background-clip:text;background-clip:text;color:transparent;animation:slide 8s linear infinite}
@keyframes slide{to{background-position:300% 0}}
.hero p{color:var(--mute);margin-top:10px}

/* ---------- cards ---------- */
.card{position:relative;background:var(--card);border:1px solid var(--line);border-radius:var(--r);
  padding:22px;margin-bottom:16px;backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);
  opacity:0;transform:translateY(18px);animation:in .7s var(--ease) forwards;transition:border-color .4s}
.card:nth-child(2){animation-delay:.08s}.card:nth-child(3){animation-delay:.16s}.card:nth-child(4){animation-delay:.24s}
@keyframes in{to{opacity:1;transform:none}}
.card.done{border-color:rgba(52,211,153,.35)}
.ch{display:flex;align-items:center;gap:14px;margin-bottom:16px}
.num{width:34px;height:34px;flex:none;border-radius:50%;display:grid;place-items:center;font-weight:700;
  background:var(--card2);border:1px solid var(--line);transition:.4s var(--ease)}
.card.done .num{background:var(--ok);border-color:var(--ok);color:#052e1f;transform:rotate(360deg)}
.ch h2{font-size:17px;font-weight:700;letter-spacing:-.01em}
.ch p{font-size:13px;color:var(--mute)}
.row{display:flex;gap:10px;flex-wrap:wrap}
.pick{flex:1 1 200px;display:flex;align-items:center;gap:12px;padding:16px;border-radius:16px;text-align:left;
  background:var(--card2);border:1px dashed rgba(255,255,255,.16);transition:.3s var(--ease)}
.pick:hover{border-style:solid;border-color:var(--a2);background:rgba(34,211,238,.07);transform:translateY(-2px)}
.pick b{display:block;font-weight:650}.pick span{font-size:12.5px;color:var(--mute)}
.ico{width:40px;height:40px;flex:none;border-radius:12px;display:grid;place-items:center;
  background:linear-gradient(135deg,rgba(255,61,110,.2),rgba(139,92,246,.2))}
.ico svg{width:20px;height:20px}
.chip{display:flex;align-items:center;gap:14px;padding:14px 16px;border-radius:16px;margin-top:10px;
  background:linear-gradient(135deg,rgba(34,211,238,.1),rgba(139,92,246,.1));border:1px solid rgba(34,211,238,.3);
  animation:pop .5s var(--ease)}
@keyframes pop{from{opacity:0;transform:scale(.94)}}
.chip .t{flex:1;min-width:0}.chip b{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.chip small{display:block;color:var(--mute);font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.x{width:30px;height:30px;border-radius:9px;color:var(--mute);transition:.2s}.x:hover{background:rgba(255,255,255,.08);color:var(--fg)}
.link{color:var(--a2);font-size:13.5px;margin-top:12px;display:inline-flex;gap:6px;align-items:center}
.link:hover{text-decoration:underline}
.manual{display:flex;gap:8px;margin-top:10px}
.in{flex:1;padding:12px 14px;border-radius:12px;background:rgba(0,0,0,.3);border:1px solid var(--line);outline:0;transition:.25s}
.in:focus{border-color:var(--a2);box-shadow:0 0 0 4px rgba(34,211,238,.12)}
label.f{display:block;font-size:12.5px;color:var(--mute);margin:0 0 6px 2px}

/* segmented */
.seg{display:grid;grid-template-columns:repeat(4,1fr);position:relative;padding:5px;border-radius:15px;
  background:rgba(0,0,0,.3);border:1px solid var(--line);margin-bottom:14px}
.seg button{position:relative;z-index:1;padding:10px 6px;border-radius:11px;color:var(--mute);font-weight:600;font-size:14px;transition:color .3s}
.seg button.on{color:var(--fg)}
.seg .pill{position:absolute;top:5px;bottom:5px;left:5px;width:calc((100% - 10px)/4);border-radius:11px;
  background:linear-gradient(135deg,var(--a1),var(--a3));box-shadow:0 6px 24px -6px var(--a1);transition:transform .45s var(--ease)}
.pane{animation:pop .4s var(--ease)}
.drives{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:10px}
.drive{padding:14px;border-radius:15px;background:var(--card2);border:1px solid var(--line);text-align:left;transition:.3s var(--ease)}
.drive:hover{transform:translateY(-2px);border-color:rgba(255,255,255,.25)}
.drive.on{border-color:var(--a2);background:rgba(34,211,238,.09);box-shadow:0 0 0 3px rgba(34,211,238,.12)}
.drive b{display:flex;align-items:center;gap:8px}.drive small{color:var(--mute);font-size:12px}
.bar{height:5px;border-radius:5px;background:rgba(255,255,255,.08);margin-top:9px;overflow:hidden}
.bar i{display:block;height:100%;background:linear-gradient(90deg,var(--a2),var(--a3));border-radius:inherit}
.tag{font-size:10.5px;padding:2px 7px;border-radius:20px;background:rgba(52,211,153,.15);color:var(--ok);font-weight:600}
.empty{padding:16px;border-radius:15px;border:1px dashed var(--line);color:var(--mute);font-size:13.5px;text-align:center}
.hint{font-size:12.5px;color:var(--mute);margin-top:8px}

/* collapsible */
.fold{display:grid;grid-template-rows:0fr;transition:grid-template-rows .5s var(--ease)}
.fold.open{grid-template-rows:1fr}.fold>div{overflow:hidden}
.toggle-h{width:100%;text-align:left;display:flex;align-items:center;gap:14px}
.chev{margin-left:auto;transition:transform .4s var(--ease);color:var(--mute)}
.card.opened .chev{transform:rotate(180deg)}
.card.opened .ch{margin-bottom:16px}.card.fd .ch{margin-bottom:0}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px}
@media(max-width:560px){.g2{grid-template-columns:1fr}.seg button{font-size:12.5px}}
.iconrow{display:flex;align-items:center;gap:12px;margin-bottom:12px}
.thumb{width:64px;height:64px;border-radius:16px;background:var(--card2) center/cover;border:1px solid var(--line);
  display:grid;place-items:center;color:var(--mute);flex:none}
.sw{display:flex;align-items:center;gap:12px;padding:12px 0;cursor:pointer}
.sw input{display:none}
.sw .k{width:44px;height:26px;border-radius:20px;background:rgba(255,255,255,.12);position:relative;transition:.3s;flex:none}
.sw .k::after{content:"";position:absolute;top:3px;left:3px;width:20px;height:20px;border-radius:50%;background:#fff;transition:.35s var(--ease)}
.sw input:checked+.k{background:var(--ok)}.sw input:checked+.k::after{transform:translateX(18px)}
.sw small{display:block;color:var(--mute);font-size:12.5px}

/* CTA */
.cta{position:relative;width:100%;padding:19px;border-radius:18px;font-size:17px;font-weight:750;letter-spacing:-.01em;
  color:#fff;background:linear-gradient(135deg,var(--a1),var(--a3) 55%,var(--a2));background-size:200% 200%;
  box-shadow:0 18px 50px -18px var(--a1);overflow:hidden;transition:transform .3s var(--ease),filter .3s,opacity .3s;
  animation:in .7s .32s var(--ease) backwards, hue 6s ease infinite}
@keyframes hue{50%{background-position:100% 100%}}
.cta::after{content:"";position:absolute;top:0;left:-60%;width:40%;height:100%;
  background:linear-gradient(100deg,transparent,rgba(255,255,255,.35),transparent);transform:skewX(-20deg);animation:shine 3.2s infinite}
@keyframes shine{60%,100%{left:130%}}
.cta:hover{transform:translateY(-2px) scale(1.01)}
.cta:disabled{filter:grayscale(.9) brightness(.6);transform:none;cursor:not-allowed}
.cta:disabled::after{display:none}
.err{color:var(--bad);font-size:13.5px;text-align:center;margin-top:12px;min-height:20px}
.shake{animation:shake .45s}
@keyframes shake{20%,60%{transform:translateX(-7px)}40%,80%{transform:translateX(7px)}}

/* ---------- run view ---------- */
.stage{text-align:center;padding:30px 22px}
.ring{position:relative;width:220px;height:220px;margin:4px auto 22px}
.ring svg{width:100%;height:100%;transform:rotate(-90deg)}
.ring circle{fill:none;stroke-width:10}
.ring .trk{stroke:rgba(255,255,255,.07)}
.ring .val{stroke:url(#gr);stroke-linecap:round;stroke-dasharray:597;stroke-dashoffset:597;transition:stroke-dashoffset .6s var(--ease)}
.ring .spin{stroke:rgba(255,255,255,.18);stroke-dasharray:60 540;animation:rot 1.4s linear infinite;transform-origin:center}
@keyframes rot{to{transform:rotate(360deg)}}
.ring .mid{position:absolute;inset:0;display:grid;place-items:center;align-content:center}
.pct{font-size:46px;font-weight:800;letter-spacing:-.04em;font-variant-numeric:tabular-nums}
.pct small{font-size:20px;color:var(--mute)}
.stepn{font-size:12.5px;color:var(--mute);text-transform:uppercase;letter-spacing:.12em}
.ring .glow{position:absolute;inset:25px;border-radius:50%;background:radial-gradient(circle,rgba(139,92,246,.35),transparent 70%);animation:pulse 2.2s infinite}
.ptitle{font-size:21px;font-weight:700;letter-spacing:-.01em;min-height:30px}
.pdetail{color:var(--mute);font-size:13.5px;min-height:22px;margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.stats{display:flex;justify-content:center;gap:12px;margin-top:16px;flex-wrap:wrap}
.stat{padding:8px 14px;border-radius:12px;background:var(--card2);border:1px solid var(--line);font-size:13px;color:var(--mute)}
.stat b{color:var(--fg);font-variant-numeric:tabular-nums}
.phases{list-style:none;text-align:left;margin-top:24px;display:grid;gap:8px}
.phases li{display:flex;align-items:center;gap:12px;padding:12px 14px;border-radius:14px;background:var(--card2);
  border:1px solid var(--line);animation:slidein .5s var(--ease)}
@keyframes slidein{from{opacity:0;transform:translateX(-16px)}}
.phases .d{width:22px;height:22px;border-radius:50%;flex:none;display:grid;place-items:center;border:2px solid rgba(255,255,255,.2)}
.phases li.act{border-color:rgba(139,92,246,.5);background:rgba(139,92,246,.1)}
.phases li.act .d{border-color:var(--a3);border-top-color:transparent;animation:rot .8s linear infinite}
.phases li.ok .d{background:var(--ok);border-color:var(--ok);color:#052e1f}
.phases li.ko .d{background:var(--bad);border-color:var(--bad);color:#300}
.cons{margin-top:16px;text-align:left}
.log{margin-top:10px;max-height:0;overflow:auto;background:rgba(0,0,0,.45);border-radius:14px;border:1px solid transparent;
  font:12px/1.55 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;color:#c8c8dc;white-space:pre-wrap;word-break:break-all;
  transition:max-height .5s var(--ease),padding .5s,border-color .5s}
.log:not(.open){border-width:0;overflow:hidden}
.log.open{max-height:300px;padding:12px 14px;border-color:var(--line)}
.btns{display:flex;gap:10px;justify-content:center;margin-top:22px;flex-wrap:wrap}
.btn{padding:12px 20px;border-radius:14px;font-weight:650;background:var(--card2);border:1px solid var(--line);transition:.25s var(--ease)}
.btn:hover{transform:translateY(-2px);border-color:rgba(255,255,255,.25)}
.btn.pri{background:linear-gradient(135deg,var(--a1),var(--a3));border:0;box-shadow:0 10px 30px -10px var(--a1)}

/* result */
.res{width:110px;height:110px;margin:6px auto 18px;border-radius:50%;display:grid;place-items:center;animation:popin .7s var(--ease)}
@keyframes popin{0%{transform:scale(0)}60%{transform:scale(1.12)}100%{transform:scale(1)}}
.res.ok{background:radial-gradient(circle,rgba(52,211,153,.3),rgba(52,211,153,.06));box-shadow:0 0 0 10px rgba(52,211,153,.06),0 0 60px rgba(52,211,153,.3)}
.res.ko{background:radial-gradient(circle,rgba(248,113,113,.3),rgba(248,113,113,.06));box-shadow:0 0 0 10px rgba(248,113,113,.06)}
.res svg{width:54px;height:54px}
.res path{stroke-dasharray:60;stroke-dashoffset:60;animation:draw .6s .35s var(--ease) forwards}
@keyframes draw{to{stroke-dashoffset:0}}
.res h2{display:none}
.steps{text-align:left;margin:22px auto 0;max-width:470px;display:grid;gap:10px;counter-reset:s}
.steps div{display:flex;gap:12px;align-items:flex-start;padding:12px 14px;border-radius:14px;background:var(--card2);border:1px solid var(--line);
  opacity:0;animation:in .6s var(--ease) forwards}
.steps div:nth-child(2){animation-delay:.12s}.steps div:nth-child(3){animation-delay:.24s}
.steps div::before{counter-increment:s;content:counter(s);flex:none;width:24px;height:24px;border-radius:50%;display:grid;place-items:center;
  font-size:12px;font-weight:700;background:linear-gradient(135deg,var(--a1),var(--a3))}
kbd{padding:1px 7px;border-radius:6px;background:rgba(255,255,255,.1);border:1px solid var(--line);font:12px ui-monospace,monospace}
#confetti{position:fixed;inset:0;pointer-events:none;z-index:50}

/* drawer */
.scrim{position:fixed;inset:0;background:rgba(0,0,0,.5);backdrop-filter:blur(4px);opacity:0;pointer-events:none;transition:.35s;z-index:20}
.scrim.on{opacity:1;pointer-events:auto}
.drawer{position:fixed;top:0;right:0;bottom:0;width:min(420px,92vw);background:#0e0e1a;border-left:1px solid var(--line);
  transform:translateX(105%);transition:transform .5s var(--ease);z-index:21;padding:24px;overflow:auto}
.drawer.on{transform:none}
.drawer h3{font-size:19px;margin-bottom:4px}
.port{display:flex;align-items:center;gap:12px;padding:13px;border-radius:14px;background:var(--card2);border:1px solid var(--line);margin-top:10px;
  animation:slidein .4s var(--ease) backwards}
.port .t{flex:1;min-width:0}.port small{color:var(--mute);font-size:12px;display:block}
.sm{padding:7px 11px;border-radius:10px;font-size:12.5px;font-weight:600;background:rgba(34,211,238,.12);color:var(--a2)}
.sm:hover{background:rgba(34,211,238,.22)}
.toast{position:fixed;left:50%;bottom:26px;transform:translate(-50%,30px);opacity:0;padding:12px 18px;border-radius:14px;
  background:#1b1b2e;border:1px solid var(--line);box-shadow:0 20px 40px -10px #000;transition:.45s var(--ease);z-index:60;font-size:14px}
.toast.on{opacity:1;transform:translate(-50%,0)}
.warn{font-size:12.5px;color:var(--mute);text-align:center;margin-top:20px;opacity:.8}
@media (prefers-reduced-motion:reduce){*{animation-duration:.01ms!important;animation-iteration-count:1!important;transition-duration:.01ms!important}}
</style></head>
<body>
<div class="bg"><div class="grid"></div><div class="blob b1"></div><div class="blob b2"></div><div class="blob b3"></div></div>
<canvas id="confetti"></canvas>

<header>
  <div class="logo"><div class="mark"><i></i></div><div>nx2-relink <span class="grad">Easy</span><small>{{tagline}}</small></div></div>
  <div class="spacer"></div>
  <select class="ghost" id="sLang" title="{{language}}" aria-label="{{language}}">%%LANGS%%</select>
  <button class="ghost" id="bSetup" title="{{setup_title}}">{{setup_btn}}</button>
  <button class="ghost" id="bPorts">{{my_ports}}</button>
</header>

<main>
<!-- ================= repo setup ================= -->
<section class="view" id="vRepo">
  <div class="hero"><h1>{{repo_h1}}</h1>
    <p>{{repo_p}}</p></div>
  <div class="card">
    <button class="pick" id="pRepo" style="width:100%"><div class="ico">%%FOLDER%%</div><div><b>{{choose_folder}}</b><span>{{repo_from_github}}</span></div></button>
    <div class="manual"><input class="in" id="iRepo" placeholder="{{paste_path_here}}"><button class="btn" id="okRepo">OK</button></div>
    <div class="err" id="eRepo"></div>
  </div>
</section>

<!-- ================= wizard ================= -->
<section class="view" id="vMain">
  <div class="hero"><h1>{{main_h1}}</h1>
    <p>{{main_p}}</p></div>

  <div class="card" id="cMiss" hidden style="margin-bottom:16px">
    <div class="ch"><div class="num">!</div><div><h2>{{miss_h}}</h2><p id="missList"></p></div></div>
    <p class="hint">{{miss_p}}</p>
    <button class="btn pri" id="bAuto">{{miss_btn}}</button>
  </div>

  <div id="cards">
  <div class="card" id="c1">
    <div class="ch"><div class="num">1</div><div><h2>{{s1_h}}</h2><p>{{s1_p}}</p></div></div>
    <div id="gamePick" class="row">
      <button class="pick" data-pick="nup" data-to="game"><div class="ico">%%FILE%%</div><div><b>{{nup_file}}</b><span>{{single_file}}</span></div></button>
      <button class="pick" data-pick="folder" data-to="game"><div class="ico">%%FOLDER%%</div><div><b>{{folder}}</b><span>exefs/ + romfs/</span></div></button>
    </div>
    <div id="gameChip"></div>
    <div id="updBox"></div>
    <div class="manual" id="mGame" hidden><input class="in" id="iGame" placeholder="{{game_path}}"><button class="btn" data-manual="game">OK</button></div>
  </div>

  <div class="card" id="c2">
    <div class="ch"><div class="num">2</div><div><h2>{{s2_h}}</h2><p>{{s2_p}}</p></div></div>
    <div class="seg" id="seg"><div class="pill"></div>
      <button data-d="sd" class="on">{{sd_card}}</button><button data-d="ftp">Wi-Fi (FTP)</button><button data-d="sw2t">SW2Transfer</button><button data-d="none">{{just_build}}</button></div>
    <div id="destPane"></div>
  </div>

  <div class="card fd" id="c3">
    <button class="toggle-h ch" id="t3"><div class="num">3</div><div><h2>{{s3_h}} <span style="color:var(--mute);font-weight:500">· {{optional}}</span></h2><p>{{s3_p}}</p></div>
      <svg class="chev" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m6 9 6 6 6-6"/></svg></button>
    <div class="fold" id="f3"><div>
      <div class="iconrow"><div class="thumb" id="thumb">%%IMAGE%%</div>
        <div><button class="sm" data-pick="image" data-to="icon">{{choose_icon}}</button>
        <button class="sm" id="clrIcon" style="background:transparent;color:var(--mute)" hidden>{{remove}}</button>
        <div class="hint">{{square_image}}</div></div></div>
      <div class="g2">
        <div><label class="f">{{shown_name}}</label><input class="in" id="iTitle" placeholder="{{like_game}}" style="width:100%"></div>
        <div><label class="f">{{version}}</label><input class="in" id="iVersion" placeholder="{{like_game}}" style="width:100%"></div>
      </div>
      <div><label class="f">{{card_folder}}</label><input class="in" id="iName" placeholder="{{automatic}}" style="width:100%"></div>
      <label class="sw"><input type="checkbox" id="iNro"><span class="k"></span><span>{{nro_only}}<small>{{nro_only_p}}</small></span></label>
    </div></div>
  </div>
  </div>

  <button class="cta" id="go" disabled>{{go_default}}</button>
  <div class="err" id="eMain"></div>
  <p class="warn">{{warn}}</p>
</section>

<!-- ================= running ================= -->
<section class="view" id="vRun">
  <div class="card stage">
    <div class="ring"><div class="glow"></div>
      <svg viewBox="0 0 220 220"><defs><linearGradient id="gr" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#ff3d6e"/><stop offset=".55" stop-color="#8b5cf6"/><stop offset="1" stop-color="#22d3ee"/></linearGradient></defs>
        <circle class="trk" cx="110" cy="110" r="95"/><circle class="spin" id="spin" cx="110" cy="110" r="95"/><circle class="val" id="val" cx="110" cy="110" r="95"/></svg>
      <div class="mid"><div class="pct" id="pct">0<small>%</small></div><div class="stepn" id="stepn">{{starting}}</div></div>
    </div>
    <div class="ptitle" id="ptitle">{{preparing}}</div>
    <div class="pdetail" id="pdetail"></div>
    <div class="stats" id="stats"></div>
    <ul class="phases" id="phases"></ul>
    <div class="cons"><button class="link" id="tLog">{{show_details}}</button><div class="log" id="log"></div></div>
    <div class="btns"><button class="btn" id="cancel">{{cancel}}</button></div>
  </div>
</section>

<!-- ================= result ================= -->
<section class="view" id="vEnd">
  <div class="card stage" id="endCard"></div>
</section>
</main>

<div class="scrim" id="scrim"></div>
<aside class="drawer" id="drawer">
  <div style="display:flex;align-items:center"><div><h3>{{my_ports}}</h3><p class="hint" style="margin:0">{{ports_p}}</p></div>
  <div class="spacer"></div><button class="x" id="closeD">✕</button></div>
  <div id="portList"></div>
</aside>
<div class="toast" id="toast"></div>

<script>
const LANG=%%LANGJS%%,T=%%L10N%%;
const fill=(s,o)=>s.replace(/\{(\w+)\}/g,(m,k)=>k in o?o[k]:m);
const $=s=>document.querySelector(s), $$=s=>[...document.querySelectorAll(s)];
const IC={file:`%%FILE%%`,folder:`%%FOLDER%%`,upd:`%%UPD%%`,sd:`%%SD%%`};
const S={game:'',gameDir:false,update:'',dest:'sd',sd:'',ftp:'',sw2t:'',sw2tPw:'',icon:'',noTk:false};
try{const o=JSON.parse(localStorage.getItem('nx2easy')||'{}');S.ftp=o.ftp||'';S.sw2t=o.sw2t||'';S.dest=o.dest||'sd';S.sd=o.sd||''}catch(e){}
const persist=()=>{try{localStorage.setItem('nx2easy',JSON.stringify({ftp:S.ftp,sw2t:S.sw2t,dest:S.dest,sd:S.sd}))}catch(e){}};
const esc=s=>String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const base=p=>p.replace(/[\\/]+$/,'').split(/[\\/]/).pop()||p;
async function api(path,body){const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json','X-Nx2':'1'},body:JSON.stringify(body)}:{});return r.json()}
function toast(m){const t=$('#toast');t.textContent=m;t.classList.add('on');clearTimeout(t._h);t._h=setTimeout(()=>t.classList.remove('on'),2600)}
function show(id){$$('.view').forEach(v=>v.classList.toggle('on',v.id===id));
  if(id==='vMain')$$('#vMain .card').forEach(c=>{c.style.animation='none';c.offsetHeight;c.style.animation=''});
  document.body.classList.toggle('busy',id==='vRun');window.scrollTo({top:0,behavior:'smooth'})}

/* ---------- pickers ---------- */
async function doPick(kind,to){
  if(S.noTk){manualFor(to);return}
  const r=await api('/api/pick',{kind});
  if(r.notk){S.noTk=true;toast(T.no_picker);manualFor(to);return}
  if(r.path)setVal(to,r.path,kind==='folder');
}
function manualFor(to){
  if(to==='game'){$('#mGame').hidden=false;$('#iGame').focus();return}
  const p=prompt(T.paste_full);if(p)setVal(to,p.trim().replace(/^"|"$/g,''));
}
async function setVal(to,path,isDir){
  const ex=await api('/api/exists',{path});
  if(!ex.exists){toast(T.path_not_found);return}
  if(to==='game'){S.game=path;S.gameDir=ex.dir}
  else if(to==='update')S.update=path;
  else if(to==='sd'){S.sd=path;persist()}
  else if(to==='icon')S.icon=path;
  render();
}
document.addEventListener('click',e=>{
  const b=e.target.closest('[data-pick]');if(b){doPick(b.dataset.pick,b.dataset.to);return}
  const m=e.target.closest('[data-manual]');if(m){const v=$('#iGame').value.trim().replace(/^"|"$/g,'');if(v)setVal('game',v)}
});

/* ---------- render wizard ---------- */
function chip(icon,name,path,clear){return `<div class="chip"><div class="ico">${icon}</div><div class="t"><b>${esc(name)}</b><small>${esc(path)}</small></div><button class="x" data-clear="${clear}" title="${T.change}">✕</button></div>`}
document.addEventListener('click',e=>{const c=e.target.closest('[data-clear]');if(!c)return;
  const k=c.dataset.clear;if(k==='game'){S.game='';S.update=''}else S[k]='';render()});
let drv=[];
async function loadDrives(){drv=await api('/api/drives');if(!S.sd&&drv.length===1){S.sd=drv[0].path;persist()}renderDest()}
function renderDest(){
  const P=$('#destPane'),i=['sd','ftp','sw2t','none'].indexOf(S.dest);
  $('#seg .pill').style.transform=`translateX(${i*100}%)`;
  $$('#seg button').forEach(b=>b.classList.toggle('on',b.dataset.d===S.dest));
  if(S.dest==='sd'){
    const known=drv.some(d=>d.path===S.sd);
    P.innerHTML=`<div class="pane"><div class="drives">${drv.map(d=>`<button class="drive ${d.path===S.sd?'on':''}" data-drive="${esc(d.path)}">
      <b>${IC.sd}${esc(d.label)} ${d.hasSwitch?'<span class="tag">homebrew</span>':''}</b><small>${esc(d.path)}${d.total?' · '+fmtB(d.free)+' '+T.free:''}</small>
      <div class="bar"><i style="width:${d.used}%"></i></div></button>`).join('')||'<div class="empty">'+T.no_card+'</div>'}</div>
      ${S.sd&&!known?chip(IC.folder,base(S.sd),S.sd,'sd'):''}
      <div style="display:flex;gap:16px"><button class="link" id="rDrv">↻ ${T.refresh}</button><button class="link" data-pick="folder" data-to="sd">${T.other_folder}</button></div></div>`;
    $('#rDrv').onclick=()=>{toast(T.searching);loadDrives()};
    $$('[data-drive]').forEach(b=>b.onclick=()=>{S.sd=b.dataset.drive;persist();render()});
  }else if(S.dest==='ftp'){
    P.innerHTML=`<div class="pane"><label class="f">${T.console_addr}</label>
      <input class="in" id="iFtp" style="width:100%" placeholder="${T.eg} 192.168.1.42" value="${esc(S.ftp)}">
      <p class="hint">${T.ftp_hint}</p></div>`;
    $('#iFtp').oninput=e=>{S.ftp=e.target.value.trim();persist();check()};
  }else if(S.dest==='sw2t'){
    P.innerHTML=`<div class="pane"><label class="f">${T.console_addr}</label>
      <input class="in" id="iSw2t" style="width:100%" placeholder="${T.eg} 192.168.1.42" value="${esc(S.sw2t)}">
      <label class="f" style="margin-top:12px">${T.sw2t_pw}</label>
      <input class="in" id="iSw2tPw" type="password" autocomplete="off" style="width:100%" value="${esc(S.sw2tPw)}">
      <p class="hint">${T.sw2t_hint}</p></div>`;
    $('#iSw2t').oninput=e=>{S.sw2t=e.target.value.trim();persist();check()};
    $('#iSw2tPw').oninput=e=>{S.sw2tPw=e.target.value};
  }else{
    P.innerHTML=`<div class="pane empty">${T.none_hint}</div>`;
  }
}
$$('#seg button').forEach(b=>b.onclick=()=>{S.dest=b.dataset.d;persist();render()});
function render(){
  $('#gamePick').hidden=!!S.game;$('#mGame').hidden=S.noTk&&!S.game?false:true;
  $('#gameChip').innerHTML=S.game?chip(S.gameDir?IC.folder:IC.file,base(S.game),S.game,'game'):'';
  $('#updBox').innerHTML=!S.game?'':S.update?chip(IC.upd,T.update_label+base(S.update),S.update,'update')
    :`<div style="display:flex;gap:16px;flex-wrap:wrap"><button class="link" data-pick="nup" data-to="update">${T.add_update}</button><button class="link" data-pick="folder" data-to="update">${T.add_update_dir}</button></div>`;
  const th=$('#thumb');
  if(S.icon){th.style.backgroundImage=`url('/api/thumb?path=${encodeURIComponent(S.icon)}')`;th.innerHTML='';$('#clrIcon').hidden=false}
  else{th.style.backgroundImage='';th.innerHTML=`%%IMAGE%%`;$('#clrIcon').hidden=true}
  renderDest();check();
}
$('#clrIcon').onclick=()=>{S.icon='';render()};
function check(){
  const ok1=!!S.game, ok2=S.dest==='none'||(S.dest==='sd'&&!!S.sd)||(S.dest==='ftp'&&/^[\w.\-]+(:\d+)?$/.test(S.ftp))||(S.dest==='sw2t'&&/^[\w.\-]+(:\d+)?$/.test(S.sw2t));
  $('#c1').classList.toggle('done',ok1);$('#c2').classList.toggle('done',ok2);
  $('#c3').classList.toggle('done',!!(S.icon||$('#iTitle').value||$('#iVersion').value||$('#iName').value));
  const g=$('#go');g.disabled=!(ok1&&ok2);
  g.textContent=S.dest==='none'?T.go_none:S.dest==='ftp'||S.dest==='sw2t'?T.go_ftp:T.go_sd;
}
['#iTitle','#iVersion','#iName'].forEach(s=>$(s).oninput=check);
$('#t3').onclick=()=>{const c=$('#c3');c.classList.toggle('opened');c.classList.toggle('fd');$('#f3').classList.toggle('open')};

/* ---------- run ---------- */
let since=0,phaseList=[],lastP=null,speed=0,pollH,lastAction='';
async function run(body){
  const r=await api('/api/run',body);
  if(!r.ok){const e=$('#eMain');e.textContent=r.error;$('#go').classList.remove('shake');void $('#go').offsetWidth;$('#go').classList.add('shake');
    if(!$('#vMain').classList.contains('on'))toast(r.error);return}
  lastAction=body.action;since=0;phaseList=[];lastP=null;speed=0;
  $('#phases').innerHTML='';$('#log').textContent='';$('#stats').innerHTML='';$('#pdetail').textContent='';
  $('#ptitle').textContent=body.action==='auto'?T.miss_run:body.action==='setup'?T.checking_setup:T.preparing;
  $('#stepn').textContent=T.starting;setPct(0,true);$('#cancel').disabled=false;
  show('vRun');poll();
}
$('#go').onclick=()=>{$('#eMain').textContent='';
  run({action:'make',game:S.game,update:S.update,dest:S.dest,sd:S.sd,ftp:S.ftp,sw2t:S.sw2t,sw2tPw:S.sw2tPw,icon:S.icon,
    title:$('#iTitle').value,version:$('#iVersion').value,name:$('#iName').value,nroOnly:$('#iNro').checked})};
$('#bSetup').onclick=()=>run({action:'setup'});
$('#bAuto').onclick=()=>run({action:'auto'});
async function checkMissing(){
  let m=[];try{m=await api('/api/missing')}catch(e){}
  $('#cMiss').hidden=!m.length;$('#missList').textContent=m.map(k=>T['m_'+k]||k).join(' · ');
}
$('#cancel').onclick=async()=>{$('#cancel').disabled=true;await api('/api/cancel',{});toast(T.cancelling)};
$('#tLog').onclick=()=>{const l=$('#log');l.classList.toggle('open');$('#tLog').textContent=l.classList.contains('open')?T.hide_details:T.show_details;l.scrollTop=l.scrollHeight};

let cur={i:0,n:0};
function setPct(p,indet){const v=$('#val'),sp=$('#spin');
  v.style.strokeDashoffset=597*(1-Math.max(0,Math.min(1,p)));sp.style.display=indet?'':'none';
  $('#pct').innerHTML=indet&&p===0?'<span style="font-size:30px">···</span>':`${Math.round(p*100)}<small>%</small>`}
function fmtB(n){const u=T.units.split(',');let i=0;while(n>=1024&&i<3){n/=1024;i++}return (i?n.toFixed(1):n.toFixed(0))+' '+u[i]}
function fmtT(s){if(!isFinite(s)||s<0)return'—';s=Math.round(s);const m=Math.floor(s/60);return m?`${m} min ${String(s%60).padStart(2,'0')} s`:`${s} s`}
const PH=[[/^downloading/,'ph_download'],[/^done\b/,'ph_done'],[/^put on the card/,'ph_install'],[/\bbuilt\b/,'ph_build'],[/^the game's code/,'ph_extract'],[/^what the game asks/,'ph_check']];
const tr=t=>{const k=t.replace(/^[^:]*: /,'');for(const [r,w] of PH)if(r.test(k))return T[w];return t};
function phase(ev){
  cur={i:ev.i,n:ev.n};
  if(phaseList.length&&phaseList[phaseList.length-1].i===ev.i)return;
  $$('#phases li.act').forEach(l=>{l.classList.remove('act');l.classList.add('ok');l.querySelector('.d').innerHTML='✓'});
  phaseList.push(ev);
  const li=document.createElement('li');li.className='act';li.innerHTML=`<span class="d"></span><span>${esc(tr(ev.title))}</span>`;
  $('#phases').appendChild(li);
  $('#ptitle').textContent=tr(ev.title);$('#stepn').textContent=fill(T.step_of,{i:ev.i,n:ev.n});$('#pdetail').textContent='';$('#stats').innerHTML='';
  lastP=null;speed=0;setPct((ev.i-1)/ev.n,true);
}
function progress(p){
  const frac=p.total>0?p.done/p.total:0, n=cur.n||1, i=cur.i||1;
  setPct(((i-1)+frac)/n,false);
  $('#pdetail').textContent=p.detail||'';
  const bytes=p.total>200000||/copy|byte|send|write|ftp|sd/i.test(p.kind);
  if(lastP&&p.at>lastP.at&&p.done>=lastP.done){const inst=(p.done-lastP.done)/(p.at-lastP.at);speed=speed?speed*.75+inst*.25:inst}
  lastP=p;
  let h=`<div class="stat"><b>${bytes?fmtB(p.done):Math.round(p.done)}</b> / ${bytes?fmtB(p.total):Math.round(p.total)}</div>`;
  if(speed>0&&bytes)h+=`<div class="stat">${T.speed} <b>${fmtB(speed)}/s</b></div><div class="stat">${T.left} <b>${fmtT((p.total-p.done)/speed)}</b></div>`;
  $('#stats').innerHTML=h;
}
async function poll(){
  clearTimeout(pollH);
  let r;try{r=await api('/api/status?since='+since)}catch(e){pollH=setTimeout(poll,1000);return}
  since=r.next;const L=$('#log');let added='';
  for(const ev of r.events){
    if(ev.t==='log'){added+=ev.s+'\n'; if(!cur.n)$('#pdetail').textContent=ev.s}
    else if(ev.t==='phase')phase(ev);
    else if(ev.t==='end'){if(added)L.textContent+=added;return finish(ev.code)}
  }
  if(added){const atB=L.scrollHeight-L.scrollTop-L.clientHeight<40;L.textContent+=added;if(atB)L.scrollTop=L.scrollHeight}
  if(r.progress)progress(r.progress);
  pollH=setTimeout(poll,r.running?250:600);
}

/* ---------- end ---------- */
function finish(code){
  const ok=code===0, E=$('#endCard'), log=$('#log').textContent, setup=lastAction==='setup'||lastAction==='auto';
  $$('#phases li.act').forEach(l=>{l.classList.remove('act');l.classList.add(ok?'ok':'ko');l.querySelector('.d').innerHTML=ok?'✓':'✕'});
  const check=`<svg viewBox="0 0 24 24" fill="none" stroke="#34d399" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>`;
  const cross=`<svg viewBox="0 0 24 24" fill="none" stroke="#f87171" stroke-width="2.6" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>`;
  const unsupported=code===2||/NOT SUPPORTED YET/.test(log);
  const failLine=(log.match(/(This step failed|FAILED):.*$/m)||[''])[0];
  let h;
  if(ok&&setup){
    h=`<div class="res ok">${check}</div><h2 style="font-size:26px">${T.all_ready}</h2><p class="pdetail" style="white-space:normal">${T.all_ready_p}</p>
      <div class="btns"><button class="btn pri" data-back>${T.continue}</button><button class="btn" data-log>${T.see_log}</button></div>`;
  }else if(ok){
    const where=lastAction==='make'&&S.dest==='none'?T.in_out:T.installed_ok;
    h=`<div class="res ok">${check}</div><h2 style="font-size:28px;letter-spacing:-.02em">${T.ready_play}</h2>
      <p class="pdetail" style="white-space:normal">${where}</p>
      <div class="steps"><div><span>${T.end1}</span></div>
      <div><span>${T.end2}</span></div>
      <div><span>${T.end3}</span></div></div>
      <div class="btns"><button class="btn pri" data-back>${T.another}</button><button class="btn" data-log>${T.see_log}</button></div>`;
    confetti();
  }else{
    const msg=code===null||code<0||code===15||code===-15?T.cancelled:unsupported?T.unsupported:
      lastAction==='auto'?T.auto_failed:setup?T.setup_missing:T.build_failed;
    const canAuto=lastAction!=='auto'&&/^MISSING|^  MISSING/m.test(log);
    h=`<div class="res ko">${cross}</div><h2 style="font-size:26px">${T.oops}</h2><p class="pdetail" style="white-space:normal">${msg}</p>
      ${canAuto?`<div class="btns"><button class="btn pri" data-auto>${T.miss_btn}</button></div><p class="hint">${T.miss_p}</p>`:''}
      ${failLine?`<p class="hint" style="margin-top:10px"><kbd>${esc(failLine)}</kbd></p>`:''}
      ${setup||canAuto?'':`<div class="steps" style="margin-top:18px"><div><span>${T.tip1}</span></div>
      <div><span>${T.tip2}</span></div></div>`}
      <div class="btns"><button class="btn pri" data-back>${T.back}</button><button class="btn" data-log>${T.see_log}</button><button class="btn" data-copy>${T.copy_log}</button></div>`;
  }
  E.innerHTML=h+`<div class="log" id="log2">${esc(log)}</div>`;
  show('vEnd');
  E.querySelector('[data-back]').onclick=()=>{show(REPO_OK?'vMain':'vRepo');render();checkMissing()};
  E.querySelector('[data-log]').onclick=()=>{const l=$('#log2');l.classList.toggle('open');l.scrollTop=l.scrollHeight};
  const au=E.querySelector('[data-auto]');if(au)au.onclick=()=>run({action:'auto'});
  const cp=E.querySelector('[data-copy]');if(cp)cp.onclick=()=>{navigator.clipboard?.writeText(log).then(()=>toast(T.log_copied),()=>toast(T.copy_failed))};
}

/* ---------- confetti ---------- */
function confetti(){
  const c=$('#confetti'),x=c.getContext('2d');c.width=innerWidth;c.height=innerHeight;
  if(matchMedia('(prefers-reduced-motion: reduce)').matches)return;
  const cols=['#ff3d6e','#8b5cf6','#22d3ee','#34d399','#fbbf24'];
  const P=Array.from({length:170},()=>({x:c.width/2,y:c.height*.38,vx:(Math.random()-.5)*16,vy:-Math.random()*15-4,
    s:Math.random()*7+4,r:Math.random()*6,vr:(Math.random()-.5)*.35,c:cols[Math.random()*5|0],l:1}));
  let t=0;(function f(){x.clearRect(0,0,c.width,c.height);t++;
    for(const p of P){p.vy+=.38;p.vx*=.99;p.x+=p.vx;p.y+=p.vy;p.r+=p.vr;p.l-=.006;
      x.save();x.globalAlpha=Math.max(0,p.l);x.translate(p.x,p.y);x.rotate(p.r);x.fillStyle=p.c;x.fillRect(-p.s/2,-p.s/4,p.s,p.s/2);x.restore()}
    if(t<220)requestAnimationFrame(f);else x.clearRect(0,0,c.width,c.height)})();
}

/* ---------- ports drawer ---------- */
function drawer(on){$('#drawer').classList.toggle('on',on);$('#scrim').classList.toggle('on',on)}
$('#bPorts').onclick=async()=>{drawer(true);const L=$('#portList');L.innerHTML='<div class="empty" style="margin-top:14px">'+T.loading+'</div>';
  const ps=await api('/api/ports');
  L.innerHTML=ps.length?ps.map((p,i)=>`<div class="port" style="animation-delay:${i*.05}s"><div class="ico">${IC.file}</div><div class="t"><b>${esc(p.name)}</b><small>${fmtB(p.size)} · ${new Date(p.date*1000).toLocaleString(LANG,{dateStyle:'short',timeStyle:'short'})}</small></div>
    <button class="sm" data-inst="${esc(p.name)}">${T.install}</button></div>`).join('')
    +`<p class="hint" style="margin-top:14px">${fill(T.install_hint,{dest:S.dest==='ftp'?'Wi-Fi '+esc(S.ftp||'?'):S.dest==='sw2t'?'SW2Transfer '+esc(S.sw2t||'?'):S.dest==='sd'?esc(S.sd||'?'):T.none_chosen})}</p>`
    :'<div class="empty" style="margin-top:14px">'+T.no_ports+'</div>';
  $$('[data-inst]').forEach(b=>b.onclick=()=>{drawer(false);run({action:'install',name:b.dataset.inst,dest:S.dest,sd:S.sd,ftp:S.ftp,sw2t:S.sw2t,sw2tPw:S.sw2tPw})});
};
$('#closeD').onclick=$('#scrim').onclick=()=>drawer(false);
document.addEventListener('keydown',e=>{if(e.key==='Escape')drawer(false)});

/* ---------- language ---------- */
$('#sLang').onchange=async e=>{
  try{sessionStorage.setItem('nx2keep',JSON.stringify({game:S.game,gameDir:S.gameDir,update:S.update,icon:S.icon,noTk:S.noTk,
    f:['iTitle','iVersion','iName'].map(i=>$('#'+i).value),nro:$('#iNro').checked}))}catch(_){}
  await api('/api/lang',{lang:e.target.value});location.reload()};
try{const k=JSON.parse(sessionStorage.getItem('nx2keep')||'null');sessionStorage.removeItem('nx2keep');
  if(k){['game','gameDir','update','icon','noTk'].forEach(p=>S[p]=k[p]);['iTitle','iVersion','iName'].forEach((i,n)=>$('#'+i).value=k.f[n]);$('#iNro').checked=k.nro}}catch(_){}

/* ---------- repo ---------- */
let REPO_OK=false;
async function setRepo(p){const r=await api('/api/repo',{path:p});if(r.ok){REPO_OK=true;checkMissing();toast(T.repo_found);show('vMain');render()}else $('#eRepo').textContent=r.error}
$('#pRepo').onclick=async()=>{const r=await api('/api/pick',{kind:'folder'});if(r.notk){$('#iRepo').focus();toast(T.paste_folder);return}if(r.path)setRepo(r.path)};
$('#okRepo').onclick=()=>setRepo($('#iRepo').value.trim().replace(/^"|"$/g,''));

(async()=>{
  const info=await api('/api/info');REPO_OK=!!info.repo;
  loadDrives();render();if(REPO_OK)checkMissing();
  const st=await api('/api/status?since=0');
  if(st.running){since=0;lastAction=st.action;show('vRun');poll();return}
  show(REPO_OK?'vMain':'vRepo');
})();
</script></body></html>"""

_I = 'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'
ICONS = {
    "%%FILE%%": f'<svg {_I}><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/></svg>',
    "%%FOLDER%%": f'<svg {_I}><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
    "%%UPD%%": f'<svg {_I}><path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/></svg>',
    "%%SD%%": f'<svg {_I} style="width:16px;height:16px;color:var(--a2)"><path d="M7 3h8l4 4v12a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z"/><path d="M9 7v3M12 7v3M15 7v3"/></svg>',
    "%%IMAGE%%": f'<svg {_I} style="width:24px;height:24px"><rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="9" cy="9" r="2"/><path d="m21 15-5-5L5 21"/></svg>',
}
for _k, _v in ICONS.items():
    PAGE = PAGE.replace(_k, _v)

if __name__ == "__main__":
    main()
