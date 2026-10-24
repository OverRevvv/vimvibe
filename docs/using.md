# Using vimvibe

Every key and mode, in detail. New here? Start with the [Overview](../README.md).

## Keys at a glance

| Do | Keys |
|---|---|
| Open / close | **Meta+Shift+Space** (**Esc Esc**, two presses, also closes) |
| Quit vimvibe completely (daemon + overlay) | **Meta+Shift+Q** (or `vimvibe stop`) |
| Settings | **Ctrl+Shift+,** from anywhere (**Ctrl+,** while the overlay is open) |
| Scroll | hold **Space** + **J** (down) / **K** (up) / **H** (left) / **L** (right), or **D** / **U** — scrolls the selected element, or the window; **Shift** = faster; release Space for fresh labels ([details](#scrolling-and-arrow-keys)) |
| Arrow keys in the app | hold **Space** + **Ctrl** + **H J K L** — ← ↓ ↑ → (needs the keyboard permission); keep Space held and press H J K L |
| Pick an element | type its **label** (`pr`) or part of its **name** (`pull`), then **Enter** |
| Right click / double click / middle click | **Ctrl+Enter** / tap **Enter** twice, like a mouse / **Shift+Enter** |
| Move the pointer onto it (hover) | off by default (bind `tap_hover` in Settings → Keys, e.g. a tapped Ctrl) |
| Give it keyboard focus (e.g. a text field) | the same key, tapped twice |
| Act on result row *n* / just select it | **Ctrl+1…9** / **Ctrl+Shift+1…9** |
| Move the selection | **↑ ↓**, **Tab / Shift+Tab**, **Ctrl+N / Ctrl+P**, **PageUp / PageDown**, mouse wheel |
| Text mode: copy / paste any text on screen with Vim keys | **Ctrl+T** ([details](#text-mode-copy-and-paste-from-anything-on-screen)) |
| Next / previous mode (labels, grid, pointer, text) | **Ctrl+Tab** / **Ctrl+Shift+Tab** |
| Mouse grid: pick a spot on screen by typing letters | **Ctrl+G**, then two letters per zoom level, **Enter** clicks ([details](#keyboard-mouse)) |
| Move the pointer with the keyboard | **Ctrl+M**, then hold **H J K L** (**Shift** faster, **Alt** precise), **Enter** clicks |
| Hide / show the search panel (labels stay) | **Space** while the search is empty (or while the panel is hidden), or **Ctrl+Space** any time ([rebind it](#customizing-keys)). The choice is remembered: a hidden panel stays hidden on the next opens until you bring it back |
| Clear the search, show every label again | **tap Alt** |
| Re-read the window (after the page changed) | **Ctrl+R** |
| Switch to another window | type its app or title (e.g. `konsole`) → **Enter** |
| Launch an app | type its name (`calculator`, `firefox`) → **Enter** |
| Use the start menu, tray or calendar popups | open the popup, then **Meta+Shift+Space**: its items get labels and the popup stays open |
| Use an open menu (also nested submenus) | open it, then **Meta+Shift+Space**: every level of the menu gets labels and stays open |
| Click something on the taskbar / panel | its buttons, tasks and tray icons are labelled in every window |
| Close / maximize / minimize the window | its title-bar buttons have labels too (`CW`, `MA`, `MW`) |
| Mouse | click a label or a row to activate it; click anywhere else to close |

While vimvibe is up, **no key reaches the app below it**: the overlay (or, over a popup, the daemon's keystroke
listener) takes every key, with or without Ctrl / Alt, so nothing typed can change what you were working in. Only the
desktop's own Super-key shortcuts still work. Copy, paste and clipboard history are in [Keyboard mouse](#keyboard-mouse).

Search tips (as in Shortcat): one or two words beat long queries; add a role word to narrow results — `btn`,
`button`, `link`, `check`, `radio`, `tab`, `menu`, `field` (`save btn`). While you type, only labels that start
with what you typed stay visible; letters already typed are dimmed.

**Continuous mode** (off by default): after each click vimvibe re-reads the window and comes back, ready for the next
click — good for browsing. It stops on Esc, after you act on a text field, or when a menu/another window takes over.

## Scrolling and arrow keys

While the overlay is open you can scroll and move around the app from the home row, like Shortcat's *Arrow Keys /
Scroll* feature. Hold **Space** and press:

| Keys | Does |
|---|---|
| **Space** + **J** / **K** | scroll down / up |
| **Space** + **H** / **L** | scroll left / right |
| **Space** + **D** / **U** | scroll down / up (a second pair, handy with the left hand) |
| add **Shift** | scroll *faster* (4× by default) |
| **Space** + **Ctrl** + **H J K L** | arrow keys ← ↓ ↑ → in the app (needs the keyboard permission). The first press only switches arrow mode on; keep Space held and use H J K L — every press is then a plain arrow |
| release **Space** | the window is re-read and vimvibe comes back with fresh labels |
| **Esc** | stop |

What scrolls: the selected result's element when you have typed something (type `files`, then Space + J scrolls that
list), otherwise the middle of the window. The pointer is parked there for the scroll and put back afterwards.

Everything is configurable in *Settings → Labels & behaviour → Scrolling and arrow keys* (or `[scroll]` in the
config):

| Setting | What it does |
|---|---|
| Space + H J K L | **Scroll** (default) or **Arrow keys** (hides the overlay while Space is held); Ctrl swaps to the other one |
| Direction keys | H J K L (Vim) or I J K L (I up, K down, J left, L right) |
| Scroll distance | mouse-wheel notches per press (default 1; about 3 lines) |
| With Shift held | the multiplier (default ×4) |
| Smooth scrolling / glide length | each press adds to a smooth glide (a critically damped spring: gentle start, no overshoot, 220 ms to settle by default). A held key flows into one continuous motion, like a smooth-scrolling mouse wheel; with it off, a press jumps |
| Top / bottom (`gg`, `G`) | **Space + g g** scrolls to the top and **Space + Shift+G** to the bottom, like Vimium (on by default); the jump distance and time are settable. It is one long glide of `edge_notches` that the app stops at the end of its content, so a page longer than that needs a second press. Not available in arrow mode (Space + Ctrl + keys) |
| Natural direction | touchpad-style: the content follows your finger |
| Swap left and right | if H should scroll right and L left |

### How scrolling works

Smooth scroll events (about 125 a second, fractions of a wheel notch each) sent through the desktop's Remote Control permission, so it works in every app, accessible or
not; while you scroll, the overlay lets the wheel events through to the app below. No modifier keys are used on
purpose (Shortcat uses Space + Cmd): on Linux apps give the wheel another meaning when one is held — Ctrl + wheel
zooms (Dolphin then does not scroll at all), Shift + wheel scrolls sideways, Alt + wheel is "back" in some browsers.

### How arrow keys work (and where they don't)

On Wayland an app may not type into another app, so arrow keys go through the keyboard part of the Remote Control
permission. When you enter arrow mode vimvibe hides, the app gets the keyboard back, and vimvibe watches only for the
H J K L / I, D / U, Space and Esc keys (through the accessibility keystroke listener screen readers use), turning H J K L
into arrow keys; every other key goes to the app as usual. Releasing Space gives everything back. The keys are matched
by their **position** on the keyboard, so they work on Dvorak, Colemak or AZERTY too.

That listener only sees keys in apps that share their key presses with accessibility: **KDE/Qt apps and GTK 3 apps
(Firefox, GIMP, …)**. In **Chrome/Electron and GTK 4** apps vimvibe could not tell your J from typing, so it checks
first (it taps Shift and looks whether the tap arrives) and, if it can't, says so and does nothing — scrolling works
everywhere. Without the keyboard permission, Space + Ctrl + H J K L scrolls instead and a notice tells you how to allow
the keyboard.

### The permission

```bash
vimvibe-core pointer-setup      # or Settings → Accessibility & setup → "Allow pointer and keyboard control…"
```

Your desktop shows its *Remote Control* dialog once: allow **pointer** (clicks, scrolling, right click, hover) and
**keyboard** (only used for the arrow keys). KDE remembers the answer; vimvibe never opens the dialog on its own.
`vimvibe doctor` shows what is allowed. (Scrolling needs the pointer part only.) Revoke it any time in **System Settings → Security & Privacy → Remote
Control**, or delete `~/.local/state/vimvibe/pointer-token`.

## Keyboard mouse

Move and click the pointer without the mouse, for anything vimvibe has no label for (canvases, maps, games, video
players). Open vimvibe as usual, then:

**The grid — Ctrl+G.** The target window is divided into 5 × 5 cells named by two letters: the row letter, then the
column letter (`aa ab ac ad ae` across the top row, `ba bb …` below). Type a cell's two letters and it fills the view and
is divided again; keep going as deep as you like (4 times by default). Then:

| Key | Does |
|---|---|
| **Enter** | click the middle of the current cell (**Ctrl+Enter** right, **Enter Enter** double, **Ctrl+Alt+Enter** or **Shift+Enter** middle click). The mode stays open for the next click: leave it with **Esc Esc** or **Meta+Shift+Space** (`stay_after_click`) |
| **Space** | only move the pointer there, no click |
| **Backspace** | zoom out one step (or drop a half-typed cell name) |
| **Ctrl+Shift+G** | switch between the window and the whole screen |
| **↑ ↓ ← →** (or Page Up / Down) | scroll what is under the grid's middle, without leaving the grid (**Shift** = further) |
| **Ctrl+M** | continue with H J K L from here |
| **Esc** | leave the grid and carry on with H J K L movement from where the grid ended (no Ctrl+M needed) |

Clicking a cell with the mouse zooms into it; right click zooms out.

**H J K L movement — Ctrl+M.** Hold a direction key and the pointer glides, getting faster the longer you hold; two keys
make a diagonal. **Shift** is faster, **Alt** is precise. **Enter** clicks where the pointer is (same modifiers as above),
**Space** leaves it there. **↑ ↓ ← →**, Page Up / Down, **Space + D / U** or **D / U** scroll what is under the pointer without leaving the mode. Holding **Space** and pressing **H J K L** scrolls ← ↓ ↑ → and the overlay stays (set *Space + H J K L* to "Arrow keys" in Settings to send real arrow keys instead; those hide the overlay while Space is held); a plain Space tap still leaves the pointer. **Esc** goes back to the search, and a second **Esc Esc** closes vimvibe. The page under the pointer shows hover effects as you move.

**Text fields, like Vimium.** **Ctrl+I** works in every mode (labels, grid, pointer movement): it shows only the text
fields of the window (the query `field`); press it again for the next one, **Enter** focuses it. From the grid or the
pointer movement it leaves that mode for the field list; if the app exposes no fields, it clicks where the pointer is
and lets you type. In both cases vimvibe steps aside so the app gets every key, takes **Esc** system-wide (a KWin
shortcut) and opens again over the window when you press it. If you go to another window instead, Esc is given back
within a second. Activating any text field from the search does the same. (Terminals and combo boxes are left out: Esc
belongs to them.)

**Apps with nothing to label** (Spotify, games, apps without an accessibility tree) fall back in layers: the text on
screen is read with OCR (`spectacle` + `tesseract`; `[mouse] ocr`, on when both are installed) and every phrase becomes
a label you can type and click, ~2 s; if nothing is found, or OCR is missing, the mouse grid opens instead, which works
in every app (`[mouse] fallback_grid`). Icon-only buttons have no text, so reach those with the grid. On a scaled
display set `[mouse] screen_width` to the logical screen width so OCR coordinates line up. Language, accuracy and the
time limit are in `[ocr]` (Settings → Mouse); how it works: [How it works → OCR](architecture.md#apps-without-accessibility-ocr-and-the-grid).

**Edit mode (switched off for now — no key starts it; the `edit_mode` binding is commented out in `vimvibe_keys.py`).** Like Vimium, for every app: vimvibe hands the keyboard back
to the app and takes a few plain keys system-wide (through KWin) until you leave, turning them into real keys:

| Key | Sends to the app |
|---|---|
| **H J K L** | ← ↓ ↑ → (arrow keys scroll pages, lists and move the caret). J / K send 3 arrows (about a wheel notch) unless selecting: `[edit] step`, or type a number first (**5 J** = 5 presses) |
| **Shift+J / Shift+K** | Page Down / Page Up |
| **Shift+H / Shift+L** | a word back / forward (Ctrl+←/→) |
| **U / D** | Home / End (top / bottom) |
| **V** | start / stop selecting: the movement keys then select (Shift is held) |
| **Y** | copy (Ctrl+C); this also ends the selection |
| **P** | paste (Ctrl+V) |
| **Esc** or **I** | leave edit mode |

A banner shows the mode; Meta+Shift+Space also ends it, and it ends by itself after 2 minutes without a key. It needs the
keyboard permission (`vimvibe-core pointer-setup`) and KDE. A key press is one arrow press: holding a key does not repeat.
Selecting works where Shift+arrows select in the app (text fields, editors, browsers with caret browsing).

**Clipboard history — Ctrl+Shift+H** (anywhere in vimvibe) lists Klipper's history, newest first: **Ctrl+J** /
**Ctrl+K** (or ↑ ↓, Ctrl+N / Ctrl+P) move, type to filter,
**Enter** or **Ctrl+1…9** pastes the entry, **Esc** closes the picker only. In the search, **Ctrl+Y** copies the selected
result's text and **Ctrl+Shift+V** clicks it and pastes the clipboard into it. Turn the clipboard keys off with
*Clipboard* in Settings → Mouse (`[clipboard] enabled`). Clipboard contents are never logged or stored by vimvibe.

Everything is customizable in **Settings → Mouse** (the `[mouse]` table in [Configuration](configuration.md)): grid size and letters, how deep a cell
can be divided, whether the grid covers the window or the screen, speeds, the movement layout, opening vimvibe
straight in the grid, or in whichever mode you used last — or turn the whole feature off with *Keyboard mouse*. The keys are in **Settings → Keys**
(`mouse_grid`, `mouse_move`, `mouse_place`, `mouse_scope`, `mouse_back`; Enter and the click variants are the same keys
as in the search). The pointer ends where you put it and stays there. It needs the pointer permission
([see above](#the-permission)); the grid covers the screen the window is on, and it is not available over Plasma popups.

## Text mode (copy and paste from anything on screen)

**Ctrl+T** (from any mode) turns the whole screen into a read-only **Vim buffer**. vimvibe takes a screenshot (it draws
nothing while it does), reads every word with OCR (`tesseract`, about 2 s), and shows the words exactly where they are,
each in a faint box. The caret starts on the first word of the window you opened vimvibe over. Nothing in the app is
edited or moved: you navigate, select, copy and paste.

| Keys | Does |
|---|---|
| **h** / **b**, **l** / **w** / **e** | previous / next word (across lines) |
| **j** / **k** | line below / above, keeping the column. On screens with columns side by side (a sidebar, two windows), it stays in the caret's column |
| **0** / **^**, **$** | start / end of the line |
| **gg** / **G** | first / last word on screen |
| a number first | repeat: **5w**, **3j** |
| **v** / **V** | select words / whole lines; motions extend it; again (or **Esc**) stops selecting |
| **y** (or **Enter**) while selecting | copy the selection to the clipboard |
| **yy** / **Y**, **yw** (**3yw**), **y$**, **y0** | copy without selecting: the line, words from the caret, to the line end / start |
| **p** | paste into a text field: vimvibe shows the window's text fields (Ctrl+I for the next one), **Enter** clicks the field and pastes |
| **P** | paste where the keyboard is now (Ctrl+V in the app) |
| **f** (or **s**) | a label on every word; type one to put the caret there |
| **/** text **Enter**, then **n** / **N** | search the screen's words, next / previous match |
| click a word | put the caret there |
| **Ctrl+Shift+H** | the clipboard history |
| **Esc** | cancel the label jump, search, count or selection; then back to the labels (**Esc Esc** closes vimvibe) |

Copied lines keep their line breaks (or are joined with spaces: Settings → Mouse → Text mode). The text comes from OCR,
so a misread letter is possible, and text that is not on screen (scrolled away, behind another window) is not in the
buffer. It needs `spectacle` and `tesseract` and `[mouse] ocr` on.

## Switching modes

vimvibe has four modes: **labels** (the search, the default), the **mouse grid**, **pointer movement** and **text**.
**Ctrl+Tab** goes to the next one, **Ctrl+Shift+Tab** to the previous one, from any of them; a short message names the
mode you are in. Each also has its own key: Ctrl+G, Ctrl+M, Ctrl+T (press it again to go back to the labels). Modes
that are off (the keyboard mouse in Settings) are skipped. What vimvibe opens in is `[mouse] open_in`.

## Customizing keys

Every key the overlay reacts to can be changed in **Settings → Keys**: click *Change…* and press the combination you
want, *Add…* gives an action a second key, *Reset* restores its default. The window warns when two actions share a
key, and before you bind a plain typing key (it would stop typing that character into the search field). The same is
possible by hand in `[keys]`; a value is a string or a list, and an empty list unbinds the action:

```toml
[keys]
toggle_panel = ["Space", "Ctrl+Space"] # hide / show the search panel (labels and typing keep working); plain Space only acts while the search is empty
click = ["Return", "Enter"]
right_click = ["Ctrl+Return"]
double_click = []                      # unbound: tap Enter twice (within [behavior] double_tap_ms) instead
middle_click = ["Shift+Return"]
close = ["Escape"]
settings = ["Ctrl+,", "Ctrl+Shift+,"]
refresh = ["Ctrl+R"]
next = ["Down", "Tab", "Ctrl+N"]
prev = ["Up", "Shift+Tab", "Ctrl+P"]
page_down = ["PgDown"]
page_up = ["PgUp"]
row_act = ["Ctrl"]                     # + 1…9: act on that result row
row_select = ["Ctrl+Shift"]            # + 1…9: only select it
tap_labels = ["Alt"]                   # tap alone: clear the search, show every label (Ctrl, Alt, Shift or [] = off)
tap_hover = []                         # tap alone: hover (twice: focus)
mouse_grid = ["Ctrl+G"]                # keyboard mouse: the zooming grid
mouse_move = ["Ctrl+M"]                # keyboard mouse: H J K L moves the pointer
mouse_place = ["Space"]                # keyboard mouse: leave the pointer here, no click
mouse_scope = ["Ctrl+Shift+G"]         # grid: window / whole screen
mouse_back = ["Backspace"]             # grid: zoom out
text_mode = ["Ctrl+T"]                 # text mode on / off
next_mode = ["Ctrl+Tab"]               # next mode: labels -> grid -> pointer movement -> text
prev_mode = ["Ctrl+Shift+Tab"]         # previous mode
```

Limits: the global shortcuts that open and quit vimvibe are KDE shortcuts (System Settings → Shortcuts → *vimvibe*,
linked from the Keys tab). Space + H J K L / D / U follow physical key positions (they are also read by the daemon);
choose between the Vim and the arrow layout in *Labels & behaviour*. Over the start menu and other popups vimvibe can't
see most Ctrl/Alt combinations, so the keys there keep their defaults (Ctrl+Space, hide / show the panel, is the one exception; Esc must be pressed twice there too).

## Excluding apps

Apps listed under `[apps] exclude` are **never read and never acted on**: when one of them is focused and you press the
shortcut, vimvibe doesn't look at its window at all and shows a notification instead. They are also left out of window
switching. Good candidates: password managers, banking apps, terminals with secrets, remote-desktop clients.

An entry matches (case-insensitively) the app's accessibility name, its window class (`org.kde.konsole`, and the
short form `konsole`) or its process name. Add entries in *Settings → Excluded apps*.

## Making apps visible (accessibility)

vimvibe can only see apps that expose an accessibility tree. `vimvibe doctor` lists which open apps are visible.

| App type | What to do |
|---|---|
| Qt / KDE apps, GTK 3/4 apps, Firefox | turn accessibility on (`vimvibe doctor --fix`), then **restart the app** |
| Chrome, Chromium, Edge, Brave, Vivaldi, any Chromium engine | need `--force-renderer-accessibility` (nothing on the accessibility bus can switch it on later — measured). vimvibe takes care of it: open vimvibe over such a window that shows nothing and it offers to **restart the app with the flag** (tabs come back) and fixes its menu launchers so it starts that way from then on. Same thing by hand: `vimvibe doctor --fix-chrome`, then quit the browser completely. Programs are recognised by their files, not their name. Turn the offer off with `[accessibility] offer_restart = false` |
| Electron apps (VS Code, Discord, Slack, …) | same as Chromium: vimvibe offers the restart |
| Java apps | need the Java ATK bridge |
| Games, Tk, Wine, apps drawn without a toolkit | not supported yet (a pixel-based fallback is planned) |

Accessibility is a session setting that is off by default on most distributions; `vimvibe doctor --fix-env` writes
`~/.config/environment.d/50-vimvibe-accessibility.conf` so toolkits enable it after your next login.

## Troubleshooting

| Problem | Fix |
|---|---|
| Nothing happens on Meta+Shift+Space | `vimvibe status`: are the daemon and overlay running? `vimvibe start`. Is the shortcut taken by something else? (`vimvibe doctor`) |
| Notification "can't read this window" | the app started before accessibility was on, or has no accessibility: restart it (see Making apps visible above) |
| The start menu closes when vimvibe opens | the overlay could not use layer-shell (`layer-shell-qt`, normally installed with Plasma): check `vimvibe logs` |
| vimvibe keeps running / want it gone | **Meta+Shift+Q**, or `vimvibe stop` |
| Notification "vimvibe is off for this app" | it's in your excluded list |
| Few or no labels in Chrome/Electron | `vimvibe doctor --fix-chrome`, then quit the app completely and reopen it from the menu (or start it with `--force-renderer-accessibility`) |
| Labels in the wrong place | report it with your scaling and monitor setup (HiDPI/multi-monitor are not tested yet) |
| "pointer control is not set up" | run `vimvibe-core pointer-setup` once and approve the dialog |
| "Arrow keys need keyboard permission" | run `vimvibe-core pointer-setup` again and allow the keyboard too |
| "can't send arrow keys here" | the app (Chrome/Electron, GTK 4) doesn't share key presses with accessibility: scroll with Space + J / K instead |
| Scrolling does nothing | hold **Space** and press **J / K / H / L** or **D / U** — no Ctrl (apps treat Ctrl+wheel as zoom); it needs the pointer permission (`vimvibe doctor`); some views move only a little per step — raise *Scroll distance* in Settings; a press moves one wheel notch by default |
| Space + J types arrow keys into my terminal | *Settings → Space + H J K L* is set to "Arrow keys"; set it to "Scroll" (the default) |
| Want to stop vimvibe from clicking or typing arrow keys | System Settings → Security & Privacy → Remote Control, or delete `~/.local/state/vimvibe/pointer-token` |
| Logs | `vimvibe logs` (`~/.local/state/vimvibe/`) |

## Command reference

```text
vimvibe start | stop (= quit) | restart | status | settings | export FILE | import FILE | logs | open | help
vimvibe doctor [--fix] [--fix-env] [--fix-chrome]

vimvibe-core <command> [--app NAME] [--json] [--strategy auto|cache|walk] ...
  daemon            the resident service (what `vimvibe start` runs)
  doctor            setup check
  pointer-setup     one-time permission for clicks, scrolling and arrow keys
  list              list the focused window's elements        (vimvibe-core --app dolphin list)
  search QUERY      search them                               (vimvibe-core --app dolphin search "new folder")
  act QUERY         activate the best match                   (--index N, --dry-run)
  status | apps | focus | watch | cursor | click X Y | serve | surfaces
  key KEY…          type keys into the focused window (testing; e.g. `key Down j -- +space -space`)
```

`vimvibe-core --help` and `vimvibe-core <command> --help` print every option.
