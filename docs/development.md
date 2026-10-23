# Development

See also [CONTRIBUTING.md](../CONTRIBUTING.md).

## Upgrading and developing side by side

**Use it** — install once, update whenever you like:

```bash
git pull && ./install.sh        # an upgrade in place: stops the running vimvibe, installs, starts it again
vimvibe version                 # what is installed
```

Your settings (`~/.config/vimvibe/`) and the pointer/keyboard permission survive upgrades and `--uninstall`.

**Develop it at the same time** — the source tree runs as a separate **dev profile** that cannot collide with the
installed one:

```bash
./dev.sh start                  # builds (only what changed), then starts the dev daemon + overlay
./dev.sh restart                # after you change code
./dev.sh settings | status | logs | doctor | stop
```

| | installed (`vimvibe …`) | dev (`./dev.sh …`) |
|---|---|---|
| program | `~/.local/bin/vimvibe-core`, `~/.local/share/vimvibe/` | `core/target/release/…`, `palette/` in the repo |
| D-Bus name | `org.vimvibe.Daemon` | `org.vimvibe.DaemonDev` |
| shortcuts (KDE group) | **Meta+Shift+Space**, **Meta+Shift+Q**, **Ctrl+Shift+,** (*vimvibe*) | **Meta+Alt+Space**, **Meta+Alt+Q**, **Ctrl+Alt+,** (*vimvibe-dev*) |
| settings | `~/.config/vimvibe/` | `~/.config/vimvibe-dev/` (starts from your installed settings, never writes to them) |
| logs | `~/.local/state/vimvibe/` | `~/.local/state/vimvibe-dev/` |
| launch at login | yes (if you tick it) | no |
| pointer/keyboard permission | shared (`~/.local/state/vimvibe/`) | approve once for both |

So you can keep the installed copy for daily use, try a change with **Meta+Alt+Space**, and only run `./install.sh`
when the change is good. Any command can target the dev copy with `VIMVIBE_PROFILE=dev` (for example
`VIMVIBE_PROFILE=dev core/target/release/vimvibe-core doctor`); a third copy is `VIMVIBE_PROFILE=beta`.

**Releases and patches** — keep the installed copy on a known version while `main` moves on:

```bash
git tag v0.2.0                                   # mark a release (bump `version` in core/Cargo.toml first)
git worktree add ../vimvibe-stable v0.2.0        # a checkout of exactly that release
(cd ../vimvibe-stable && ./install.sh)           # install it
# ... develop in this tree with ./dev.sh; for a patch: fix, tag v0.2.1, then in ../vimvibe-stable:
git -C ../vimvibe-stable checkout v0.2.1 && (cd ../vimvibe-stable && ./install.sh)
```

## Developer guide

### Build and run from the source tree (no install)

```bash
cargo build --release --manifest-path core/Cargo.toml   # binary: core/target/release/vimvibe-core
cargo test  --release --manifest-path core/Cargo.toml   # unit tests

./dev.sh start                                          # daemon + overlay as the separate dev profile (recommended)
# or by hand, as the installed profile (stop the installed copy first: both would want the same shortcuts):
core/target/release/vimvibe-core daemon &
VIMVIBE_DEBUG=1 python3 palette/vimvibe_palette.py      # overlay with debug output
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
  src/daemon.rs      D-Bus service org.vimvibe.Daemon (the entry point for most behaviour)
  src/enumerate.rs   find the target window, read its elements (Cache / concurrent walk)
  src/matcher.rs     fuzzy search with role words and synonyms
  src/hints.rs       letter labels
  src/model.rs       elements and the activation ladder (action → selection → focus → pointer)
  src/kwin.rs        KWin scripts: focus, geometry, window list, raise, cursor
  src/decor.rs       title-bar buttons          src/popups.rs   menus and Plasma popups
  src/apps.rs        installed applications as results
  src/keygrab.rs     keys through the accessibility registry (over popups; arrow mode)
  src/scroller.rs    smooth scrolling           src/pointer.rs  RemoteDesktop portal: clicks, motion, keys
  src/chromium.rs    Chromium/Electron: detect, fix launchers, restart with --force-renderer-accessibility
  src/config.rs      ~/.config/vimvibe/config.toml (parts the daemon enforces), profiles (dev next to installed)
  src/doctor.rs      setup check and its --fix options
packaging/icons/     the icon: vimvibe.svg (edit this) and the generated PNG sizes (`python3 packaging/icons/make-icons.py`)
palette/             Python/Qt: overlay (vimvibe_palette.py), Settings window (vimvibe_settings.py),
                     shared config + theme (vimvibe_style.py), key bindings (vimvibe_keys.py, tests: test_keys.py),
                     the mouse grid logic (vimvibe_mouse.py, tests: test_mouse.py)
packaging/           launcher script, optional systemd user unit
research/            design notes and measurements (start with 09, 10, 11)
```

Checks before a pull request (details and conventions in [CONTRIBUTING.md](CONTRIBUTING.md)):

```bash
cargo test   --release --manifest-path core/Cargo.toml
cargo clippy --release --manifest-path core/Cargo.toml
(cd palette && python3 -m unittest test_keys test_mouse test_overlay)
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
| `RestartWithAccessibility(pid)` | restart a Chromium-based app (only a main process that lacks `--force-renderer-accessibility`) with the flag, restoring its session, and fix its launchers |
| `PointerMotion(dx, dy)`, `PointerAct(x, y, here, action)` | the keyboard mouse: move the pointer by whole pixels (no waiting); close the overlay, then `move`/`click`/`right`/`double`/`middle` at (x, y) or, with `here`, where the pointer is (`goto` only moves, keeping the overlay). Refused when `[mouse] enabled` is false |
| `ScrollStart(id)`, `Scroll(dx, dy)`, `ScrollEdge(dir)`, `ScrollEnd()` | park the pointer over element `id` (or the window), glide by `dx`/`dy` tenths of a wheel notch (returns at once; the glide carries on), jump to the top (`dir` -1) or bottom (1), put the pointer back after the glide |
| `InsertStart()` | insert mode: take Esc system-wide until pressed (then vimvibe reopens) or the focus moves to another window |
| `EditStart()` / `EditEnd()` | edit mode: take H J K L, U / D, V, Y, P, Esc / I system-wide (KWin shortcuts) and turn them into arrows, Home / End, selecting, Ctrl+C / V; emits `EditMode(visual)` |
| `PointerHold(down)` | hold / release the left button |
| `SendKeys(combo)` | close the overlay, then press `ctrl+c`, `ctrl+v`... in the window below |
| `PointerScroll(dx, dy, x, y, here)` | scroll from the keyboard-mouse modes: move the pointer to (x, y) first unless `here`, then glide `dx`/`dy` tenths of a wheel notch; the pointer stays where it is |
| `ArrowStart(dx, dy)`, `ArrowEnd(reopen)` | arrow-edit mode: hide, take the physical H/J/K/L/I, D/U, Space, Esc keys and send arrows; Space release reopens |
| `Close()`, `Status() → json`, `Quit()` | `Quit` = Meta+Shift+Q |
| signals `Opened(json)`, `Closed()`, `Refused(json)`, `Quitting()`, `Key(json)`, `OpenSettings()` | |

Try it: `gdbus call --session --dest org.vimvibe.Daemon --object-path /org/vimvibe/Daemon --method org.vimvibe.Daemon.Status`
