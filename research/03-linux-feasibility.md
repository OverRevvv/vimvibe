# 03 — Linux feasibility (Fedora 44, KDE Plasma 6.7.5)

Verification legend: **[LOCAL]** observed on this machine; **[SECONDARY]** from `~/Downloads/linux-shortcat-roadmap.md` (unknown provenance, targets GNOME — unverified); **[KNOWLEDGE]** general knowledge of the interfaces, not yet tested here. None of the Wayland claims below has been experimentally validated; each lists an experiment.

## Local facts
- Session bus is Wayland/KDE; AT-SPI bus address returned by `org.a11y.Bus.GetAddress` → `unix:path=/run/user/1000/at-spi/bus_0` [LOCAL].
- `python3` can import `Atspi 2.0` [LOCAL]; rust/cargo 1.98.1 present [LOCAL]; `at-spi2-core` 2.60.7 [LOCAL].
- GNOME key `toolkit-accessibility` = false [LOCAL] — a GNOME setting, not authoritative for KDE; whether Qt/GTK/Chromium/Electron apps actually publish trees in this session is untested.
- `spectacle`, `xdg-desktop-portal-kde` present [LOCAL]. No tesseract/ydotool/xdotool.

## Feature → Linux mechanism
| Feature | Mechanism | Wayland (KDE) | X11 | Must test |
|---|---|---|---|---|
| Enumerate focused app's elements | AT-SPI2 over D-Bus: Registry → app → `Accessible` tree (role, name, states) | Toolkit-independent (D-Bus) [KNOWLEDGE]; getting the *focused window* is the hard part (see below) | Works | Tree completeness in Qt6 (Dolphin/Kate), GTK4, Firefox, Chromium/Electron (Chromium may need `--force-renderer-accessibility` / a11y enabled flag), speed on big trees |
| Activate element | AT-SPI `Action.DoAction` | Works without synthetic input [KNOWLEDGE]/[SECONDARY] | Same | Which widgets expose actions; web content links |
| Right-click / double-click / hover / modifier-click | No AT-SPI equivalent for most; needs synthetic pointer: XTest (X11), RemoteDesktop portal + libEI (Wayland), uinput (ydotool) | Needs portal permission prompt; KDE implementation of RemoteDesktop+EIS [KNOWLEDGE] | XTest trivial | Portal prompt persistence, pointer warp accuracy with scaling |
| Element bounds for hint labels | `Component.GetExtents(SCREEN/WINDOW)` | **Risk:** on native Wayland, screen coordinates for windows are not exposed; clients often return window-relative coordinates or 0,0 [KNOWLEDGE] | Reliable | Compare extents vs actual position on Qt/GTK/XWayland apps; KWin script can supply window geometry |
| Global shortcut | `org.freedesktop.portal.GlobalShortcuts` (KDE's kglobalaccel backs it) or KDE `.desktop` + `kglobalaccel` D-Bus | Likely OK on Plasma 6 [KNOWLEDGE] | `XGrabKey` | Registration flow, conflict with KRunner/Meta key |
| Overlay UI (search palette) | Normal always-on-top window; or `wlr-layer-shell` (KDE supports it) | Layer-shell with keyboard-interactivity on-demand [KNOWLEDGE] — gives focus for typing without stealing; plain xdg-toplevel can't force position/always-on-top | override-redirect/undecorated | Focus stealing rules in KWin; whether Tauri/GTK/Qt can use layer-shell |
| Hint labels drawn over target UI | Full-screen transparent layer-shell surface (click-through input region) | Possible with layer-shell; **depends on extents** | Transparent window | Depends on extents row above |
| Active window identification | X11: `_NET_ACTIVE_WINDOW`. Wayland: no client API; KWin scripting/D-Bus (`org.kde.KWin`) or AT-SPI `window:activate` events/state `ACTIVE` | KWin-specific script is the realistic route [KNOWLEDGE] | Easy | Latency, permission; AT-SPI "active" state reliability |
| Window switching list | KWin D-Bus/scripting for windows; or AT-SPI top-level frames | Wayland has no foreign-toplevel for clients without KWin script/plasma-window-management (privileged) [KNOWLEDGE] | `_NET_CLIENT_LIST` | Which KWin interface is available to unprivileged clients; raising windows |
| Menu-bar search | AT-SPI menu bar tree; (KDE global menu `com.canonical.dbusmenu` as an alternative) | Same as above | Same | Many Qt/GTK4 apps lazily build menus: need to open to enumerate |
| Fuzzy/synonym search | In-process (Rust: nucleo / skim-style matcher) + synonym table | n/a | n/a | Quality tuning |
| Focus restoration | Return to previous window after action | Needs window activation by KWin | `_NET_ACTIVE_WINDOW` | |
| Screenshot / OCR fallback | `org.freedesktop.portal.Screenshot` (interactive grant) or spectacle CLI; tesseract OCR | Per-capture permission/portal prompt makes it slow; not a hot path | `xdotool`/X capture works | Only evaluate after AT-SPI proves insufficient |

## Architecture evaluation
Proposal: Tauri 2 + Vue 3 + TS + Vite + Rust + AT-SPI2 (+ optional PyGObject helper).

Concerns (to be verified):
1. **Overlay needs.** The main platform-sensitive piece is a focus-taking, always-on-top, transparent, click-through, full-screen surface. Tauri uses WebKitGTK/GTK3 (via tao/wry). On Wayland, `gtk-layer-shell` supports GTK3, so layer-shell is feasible but unproven with Tauri's window; transparency with WebKitGTK has historically been flaky. Test early.
2. **AT-SPI in Rust.** The `atspi` crate (zbus-based, pure Rust) exists [KNOWLEDGE]; a PyGObject helper is fine for prototyping and is already importable here, but adds a Python runtime dependency.
3. **Search palette in a webview** costs memory and start latency for a tool that must open instantly; a resident hidden window mitigates this.

Recommendation (provisional, pending spikes): keep **Rust for the core** (AT-SPI client, matcher, actuation, portals via `ashpd`). Treat the UI as swappable: prototype with Tauri/Vue as proposed, but run a one-day spike comparing it with a native layer-shell UI (e.g. `gtk4-layer-shell` GTK4 or Qt6 + LayerShellQt, which is KDE-native). If the Tauri window cannot reliably take keyboard focus and draw click-through hints on KWin Wayland, move the overlay to GTK4/Qt and keep Vue only for settings. Do not decide before the spikes.

## Experiments (ordered; each ≤ half a day)
1. Python/`Atspi` dump of the tree for Dolphin, Kate, Firefox, a GTK4 app, Electron app; record roles, names, actions, extents, time taken.
2. Compare `GetExtents` against real positions under Wayland vs XWayland.
3. Get the active window under Plasma Wayland (AT-SPI active state vs KWin script).
4. `DoAction` on buttons/links/menu items in each toolkit.
5. GlobalShortcuts portal registration from a Rust test binary.
6. Layer-shell overlay with keyboard focus (GTK3/GTK4/Qt) and Tauri window comparison.
7. libEI/RemoteDesktop pointer warp + click for right-click/hover.
