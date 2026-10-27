# Configuration

Settings window and `config.toml`.

## Settings

Open the Settings window with **Ctrl+Shift+,** (or `vimvibe settings`). It has a live preview of the labels and edits
`~/.config/vimvibe/config.toml`, which you can also edit by hand. Changes apply the next time the overlay opens.

| Tab | What you can set |
|---|---|
| General | shortcuts (changed in System Settings), launch at login, window switching, app launching, panel labels |
| Appearance | theme presets (Blue, Shortcat, Nord, Dracula, Gruvbox, Solarized light, High contrast); label background, text, outline and selected colours; font; label text size; overall label size; corner radius; capitals; panel style (dark/light), opacity, width, result rows, text size, position, key-hint line, hide-until-typing; screen dimming |
| Labels & behaviour | when labels appear (immediately … 5 s, after input), Vimium-style auto-click, continuous mode, and the scrolling group: what Space+HJKL does, direction keys, distance, Shift multiplier, smooth animation and its length, natural direction, swap left/right |
| Keys | every key the overlay uses, with Change / Add / Reset per action, and conflict warnings |
| Excluded apps | apps vimvibe must never read or click |
| Labels & behaviour (more) | tap Enter twice within (double click; 0 = off), Enter clicks with (pointer / app action), text fields: type and come back with Esc |
| Mouse → Text mode | darken the screen, keep line breaks or join with spaces, jump label letters; "vimvibe opens in: Text mode" |
| Mouse (more) | OCR on/off, OCR language, minimum confidence, time limit, logical screen width for scaled displays, grid fallback, stay after click, clipboard keys |
| Accessibility & setup | setup check, turn accessibility on, turn it on whenever vimvibe starts, offer Chromium restarts, keep it on after login, allow pointer and keyboard control |

```toml
[ui]
theme = "Blue"             # preset the colours came from (informational)
accent = "#3b82f6"         # label background ("#facc15" + label_text "#000000" = Shortcat's look)
label_text = "auto"        # label text colour; auto = black or white, whichever reads
label_border = "auto"      # label outline colour
selected = "auto"          # highlight of the selected element/label (Shortcat uses light green, "#86efac")
font = ""                  # font family; empty = desktop font
label_font_size = 0        # points; 0 = automatic
label_scale = 1.0          # overall label size, 0.6–2.0
label_radius = 3           # corner radius, px
uppercase = true           # SA vs sa (typing is case-insensitive)
panel = "auto"             # auto | top | center | bottom
panel_theme = "dark"       # dark | light
panel_opacity = 0.96
panel_width = 640
rows = 9                   # result rows shown (Ctrl+1..9 reach the first nine)
panel_font_size = 0        # points; 0 = automatic
hint_line = true
hide_panel_until_typing = false   # labels only until you type (Shortcat's "hide query pane")
start_hidden = false       # open with the panel hidden; the toggle_panel key (Space / Ctrl+Space) shows it
remember_panel = true      # a panel you hid stays hidden on the next opens (the state is kept in ~/.local/state/vimvibe/ui-state.json)
dim = 0                    # darken the screen behind the labels, percent 0–60

[hints]
delay_ms = 0               # when labels appear after opening (Shortcat's default is 2000)
after_input = false        # true: labels appear only once you start typing
auto_activate = false      # true: a fully typed label clicks at once (Vimium-style), no Enter

[behavior]
continuous = false         # come back after each click
continuous_delay_ms = 500
double_esc_close = true    # Esc must be pressed twice to close vimvibe (one Esc only steps back or warns)
double_tap_ms = 250        # Enter twice within this many ms double-clicks; 0 = off (Enter then clicks at once, with no wait)
click_with = "pointer"     # Enter clicks with a real pointer click, like a mouse (popups open and stay open); "semantic" = the app's own action first
insert_after_field = true  # after a text field is clicked/focused, typing goes to the app and Esc brings vimvibe back
keep_focus = false         # the normal shortcut also opens without taking the keyboard (popups stay open; see Meta+Shift+Alt+Space)

[keys]                     # only what you changed is written; see Using vimvibe → Customizing keys
toggle_panel = ["Ctrl+Space"]

[scroll]
keys = "hjkl"              # direction keys: "hjkl" (Vim) or "ijkl"
hjkl = "scroll"            # Space + H J K L: "scroll" or "arrows" (Space + Ctrl + key does the other one)
distance = 1.0             # mouse-wheel notches per press (about 3 lines)
fast = 4                   # Shift multiplies the distance by this
smooth = true              # glide like a smooth-scrolling mouse wheel instead of jumping
smooth_ms = 220            # how long a glide takes to settle
edge_keys = true           # Space + g g = top, Space + Shift+G = bottom
edge_notches = 600.0       # how far a jump to top/bottom travels (the app stops at the end)
edge_ms = 600              # how long that jump takes
natural = false            # touchpad-style direction
invert_horizontal = false  # swap left and right for H / L

[edit]
step = 3                  # edit mode: arrow presses per J / K while not selecting

[clipboard]
enabled = true             # copy / paste keys and the history picker (Ctrl+Shift+H)

[mouse]
enabled = true             # master switch for the keyboard mouse (grid and H J K L movement); false turns it all off
open_in = "search"         # what vimvibe opens in: "search", "grid" or "text"
fallback_grid = true       # an app with nothing to label opens in the mouse grid
ocr = true                 # ...after labelling its on-screen text with OCR (spectacle + tesseract)
screen_width = 0           # logical screen width, only for scaled displays (0 = 1:1)
stay_after_click = true    # a click from the grid / H J K L movement keeps the mode open (leave: Esc Esc or Meta+Shift+Space)
remember_mode = false      # instead, open in the mode used last (search, grid or H J K L movement); off by default
scope = "window"           # what the grid covers at first: "window" or "screen"
cols = 5                   # cells per grid level
rows = 5
alphabet = "abcdefghijklmnopqrstuvwxyz"   # cell names are a row letter + a column letter from this
max_depth = 4              # how many times a cell can be divided again
keys = "hjkl"              # pointer movement keys: "hjkl" or "ijkl"
speed = 500                # px per second
fast = 3                   # Shift multiplies the speed by this (Alt slows it to a quarter)
accelerate = true          # speed up while a key is held

[text]                     # text mode (Ctrl+T): the words on screen as a Vim buffer
dim = 15                   # darken the screen behind it, percent 0–60
join_lines = "newline"     # copied lines are joined with "newline" or "space"
labels = "asdfghjklqwertyuiopzxcvbnm"   # letters of the f-jump labels
line_notches = 1.0         # Space+J / K, Space+E / Y and j / k past the screen edge scroll this many wheel notches
page_notches = 8.0         # Space+F / B scroll this many notches (Space+D / U half)

[ocr]                      # the OCR labels for apps that expose nothing (on/off: [mouse] ocr)
lang = "eng"               # tesseract language(s), e.g. "eng+deu" (install each language's data)
min_confidence = 55.0      # 0-100: lower finds more text, and more noise
timeout_ms = 8000          # give up after this long and open the grid instead

[search]
windows = true             # offer your other open windows as results (window switching)
apps = true                # offer installed applications as results
panel = true               # label Plasma's panels (only while they are visible)

[apps]
exclude = ["keepassxc", "org.kde.konsole"]

[accessibility]
enable_on_start = true     # the daemon turns desktop accessibility on when it starts
offer_restart = true       # offer to restart a Chromium-based app (Chrome, Brave, Electron) that shows nothing, with accessibility on
```

One-off colour for a single run: `python3 ~/.local/share/vimvibe/vimvibe_palette.py --accent orange`
(or set `VIMVIBE_ACCENT`).

## Export and import

Every setting can be saved to one JSON file and loaded again, on this machine or another one. This covers colours and
label theme, panel, key bindings, scrolling, mouse, OCR, behaviour, excluded apps, accessibility options and launch at
login.

- **Settings window:** use **Export settings…** and **Import settings…** at the bottom. Import asks first and replaces
  the current settings.
- **Shell:**

  ```bash
  vimvibe export ~/vimvibe-settings.json
  vimvibe import ~/vimvibe-settings.json     # launch at login is only changed from the Settings window
  ```

The file is readable and safe to edit:

```json
{
  "format": "vimvibe-settings",
  "format_version": 1,
  "vimvibe_version": "vimvibe-core 2.1.2",
  "profile": "stable",
  "config": { "ui": { "accent": "#3b82f6", "...": "..." }, "mouse": { "...": "..." } },
  "keys": { "click": ["Return", "Enter"], "mouse_grid": ["Ctrl+G"], "...": "..." },
  "launch_at_login": true
}
```

- **What gets exported:** every option, with defaults filled in, and every key binding as it is in effect, so the file
  doubles as a reference of all settings.
- **On import:**
  - values are merged over the defaults;
  - a value of the wrong type is ignored (the default stays);
  - bindings equal to the defaults are not pinned, so a later release can still improve them;
  - options a later release adds take their defaults, so old exports keep working.
