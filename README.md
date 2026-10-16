# vimvibe

**Click anything on your Linux desktop by typing its name — or the two letters on its label.**
An open-source, Linux-native take on [Shortcat](https://shortcat.app) (macOS), and Vimium's link hints for the whole
desktop instead of just the browser.

Press **Meta+Shift+Space** in any app. Every button, link, tab and field in the focused window gets a small letter label
(`SA` for *Save*, `PR` for *Pull requests*). Type the label or part of the name, press **Enter**, done — no mouse.

> **Status: working prototype.** Built and tested on Fedora 44, KDE Plasma 6.7 on Wayland. Other desktops are planned
> (see [research/11](research/11-os-scope-plan.md)). Expect rough edges; reports are welcome.

- [How it works](#how-it-works)
- [Install](#install)
- [Quick start](#quick-start)
- [Using it](#using-it)
- [Settings](#settings)
- [Arrow keys and scrolling](#arrow-keys-and-scrolling)
- [Excluding apps](#excluding-apps)
- [Making apps visible](#making-apps-visible-accessibility)
- [Troubleshooting](#troubleshooting)
- [Commands](#command-reference)
- [Developer guide](#developer-guide)
- [Shortcat feature parity](#shortcat-feature-parity)
- [Privacy and security](#privacy-and-security)

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
- **Esc** closes it.

To start vimvibe automatically, tick *Launch at login* in `vimvibe settings`.

For clicks that need the pointer (see [How it works](#how-it-works)), allow it once:
`vimvibe-core pointer-setup` (your desktop shows a *Remote Control* dialog; allow the pointer, and the keyboard if
you want Space + H/J/K/L arrow keys).

## Using it

| Do | Keys |
|---|---|
| Open / close | **Meta+Shift+Space** (Esc also closes) |
| Quit vimvibe completely (daemon + overlay) | **Meta+Shift+Q** (or `vimvibe stop`) |
| Settings | **Ctrl+Shift+,** from anywhere (**Ctrl+,** while the overlay is open) |
| Arrow keys in the app | hold **Space** + **H J K L** (or I J K L) — ← ↓ ↑ →; add Shift/Ctrl/Alt for selection or word jumps; release Space to come back ([details](#arrow-keys-and-scrolling)) |
| Scroll | hold **Space** + **Ctrl** + **H J K L** — scrolls the selected element, or the window; **Shift** = 4× further |
| Pick an element | type its **label** (`pr`) or part of its **name** (`pull`), then **Enter** |
| Right click / double click / middle click | **Ctrl+Enter** / **Alt+Enter** / **Shift+Enter** |
| Move the pointer onto it (hover) | **tap Ctrl** |
| Give it keyboard focus (e.g. a text field) | **tap Ctrl twice** |
| Act on result row *n* / just select it | **Ctrl+1…9** / **Ctrl+Shift+1…9** |
| Move the selection | **↑ ↓**, **Tab / Shift+Tab**, **Ctrl+N / Ctrl+P**, **PageUp / PageDown**, mouse wheel |
| Clear the search, show every label again | **tap Alt** |
| Re-read the window (after the page changed) | **Ctrl+R** |
| Switch to another window | type its app or title (e.g. `konsole`) → **Enter** |
| Launch an app | type its name (`calculator`, `firefox`) → **Enter** |
| Use the start menu, tray or calendar popups | open the popup, then **Meta+Shift+Space**: its items get labels and the popup stays open |
| Use an open menu (also nested submenus) | open it, then **Meta+Shift+Space**: every level of the menu gets labels and stays open |
| Click something on the taskbar / panel | its buttons, tasks and tray icons are labelled in every window |
| Close / maximize / minimize the window | its title-bar buttons have labels too (`CW`, `MA`, `MW`) |
| Mouse | click a label or a row to activate it; click anywhere else to close |

Search tips (as in Shortcat): one or two words beat long queries; add a role word to narrow results — `btn`,
`button`, `link`, `check`, `radio`, `tab`, `menu`, `field` (`save btn`). While you type, only labels that start
with what you typed stay visible; letters already typed are dimmed.

**Continuous mode** (off by default): after each click vimvibe re-reads the window and comes back, ready for the next
click — good for browsing. It stops on Esc, after you act on a text field, or when a menu/another window takes over.

## Settings

Open the Settings window with **Ctrl+Shift+,** (or `vimvibe settings`). It has a live preview of the labels and edits
`~/.config/vimvibe/config.toml`, which you can also edit by hand. Changes apply the next time the overlay opens.

| Tab | What you can set |
|---|---|
| General | shortcuts (changed in System Settings), launch at login, window switching, app launching, panel labels |
| Appearance | theme presets (Blue, Shortcat, Nord, Dracula, Gruvbox, Solarized light, High contrast); label background, text, outline and selected colours; font; label text size; overall label size; corner radius; capitals; panel style (dark/light), opacity, width, result rows, text size, position, key-hint line, hide-until-typing; screen dimming |
| Labels & behaviour | when labels appear (immediately … 5 s, after input), Vimium-style auto-click, continuous mode, arrow/scroll keys (HJKL/IJKL) and scroll distance |
| Excluded apps | apps vimvibe must never read or click |
| Accessibility & setup | setup check, turn accessibility on, keep it on after login, allow pointer and keyboard control |

```toml
[ui]
theme = "Blue"             # preset the colours came from (informational)
accent = "#3b82f6"         # label background ("#facc15" + label_text "#000000" = Shortcat's look)
label_text = "auto"        # label text colour; auto = black or white, whichever reads
label_border = "auto"      # label outline colour
selected = "auto"          # highlight of the selected element/label (Shortcat uses light green, "#86efac")
font = ""                  # font family; empty = desktop font
label_font_size = 0        # points; 0 = automatic
label_scale = 1.0          # overall label size, 0.6–2.0
label_radius = 3           # corner radius, px
uppercase = true           # SA vs sa (typing is case-insensitive)
panel = "auto"             # auto | top | center | bottom
panel_theme = "dark"       # dark | light
panel_opacity = 0.96
panel_width = 640
rows = 9                   # result rows shown (Ctrl+1..9 reach the first nine)
panel_font_size = 0        # points; 0 = automatic
hint_line = true
hide_panel_until_typing = false   # labels only until you type (Shortcat's "hide query pane")
dim = 0                    # darken the screen behind the labels, percent 0–60

[hints]
delay_ms = 0               # when labels appear after opening (Shortcat's default is 2000)
after_input = false        # true: labels appear only once you start typing
auto_activate = false      # true: a fully typed label clicks at once (Vimium-style), no Enter

[behavior]
continuous = false         # come back after each click
continuous_delay_ms = 500

[scroll]
keys = "hjkl"              # or "ijkl": arrow keys (Space+keys) and scrolling (Space+Ctrl+keys)
step = 3                   # wheel clicks per key press (Shift: 4×)

[search]
windows = true             # offer your other open windows as results (window switching)
apps = true                # offer installed applications as results
panel = true               # label Plasma's panels (only while they are visible)

[apps]
exclude = ["keepassxc", "org.kde.konsole"]

[accessibility]
enable_on_start = true     # the daemon turns desktop accessibility on when it starts
```

One-off colour for a single run: `python3 ~/.local/share/vimvibe/vimvibe_palette.py --accent orange`
(or set `VIMVIBE_ACCENT`).

## Arrow keys and scrolling

Like Shortcat's *Arrow Keys / Scroll* feature, vimvibe lets you move around an app from the home row while the
overlay is open. You need the desktop's **Remote Control** permission once (see below).

| Hold | Then press | Does |
|---|---|---|
| **Space** | **H J K L** (or I J K L) | sends ← ↓ ↑ → to the app — move in lists, menus, text, file views |
| **Space** + **Shift** / **Ctrl** / **Alt** | **H J K L** | the arrow key with that modifier — Space+Shift+J selects downward, Space+Ctrl+L jumps a word |
| **Space** + **Ctrl** | **H J K L** | scrolls (mouse-wheel steps); add **Shift** to scroll 4× further |
| — | release **Space** | the window is re-read and vimvibe comes back with fresh labels |
| — | **Esc** | stop (arrow mode ends, vimvibe stays closed) |

The keys are matched by their **position** on the keyboard, not the letter they type, so they sit under your right
hand on Dvorak, Colemak or AZERTY too. Choose H J K L (Vim) or I J K L (arrow layout) in *Settings → Labels &
behaviour*, together with the scroll distance.

### How arrow keys work (and where they don't)

On Wayland an app may not type into another app, so arrow keys go through the desktop's Remote Control permission
— the keyboard part of it. When you press Space + J, vimvibe hides, the app gets the keyboard back, and vimvibe
watches only for the H J K L / I, Space and Esc keys (through the accessibility keystroke listener screen readers use),
turning them into arrow keys; every other key goes to the app as usual. Releasing Space gives everything back.

That listener only sees keys in apps that share their key presses with accessibility: **KDE/Qt apps and GTK 3 apps
(Firefox, GIMP, …)**. In **Chrome/Electron and GTK 4** apps vimvibe could not tell your J from typing, so it checks
first (it taps Shift and looks whether the tap arrives) and, if it can't, says so and does nothing — use
Space+Ctrl+H/J/K/L scrolling there, which works everywhere. Without the keyboard permission, Space + H/J/K/L scrolls
instead and a notice tells you how to allow the keyboard.

### How scrolling works

- What scrolls: the selected result's element when you have typed something (e.g. type `files`, then Space+Ctrl+J
  scrolls that list), otherwise the middle of the window. The pointer is parked there for the scroll and put back
  afterwards.
- How: real mouse-wheel steps through the Remote Control permission, so it works in every app, accessible or not.
  While you scroll, the overlay lets the wheel events through to the app.

### The permission

```bash
vimvibe-core pointer-setup      # or Settings → Accessibility & setup → "Allow pointer and keyboard control…"
```

Your desktop shows its *Remote Control* dialog once: allow **pointer** (clicks, scrolling, right click, hover) and
**keyboard** (only used for the arrow keys). KDE remembers the answer; vimvibe never opens the dialog on its own.
`vimvibe doctor` shows what is allowed. Revoke it any time in **System Settings → Security & Privacy → Remote
Control**, or delete `~/.local/state/vimvibe/pointer-token`.

## Excluding apps

Apps listed under `[apps] exclude` are **never read and never acted on**: when one of them is focused and you press the
shortcut, vimvibe doesn't look at its window at all and shows a notification instead. They are also left out of window
switching. Good candidates: password managers, banking apps, terminals with secrets, remote-desktop clients.

An entry matches (case-insensitively) the app's accessibility name, its window class (`org.kde.konsole`, and the
short form `konsole`) or its process name. Add entries in *Settings → Excluded apps*.

## Making apps visible (accessibility)

vimvibe can only see apps that expose an accessibility tree. `vimvibe doctor` lists which open apps are visible.

| App type | What to do |
|---|---|
| Qt / KDE apps, GTK 3/4 apps, Firefox | turn accessibility on (`vimvibe doctor --fix`), then **restart the app** |
| Chrome, Chromium, Edge, Brave | start with `--force-renderer-accessibility` |
| Electron apps (VS Code, Discord, Slack, …) | start with `--force-renderer-accessibility` |
| Java apps | need the Java ATK bridge |
| Games, Tk, Wine, apps drawn without a toolkit | not supported yet (a pixel-based fallback is planned) |

Accessibility is a session setting that is off by default on most distributions; `vimvibe doctor --fix-env` writes
`~/.config/environment.d/50-vimvibe-accessibility.conf` so toolkits enable it after your next login.

## Troubleshooting

| Problem | Fix |
|---|---|
| Nothing happens on Meta+Shift+Space | `vimvibe status`: are the daemon and overlay running? `vimvibe start`. Is the shortcut taken by something else? (`vimvibe doctor`) |
| Notification "can't read this window" | the app started before accessibility was on, or has no accessibility: restart it (see table above) |
| The start menu closes when vimvibe opens | the overlay could not use layer-shell (`layer-shell-qt`, normally installed with Plasma): check `vimvibe logs` |
| vimvibe keeps running / want it gone | **Meta+Shift+Q**, or `vimvibe stop` |
| Notification "vimvibe is off for this app" | it's in your excluded list |
| Few or no labels in Chrome/Electron | start the app with `--force-renderer-accessibility` |
| Labels in the wrong place | report it with your scaling and monitor setup (HiDPI/multi-monitor are not tested yet) |
| "pointer control is not set up" | run `vimvibe-core pointer-setup` once and approve the dialog |
| "Arrow keys need keyboard permission" | run `vimvibe-core pointer-setup` again and allow the keyboard too |
| "can't send arrow keys here" | the app (Chrome/Electron, GTK 4) doesn't share key presses with accessibility: use Space+Ctrl+H/J/K/L to scroll |
| Want to stop vimvibe from clicking or typing arrow keys | System Settings → Security & Privacy → Remote Control, or delete `~/.local/state/vimvibe/pointer-token` |
| Logs | `vimvibe logs` (`~/.local/state/vimvibe/`) |

## Command reference

```text
vimvibe start | stop (= quit) | restart | status | settings | logs | open | help
vimvibe doctor [--fix] [--fix-env]

vimvibe-core <command> [--app NAME] [--json] [--strategy auto|cache|walk] ...
  daemon            the resident service (what `vimvibe start` runs)
  doctor            setup check
  pointer-setup     one-time permission for clicks, scrolling and arrow keys
  list              list the focused window's elements        (vimvibe-core --app dolphin list)
  search QUERY      search them                               (vimvibe-core --app dolphin search "new folder")
  act QUERY         activate the best match                   (--index N, --dry-run)
  status | apps | focus | watch | cursor | click X Y | serve | surfaces
  key KEY…          type keys into the focused window (testing; e.g. `key Down j -- +space -space`)
```

`vimvibe-core --help` and `vimvibe-core <command> --help` print every option.

## Developer guide

### Build and run from the source tree (no install)

```bash
cargo build --release --manifest-path core/Cargo.toml   # binary: core/target/release/vimvibe-core
cargo test  --release --manifest-path core/Cargo.toml   # unit tests

core/target/release/vimvibe-core daemon &               # terminal 1 (or in the background)
VIMVIBE_DEBUG=1 python3 palette/vimvibe_palette.py      # terminal 2: overlay with debug output
python3 palette/vimvibe_palette.py --settings           # the Settings window
```

Useful while developing:

```bash
core/target/release/vimvibe-core --app dolphin list            # what vimvibe sees in an app
core/target/release/vimvibe-core --app dolphin search "folder"
VIMVIBE_DEBUG=1 core/target/release/vimvibe-core focus         # which window it would target, and why
python3 palette/vimvibe_palette.py --trigger --query sa --quit-after 5   # open once without the shortcut
```

### Layout

```
core/                Rust: AT-SPI reading, matching, labels, KWin bridge, daemon, pointer, doctor
  src/enumerate.rs   find the target window, read its elements (Cache / concurrent walk)
  src/matcher.rs     fuzzy search with role words and synonyms
  src/hints.rs       letter labels
  src/model.rs       elements and the activation ladder (action → selection → focus → pointer)
  src/kwin.rs        KWin scripts: focus, geometry, window list, raise, cursor
  src/daemon.rs      D-Bus service org.vimvibe.Daemon
  src/pointer.rs     RemoteDesktop portal clicks
  src/config.rs      ~/.config/vimvibe/config.toml (parts the daemon enforces)
  src/doctor.rs      setup check
palette/             Python/Qt: overlay (vimvibe_palette.py), Settings window (vimvibe_settings.py),
                     shared config + theme (vimvibe_style.py)
packaging/           launcher script, optional systemd user unit
research/            design notes and measurements (start with 09, 10, 11)
```

### D-Bus API

Any UI can drive the daemon (session bus, `org.vimvibe.Daemon`, path `/org/vimvibe/Daemon`):

| Method / signal | |
|---|---|
| `Trigger() → json` | snapshot the focused window (toggles); emits `Opened(json)` or `Refused(json)` |
| `Search(q) → json` | ranked hits `[{id, hint, score, element, screen}]`; a query equal to a label puts that element first |
| `Elements() → json` | every element with id, label, role, screen rectangle |
| `Activate(i)` / `ActivateId(id)` / `ActivateWith(id, action)` | act on a hit / an element; action = `click right double middle hover focus` |
| `Refresh()` | re-read the same window |
| `ScrollStart(id)`, `Scroll(dx, dy)`, `ScrollEnd()` | park the pointer over element `id` (or the window), scroll by wheel clicks, put it back |
| `ArrowStart(dx, dy)`, `ArrowEnd(reopen)` | arrow-key mode: hide, take the physical H/J/K/L/I, Space, Esc keys and send arrows; Space release reopens |
| `Close()`, `Status() → json`, `Quit()` | `Quit` = Meta+Shift+Q |
| signals `Opened(json)`, `Closed()`, `Refused(json)`, `Quitting()`, `Key(json)`, `OpenSettings()` | |

Try it: `gdbus call --session --dest org.vimvibe.Daemon --object-path /org/vimvibe/Daemon --method org.vimvibe.Daemon.Status`

## Shortcat feature parity

| Shortcat | vimvibe |
|---|---|
| Search elements by name, role words, synonyms | ✅ |
| Letter labels (hints) on every element, typed to select | ✅ (2–3 letters; colour configurable) |
| Label delay setting (immediately … 5 s, after input) | ✅ |
| Enter click · Ctrl+Enter right click · double click | ✅ (double click = Alt+Enter) |
| Tap Ctrl to hover · double-tap to focus | ✅ |
| Cmd+number act on row · Cmd+Shift+number select | ✅ as Ctrl+number / Ctrl+Shift+number |
| Option shows all labels | ✅ tap Alt |
| Tab / Ctrl+N / Ctrl+P navigation | ✅ |
| Cmd+R refresh | ✅ Ctrl+R |
| Continuous mode | ✅ (experimental, as in Shortcat) |
| Window switching, minimised windows | ✅ (KDE) |
| Custom activation shortcut, launch at login | ✅ (shortcut via System Settings) |
| Launch applications | ✅ (installed apps; also from the start menu) |
| Window title-bar buttons | ✅ (close, maximize, minimize, window menu, all desktops) |
| Menu bar / app menu search, Dock | ⏳ planned ([research/11](research/11-os-scope-plan.md)) |
| Space+HJKL arrow keys (IJKL option, keycode-based) | ✅ in KDE/Qt and GTK 3 apps, with the desktop's keyboard permission |
| Space+Cmd+HJKL scroll | ✅ as Space+Ctrl+HJKL, wheel events through the pointer permission, in every app |
| Preferences window (Cmd+,) | ✅ Ctrl+Shift+, anywhere, Ctrl+, in the overlay; plus label/panel theming Shortcat doesn't offer |
| Hide query pane by default | ✅ `hide_panel_until_typing` |
| Emoji search with `:` | ⏳ planned |
| Cmd+Enter / Shift+Enter modifier clicks | ⏳ planned (Shift+Enter is middle click for now) |
| — | ➕ excluded-apps list, setup doctor, works with any UI over D-Bus |

## Privacy and security

- Everything runs locally. vimvibe has no network code and sends nothing anywhere.
- It reads element names only from the window you trigger it on, only when you trigger it, and keeps them in memory
  until the overlay closes. Window titles are used for window switching and never written to logs.
- Excluded apps are never read.
- Pointer control goes through the desktop's permission prompt; you can revoke it any time. No root, no `uinput`.

## Known limitations

- KDE Plasma (Wayland) only for now; focus tracking and the shortcut use KWin/kglobalaccel.
- The overlay is a normal fullscreen window, not a layer-shell surface: keys typed in the instant between the shortcut
  and the overlay appearing can reach the app, and KDE may animate the overlay.
- Not yet tested: HiDPI/fractional scaling, multiple monitors, XWayland apps, very large pages with the overlay.
- Only the focused window's elements (plus other windows as switch targets) — menus, tray, launcher: see the plan.
- To find open menus (Qt keeps them out of the accessibility tree) vimvibe listens for "menu shown" events. While any
  client listens for accessibility events, Qt apps hand each key press to the accessibility registry first, exactly as
  when a screen reader runs; vimvibe only takes keys while it is open over a popup.
- Menus that were already open when the daemon started are not known until they are reopened.
- Over Plasma's popups (start menu, tray, calendar) and open menus vimvibe reads your keys through the accessibility registry instead
  of taking the keyboard (so the popup stays open). Plain keys and Shift go to vimvibe while it is open there;
  Ctrl/Alt/Super combinations still reach the popup. Esc, or 60 s without a key, gives the keyboard back.
- Elements an app doesn't expose to accessibility (custom-drawn canvases, some image views) get no label.
- Title-bar button labels are placed from the KWin button layout; with an unusual decoration theme they may sit a few
  pixels off (pressing them is exact: it runs the KWin action, not a click).

## Project background

`research/` holds the evidence behind every design choice: how Shortcat behaves (from its public docs), what
existing Linux tools do ([10](research/10-prior-art-analysis.md)), measurements on this machine
([09](research/09-core-prototype.md)), and the plan to reach the rest of the desktop
([11](research/11-os-scope-plan.md)). vimvibe is independent and not affiliated with Shortcat.
