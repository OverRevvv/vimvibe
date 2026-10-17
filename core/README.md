# vimvibe-core

> Users: see the top-level [README](../README.md) for install, usage and settings. This file covers the core only.

Keyboard-driven "click anything by typing its name" core for Linux, built on AT-SPI2, with a resident daemon (KDE Plasma 6 / Wayland first). **Working prototype**: see `../research/` for the evidence behind each design choice (start with 09 and 10), and `../palette/` for the thin UI client.

```
cargo build --release          # binary: target/release/vimvibe-core
vimvibe-core doctor            # first-run check: accessibility, apps, shortcut, daemon (read-only)
vimvibe-core doctor --fix      # turn session accessibility on (restart apps afterwards)
vimvibe-core doctor --fix-env  # write ~/.config/environment.d/50-vimvibe-accessibility.conf (next login)
vimvibe-core daemon            # resident: warm focus tracking, global shortcut (Meta+Shift+Space), D-Bus API
vimvibe-core status            # is session accessibility enabled?
vimvibe-core [--app NAME] list | search btn save | act delete [--index N] [--dry-run]
vimvibe-core focus | watch [secs]   # what KWin says is focused / focus+geometry events
vimvibe-core pointer-setup     # ONE-TIME consent dialog for the pointer-click fallback (RemoteDesktop portal)
vimvibe-core cursor | click X Y [--right] [--double]   # pointer tools (need pointer-setup for click)
```
Flags: `--json`, `--strategy auto|cache|collection|walk`, `--with-actions`, `--timeout-ms`, `--include-hidden`, `--enable-a11y`.

## Daemon API
Session bus, `org.vimvibe.Daemon` at `/org/vimvibe/Daemon`. The full method and signal list is in the header comment of
`src/daemon.rs` and in the top-level README (*Developer guide → D-Bus API*). On non-KDE desktops bind any key to `gdbus call --session --dest org.vimvibe.Daemon --object-path /org/vimvibe/Daemon --method org.vimvibe.Daemon.Trigger`.

## How it works
- Window: KWin script (reports over our own D-Bus service) gives the focused window's PID and `clientGeometry`; the AT-SPI app is matched by PID. Screen position = geometry origin + window-relative extents.
- Elements: `auto` tries the app's AT-SPI cache (one call for the whole tree; Chrome, Firefox), then a concurrent breadth-first walk (Qt). Hidden subtrees are pruned, results clipped to the window, time budget with partial results reported as TRUNCATED.
- Matching: `nucleo-matcher` fuzzy, Shortcat-style role words (`button`, `btn`, `link`, `check`, `radio`, `tab`, `field`, ...), a small synonym table, shorter-label/prefix/exact bonuses, disabled elements last.
- Acting, in order: the best AT-SPI action (click/press/toggle…) → selection through the parent (tabs, list rows) → focus → **pointer click** through the RemoteDesktop portal (GTK4 check boxes; needs `pointer-setup` once; cursor restored afterwards). `--no-pointer` disables the last step.

Overlay: `python3 ../palette/vimvibe_palette.py` shows the search panel and a letter label on every element. Keys and settings are documented in the palette's docstring and the top-level README.

Known gaps are listed in the top-level README (*Known limitations*); contributors start with [CONTRIBUTING](../CONTRIBUTING.md).
