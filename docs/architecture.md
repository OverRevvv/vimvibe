# How vimvibe works

This page explains the logic behind every feature: what happens between pressing a key and the click landing, and
why it is done that way. It is written for contributors and for anyone who wants to know what vimvibe does on their
machine. For using vimvibe see [Using vimvibe](using.md); for building, testing and releasing see
[CONTRIBUTING.md](../CONTRIBUTING.md).

Every claim here can be checked in the code: each section names the files involved, and every function there carries a
comment saying what it is responsible for.

## The two processes

```
 Meta+Shift+Space                                   (KDE global shortcut, kglobalaccel)
        │
        ▼
 vimvibe-core daemon  (Rust, core/)                  overlay + Settings  (Python / PySide6, palette/)
  • focus tracking (KWin script)            Opened ─► • draws the letter labels and the search panel
  • reads the window (AT-SPI)                         • handles every key while it is open
  • labels, ranking, OCR                    ◄─ calls  • asks the daemon to Search / Activate / Scroll / Pointer…
  • clicks, scrolls, keys (portal)                    • never reads other apps or the screen itself
```

- They talk over the **session D-Bus**: the daemon is the service `org.vimvibe.Daemon` (`core/src/daemon.rs`), the
  overlay is a client (`palette/vimvibe_palette.py`). The full method table is in
  [Development → D-Bus API](development.md#d-bus-api).
- The split keeps the part that touches the system (accessibility, KWin, the input portal) small, typed and fast, and
  keeps the drawing in Qt, where layer-shell, fonts and colours are easy. Another UI could replace the overlay.
- **Idle means idle.** While the overlay is closed the daemon only waits for D-Bus messages; no timers or polling run.
- **Profiles.** `VIMVIBE_PROFILE=dev` gives a second copy its own D-Bus name (`org.vimvibe.DaemonDev`), shortcuts,
  settings and logs, so a development build runs next to the installed one (`core/src/config.rs`, `dev.sh`).

## Opening: from the shortcut to the labels

`daemon.rs → open()` runs every time the shortcut is pressed. In order:

1. **Which window is focused.** A tiny KWin script (`kwin.rs`) reports the active window's class, PID, caption and
   geometry to the daemon over D-Bus whenever focus changes, so this is already known (no round trip). Accessibility
   frames cannot be trusted for this on Wayland: several apps flag a frame "active" when they are not.
2. **Excluded apps** (`[apps] exclude`) are refused here, before anything of theirs is read.
3. **Popup mode.** If the focused surface is a Plasma popup (start menu, tray, calendar) or an app has a menu open,
   taking the keyboard would close it. vimvibe then opens a *passive* overlay that never takes the keyboard and reads
   keys through the accessibility registry instead (see [Keys](#keys-and-never-leaking-them)).
4. **Find the app's accessibility window** (`enumerate.rs → target_window`): the AT-SPI application is matched to
   KWin's window by **PID** (authoritative), then the active frame, then the frame whose title equals KWin's caption.
   Flatpak apps run in their own PID namespace, so they are matched by title and placed with KWin's geometry.
5. **Read its elements** (`find_elements`): first AT-SPI's cache, else a concurrent walk of the tree. Only actionable,
   visible elements with a name and a size are kept (buttons, links, tabs, fields, list items, menu items…). Up to
   50 000 nodes are visited within a time limit.
6. **Add what the app does not list itself:** open menus (`popups.rs`, found from "menu shown" events and paired
   with KWin's popup surfaces by app and size), the panel's buttons and tray icons, the window's title-bar buttons
   (`decor.rs`, drawn by KWin), other open windows (window switching) and installed applications (`apps.rs`).
7. **Nothing to read?** See [Apps without accessibility](#apps-without-accessibility-ocr-and-the-grid).
8. **Labels** are assigned (`hints.rs`), the snapshot is stored, and the daemon emits `Opened(json)` with the window
   origin and counts. The overlay asks for `Elements()` and draws.

Typical cost: 10–40 ms for a normal window, 100–200 ms for a big Chrome page (`vimvibe status` shows the last timings).

### Chromium and Electron

These build no accessibility tree unless started with `--force-renderer-accessibility`; nothing on the bus can switch
it on later (measured, `research/`). `chromium.rs` recognises a Chromium engine by its files, not its name. When the
window shows nothing, the daemon refuses with a `restart` offer; the overlay asks you, and only then
`RestartWithAccessibility(pid)` quits and relaunches it with the flag (tabs restore). `doctor --fix-chrome` also adds
the flag to the menu launchers.

## Labels

`hints.rs` gives every element a 2–3 letter label derived from its name where possible (*Pull requests* → `PR`,
*Changelog* → `CH`), unique within the snapshot. Single letters are never used, because labels are typed into the same
field as the search and one letter would hijack every one-letter query. Assignment runs in reading order (top to
bottom, left to right) and is deterministic, so the same window gets the same labels every time.

The overlay draws them (`paint_labels`), hides those that no longer match what you typed, and dims typed letters.
Colours, font, size, radius and capitals come from `[ui]` through `vimvibe_style.Theme`, which the Settings preview
uses too, so the preview is exact. The selected element gets a highlight box only once you type, and a very large
element (over a quarter of the screen) gets an outline only, so a page-sized link does not cover the screen in colour.

## Search

`Search(q)` in the daemon ranks the snapshot with `matcher.rs`: fuzzy matching (nucleo) on the name, plus **role
words** (`btn`, `link`, `tab`, `field`, `check`…) that filter by element type, and synonyms. A query that equals a label
puts that element first. Windows and applications are ranked in the same list. The overlay shows the top rows; Ctrl+1…9
act on a row.

## Clicking

`ActivateWith(id, action)` (the overlay hides first, so the app has its window back):

| Action | How it is done |
|---|---|
| **Click** (Enter) | With `[behavior] click_with = "pointer"` (default) and the pointer permission: a **real pointer click** at the element's centre through the portal, exactly like a hardware mouse. If that fails, or the element has no place on screen, the **semantic ladder** runs (`model.rs → activate`): the element's own accessibility action → selecting it through its parent → focusing it. Focus-only actions (Qt's `SetFocus`) are never treated as clicks. |
| Right / middle click, hover | Always pointer actions at the centre. A right click leaves the pointer where the menu opened; other clicks put it back, except on combo boxes and menu buttons, whose popup would close if the pointer left. |
| **Double click** (Enter twice) | The overlay waits `[behavior] double_tap_ms` after an Enter. A second Enter in time sends one pointer double click (two press/release pairs within the toolkit's double-click time); otherwise the single click goes out when the time is up. The target is fixed at the first press. |
| Focus | `grab_focus` through accessibility; text fields fall back to a click. |
| Windows, title-bar buttons, apps | KWin raises the window / runs the window operation; apps are launched from their `.desktop` file. |

**Why pointer first:** an accessibility action can report success and still not behave like a click. Measured on Qt:
a combo box's "Press" opens its popup, which then closes again when the window gets focus back after the overlay; a
menu button only offers "SetFocus". A real click has none of these differences. `click_with = "semantic"` restores
the old order (no pointer movement at all).

**How the pointer moves** (`pointer.rs`): Wayland lets no client move the pointer, so vimvibe uses the XDG
**RemoteDesktop portal** with your one-time consent (`vimvibe-core pointer-setup`; the token is in
`~/.local/state/vimvibe/pointer-token`). Absolute motion would need a second (screen-cast) permission, so motion is
**relative with a closed loop**: read the real cursor from KWin, send the difference, read again, until within a pixel.
That is robust to pointer acceleration and scaling.

## Keys, and never leaking them

- **Normal overlay:** a full-screen **layer-shell** surface on the Overlay layer with exclusive keyboard
  (`make_passive(…, exclusive=True)` through Plasma's `layer-shell-qt`). While it is up, no key reaches the app below;
  only the desktop's own Super shortcuts still work.
- **Over popups:** the passive overlay never takes the keyboard (the popup would close); `keygrab.rs` registers a
  keystroke listener on the accessibility registry (what screen readers use) that answers "consumed" for every key and
  forwards it to the overlay as a `Key` signal. Qt and GTK 3 apps wait for that answer, so the key never reaches them.
- **Key bindings** (`palette/vimvibe_keys.py`): every action has a list of key combinations, overridable in `[keys]`;
  only changed bindings are written. `KeyMap.match(key, mods, mouse=…)` resolves a key per context, so one key can
  mean different things in the search and in the mouse modes (Space hides the panel in one, places the pointer in the
  other). Conflicts are reported in Settings → Keys.
- **Esc Esc to close** (`[behavior] double_esc_close`): one Esc only steps back or warns, so a stray Esc does not throw
  away a typed query.
- **System-wide keys while the overlay is hidden** (insert mode, edit mode): `kwin::grab_keys` loads a KWin script that
  registers plain keys as global shortcuts; KWin then consumes them everywhere and calls back into the daemon. Unloading
  the script hands them back. Shortcuts fire once per press (no auto-repeat, no releases), and any leftover script is
  unloaded at daemon start.

## Scrolling and arrow keys

- **Scrolling** (Space + H J K L / D / U): the daemon parks the pointer over the selected element (or the window's
  middle), and `scroller.rs` turns key presses into a **smooth glide**: each press adds distance, and a critically
  damped spring (no overshoot) moves through it with smooth axis events every ~8 ms (1 unit = 1/10 wheel notch). While
  scrolling, the overlay lets wheel events through. No modifier is ever held, because apps give the wheel other
  meanings with one (Ctrl + wheel zooms). `gg` / `G` are one long glide that the app stops at its end.
- **Arrow keys** (Space + Ctrl + H J K L, or `[scroll] hjkl = "arrows"`): the overlay hides and the daemon takes only
  the physical H J K L, D / U, Space and Esc keys through the keystroke listener (by key **position**, so other layouts
  work) and sends real arrow keys through the portal's keyboard. Chrome/Electron and GTK 4 do not share key presses
  with the registry; vimvibe checks first (it taps Shift and watches whether the tap arrives) and refuses there.

## Keyboard mouse

- **Grid** (Ctrl+G, `vimvibe_mouse.py`): the window (or screen) is cut into cols × rows cells named row letter +
  column letter; typing a name zooms into that cell, up to `max_depth` times. Enter clicks the centre with
  `PointerAct(x, y, …)`.
- **Pointer movement** (Ctrl+M): held keys feed a velocity with acceleration; the overlay sends `PointerMotion(dx, dy)`
  in whole pixels each frame; Shift is faster, Alt precise.
- **Stay after click** (`[mouse] stay_after_click`): the overlay turns input-transparent for the click
  (`PointerAct "stay:click"`), the click activates the app below, and the overlay answers the `WindowDeactivate` by
  asking to be activated again (`requestActivate`), so the keyboard comes back with no hide/show flicker. Movement
  stops on deactivation so a held key cannot drift.
- **Scrolling in the mouse modes** uses `PointerScroll` at the grid centre or the pointer.

## Text fields (insert mode)

- **Ctrl+I in any mode** sets the query `field` (the role word for text fields), so only text fields keep labels;
  pressed again it selects the next one. From the grid or the movement mode the daemon is asked first: if the window
  has fields the mode is left for the list, otherwise vimvibe clicks where the pointer is and lets you type.
- **After a field is clicked or focused** (`[behavior] insert_after_field`), the daemon starts **insert mode**
  (`begin_insert`): the overlay is gone, the app gets every key, and only **Esc** is taken system-wide through
  `kwin::grab_keys`. Esc re-opens vimvibe over the same window. A task checks the focus every second and ends insert
  mode (handing Esc back) when you switch windows. Terminals and combo boxes are not text fields here: Esc belongs to
  them.

## Apps without accessibility: OCR and the grid

When `target_window` finds nothing but KWin knows the window (Spotify, games, apps started without accessibility):

1. **OCR** (`ocr.rs`, `[mouse] ocr` and `[ocr]`): `spectacle -b -f -n` captures the screen (before the overlay is
   shown, so it is clean), `tesseract … --psm 11 tsv` finds sparse text, words below `min_confidence` or without letters
   are dropped, neighbouring words on one line are merged into phrases (gap smaller than the text height), phrases
   outside the window are dropped, and screenshot pixels are divided by the display scale (`[mouse] screen_width`).
   Each phrase becomes an element with `Extra::Ocr`, so every action on it is a pointer action. The screenshot is
   deleted immediately. Typical cost ~2 s; `timeout_ms` caps it.
2. **The grid**, if OCR finds nothing or is unavailable (`[mouse] fallback_grid`): the daemon opens with zero elements
   on KWin's window rectangle and the overlay goes straight into the grid, which works on anything.

Icon-only buttons have no text for OCR; use the grid for them.

## Text mode

The screen as a read-only Vim buffer (`vimvibe_select.py` for the logic, `text_*` methods in `vimvibe_palette.py`).

1. **Capture without vimvibe in it.** `enter_text` stops drawing anything (the search field moves off screen but
   keeps the keyboard) and, ~150 ms later, once that empty frame is on screen, calls `TextCapture()`. The daemon runs
   `spectacle -b -f -n` and returns as soon as the screenshot exists.
2. **Read in the background.** A daemon task runs tesseract on it (`ocr::read_words`: words, not merged phrases,
   with their block/paragraph/line numbers), deletes the screenshot, and emits `TextWords(json)`. The overlay shows
   "Reading the text on screen…" meanwhile; Esc gives up.
3. **Build the buffer.** `Layout` puts the words in reading order and groups them into lines (by tesseract's line
   numbers, otherwise by vertical overlap). `Selection` holds an anchor and a cursor. `Buffer` turns keys into
   motions, selections and requests (`("copy", text)`, `("paste_field",)`, `("paste_here",)`, `("leave",)`).
4. **Columns.** `j` / `k` score every line above / below by vertical distance plus twice the horizontal distance from
   the remembered column to the line's nearest word, so the caret stays in its column on screens with side-by-side
   text (measured on a real screen: a terminal line beside a window must not win over the window's next line).
5. **Copy** goes to Klipper (`vimvibe_clip.set_text`). **p** leaves text mode for the text-field list (the `field`
   query) and marks the next Enter as "paste here": the field is clicked, then `SendKeys("ctrl+v")`. **P** sends
   Ctrl+V to whatever has the keyboard.

6. **Scrolling.** Ctrl+E / Y / D / U / F / B, the wheel, and j / k past the screen edge call `PointerScroll` at the
   caret (the overlay draws nothing and lets input through), then `TextCapture()`, which first waits for the glide to
   end. `estimate_shift` finds how far the text moved from words that occur once in both readings, preferring a
   moving group over still text (a scrolled list next to a still terminal); `carry_over` puts the caret and selection
   back on their words inside the moved area (`moved_region`), and j / k are replayed. With no overlap the caret keeps
   its screen position, like Vim's Ctrl+D.

Nothing is edited: the buffer is a picture of the screen, so it is never out of sync with an app. Accessible apps
could give exact text instead of OCR (planned: research/12, milestone 3).

## Modes

`current_mode()` is one of `search` (labels), `grid`, `move`, `text`; `mode_key` handles Ctrl+T (text on / off) and
Ctrl+Tab / Ctrl+Shift+Tab (next / previous, skipping modes that are off), `switch_mode` leaves the current mode and
enters the next.

## Clipboard

`vimvibe_clip.py` talks to **Klipper** over D-Bus: history for the picker (Ctrl+Shift+H) and setting the clipboard.
Ctrl+Y copies the selected result's name; Ctrl+Shift+V clicks the element and sends Ctrl+V (`SendKeys`, after the
overlay has hidden, because the overlay holds the keyboard). vimvibe never stores or logs clipboard contents.
Selecting and copying any text on screen is [text mode](#text-mode); the plan and its milestones are in
[research/12](../research/12-copy-paste-plan.md). In the history picker Ctrl+J / Ctrl+K move.

## Settings

- One file, `~/.config/vimvibe/config.toml`. The daemon re-reads it on every open, the overlay on every open, so
  changes apply without a restart. Defaults live in `core/src/config.rs` (what the daemon enforces) and
  `palette/vimvibe_style.py` (everything); both must agree on names.
- The Settings window (`vimvibe_settings.py`) loads the file merged over the defaults, shows a control for every
  option, and writes back keeping keys it does not know.
- **Export / import** (`export_settings` / `import_settings` in `vimvibe_style.py`): the export is JSON with the full
  config (defaults filled in), every key binding as in effect, and launch-at-login. Import merges over the defaults,
  ignores values of the wrong type, and drops bindings equal to the defaults again. From the window (Export… /
  Import…) or the shell (`vimvibe export FILE`, `vimvibe import FILE`).
- Small UI state that is not a setting (panel hidden, last mouse mode) is kept in `~/.local/state/vimvibe/ui-state.json`.

## Setup and diagnostics

`doctor.rs` checks accessibility, the environment file, KWin, the shortcut, the pointer token and which open apps are
visible; `--fix`, `--fix-env` and `--fix-chrome` change only what they say. It prints application classes and PIDs,
never window titles.

## Privacy

No network code. Element names are read only from the window you open vimvibe on, only then, and kept in memory until
it closes. Excluded apps are never read. OCR screenshots are deleted at once. Clipboard contents are never stored.
Pointer and keyboard injection only happen through the portal permission you granted, which you can revoke.
