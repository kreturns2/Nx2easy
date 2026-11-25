# nx2-relink Easy

[English](README.md) · **Français**

Une interface simple et multilingue pour **nx2-relink**, qui transforme un jeu Nintendo Switch 2 que vous possédez en programme
homebrew (`.nro`). Basé sur le travail d'Olmectron ([nx-relink](https://github.com/Olmectron/nx-relink)), licence MIT.

> **Logiciel expérimental, à vos risques** : plantages, perte de données et bannissement de la console sont possibles.
> Uniquement pour vos propres sauvegardes de jeux. Ce dépôt ne contient ni jeu, ni clé, ni fichier Nintendo, et n'en fournit pas.

## Prérequis (Windows 64 bits)

- **Python 3.10 ou plus récent**
- [devkitPro](https://devkitpro.org/wiki/Getting_Started), groupe `switch-dev`
- [ounce-devkit](https://github.com/ouncebrew/ounce-devkit) : `sh install.sh` dans le msys2 de devkitPro

## Installation automatique (Windows)

Lancez `python nx2_easy.py` : s'il manque quelque chose, la page propose **Télécharger ce qui manque**. En ligne de commande :

```powershell
python nxrelink.py setup --auto
```

- **Paquets Python** : depuis PyPI. Si votre Python est trop récent (3.15), un Python 3.14 privé est placé dans `deps/` (NuGet).
- **devkitPro** : son installateur officiel s'ouvre ; gardez le dossier proposé et cochez « Switch Development ».
- **ounce-devkit** : son `install.sh` ajoute son dépôt et sa clé de signature au pacman de devkitPro.

Python, l'installateur et `install.sh` sont vérifiés par SHA-256 avant d'être utilisés.

## Installation manuelle

```powershell
py -3.14 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe nxrelink.py setup
```

## Utilisation

```powershell
.venv\Scripts\python.exe nx2_easy.py
```

ou en ligne de commande :

```powershell
.venv\Scripts\python.exe nxrelink.py make "D:\jeu.nup" --name monjeu --sd E:
```

### Par Wi-Fi avec SW2Transfer

[SW2Transfer](https://github.com/Rodpad/SW2Transfer) (l'application, ou son plugin en arrière-plan) reçoit le port par Wi-Fi, sur
plusieurs connexions à la fois : bien plus rapide que le FTP. Choisissez **SW2Transfer** à l'étape 2 et tapez l'adresse affichée
sur l'écran de la console, ou en ligne de commande :

```powershell
.venv\Scripts\python.exe nxrelink.py make "D:\jeu.nup" --name monjeu --sw2t 192.168.1.42
```

Si SW2Transfer a un mot de passe, donnez-le dans la fenêtre, ou dans `SW2T_PASSWORD` (sinon le terminal le demande).

## Langues

Français, anglais, espagnol, allemand, italien et portugais. La langue du navigateur est prise par défaut ; le menu en haut de la page
la change, et le choix est gardé. Le journal technique de nx2-relink reste en anglais.

Pour ajouter une langue, copiez `locales/en.json` sous son code (par exemple `nl.json`) et traduisez les textes, `_name` compris.
Gardez les balises et les `{mots}` entre accolades. Un texte absent s'affiche en anglais.

Documentation complète (en anglais) : [docs/nx2-relink.md](docs/nx2-relink.md).

## Licence

[MIT](LICENSE), © 2026 Olmectron pour nx2-relink.
