# 06 — MVP specification (draft, pending review; not approved for implementation)

Assumptions marked "(spike)" depend on 03's experiments.

## Goal
Keyboard-only: press a global shortcut, type part of an element's name, press Enter to activate it, in the focused application, on Fedora KDE Plasma Wayland (X11 secondary).

## Scope (v0.1)
1. Global shortcut via KDE `kglobalaccel` D-Bus (verified, 08 R12); XDG GlobalShortcuts portal as the generic path; X11 fallback `XGrabKey`. Default chord to be chosen after checking conflicts.
2. On activation: identify the focused application window; enumerate its AT-SPI tree for actionable roles (push button, link, menu item, check box, radio button, tab, list item, text field) with non-empty names; cap by timeout (e.g. 1.5 s, partial results allowed).
3. Palette with search field focused immediately; list of ranked results showing name, role, app.
4. Matching: case/accent-insensitive fuzzy, role words (e.g. "button"), a small synonym table; ranking by match quality, shorter label, visibility.
5. Actions: Enter = AT-SPI `DoAction` (default); focus for text fields via `GrabFocus`; Esc dismisses, restoring focus.
6. Navigation: arrows, Tab/Shift+Tab, Ctrl+N/P.
7. Menu bar search for the focused app (where AT-SPI exposes it).

## Behaviours borrowed from Shortcat docs (see 01 addendum)
- Single unified list: focused window's elements + that app's menu items (+ window list later).
- Buffered Enter: Enter typed before scoring completes applies to the first result when ready.
- Role/type words in the query (`button`, `link`, `check`…) filter by role.
- Configurable hint delay; hints (post-MVP) are 1–2 letters, typed to select.
- First-run check: ensure AT-SPI is enabled (`org.a11y.Status.IsEnabled`), explain relaunch needs for already-running apps. **Implemented as `vimvibe-core doctor` (see 09, update 4).**
- Geometry recipe (verified, 08 R9): screen position = KWin `clientGeometry` origin + AT-SPI WINDOW extents; capture focused window *before* the overlay appears.

## Out of scope for MVP
Hint labels over the UI (needs reliable extents — spike), right-click/hover/double-click in the palette (the portal pointer path exists in the core, see 09 update 6), window switching, emoji mode, continuous mode, arrow/scroll chords, OCR, GNOME support, Flatpak.

## Acceptance criteria
- AC1: Shortcut opens palette in <150 ms (warm) on Plasma Wayland; field focused.
- AC2: In Dolphin, Kate and a GTK4 app, ≥90% of visible named buttons/menu items are found; Firefox links reachable when a11y is enabled. (Define the test list before measurement.)
- AC3: Enter activates the element without synthetic mouse input where `Action` exists; failures reported, not silently ignored.
- AC4: Esc closes without side effects and the prior window regains focus.
- AC5: No-match state shown; duplicate names disambiguated by role/position/parent.
- AC6: Unlabeled elements reported as such (not clickable by name).
- AC7: Works on X11 session for the same apps.

## Prototype status
A Rust core with a resident daemon (`core/`, D-Bus API) and a thin PySide6 palette client (`palette/`) exist; see 09. Hotkey→snapshot→palette verified with a synthetic trigger (13–15 ms warm); typing, Enter-activation from the palette, real keypresses and the pre-palette keystroke leak are untested/open.

## Phases
- **P0 Spikes (1–2 wks):** the seven experiments in 03; choose overlay toolkit (Tauri vs GTK4/Qt layer-shell); decide extents strategy.
- **P1 Core library (Rust):** AT-SPI enumeration, matcher, DoAction, unit tests with fixtures; CLI that prints ranked results.
- **P2 Palette UI + shortcut:** Plasma Wayland first, then X11.
- **P3 Fallback input:** RemoteDesktop/libEI for right-click, double-click, hover.
- **P4 Hints & overlay:** only if extents proven.
- **P5 Window & menu modes, packaging (rpm/COPR).**

## Stack decision
Rust core mandatory; UI toolkit decided by P0. Vue 3/TS/Vite retained for the settings UI if Tauri is kept.
