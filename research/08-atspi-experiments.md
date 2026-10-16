# 08 — AT-SPI experiments on Fedora 44 / Plasma 6.7.5 Wayland (run 2026-10-13)

Scripts: PyGObject `Atspi 2.0`, read-only tree walks, plus a few `do_action` calls on KCalc. Launched Dolphin 26.08.1, KCalc, Firefox myself; closed afterwards. The flag change below was reverted.

## R1 — Accessibility is OFF by default on this session (new, important)
`org.a11y.Status.IsEnabled=false`, `ScreenReaderEnabled=false`. With it off, only helper processes (ksmserver, kwin, plasmashell-adjacent) and Konsole were on the tree; a running Google Chrome and a freshly started Dolphin/KCalc/Firefox were absent. After setting `IsEnabled=true` on the a11y bus (transient; reverted afterwards), Dolphin, KCalc and Firefox appeared within ≤15 s of launch. (Chrome, already running before the flag changed, never appeared — not retested after restart; Chrome/Electron need to be tested after relaunch.)
→ **Product implication:** the tool must set `IsEnabled` on startup (and apps launched earlier may need restart). Class: CONFIRMED for this machine.

## R2 — Tree coverage and speed (apps launched with a11y on)
| App | Nodes | Actionable-role nodes | Named | With Action | Walk time |
|---|---|---|---|---|---|
| Konsole (Qt) | 467 | 212 | 187 | 212 | 0.28 s |
| Dolphin (Qt6/KF6) | 789 | 621 | 615 | 464 | 0.49 s |
| KCalc (Qt) | 237 | 104 | 37 | 40 | 0.13 s |
| Firefox (about:blank/new tab) | 423 | 32 | 32 | 32 | 0.12 s |
Firefox exposed page tabs, urlbar, and links with actions (`switch`, `activate`, `jump`). KCalc's number buttons were not found under role `button` with digit names (mode-dependent; the visible set was hex/scientific buttons); many KCalc buttons have empty names (use description). Counts include non-visible menu items — visibility filtering is required. Class: CONFIRMED (one sample per app; no GTK4 app installed to test).

## R3 — Screen coordinates on Wayland are NOT available (CONFIRMED)
Every top-level frame reported screen extents `(0,0,w,h)` (KCalc 640×480, Dolphin 944×570, Firefox 1366×768, Konsole 1366×740) and window-relative origin `(0,0)`. Child extents are relative to the window (e.g. Dolphin list item `(167,59,125,88)`). Many items returned `(0,0,0,0)`. → Hint labels cannot be placed from AT-SPI alone; need window geometry from KWin (not obtained) or window-relative drawing inside an overlay aligned to the target window.

## R4 — Active window detection (CONFIRMED for Konsole sample)
`STATE_ACTIVE` was True only for the Konsole frame (the terminal in use) and False for Dolphin/KCalc/Firefox (backgrounded). So AT-SPI can identify the focused toplevel under Wayland. Not tested while the palette overlay itself steals focus — the focused app must be captured *before* showing the overlay.

## R5 — DoAction (PARTIAL)
`Action.do_action(0)` on KCalc button `i` returned True; the app rebuilt part of its UI, and previously cached node paths became invalid (`No such object path …`). Visible effect of the press not conclusively verified (display text not captured). Action names vary: `Press`, `Toggle`, `ShowMenu`, `SetFocus`, `switch`, `activate`, `jump`. → Design: re-query after each action; treat object refs as short-lived.

## R6 — KWin D-Bus
`org.kde.KWin /KWin` exposes `queryWindowInfo` and `getWindowInfo(s)`; calling `queryWindowInfo` timed out (it waits for an interactive click). `getWindowInfo` with a window UUID is the candidate for geometry, UUID source not yet found. UNVERIFIED.

## Not yet done
GTK4 app (none installed), Electron/Chromium after relaunch, GlobalShortcuts portal, layer-shell/Tauri overlay, libEI. Hopper/REA MCP not exercised.

## Next
1. Obtain window geometry (KWin scripting `workspace.windowList()` or `getWindowInfo`).
2. Retest Chrome/VS Code after relaunch with a11y on.
3. Install a GTK4 test app (e.g. gnome-calculator) — needs your OK.

## Update (after Claude Code restart)

### R7 — KWin scripting supplies window geometry, active flag and UUID (CONFIRMED)
A temporary KWin script (loaded via `org.kde.kwin.Scripting.loadScript`, started with `/Scripting/Script0 org.kde.kwin.Script.run`, unloaded afterwards) read `workspace.windowList()` and reported `resourceClass`, `caption`, `active`, `frameGeometry` and `internalId` (UUID) for every normal window. Script `print()` output did NOT reach the journal; results were captured by having the script call `callDBus(...)` and watching with `dbus-monitor`. All windows were maximized (0,0,1366,768), so this run proves the mechanism and fields, not offset correctness for floating windows. Windows seen: konsole (`*` active), two google-chrome windows, xwaylandvideobridge. Mechanism for a product: ship a small KWin script that pushes (or answers on request) window list/geometry over D-Bus — needs install/enable of a script, which is KDE-specific. Direct call `queryWindowInfo` remains interactive-only.
→ Resolves Q8/Q9 mechanism: window origin from KWin + window-relative AT-SPI extents ⇒ screen position (to be validated with a non-maximized window; also Chrome windows show titles, so don't log them).

### R8 — REA MCP and Hopper provider verified on this host (CONFIRMED)
MCP tools now load. `inspect_artifact` takes no path (works on the opened target); `open_binary(path)` is the entry point. Opened `/usr/bin/true` (ELF x86_64, sha256 b639fd49…2921) with provider Hopper (via `rea-workflow`), `binary_overview` → 4 segments, 98 procedures, 50 strings, evidence id `ev_ab4f6df9…`. Closed afterwards. Hopper licence/size limits still unknown (small binary). This was a harmless sanity check, not Shortcat analysis.

## Update 2 (2026-10-14) — floating-window geometry, DoAction effect, overlay spike

### R9 — Screen position = KWin client origin + AT-SPI WINDOW extents (CONFIRMED visually)
KCalc moved by a KWin script to frame (300,200,640,508); `clientGeometry` = (300,228,640,480) (28 px server-side title bar excluded). 22 visible buttons' AT-SPI `CoordType.WINDOW` extents, offset by the client origin (300,228) and drawn as rectangles on a Spectacle screenshot, aligned exactly with the real buttons. Scale factor 1.0 (screenshot 1366×768); fractional/HiDPI scaling NOT tested. Must use `clientGeometry`, not `frameGeometry`. Use the `SHOWING` state + non-zero extents to drop hidden widgets (hidden KCalc panels report 0,0,0,0).
`spectacle -b -n -f -o file` captured the full screen non-interactively here (no prompt) — useful for test automation only.

### R10 — DoAction effect (CONFIRMED)
Pressing Seven, Multiply, Six, Equals via `do_action(0)` produced **42** on KCalc's display (screenshot). No cursor movement or synthetic input. Gap: KCalc's display text is *not exposed* in the AT-SPI tree (labels only showed "NORM"), so results of actions can't always be read back via AT-SPI.

### R11 — Overlay spike with PySide6 (plain Wayland xdg-toplevel, no layer-shell)
`QT_QPA_PLATFORM=wayland`, frameless + stay-on-top + translucent window, run from the focused terminal:
- Small palette (540×80): `activeWindow` was ours; QLineEdit had keyboard focus (CONFIRMED).
- Fullscreen translucent overlay (1366×768): transparency worked (terminal visible beneath), line edit focused, a yellow "hint" box painted at screen (300,228) appeared at the right position (CONFIRMED; screenshot).
Not tested: launching/activating from a *global shortcut while another app is focused* (KWin focus-stealing prevention may behave differently from "launched by the focused terminal"); click-through input region; always-on-top guarantee; layer-shell; Tauri/WebKitGTK transparency.
Blocked (needs `sudo dnf install …`): `qt6-qtbase-devel layer-shell-qt-devel qt6-qtwayland-devel` for a LayerShellQt C++ spike; `webkit2gtk4.1-devel` (+ Tauri prerequisites) for a Tauri spike. `gtk4-layer-shell` isn't installed either. `layer-shell-qt` 6.7.5 runtime, `libei` 1.6.0, PySide6 6.11.2, GTK4 4.22.5 are present.

## Update 3 (2026-10-14) — global shortcut registration and activation (no installs)

### R12 — KDE `kglobalaccel` D-Bus API works for an unprivileged client (CONFIRMED)
Using `org.kde.kglobalaccel` `/kglobalaccel` / interface `org.kde.KGlobalAccel` (introspected, not guessed): `doRegister(as actionId)` with `[componentUnique, actionUnique, componentFriendly, actionFriendly]` succeeded and created `/component/<name>`; `setShortcut(as, ai keys, u flags)` returned the assigned key code (no conflict for Ctrl+Alt+Shift+F-key); `unregister(s,s)` removed it (verified `allComponents` no longer lists it). Qt6 key codes are plain ints (modifier masks Ctrl 0x04000000, Alt 0x08000000, Shift 0x02000000, Meta 0x10000000 + key). The daemon broadcasts `globalShortcutPressed(s componentUnique, s shortcutUnique, x timestamp)` on `/component/<name>`, interface `org.kde.kglobalaccel.Component`; clients subscribe to that signal (a Python/PySide client needed the `1`-prefixed slot string to connect). The Component also has `invokeShortcut(s name[, s activationToken])`, useful for automated tests.
This is the KDE-native path for the global hotkey; the XDG GlobalShortcuts portal was NOT tested (it would show a dialog).

### R13 — Palette gets focus on activation from another app (PARTIAL)
With KCalc forced active via KWin script, triggering the shortcut via `invokeShortcut` made a PySide6 frameless window appear, become `activeWindow`, with its QLineEdit focused (CONFIRMED for this path). Limits: the trigger came from `gdbus` (not a physical key press), with no activation token; KWin's focus-stealing prevention may behave differently for a real keypress, and a different app could be focused. Needs a real-key test (manual: press the registered chord) before relying on it.
