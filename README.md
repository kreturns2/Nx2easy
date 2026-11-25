# nx2-relink Easy

**English** · [Français](README.fr.md)

A simple, multilingual interface for **nx2-relink**, which turns a Nintendo Switch 2 game you own into a homebrew program (`.nro`).
Based on the work of Olmectron ([nx-relink](https://github.com/Olmectron/nx-relink)), MIT license.

> **Experimental software, at your own risk**: crashes, data loss and a console ban are possible.
> Only for your own backups of games. This repository contains no games, keys or Nintendo files, and does not provide any.

## Requirements (Windows 64-bit)

- **Python 3.10 or newer**
- [devkitPro](https://devkitpro.org/wiki/Getting_Started), `switch-dev` group
- [ounce-devkit](https://github.com/ouncebrew/ounce-devkit): `sh install.sh` in devkitPro's msys2

## Automatic setup (Windows)

Run `python nx2_easy.py`: if something is missing, the page offers **Download what is missing**. From the command line:

```powershell
python nxrelink.py setup --auto
```

- **Python packages**: from PyPI. If your Python is too new (3.15), a private Python 3.14 is put in `deps/` (NuGet).
- **devkitPro**: its official installer opens; keep the proposed folder and tick "Switch Development".
- **ounce-devkit**: its `install.sh` adds its repository and signing key to devkitPro's pacman.

Python, the installer and `install.sh` are checked by SHA-256 before they are used.

## Manual setup

```powershell
py -3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe nxrelink.py setup
```

## Use

```powershell
.venv\Scripts\python.exe nx2_easy.py
```

or from the command line:

```powershell
.venv\Scripts\python.exe nxrelink.py make "D:\game.nup" --name mygame --sd E:
```

### Over Wi-Fi with SW2Transfer

[SW2Transfer](https://github.com/Rodpad/SW2Transfer) (the app, or its background plugin) receives the port over Wi-Fi, several
connections at once: much faster than FTP. Choose **SW2Transfer** in step 2 and type the address shown on the console's screen,
or from the command line:

```powershell
.venv\Scripts\python.exe nxrelink.py make "D:\game.nup" --name mygame --sw2t 192.168.1.42
```

If a password is set in SW2Transfer, give it in the window, or in `SW2T_PASSWORD` (the terminal asks for it otherwise).

Full documentation: [docs/nx2-relink.md](docs/nx2-relink.md).

## Languages

English, French, Spanish, German, Italian and Portuguese. The browser's language is used by default; the menu at the top of the page
changes it, and the choice is kept. nx2-relink's technical log stays in English.

To add a language, copy `locales/en.json` under its code (for example `nl.json`) and translate the texts, including `_name`.
Keep the tags and the `{words}` in braces. A missing text is shown in English.

## License

[MIT](LICENSE), © 2026 Olmectron for nx2-relink.
