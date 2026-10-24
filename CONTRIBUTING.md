# Contributing to vimvibe

Thanks for helping. vimvibe is a keyboard-driven "click anything" overlay for Linux (KDE Plasma on Wayland first).
This file explains how the project fits together, how to run and test your changes, and what a good contribution
looks like. The [README](README.md) and [docs/](docs/using.md) cover using vimvibe; this covers working on it.

## Contents

- [How the project fits together](#how-the-project-fits-together)
- [Set up](#set-up)
- [Run your changes without touching your installed copy](#run-your-changes-without-touching-your-installed-copy)
- [Tests and checks](#tests-and-checks)
- [Testing by hand](#testing-by-hand)
- [The development and release workflow (DevOps)](#the-development-and-release-workflow-devops)
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

**How every feature works inside** (opening, labels, search, clicking, keys, scrolling, the keyboard mouse, insert
mode, OCR, clipboard, settings) is explained in [docs/architecture.md](docs/architecture.md). Read the section for the
area you change.

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
| `spectacle` and `tesseract` (+ `tesseract-langpack-eng`) | the OCR layer (`sudo dnf install tesseract`) |
| `podman` or `docker` | building the RPM in a clean Fedora container |
| `gh` (GitHub CLI) | watching CI runs and releases |

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
cargo test   --release --manifest-path core/Cargo.toml     # Rust unit tests (labels, matching, OCR parsing, key combos, ...)
cargo clippy --release --manifest-path core/Cargo.toml     # must stay free of warnings
(cd palette && python3 -m unittest test_keys test_mouse test_overlay test_select)   # overlay logic, headless
(cd palette && python3 -m unittest test_settings)          # settings export/import + Settings window (own process: it
                                                           # points XDG_CONFIG_HOME at a temporary directory)
```

What each suite covers:

| Suite | What it pins down |
|---|---|
| `core/src/*.rs` `#[cfg(test)]` | label assignment and speed (`hints.rs`), fuzzy matching and role words (`matcher.rs`), which accessibility action counts as a click (`model.rs`), OCR TSV parsing / phrase merging / clipping / scaling (`ocr.rs`), key-combo parsing (`daemon.rs`), command-line splitting (`chromium.rs`) |
| `test_keys.py` | key-combination parsing, defaults, conflicts, `[keys]` overrides |
| `test_mouse.py` | grid naming, zooming, depth limits, alphabet clean-up |
| `test_overlay.py` | the real `Overlay` widget, offscreen, with a fake daemon that records every D-Bus call: Esc Esc, Space panel toggle and scroll chords, mouse modes staying open, Enter twice = double click, Ctrl+I from every mode, clipboard picker (Ctrl+J / K), text mode capture → copy → paste into a field, Ctrl+Tab mode cycle, popups |
| `test_settings.py` | export → import round trip, refusal of foreign or mistyped files, every option survives the Settings window |
| `test_select.py` | text mode: reading order and lines, column-aware j / k, motions with counts, v / V, yank operators, p / P, f label jump, / search, Esc steps, scroll alignment (repeated words, still text beside a list), the multi-screen document (a 30-line paragraph over 27 scrolls copied once, still text left out) |

Run one test: `(cd palette && python3 -m unittest test_overlay.OverlayKeys.test_enter_double_tap_double_clicks)`.

- Unit tests cover the logic that does not need a desktop (matching, labels, key tables, the mouse grid, command-line
  splitting). **Put new logic in a testable function and add a test.** Keep GUI code thin so this stays possible.
- Anything that needs a real desktop (AT-SPI, KWin, the portal, the overlay) cannot run in CI. For those changes,
  test it by hand with `./dev.sh` and say in the pull request **what you ran and what you saw**, including the
  desktop, session type and the app(s) you tried it on.
- The code is not auto-formatted as a whole (`cargo fmt` would rewrite files you did not touch). Match the style
  of the code around yours, and do not reformat unrelated lines; it makes reviews unreadable.

## Testing by hand

Anything involving AT-SPI, KWin, the portal or the overlay on screen needs a real Plasma session. These are the
methods used during development; use them, and say in the pull request which ones you ran.

**Safety first.** Test on windows you own, never on your real work:

- Use `tools/click-target.py` (a window with a plain button, a menu button, a combo box and a double-click button that
  logs every event) instead of clicking in your editor, browser or terminal.
- Never use `pkill -f` / `pgrep -f`. They match your own shell's command line and kill it. Kill test windows by their
  PID (the click target logs it).

```bash
./dev.sh start                                   # the dev profile: Meta+Alt+Space opens it
python3 tools/click-target.py /tmp/ct.log &      # a throwaway window to click
B="busctl --user call org.vimvibe.DaemonDev /org/vimvibe/Daemon org.vimvibe.Daemon"   # (org.vimvibe.Daemon for the installed copy)
$B Trigger                                       # open over the focused window (the click target)
$B Elements                                      # every element: id, label, role, screen rectangle
$B ActivateWith is 2 click                       # act on element 2: click | right | double | middle | hover | focus
$B Search s save                                 # ranked results for a query
$B Status                                        # timings of the last open, pointer and keyboard permission
$B Close
cat /tmp/ct.log                                  # what the window really saw ("menu show", "DOUBLE", ...)
```

More tools:

```bash
core/target/release/vimvibe-core --app dolphin list      # what vimvibe reads in an app (no daemon needed)
core/target/release/vimvibe-core surfaces                # windows, panels and popups as KWin sees them
core/target/release/vimvibe-core cursor                  # the real pointer position
core/target/release/vimvibe-core click 400 300           # a portal click at screen coordinates
core/target/release/vimvibe-core key -- +Control_L m -Control_L   # press keys in the focused window (+ down, - up)
core/target/release/vimvibe-core watch 15                # KWin focus/geometry events for 15 s
spectacle -b -f -n -o /tmp/shot.png                      # a screenshot, to check what is drawn
tesseract /tmp/shot.png stdout --psm 11 tsv | head       # what OCR reads from it
python3 palette/vimvibe_palette.py --trigger --query sa --quit-after 5 --snapshot /tmp/overlay.png   # overlay only
VIMVIBE_DEBUG=1 python3 palette/vimvibe_palette.py       # overlay with debug output
./dev.sh logs                                            # daemon + overlay logs
```

**Docs website:** browsers block `fetch` from `file://`, so serve the repository and open it:

```bash
python3 -m http.server 8765            # then http://localhost:8765/index.html
google-chrome --headless=new --window-size=1300,1000 --virtual-time-budget=6000 \
  --screenshot=/tmp/site.png "http://localhost:8765/index.html#/using"      # check a page without a browser window
```

## The development and release workflow (DevOps)

Everything below is the exact sequence the project uses, from a change to a published release.

### 1. Develop on `beta`

```bash
git switch beta && git pull
./dev.sh start                      # build + run the dev profile next to your installed vimvibe
# ... edit ...
./dev.sh restart                    # rebuilds what changed (cargo) and restarts daemon + overlay
```

### 2. Check

```bash
cargo test   --release --manifest-path core/Cargo.toml
cargo clippy --release --manifest-path core/Cargo.toml
(cd palette && python3 -m unittest test_keys test_mouse test_overlay test_select)
(cd palette && python3 -m unittest test_settings)
```

Then test by hand as above, and update the docs: `docs/using.md` (behaviour), `docs/configuration.md` (settings),
`docs/architecture.md` (how it works), `docs/development.md` (D-Bus API).

### 3. Install for daily use (optional)

```bash
./install.sh                        # build + install to ~/.local (stops and restarts a running vimvibe)
./install.sh --uninstall            # remove it again (settings are kept)
```

### 4. Commit and push

```bash
git add -A && git commit            # imperative summary, then why
git push origin beta
```

### 5. Release

```bash
# 1) bump the version in two places
sed -i 's/^version = ".*"/version = "X.Y.Z"/' core/Cargo.toml
#    packaging/rpm/vimvibe.spec: Version default and a new %changelog entry at the top
cargo build --release --manifest-path core/Cargo.toml     # refreshes Cargo.lock
git commit -am "Release X.Y.Z" && git push origin beta

# 2) tag: this triggers .github/workflows/release.yml, which builds the tarball and publishes a GitHub release
git tag vX.Y.Z && git push origin vX.Y.Z
gh run list --limit 1               # find the run
gh run watch <run-id> --exit-status
gh release view vX.Y.Z              # the tarball and its .sha256 are attached
```

Do not move a published tag. A fix after a release is a new patch version.

### 6. Packages

```bash
packaging/make-tarball.sh           # dist/vimvibe-X.Y.Z-linux-x86_64.tar.gz (+ .sha256): compiled core, overlay,
                                    # installer, icons, README, LICENSE; users need no Rust
packaging/make-rpm.sh               # dist/vimvibe-X.Y.Z-1.fcNN.x86_64.rpm, built in a fedora:latest container
                                    # from the tarball (run make-tarball.sh first); no rpmbuild needed on the host
```

Verify them the way the releases were verified:

```bash
# the tarball installs without Rust, into a scratch home
mkdir -p /tmp/t && tar xzf dist/vimvibe-*.tar.gz -C /tmp/t && cd /tmp/t/vimvibe-*/ && \
  HOME=/tmp/t/home PATH=/usr/bin:/bin ./install.sh && /tmp/t/home/.local/bin/vimvibe version

# the RPM installs with its dependencies in a clean Fedora
podman run --rm -v "$PWD/dist:/d:Z" fedora:latest bash -c \
  "dnf -y install /d/vimvibe-*.rpm && vimvibe version && rpm -qpL /d/vimvibe-*.rpm"
```

### 7. Merge to `main`, docs site

Open a pull request `beta` → `main` (summary, what changed, how it was tested). The documentation site
(`index.html`) is served by GitHub Pages from `main`, root folder. It renders the Markdown files directly, so it
updates with the merge.

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
  ocr.rs         OCR labels for apps without accessibility (spectacle + tesseract)
  config.rs      config.toml and profiles                    doctor.rs  setup check and the --fix options
palette/
  vimvibe_palette.py   the overlay            vimvibe_settings.py   the Settings window
  vimvibe_style.py     config, defaults, theme  vimvibe_keys.py      rebindable keys (tests: test_keys.py)
  vimvibe_mouse.py     mouse grid logic (tests: test_mouse.py)   vimvibe_clip.py  clipboard history (Klipper) and set-clipboard   test_overlay.py  overlay key behaviour, headless
  test_settings.py     settings export/import and the Settings window
  vimvibe_select.py    text mode: the screen's words as a Vim buffer (tests: test_select.py)
packaging/       launcher script, systemd user unit, icons      install.sh   installer / upgrader / --uninstall
packaging/make-tarball.sh, make-rpm.sh, rpm/vimvibe.spec         release tarball and RPM
.github/workflows/release.yml    on a v* tag: build the tarball, publish the GitHub release
docs/            the user and developer documentation (also the website's pages)   index.html   the docs website
tools/click-target.py            a throwaway window for testing clicks by hand
research/        design notes, measurements and plans (12: copy text from the screen)
```

## Rules the design depends on

Keep these when you change anything; reviewers will check them.

1. **Local and private.** No network code, no telemetry. Element names are read only from the window the user
   triggered, only on trigger, and kept in memory. Window titles are never written to logs or `doctor` output.
2. **Clicks behave like the mouse.** Enter makes a real pointer click when the pointer permission is there; the
   semantic ladder in `model.rs` (action → selection → focus) is the fallback and the `click_with = "semantic"` mode.
   Never count a focus-only action as a click. See docs/architecture.md → *Clicking* for the measurements.
3. **No root, no `uinput`.** Pointer and keyboard injection go through the XDG RemoteDesktop portal with the user's
   one-time consent. The daemon never opens the consent dialog on its own (only `pointer-setup` does).
4. **Idle means idle.** No polling or timers while the overlay is closed. Wake-ups come from D-Bus messages.
5. **Excluded apps are never read.** `[apps] exclude` is enforced in the daemon, not the overlay.
6. **The overlay never takes the keyboard when it must not.** Over popups (the start menu, open menus) keys come
   through `keygrab.rs`. Do not add shortcuts that steal keys from a popup.
7. **A new setting is a full feature:** a default in both places, a control in Settings (load and collect), a line in
   docs/configuration.md, and it must survive export → import (`test_settings.py` checks every default appears).
   Only non-default key bindings are written to `[keys]`.
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
- Releases: see [The development and release workflow](#the-development-and-release-workflow-devops).

## Reporting bugs

Open an issue with:

1. The output of `vimvibe doctor` (it prints application classes and PIDs, never window titles).
2. Desktop, version and session type (for example "KDE Plasma 6.7, Wayland"), and the app and its version.
3. Exactly what you pressed and what happened versus what you expected.
4. The tail of `vimvibe logs` (`~/.local/state/vimvibe/`) if something crashed or a notification appeared.

"It finds nothing in app X" is very often accessibility setup; check *Making apps visible* in the README first.

## Licence

vimvibe is [MIT-licensed](LICENSE); contributions are accepted under the same licence. Do not copy code into vimvibe
from projects whose licence is incompatible or unknown (the prior-art notes in `research/10` record which projects are
GPL-3 and which have no licence).
