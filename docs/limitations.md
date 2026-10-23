# Known limitations


- KDE Plasma (Wayland) only for now; focus tracking and the shortcut use KWin/kglobalaccel.
- The overlay is a layer-shell surface when `layer-shell-qt` is available (it ships with Plasma); without it, it falls
  back to a normal fullscreen window, where keys typed in the instant between the shortcut and the overlay appearing
  can reach the app and KDE may animate it.
- Not yet tested: HiDPI/fractional scaling, multiple monitors, XWayland apps, very large pages with the overlay.
- Only the focused window's elements (plus other windows as switch targets) — menus, tray, launcher: see the plan.
- To find open menus (Qt keeps them out of the accessibility tree) vimvibe listens for "menu shown" events. While any
  client listens for accessibility events, Qt apps hand each key press to the accessibility registry first, exactly as
  when a screen reader runs; vimvibe only takes keys while it is open over a popup.
- Menus that were already open when the daemon started are not known until they are reopened.
- Over Plasma's popups (start menu, tray, calendar) and open menus vimvibe reads your keys through the accessibility registry instead
  of taking the keyboard (so the popup stays open). Plain keys and Shift go to vimvibe while it is open there;
  Ctrl/Alt/Super combinations still reach the popup, except Ctrl+Space (hide/show the panel), which vimvibe takes. Esc, or 60 s without a key, gives the keyboard back.
- Restarting a Chromium-based app (to turn its accessibility on) is a normal quit and relaunch; unsaved text in
  forms can be lost, and PWAs or apps started from a terminal get the flag only through that restart, not the launcher fix.
- Elements an app doesn't expose to accessibility (custom-drawn canvases, some image views) get no label.
- Title-bar button labels are placed from the KWin button layout; with an unusual decoration theme they may sit a few
  pixels off (pressing them is exact: it runs the KWin action, not a click).
