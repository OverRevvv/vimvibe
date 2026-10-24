<img src="docs/icon.png" alt="vimvibe icon: a keycap with a V on a keyboard" width="112" align="right">

# vimvibe

**Click anything on your Linux desktop by typing its name — or the two letters on its label.**
An open-source, Linux-native take on [Shortcat](https://shortcat.app) (macOS), and Vimium's link hints for the whole
desktop instead of just the browser.

Press **Meta+Shift+Space** in any app. Every button, link, tab and field in the focused window gets a small letter label
(`SA` for *Save*, `PR` for *Pull requests*). Type the label or part of the name, press **Enter**, done — no mouse.

![vimvibe over Konsole: a letter label on every button, tab and title-bar control, and the search panel with results](docs/screenshot.png)

*vimvibe over Konsole (default blue theme): a label on every control, including the title-bar buttons and the buttons
inside each split terminal; the panel lists the matches with their labels and Ctrl+1…9 shortcuts.*

> **Status: working prototype.** Built and tested on Fedora 44, KDE Plasma 6.7 on Wayland. Other desktops are planned
> (see [research/11](research/11-os-scope-plan.md)). Expect rough edges; reports and contributions are welcome
> ([CONTRIBUTING.md](CONTRIBUTING.md)).


## How it works

```
 Meta+Shift+Space ──► vimvibe-core daemon (Rust)                     vimvibe overlay (Python/Qt)
                       • knows the focused window (KWin script)  ──► • search panel + letter labels
                       • reads its elements (AT-SPI accessibility)    • sends your choice back
                       • assigns labels, ranks search results    ◄── over D-Bus
                       • acts: the app's own action first, pointer click only as a fallback
```

- **Semantic first.** vimvibe reads the same accessibility tree screen readers use, so it knows each element's *name*
  and *role*, and it activates elements through the app itself (no mouse needed for most clicks).
- **Pointer fallback.** Some controls can't be activated that way (GTK4 check boxes, for example). For those, and for
  right click / hover, vimvibe clicks through the desktop's Remote Control permission, which your desktop asks you for
  once. The pointer goes back where it was.
- **Fast and light.** The daemon idles at ~10 MB and zero CPU (no polling). Opening the overlay on a typical window takes
  10–40 ms; a big Chrome page ~100–200 ms.

## Install

Requirements: KDE Plasma 6 (Wayland), Rust (`cargo`), Python 3 with PySide6, `gdbus`.

```bash
# Fedora
sudo dnf install cargo python3-pyside6 glib2
# Debian/Ubuntu: sudo apt install cargo python3-pyside6.qtwidgets libglib2.0-bin   (or: pip install --user PySide6)
# Arch:          sudo pacman -S rust pyside6 glib2

git clone <this repo> vimvibe && cd vimvibe
./install.sh
```

`install.sh` builds the core and installs, for your user only (no root):

| File | What |
|---|---|
| `~/.local/bin/vimvibe-core` | the core and daemon |
| `~/.local/bin/vimvibe` | launcher: `start`, `stop`, `settings`, `doctor`, … |
| `~/.local/share/vimvibe/` | the overlay and the Settings window |
| `~/.local/share/icons/hicolor/…/vimvibe.*` | the icon (SVG + 16–512 px PNGs) |
| `~/.local/share/applications/vimvibe.desktop` | the "vimvibe Settings" entry in your app menu |

**No Rust?** Download `vimvibe-<version>-linux-x86_64.tar.gz` from the releases page, unpack it and run its `./install.sh`:
it ships the compiled core, so only Python 3, PySide6 and `layer-shell-qt` (from your distro) are needed. Maintainers
build it with `packaging/make-tarball.sh`; pushing a `v*` tag builds and publishes it through GitHub Actions.

Make sure `~/.local/bin` is on your `PATH` (Fedora has it by default). Uninstall with `./install.sh --uninstall`
(your settings in `~/.config/vimvibe/` are kept).

## Quick start

```bash
vimvibe start             # starts the daemon and the overlay; the daemon turns desktop accessibility on
# now restart the apps you want to use (apps started before accessibility was on stay invisible)
vimvibe doctor            # checks your setup and lists which open apps vimvibe can see
vimvibe doctor --fix-env  # optional: keep accessibility on for Qt/GTK apps from the start of your next login
```

Press **Meta+Shift+Space** in, say, Dolphin or System Settings. Then:

- type `sa` → the *Save* label is selected → **Enter**
- or type `save` → **Enter**
- press **Esc twice** to close it (one Esc only warns; in the mouse modes it steps back first).

To start vimvibe automatically, tick *Launch at login* in `vimvibe settings`.

For clicks that need the pointer (see [How it works](#how-it-works)), allow it once:
`vimvibe-core pointer-setup` (your desktop shows a *Remote Control* dialog; allow the pointer, and the keyboard if
you want Space + H/J/K/L arrow keys).

## Keys at a glance

| Do | Keys |
|---|---|
| Open / close | **Meta+Shift+Space** (**Esc Esc** also closes) |
| Pick an element | type its **label** (`pr`) or part of its **name** (`pull`), then **Enter** |
| Right / double / middle click | **Ctrl+Enter** / **Enter twice** / **Shift+Enter** |
| Scroll | hold **Space** + **J K H L** (or **D** / **U**) |
| Text fields (like Vimium) | **Ctrl+I** in any mode, again for the next one, then **Enter** |
| Keyboard mouse | **Ctrl+G** (grid) · **Ctrl+M** (H J K L movement) |
| Switch window / launch app | type its name, **Enter** |
| Settings / quit | **Ctrl+Shift+,** / **Meta+Shift+Q** |

The full list of keys, modes and settings is in the [documentation](docs/using.md).

## Documentation

| | |
|---|---|
| [Using vimvibe](docs/using.md) | every key, scrolling, the keyboard mouse, text fields, accessibility, troubleshooting, commands |
| [Configuration](docs/configuration.md) | the Settings window and every `config.toml` option |
| [Development](docs/development.md) | build, dev profile, code layout, D-Bus API |
| [Shortcat parity](docs/shortcat-parity.md) · [Limitations](docs/limitations.md) | what matches Shortcat, what does not yet |
| [CONTRIBUTING.md](CONTRIBUTING.md) | conventions and checks |

The same pages are published as a website (`index.html`, no build step; GitHub Pages: Settings → Pages → deploy from the `main` branch, root folder).

## Privacy and security

- Everything runs locally. vimvibe has no network code and sends nothing anywhere.
- It reads element names only from the window you trigger it on, only when you trigger it, and keeps them in memory
  until the overlay closes. Window titles are used for window switching and never written to logs.
- Excluded apps are never read.
- Pointer control goes through the desktop's permission prompt; you can revoke it any time. No root, no `uinput`.

## Project background

`research/` holds the evidence behind every design choice: how Shortcat behaves (from its public docs), what
existing Linux tools do ([10](research/10-prior-art-analysis.md)), measurements on this machine
([09](research/09-core-prototype.md)), and the plan to reach the rest of the desktop
([11](research/11-os-scope-plan.md)). vimvibe is independent and not affiliated with Shortcat.

## License

[MIT](LICENSE).
