# 11 — Plan: reaching the whole OS, like Shortcat

Question: Shortcat (macOS) can act on more than the focused window. How does vimvibe get the same reach on Linux?
Evidence tags as in 04. Shortcat's scope comes from its public changelog/docs (CONFIRMED as documentation): menu bar
search (0.5.0), the current app's menu bar (0.8.0), the Dock (0.7.4), open applications and windows of all apps (0.9.0),
minimised windows (0.10.0), tabs in web views (0.11.0), emoji search with `:` (0.10.0), intents/commands. On macOS one
API (AXUIElement) reaches all of that. On Linux each piece lives behind a different interface, so the plan is a set of
**sources** that all feed the same result list and the same activation ladder.

## Where we are (2026-10-16)

| Source | Status | How |
|---|---|---|
| Focused window's elements | **done** | AT-SPI tree (Cache or walk), KWin geometry, letter labels |
| Other open windows (window switching, incl. minimised) | **done** (KDE) | KWin script `workspace.windowList()`, raise via `workspace.activeWindow` |
| Pointer actions (click, right, double, middle, hover) | **done** | XDG RemoteDesktop portal, one-time consent |
| Excluded apps | **done** | config `[apps] exclude`, checked before any tree is read |
| Window title-bar buttons (server-side decorations) | **done** (KDE) | positions from frame/client geometry + kwinrc button layout; KWin ops |
| Installed applications (source 4 below) | **done** | XDG `.desktop` entries, launched with `kioclient exec` / `gio launch` |
| Plasma popups: start menu, tray, calendar (part of source 3) | **done** (KDE) | passive layer-shell overlay + AT-SPI keystroke listener, see 09 update 11 |
| Open menus and nested submenus (source 1) | **done** (Qt, KDE) | `showing` events + KWin popup surfaces paired by app and size; 09 update 12 |
| Plasma panels / taskbar (source 3) | **done** (KDE) | plasmashell AT-SPI windows paired with KWin dock surfaces by size |

## Next sources, in priority order

1. **Open popups and context menus** (right-click menus, dropdown lists, popovers). On Wayland these are `xdg_popup`
   surfaces; KWin's *active window* stays the parent. AT-SPI usually exposes them as a `Menu`/`Window` child of the same
   app with state Showing (SUPPORTED INFERENCE from Qt/GTK behaviour; to be measured). Plan: on trigger, also take the
   app's other Showing top-level accessibles whose role is menu/popup and merge them first (they are what the user is
   looking at). Geometry: AT-SPI window-relative extents + the popup's position, which KWin knows for its popup windows
   (UNVERIFIED for xdg_popup; measure on 6.7).
2. **Application menus.**
   - In-window menu bars (Qt Widgets, GTK3, LibreOffice): already in the AT-SPI tree as MenuBar → Menu → MenuItem,
     often even while closed (we saw closed-menu items via Collection, see 09 update 2). Index them as
     `File ▸ Save As…` and activate with the item's AT-SPI action. Needs: path names, ranking below on-screen elements.
   - KDE Global Menu / apps that export menus: `com.canonical.dbusmenu` (registrar `com.canonical.AppMenu.Registrar`
     `GetMenuForWindow`), read with `GetLayout`, trigger with `Event(id, "clicked")`. No pointer, no focus change.
   - GTK4/libadwaita apps have no menu bar; their menus and commands are `GAction`s exported on D-Bus
     (`org.gtk.Actions` `DescribeAll` / `Activate`, `org.gtk.Menus`). That gives "app.preferences", "win.save" etc. as
     searchable commands even when the hamburger menu is closed (SUPPORTED INFERENCE: standard GApplication behaviour;
     to be verified per app).
3. **Panel, taskbar and system tray** (the "Dock"). Taskbar = window list (done). Tray icons: StatusNotifierItem over
   D-Bus (`org.kde.StatusNotifierWatcher` → each item's `Activate`, `ContextMenu`, and its dbusmenu). The Plasma panel
   itself (plasmashell, QML) can also be read over AT-SPI; measure whether its tree is usable.
4. **Applications not running yet** ("open Firefox"): XDG `.desktop` entries (names, keywords, translated names);
   launch through D-Bus activation / `gio launch`. Results like `Application ▸ Firefox`.
5. **Elements of other visible windows** (not only the focused one): enumerate lazily, only when the query found
   nothing good in the focused window, under a time budget; activation raises the window first.
6. **Commands / intents** (Shortcat's intents, emoji with `:`): a small built-in command list (lock screen, night colour,
   volume, screenshot, dark mode via D-Bus/KDE settings) and an emoji table. Inserting text (emoji) needs keyboard input:
   the RemoteDesktop portal's keyboard device (a second consent) or the clipboard + paste.
7. **Apps with no accessibility** (games, Tk, Wine, Java without the ATK bridge, some Flutter): optional pixel tier,
   off by default. Capture the window through the ScreenCast portal (consent), find boxes with edge/contour detection
   (swiftmouse/hints approach, see 10), optionally OCR (tesseract) for names. Labels only, no semantics; everything stays
   local, nothing is saved.
8. **Other desktops.** The KDE-specific parts sit behind three small seams: *focus + geometry* (KWin script), *global
   shortcut* (kglobalaccel), *window list/raise* (KWin script). Ports:
   - GNOME: a small Shell extension for focus/geometry/window list; shortcut through the extension or the
     GlobalShortcuts portal; overlay needs the extension (no layer-shell on GNOME).
   - wlroots (Sway, Hyprland, river), niri: `wlr-foreign-toplevel` / compositor IPC for windows, `layer-shell` overlay.
   - X11: `_NET_ACTIVE_WINDOW`/XGetGeometry, XTest for pointer, override-redirect overlay with a keyboard grab.
   - The GlobalShortcuts portal (`org.freedesktop.portal.GlobalShortcuts`) is the desktop-neutral shortcut path.

## Infrastructure these need

- **True overlay surface**: `wlr-layer-shell` (KDE: layer-shell-qt, already installed with Plasma; used for the
  passive popup overlay since 09 update 11). Still to do: use it with exclusive keyboard focus for the normal overlay
  too, which fixes keystrokes leaking to the app before the overlay appears and keeps panels from covering it.
- **Event-driven cache**: subscribe to AT-SPI `object:children-changed` / `state-changed` for the focused app and keep
  its element list warm, so triggers on big pages are instant (today: ~100–200 ms for a 9k-node Chrome page).
  Idle cost must stay at zero for apps the user isn't in.
- **Source trait** in the core: `fn collect(budget) -> Vec<Result>` + `fn activate(result)`, so each item above is an
  independent module that can be turned off in settings.

## What stays out of scope

- Reading or acting on excluded apps, password fields' contents, or anything outside the user's session.
- Bypassing the desktop's permission prompts (pointer/keyboard/screen capture always go through portals the user approves).
- Root helpers (`uinput`) unless a user explicitly opts in.
