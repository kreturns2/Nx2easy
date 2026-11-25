"""A game you own, made into a homebrew program (.nro) that runs it on its own console: the game's code relinked, not emulated.

Two tools are made from this source, each with its own console's options alone (tools/edition.py says which this copy is):
    nx-relink     a Switch game (an NSP, with your console's keys)                ->  a Switch
    nx2-relink    a Switch 2 game (a NUP container, or a folder of loose files)   ->  a Switch 2
`python nxrelink.py help` prints this copy's commands.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__)).replace('\\', '/')
sys.path.insert(0, f'{ROOT}/tools')
from edition import EDITION, TOOL, VERSION  # noqa: E402
import fetch  # noqa: E402

PY = sys.executable
ME = 'python nxrelink.py'
SWITCH, SWITCH2 = EDITION in ('switch', 'dev'), EDITION in ('switch2', 'dev')
FOR_2 = 'every game' if EDITION == 'switch2' else 'a Switch 2'  # (what the newer console's kit is said to be for: all of nx2-relink's games)
MEMORY = (2048, 8000, 7800)  # (the least and the most --memory takes, and what a port has when it isn't given; MB)

HELP_SWITCH = f"""{TOOL} {VERSION}: a Switch game you own, made into a homebrew program (.nro) for a Switch.

  {ME}                      the window (the same steps, with buttons)
  {ME} setup                what this needs, checked; the Python packages it lacks, installed
  {ME} setup --auto         all that is missing, downloaded and installed (Windows)
  {ME} check <game.nsp> [--update <update.nsp>]
                                     what the game asks of the port, before anything is built
  {ME} make <game.nsp>      the port built: out/<name>.nro
      --update <update.nsp>          the game's update, applied (its code, and its files over the game's)
      --aoc <dlc.nsp>                an add-on content (DLC); as many of these as there are
      --name <name>                  the port's short name, in its files' names (default: made from the game's title)
      --keys <prod.keys>             your console's keys (default: ~/.switch/prod.keys)
      --title, --version, --icon <picture>   what the homebrew menu shows (default: the game's own name, version and icon)
      --no-romfs                     the game's files aren't extracted again (they are in build/<name>_nsp already)
    ... and then put on a card, with either of:
      --sd <drive or folder>         the console's card, in this computer
      --ftp <host[:port]>            an FTP server on the console (port 5000)
      --sw2t <host[:port]>           SW2Transfer open on the console (port 6967; faster than FTP. Its password, if it has one:
                                     SW2T_PASSWORD, or asked for)
      --sd-format auto | fat32 | exfat     fat32: a large RomFS in 2 GB parts; exfat: one file (default: asked of the drive)
  {ME} install <name> --sd <drive> | --ftp <host> | --sw2t <host>  [--sd-format ..] [--nro-only]
                                     a port already built, put on a card (--nro-only: its program alone, when the game's
                                     files are on the card already)
  {ME} list                 the ports already built

  ADVANCED option of make and install:
      --long-log                     with --sd, --ftp or --sw2t: the port writes its detailed log from its first run (the file "debug"
                                     in its folder; much slower, and a large file. Delete "debug" to turn it off)

On the card a port is its program, /switch/nx-relink/<name>.nro, and its folder at the card's root, /nx-relink/<name>/: the
game's files, its saved data (save/), its log (log.txt) and, after a run that ended badly, crash.txt: the file to send with a
report.
The game's files stay on this computer and on your card: nothing is sent anywhere else, and no key is ever shown.
"""

HELP_SWITCH2 = f"""{TOOL} {VERSION}: a game you own, from its NUP container or a folder of its files, made into a homebrew program (.nro) for its console.

  {ME}                      the window (the same steps, with buttons)
  {ME} setup                what this needs, checked; the Python packages it lacks, installed
  {ME} setup --auto         all that is missing, downloaded and installed (Windows)
  {ME} make <game.nup | folder>
                                     the port built: out/<name>-switch2.nro. The game's dump is a NUP container, or a folder of
                                     its loose files (exefs/ and romfs/; or base/ and updates/<version>/ with those in them).
                                     Its updates are laid over it: the newest program, and each update's files over the game's
      --update <nup | folder>        an update kept apart from the game, laid over it too
      --name <name>                  the port's short name, in its files' names (default: made from the dump's name)
      --title, --version, --icon <picture>   what the homebrew menu shows (default: the game's own, if its dump has them)
      --nro-only                     the program alone is put on the card: the game's files are there already (a port built
                                     again). --no-romfs is the same
    ... and then put on a card, with either of:
      --sd <drive or folder>         the console's card, in this computer
      --ftp <host[:port]>            an FTP server on the console (port 5000)
      --sw2t <host[:port]>           SW2Transfer open on the console (port 6967; faster than FTP. Its password, if it has one:
                                     SW2T_PASSWORD, or asked for)
      --sd-format auto | fat32 | exfat     fat32: a large RomFS in 2 GB parts; exfat: one file (default: asked of the drive)
  {ME} install <name> --sd <drive> | --ftp <host> | --sw2t <host>  [--sd-format ..] [--nro-only]
                                     a port already built, put on a card (--nro-only: its program alone)
  {ME} identity <name> --title "..." [--author "..."] [--version "..."] [--icon <picture>] [--ftp <host> | --sw2t <host> | --sd <drive>]
  {ME} identity <name> --ftp <host>
                                     the name, version and icon the homebrew menu shows for a port: the ones you give (the icon
                                     from any picture), or, with --ftp alone, the game's own taken from the console if the game
                                     has been used on it (in two steps: the port is opened once in between). A dump that has
                                     the game's name and version gives them to the port by itself; one that hasn't leaves the
                                     dump's file name and no icon until this is done. The port is built again, and put on the
                                     card if one is given
  {ME} list                 the ports already built

  ADVANCED options of make. They change what the game is given, and a wrong value makes a game that worked stop at its start
  or while it loads. Leave them alone unless a game needs one; nothing here can harm the console.
      --memory <MB>                  how much memory the game is told there is: {MEMORY[0]} to {MEMORY[1]} (default {MEMORY[2]}). The port sets none
                                     aside: the game takes what it asks for as it runs, and this is only the most it is told
                                     of. Less makes a game that sizes itself by it smaller; more than the console has is cut
                                     to what there is
      --whole auto | all | none | <module,module>
                                     which of the game's modules are kept whole, as on its console, and which are relinked
                                     (default auto: all of them, or main, sdk and those with thread-local storage when the
                                     game loads modules of its own as it runs). The console's loader maps eight images for a
                                     program: "all" leaves a game that loads its own no room for them
      --long-log                     with --sd, --ftp or --sw2t: the port writes its detailed log from its first run (the file "debug"
                                     in its folder; slower, and larger)

On the card a port is its program, /switch/nx2-relink/<name>.nro, and its folder at the card's root, /nx2-relink/<name>/: the
game's files, its saved data (save/), its log (log.txt) and, after a run that ended badly, crash.txt: the file to send with a
report.
The game's files stay on this computer and on your card: nothing is sent anywhere else.
"""

HELP = HELP_SWITCH if EDITION == 'switch' else HELP_SWITCH2 if EDITION == 'switch2' else (
    f'{TOOL}: the copy both tools are made from. Their commands, each with its own console\'s options:\n\n' + HELP_SWITCH + '\n' + HELP_SWITCH2 +
    '\nIn this copy only:  make <game.nsp> --target switch | switch2 | both   (a Switch game on a Switch 2: not working yet for most),\n'
    '                    --install-target switch | switch2\n')

PACKAGES = [('Cryptodome', 'pycryptodomex', 'opens the game\'s NSP with your keys', SWITCH),
            ('lz4', 'lz4', 'unpacks the game\'s code (and the files of games whose RomFS is compressed)', True),
            ('zstandard', 'zstandard', 'opens a NUP container\'s files', SWITCH2),
            ('PIL', 'Pillow', 'makes a port\'s icon the size the homebrew menu shows, from a larger one or from any picture', True)]


DEVKITPRO = 'https://devkitpro.org/wiki/Getting_Started'
DEVKITPRO_WINDOWS = 'https://github.com/devkitPro/installer/releases/latest'
OUNCE = 'https://github.com/ouncebrew/ounce-devkit'


def links(what):
    """Where a thing the tool needs is had: [(what the link is, its address)], for the window to make links of and the terminal
    to print. A Python package's is its page (setup installs it by itself); a key isn't had from anywhere but your console."""
    if what in [p for _, p, _, _ in PACKAGES]:
        return [(f'{what} on PyPI', f'https://pypi.org/project/{what}/')]
    if 'ounce' in what:
        return [('ounce-devkit: download and instructions', OUNCE)]
    if what.startswith(('devkitA64', 'libnx', 'elf2nro')):
        return ([('devkitPro installer for Windows', DEVKITPRO_WINDOWS)] if os.name == 'nt' else []) + [('devkitPro: Getting Started', DEVKITPRO)]
    return []


def dkp():
    # (the variable may hold a path of msys's, which this Python can't open: the first place that has the compiler's folder)
    places = [os.environ.get('DEVKITPRO', '').replace('\\', '/'), 'C:/devkitPro', '/opt/devkitpro']
    return next((d for d in places if d and os.path.isdir(f'{d}/devkitA64')), 'C:/devkitPro')


def default_keys():
    for p in ('~/.switch/prod.keys', '~/.3ds-nx/prod.keys'):
        p = os.path.expanduser(p)
        if os.path.isfile(p):
            return p
    return None


def setup(install=True, quiet=False):
    """What the tool needs, checked. Python packages that are missing are installed (pip); what can't be installed from here is
    said, with where it is had. Returns the list of what is still missing: (what, needed for, how to get it)."""
    missing = []
    say = (lambda *a: None) if quiet else print
    for module, package, why, wanted in PACKAGES:
        if not wanted:
            continue
        if importlib.util.find_spec(module) is None and install:
            say(f'installing the Python package {package} ({why}) ...')
            r = subprocess.run([PY, '-m', 'pip', 'install'] + (['--only-binary=:all:'] if os.name == 'nt' else []) + [package], capture_output=True, text=True)
            importlib.invalidate_caches()
            if r.returncode:
                say((r.stdout + r.stderr).strip()[-600:])
        ok = importlib.util.find_spec(module) is not None
        say(f'  {"ok     " if ok else "MISSING"} Python package {package}: {why}')
        if not ok:
            missing.append((package, 'every game', f'{os.path.basename(PY)} -m pip install {package}'))
    d = dkp()
    exe = '.exe' if os.name == 'nt' else ''
    checks = [
        (f'{d}/devkitA64/bin/aarch64-none-elf-gcc{exe}', 'devkitA64 (the compiler)', 'every game',
         'install devkitPro, choosing "Switch Development" (the switch-dev group)', True),
        (f'{d}/libnx/lib/libnx.a', 'libnx', 'a Switch', 'devkitPro\'s switch-dev group:  dkp-pacman -S switch-dev', SWITCH),
        (f'{d}/tools/bin/elf2nro{exe}', 'elf2nro and nacptool (switch-tools)', 'every game', 'devkitPro\'s switch-dev group:  dkp-pacman -S switch-dev', True),
        (f'{d}/libounce/lib/libounce.a', 'ounce-devkit (libounce)', FOR_2, 'after devkitPro: get ounce-devkit and run  sh install.sh  in devkitPro\'s msys2 shell',
         SWITCH2),
    ]
    for path, what, for_what, how, wanted in checks:
        if not wanted:
            continue
        ok = os.path.isfile(path)
        say(f'  {"ok     " if ok else "MISSING"} {what}: for {for_what}' + ('' if ok else f'\n          {how}' +
                                                                                 ''.join(f'\n          {t}: {u}' for t, u in links(what) if u not in how)))
        if not ok:
            missing.append((what, for_what, how))
    if SWITCH:
        keys = default_keys()
        say(f'  {"ok     " if keys else "MISSING"} prod.keys: your console\'s keys, to open your games' +
            ('' if keys else '\n          Lockpick_RCM writes it on the console; put it at ~/.switch/prod.keys, or give it with --keys'))
        if not keys:
            missing.append(('prod.keys', 'a Switch game (or --keys)', 'Lockpick_RCM, then ~/.switch/prod.keys'))
    return missing


def has_switch2():
    return os.path.isfile(f'{dkp()}/libounce/lib/libounce.a')


def phase(i, n, title):
    """The step the tool is at, of how many: a heading on a terminal, a line for the window to read (it sets NX2_GUI)."""
    if os.environ.get('NX2_GUI'):
        print(f'@@phase|{i}|{n}|{title}', flush=True)
    print(f'{"" if i == 1 else chr(10)}== step {i} of {n}: {title}', flush=True)


def run(cmd):
    """A step of the tool's, its output shown as it comes, and how far it has got (tools/progress.py): a percentage on a terminal;
    for the window, the tool's own line passed on. Ends the tool if the step failed."""
    import progress
    gui, tty = bool(os.environ.get('NX2_GUI')), sys.stdout.isatty()
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', cwd=ROOT,
                         env=dict(os.environ, NX2_PROGRESS='1', PYTHONIOENCODING='utf-8'))
    open_line = False  # a percentage is on the terminal's line, to be written over
    refused = False
    for line in p.stdout:
        refused = refused or 'NOT SUPPORTED YET' in line
        if line.startswith('@@progress|'):
            if gui:
                print(line, end='', flush=True)
            elif tty:
                _, kind, detail, done, total = line.rstrip('\n').split('|')
                progress.show(kind, detail, int(done), int(total))
                open_line = int(done) < int(total)
            continue
        if open_line:
            print()
            open_line = False
        print(line, end='', flush=True)
    if p.wait():
        if refused:  # (a game this release can't open yet: not a fault of the dump's, or of a step's)
            sys.exit(2)
        sys.exit(f'This step failed: {" ".join(os.path.basename(c) if os.sep in c or "/" in c else c for c in cmd[:3])} ...')


def take(args, name, default=None, many=False):
    out = []
    while name in args:
        i = args.index(name)
        if i + 1 >= len(args):
            sys.exit(f'{name} needs a value.')
        out.append(args[i + 1])
        del args[i:i + 2]
        if not many:
            break
    return out if many else (out[0] if out else default)


def flag(args, name):
    if name in args:
        args.remove(name)
        return True
    return False


def slug(title):
    s = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')
    return s[:24].strip('-') or 'game'


def title_of(game):
    """A short name from a game's file or folder name: what is before its first bracket."""
    base = os.path.basename(os.path.normpath(game))
    return re.split(r'[\[\(]', os.path.splitext(base)[0] if os.path.isfile(game) else base)[0].strip() or 'game'


def need(parts):
    """Ends the tool, saying what is missing, if what a step needs isn't there."""
    gaps = [m for m in setup(install=True, quiet=True) if any(p in m[1] or p == m[0] for p in parts)]
    if gaps:
        for what, for_what, how in gaps:
            print(f'MISSING {what} (for {for_what}):\n   {how}')
        sys.exit(f'Run  {ME} setup --auto  to download and install what is missing.')


def cmd_check(args):
    update, keys = take(args, '--update'), take(args, '--keys')
    if len(args) != 1 or not SWITCH:
        sys.exit(HELP)
    need(['every game', 'a Switch game'])
    work = f'{ROOT}/build/check_nsp'
    phase(1, 2, 'the game\'s code, from its NSP')
    run([PY, f'{ROOT}/tools/nsp.py', args[0], work] + (['--update', update] if update else []) + (['--keys', keys] if keys else []))
    phase(2, 2, 'what the game asks of the port')
    run([PY, f'{ROOT}/tools/check.py', f'{work}/exefs'])


def destination(sd, ftp, sw2t):
    """tools/install.py's arguments for where a port goes: the card in this computer, an FTP server or SW2Transfer on the console."""
    return ['--sd', sd] if sd else ['--ftp', ftp] if ftp else ['--sw2t', sw2t] if sw2t else []


def cmd_make(args):
    update, aocs = take(args, '--update'), take(args, '--aoc', many=True)
    name, target, keys = take(args, '--name'), take(args, '--target'), take(args, '--keys')
    shown = [(k, take(args, k)) for k in ('--title', '--version', '--icon', '--author')]
    sd, ftp, sw2t, fmt = take(args, '--sd'), take(args, '--ftp'), take(args, '--sw2t'), take(args, '--sd-format', 'auto')
    install_target = take(args, '--install-target')
    ttx, memory, whole = take(args, '--ttx'), take(args, '--memory'), take(args, '--whole')
    nro_only = flag(args, '--nro-only')
    no_romfs, long_log = flag(args, '--no-romfs') or nro_only, flag(args, '--long-log')
    if len(args) != 1 or [bool(sd), bool(ftp), bool(sw2t)].count(True) > 1:
        sys.exit(HELP)
    where = destination(sd, ftp, sw2t)
    game = args[0]
    if game.lower().endswith('.nup') or os.path.isdir(game):
        if not SWITCH2:
            sys.exit(f'{game} is a NUP container or a folder. {TOOL} takes a Switch game\'s NSP: that kind of dump is nx2-relink\'s.')
        return make_switch2(game, update, name, shown, where, ttx, fmt, no_romfs, memory, whole, long_log)
    if not SWITCH:
        sys.exit(f'{game}: {TOOL} takes a NUP container, or a folder of a game\'s loose files. A Switch game (NSP) is nx-relink\'s.')
    for path in [game, update, *aocs]:
        if path and not os.path.isfile(path):
            sys.exit(f'{path} isn\'t there.')
    if EDITION == 'switch':
        target = 'switch'
    target = target or ('both' if has_switch2() else 'switch')
    if target not in ('switch', 'switch2', 'both'):
        sys.exit('--target is switch, switch2 or both.')
    need(['every game', 'a Switch game'] + ([FOR_2] if target != 'switch' else []) + (['a Switch'] if target != 'switch2' else []))
    name = slug(name or title_of(game))
    work = f'{ROOT}/build/{name}_nsp'
    steps = 4 if where else 3
    phase(1, steps, f'{name}: the game\'s code{"" if no_romfs else " and files"}, from its NSP')
    run([PY, f'{ROOT}/tools/nsp.py', game, work] + ([] if no_romfs else ['--romfs']) + (['--update', update] if update else []) +
        [x for a in aocs for x in ('--aoc', a)] + (['--keys', keys] if keys else []))
    print(f'\n-- {name}: what the game asks of the port')
    run([PY, f'{ROOT}/tools/check.py', f'{work}/exefs'])
    if target != 'switch' and os.path.isfile(f'{work}/romfs.bin'):
        # (a Switch 2 can't be given shaders compiled for the Switch's GPU: they are translated here, once, and go on the card)
        print(f'\n-- {name}: its compiled shaders, translated for a Switch 2')
        run([PY, f'{ROOT}/tools/shaderpack.py', work])
    phase(2, steps, f'{name}: the port, built for {target}')
    run([PY, f'{ROOT}/tools/build.py', f'{work}/exefs', '--name', name, '--target', target] + [x for k, v in shown if v for x in (k, v)])
    if where:
        it = install_target or ('switch2' if target == 'switch2' else 'switch')
        phase(3, steps, f'{name}: put on the card ({it}), and read back')
        run([PY, f'{ROOT}/tools/install.py', name, '--target', it, '--sd-format', fmt] + where +
            (['--long-log'] if long_log else []))
        phase(steps, steps, f'{name}: done. It is on the card: open it from the homebrew menu, started over a game')
    else:
        phase(steps, steps, f'{name}: done. To put it on a console\'s card:  {ME} install {name} --sd <drive>   (or --ftp / --sw2t <host>)')


def advanced(memory, whole):
    """The advanced options of a Switch 2 port, checked and said: what tools/build.py is given for them."""
    out = []
    if memory is not None:
        if not memory.isdigit() or not MEMORY[0] <= int(memory) <= MEMORY[1]:
            sys.exit(f'--memory is a number of MB from {MEMORY[0]} to {MEMORY[1]} (the default is {MEMORY[2]}).')
        print(f'ADVANCED: the game is told there are {memory} MB of memory (the default is {MEMORY[2]}). A game may not start, or may stop as it loads.')
        out += ['--heap', memory]
    if whole is not None:
        if not re.fullmatch(r'[A-Za-z0-9_,]+', whole):
            sys.exit('--whole is auto, all, none, or modules\' names with commas between them (main,sdk,subsdk0).')
        print(f'ADVANCED: the game\'s modules kept whole: {whole} (the default is auto). A game may not start, or may be refused modules it loads itself.')
        out += ['--whole' if whole == 'all' else f'--whole={whole}']
    return out


def make_switch2(game, update, name, shown, where, ttx, fmt, no_romfs, memory=None, whole=None, long_log=False):
    """A Switch 2 game, from its NUP container or a folder of its loose files: its own SDK does the drawing, so nothing of a Switch
    game's port is needed but the relinking (no keys: a dump of these isn't encrypted; no shaders translated; no check of what it
    asks, which is of a Switch's). Its updates are laid over it by tools/game2.py."""
    for path in (game, update):
        if path and not os.path.exists(path):
            sys.exit(f'{path} isn\'t there.')
    extra = advanced(memory, whole)
    need([FOR_2, 'devkitA64 (the compiler)', 'elf2nro and nacptool (switch-tools)', 'zstandard', 'lz4'])
    name = slug(name or title_of(game))
    steps = 3 if where else 2
    phase(1, steps, f'{name}: the game\'s code, from its dump, and the port built')
    run([PY, f'{ROOT}/tools/build.py', game, '--name', name, '--target', 'switch2'] + (['--update', update] if update else []) + extra +
        [x for k, v in shown if v for x in (k, v)])
    if where:
        phase(2, steps, f'{name}: put on the card, with the game\'s files made into one image as they go')
        run([PY, f'{ROOT}/tools/install.py', name, '--target', 'switch2', '--sd-format', fmt] + where +
            (['--ttx', ttx] if ttx else []) + (['--no-romfs'] if no_romfs else []) + (['--long-log'] if long_log else []))
        phase(steps, steps, f'{name}: done. It is on the card: open it from the homebrew menu (the folder "nx2-relink"), started over a game')
    else:
        phase(steps, steps, f'{name}: done. To put it on a console\'s card:  {ME} install {name} --sd <drive>   (or --ftp / --sw2t <host>)')


def cmd_install(args):
    name = next((a for a in args if not a.startswith('--')), None)
    if EDITION != 'dev' and '--target' not in args:
        args += ['--target', EDITION]
    phase(1, 2, 'put on the card, and read back')
    run([PY, f'{ROOT}/tools/install.py'] + args)
    phase(2, 2, f'done. {name or "It"} is on the card')


def cmd_identity(args):
    """A port's name, version and icon (tools/control.py), and the port built again with them, and installed if a card is given."""
    if not args:
        sys.exit(HELP)
    name = args[0]
    by_hand = any(a in args for a in ('--title', '--author', '--version', '--icon'))
    sd, ftp, sw2t = take(args, '--sd'), (take(args, '--ftp') if by_hand else None), take(args, '--sw2t')
    if not by_hand and '--ftp' in args:
        ftp = args[args.index('--ftp') + 1]
    where = destination(sd, ftp, sw2t)
    r = subprocess.run([PY, f'{ROOT}/tools/control.py'] + args)
    if r.returncode:
        sys.exit(r.returncode)
    info = json.load(open(f'{ROOT}/build/{name}_nsp/info.json', encoding='utf-8'))
    targets = ['switch2'] if info.get('switch2') else [t for t, f in (('switch', f'{ROOT}/out/{name}.nro'), ('switch2', f'{ROOT}/out/{name}-switch2.nro'))
                                                       if os.path.isfile(f)]
    for t in targets:
        phase(1, 2 if where else 1, f'{name}: built again, with its name, version and icon')
        run([PY, f'{ROOT}/tools/build.py', f'{ROOT}/build/{name}_nsp/exefs', '--name', name, '--target', t])
    if where:
        phase(2, 2, f'{name}: put on the card')
        for t in targets[-1:]:
            run([PY, f'{ROOT}/tools/install.py', name, '--target', t, '--no-romfs'] + where)


def built():
    """The ports that are built: {name: (title, version, targets)}. Only this edition's: a Switch's ports for nx-relink, a Switch
    2's for nx2-relink."""
    out = {}
    for d in sorted(os.listdir(f'{ROOT}/build')) if os.path.isdir(f'{ROOT}/build') else []:
        if not d.endswith('_nsp') or d == 'check_nsp':
            continue
        name = d[:-4]
        targets = [t for t, f, wanted in (('switch', f'{ROOT}/out/{name}.nro', SWITCH), ('switch2', f'{ROOT}/out/{name}-switch2.nro', SWITCH2))
                   if wanted and os.path.isfile(f)]
        info = {}
        if os.path.isfile(f'{ROOT}/build/{d}/info.json'):
            info = json.load(open(f'{ROOT}/build/{d}/info.json', encoding='utf-8'))
        if EDITION == 'switch2' and not info.get('switch2'):
            targets = []  # (a Switch game's port for a Switch 2: the other tool's, and not working yet)
        if not targets:
            continue
        out[name] = (info.get('title') or name, info.get('version') or '', targets)
    return out


def main():
    args = sys.argv[1:]
    if not args:
        import gui
        return gui.main()
    if args[0] not in ('setup', '-h', '--help', 'help') or '--auto' not in args:
        own = fetch.python()
        if own != PY:  # (the tool's own Python, with the packages this one can't have: tools/fetch.py)
            sys.exit(subprocess.call([own, f'{ROOT}/nxrelink.py'] + args))
    cmd = args.pop(0)
    if cmd in ('-h', '--help', 'help'):
        print(HELP)
    elif cmd == 'setup':
        auto = flag(args, '--auto')
        if not auto and SWITCH2 and sys.stdin and sys.stdin.isatty() and fetch.todo(dkp()):
            print('Something is missing. It can be downloaded and installed now: Python packages (PyPI), devkitPro (its own installer)\n'
                  'and ounce-devkit, which adds its repository and its signing key to devkitPro\'s pacman.')
            try:
                auto = input('Download and install? [y/N] ').strip().lower() in ('y', 'yes', 'o', 'oui')
            except EOFError:  # (nobody there to answer)
                print()
        if auto:
            try:
                fetch.install(dkp(), phase)
            except fetch.Failed as e:
                sys.exit(f'FAILED: {e}')
            if fetch.python() != PY:
                sys.exit(subprocess.call([fetch.python(), f'{ROOT}/nxrelink.py', 'setup'], stdin=subprocess.DEVNULL))
        missing = setup()
        print('\nEverything this needs is here.' if not missing else f'\n{len(missing)} thing(s) missing: see above.')
        if missing:
            sys.exit(3)
    elif cmd == 'check':
        cmd_check(args)
    elif cmd == 'make':
        cmd_make(args)
    elif cmd == 'install':
        cmd_install(args)
    elif cmd == 'identity' and SWITCH2:
        cmd_identity(args)
    elif cmd == 'list':
        for name, (title, version, targets) in built().items():
            print(f'{name}: {title} {version}' + (f' ({", ".join(targets)})' if EDITION == 'dev' else ''))
    else:
        sys.exit(HELP)


if __name__ == '__main__':
    main()
