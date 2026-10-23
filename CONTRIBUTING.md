# Contributing to vimvibe

Thanks for helping. vimvibe is a keyboard-driven "click anything" overlay for Linux (KDE Plasma on Wayland first).
This file explains how the project fits together, how to run and test your changes, and what a good contribution
looks like. The [README](README.md) and [docs/](docs/using.md) cover using vimvibe; this covers working on it.

## Contents

- [How the project fits together](#how-the-project-fits-together)
- [Set up](#set-up)
- [Run your changes without touching your installed copy](#run-your-changes-without-touching-your-installed-copy)
- [Tests and checks](#tests-and-checks)
- [Where things live](#where-things-live)
- [Rules the design depends on](#rules-the-design-depends-on)
- [Comments: how the code is documented](#comments-how-the-code-is-documented)
- [Common changes](#common-changes)
- [Branches, commits and pull requests](#branches-commits-and-pull-requests)
- [Reporting bugs](#reporting-bugs)
- [Licence](#licence)

## How the project fits together

Two processes talk over the session D-Bus:

```
 vimvibe-core daemon (Rust, core/)                 overlay + Settings (Python/PySide6, palette/)
  • global shortcut, focus tracking (KWin)    ──►   • draws the search panel and the letter labels
  • reads the focused window (AT-SPI)               • sends your choice back (Search / Activate / ...)
  • letters, ranking, activation, pointer     ◄──   • never reads the screen or other apps itself
```

- The **daemon** owns everything that needs the system: the accessibility tree, KWin, the pointer and keyboard
  permission, the global shortcuts. It idles with no polling.
- The **overlay** is a thin client. Anything that speaks the same D-Bus API could replace it
  (API table: docs/development.md → *D-Bus API*, and the header of `core/src/daemon.rs`).
- Settings live in `~/.config/vimvibe/config.toml`. The daemon reads only what it enforces; the overlay reads the rest.
  Defaults for the overlay are in `palette/vimvibe_style.py`, for the daemon in `core/src/config.rs`. A new setting
  needs both sides to agree on its name.

`research/` holds the measurements behind the design (start with 09, 10 and 11). Read the relevant note before
changing something it covers: several things that look odd (for example how Chromium is enabled, or why keys are
taken through the accessibility registry) are the result of measured dead ends.

## Set up

You need a Linux machine to test on. KDE Plasma 6 on Wayland is the supported target; other desktops are planned.

| What | Needed for |
|---|---|
| Rust (stable, edition 2024) and `cargo` | the daemon |
| Python 3 with PySide6 | the overlay and Settings (`python3-pyside6.qtwidgets`, or `pip install --user PySide6`) |
| `glib2` tools (`gdbus`) | talking to the daemon from a shell |
| `layer-shell-qt` | normally installed with Plasma |

```bash
git clone https://github.com/OverRevvv/vimvibe.git && cd vimvibe
git switch beta            # day-to-day work happens on beta; main holds releases
cargo build --release --manifest-path core/Cargo.toml
```

Accessibility must be on for anything to be visible: `core/target/release/vimvibe-core doctor --fix`, then restart
the apps you test with. `doctor` tells you what it sees and what is wrong.

## Run your changes without touching your installed copy

Use the **dev profile**. It has its own D-Bus name, shortcuts, settings and logs, so it can run next to an
installed vimvibe.

```bash
./dev.sh start          # builds what changed, starts the dev daemon + overlay
./dev.sh restart        # after changing code
./dev.sh settings | status | logs | doctor | stop
```

The dev shortcuts are **Meta+Alt+Space** (open), **Meta+Alt+Q** (quit) and **Ctrl+Alt+,** (Settings).
Dev settings are in `~/.config/vimvibe-dev/`; logs in `~/.local/state/vimvibe-dev/`.

Do not run `./install.sh` to test a change. It replaces your installed copy.

Handy when debugging:

```bash
core/target/release/vimvibe-core --app dolphin list           # what vimvibe sees in an app
VIMVIBE_DEBUG=1 core/target/release/vimvibe-core focus        # which window it would target, and why
VIMVIBE_PROFILE=dev core/target/release/vimvibe-core doctor   # doctor for the dev profile
python3 palette/vimvibe_palette.py --trigger --query sa --quit-after 5   # open once, no shortcut
gdbus call --session --dest org.vimvibe.DaemonDev --object-path /org/vimvibe/Daemon --method org.vimvibe.Daemon.Status
```

## Tests and checks

Run these before you open a pull request:

```bash
cargo test   --release --manifest-path core/Cargo.toml     # Rust unit tests
cargo clippy --release --manifest-path core/Cargo.toml     # must stay free of warnings
(cd palette && python3 -m unittest test_keys test_mouse test_overlay)   # Python logic tests
```

- Unit tests cover the logic that does not need a desktop (matching, labels, key tables, the mouse grid, command-line
  splitting). **Put new logic in a testable function and add a test.** Keep GUI code thin so this stays possible.
- Anything that needs a real desktop (AT-SPI, KWin, the portal, the overlay) cannot run in CI. For those changes,
  test it by hand with `./dev.sh` and say in the pull request **what you ran and what you saw**, including the
  desktop, session type and the app(s) you tried it on.
- The code is not auto-formatted as a whole (`cargo fmt` would rewrite files you did not touch). Match the style
  of the code around yours, and do not reformat unrelated lines; it makes reviews unreadable.

## Where things live

```
core/src/
  main.rs        command line (clap) and the small subcommands
  daemon.rs      D-Bus service org.vimvibe.Daemon: Trigger/Search/Activate/Scroll/Pointer*/... (start here)
  enumerate.rs   finds the target window, reads its elements (AT-SPI cache or concurrent walk)
  model.rs       Element and the activation ladder: action -> selection -> focus -> pointer
  matcher.rs     fuzzy search, role words, synonyms          hints.rs   letter labels
  kwin.rs        KWin scripts: focus, geometry, window list  decor.rs   title-bar buttons
  popups.rs      menus and Plasma popups                     apps.rs    installed applications as results
  keygrab.rs     keys through the accessibility registry (popup mode, arrow mode)
  scroller.rs    smooth scrolling                            pointer.rs RemoteDesktop portal: clicks, motion, keys
  chromium.rs    Chromium/Electron: detect, fix launchers, restart with --force-renderer-accessibility
  config.rs      config.toml and profiles                    doctor.rs  setup check and the --fix options
palette/
  vimvibe_palette.py   the overlay            vimvibe_settings.py   the Settings window
  vimvibe_style.py     config, defaults, theme  vimvibe_keys.py      rebindable keys (tests: test_keys.py)
  vimvibe_mouse.py     mouse grid logic (tests: test_mouse.py)   vimvibe_clip.py  clipboard history (Klipper) and set-clipboard   test_overlay.py  overlay key behaviour, headless
packaging/       launcher script, systemd user unit, icons      install.sh   installer / upgrader / --uninstall
docs/            screenshots used by the README                 research/    design notes and measurements
```

## Rules the design depends on

Keep these when you change anything; reviewers will check them.

1. **Local and private.** No network code, no telemetry. Element names are read only from the window the user
   triggered, only on trigger, and kept in memory. Window titles are never written to logs or `doctor` output.
2. **Semantic first.** Activate through the app (AT-SPI action, selection, focus) before falling back to a pointer
   click. Keep the activation order in `model.rs`.
3. **No root, no `uinput`.** Pointer and keyboard injection go through the XDG RemoteDesktop portal with the user's
   one-time consent. The daemon never opens the consent dialog on its own (only `pointer-setup` does).
4. **Idle means idle.** No polling or timers while the overlay is closed. Wake-ups come from D-Bus messages.
5. **Excluded apps are never read.** `[apps] exclude` is enforced in the daemon, not the overlay.
6. **The overlay never takes the keyboard when it must not.** Over popups (the start menu, open menus) keys come
   through `keygrab.rs`. Do not add shortcuts that steal keys from a popup.
7. **A new setting is a full feature:** a default in both places, a control in Settings, loading and saving that keeps
   unknown keys, and a line in docs/using.md. Only non-default key bindings are written to `[keys]`.
8. **Never kill or restart a user's app without asking.** The Chromium restart is only offered, never automatic.
9. **Do not invent measurements.** If you claim a behaviour ("Chrome ignores X"), measure it, and put the result in
   `research/` or the pull request.

## Comments: how the code is documented

The code is meant to be read top-down by someone new to the project, so comments are part of every change:

- **Every function gets a comment** saying what it is responsible for and what it returns or changes: `///` in Rust,
  a docstring in Python. Tests get a one-line comment saying what behaviour they pin down.
- **Every file starts with a header** (`//!` or a module docstring) saying what the file is for and where it fits.
- **Explain *why*, not *what*.** Comment non-obvious logic: ordering that matters, a workaround for an app's quirk,
  a measured number, a lock or `await` you must not move. Long functions get short step comments (1., 2., ...).
- **Keep comments true.** If you change behaviour, change the comment in the same commit. A stale comment is worse
  than none. When you add or change a D-Bus method, update the header in `daemon.rs` and the table in docs/development.md.
- Do not narrate the obvious (`// increment i`) and do not leave commented-out code.

## Common changes

**Add a D-Bus method.** Implement it in `daemon.rs` (follow the existing `#[zbus::interface]` methods, validate input, return
JSON text), document it in the header comment there and in the D-Bus table in docs/development.md, then call it from the overlay.

**Add a keyboard shortcut to the overlay.** Add an action in `palette/vimvibe_keys.py` (name, default, label), handle
it in `vimvibe_palette.py`, extend `test_keys.py`, and mention it in the palette docstring and docs/using.md → *Customizing keys*.

**Add a setting.** Struct and default in `core/src/config.rs` (if the daemon needs it), default in
`palette/vimvibe_style.py`, widget + load + collect in `vimvibe_settings.py`, docs/configuration.md.

**Support another app or toolkit.** First run `vimvibe-core --app NAME list` and `doctor`. If the tree is empty, it is
usually an accessibility setup problem, not a bug in matching; add it to docs/using.md → *Making apps visible* once you know
the fix. Chromium-based apps are handled generically in `chromium.rs`; do not add per-app name lists.

**Support another desktop.** Most of the daemon is desktop-neutral (AT-SPI, portal). The KDE-only parts are the
shortcut and focus tracking in `kwin.rs`. Read [research/11](research/11-os-scope-plan.md) first and open an issue
to agree on the shape before writing a lot of code.

**Change the icon.** Edit `packaging/icons/vimvibe.svg`, then run `python3 packaging/icons/make-icons.py`.

## Branches, commits and pull requests

- Branch from `beta` and open pull requests against `beta`. `main` is for releases.
- One topic per pull request. Fix a bug in one, add a feature in another.
- Commit messages: a short imperative summary line ("Fix start menu closing on Ctrl+Space"), then a paragraph on
  *why* if it is not obvious. Say what was wrong, not just what changed.
- In the pull request description, include:
  - what changed and why, and what you did **not** change on purpose;
  - how you tested it (commands run, the desktop and apps you tried by hand);
  - screenshots or a short recording for anything visible in the overlay or Settings;
  - any new permission, file, or D-Bus surface the change adds.
- Every new or changed function is commented as described in [Comments](#comments-how-the-code-is-documented).
- Update the docs in the same pull request: README and docs/ (user-facing behaviour, commands, D-Bus table, limitations),
  the doc comment at the top of the file you changed, and this file if you changed how to build or test.
- Do not commit build output (`core/target/`), `__pycache__`, personal config, or tokens.
- Releases: bump `version` in `core/Cargo.toml`, tag `vX.Y.Z`. See README → *Upgrading and developing side by side*.

## Reporting bugs

Open an issue with:

1. The output of `vimvibe doctor` (it prints application classes and PIDs, never window titles).
2. Desktop, version and session type (for example "KDE Plasma 6.7, Wayland"), and the app and its version.
3. Exactly what you pressed and what happened versus what you expected.
4. The tail of `vimvibe logs` (`~/.local/state/vimvibe/`) if something crashed or a notification appeared.

"It finds nothing in app X" is very often accessibility setup; check *Making apps visible* in the README first.

## Licence

The repository does not yet carry a licence file. Until one is added, ask the maintainer before assuming how
contributions may be reused, and do not copy code into vimvibe from projects whose licence is incompatible or
unknown (the prior-art notes in `research/10` record which projects are GPL-3 and which have no licence).
