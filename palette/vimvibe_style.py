"""vimvibe settings file and look: config.toml reading/writing, theme presets, and the Theme that turns settings into
colours, fonts and sizes. Shared by the overlay (vimvibe_palette.py) and the Settings window (vimvibe_settings.py), so
the Settings preview draws labels with exactly the code the overlay uses."""
import json, os, sys

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainterPath, QPen
from PySide6.QtWidgets import QApplication

# Profiles let a development build run next to the installed one (see README "Developing"): VIMVIBE_PROFILE=dev gives
# the daemon its own D-Bus name, shortcuts and settings directory. Empty = the installed ("stable") vimvibe.
PROFILE = "".join(c for c in os.environ.get("VIMVIBE_PROFILE", "").lower() if c.isalnum())
CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
CONFIG = os.path.join(CONFIG_HOME, f"vimvibe-{PROFILE}" if PROFILE else "vimvibe", "config.toml")
# a profile without settings of its own starts from the installed vimvibe's (read-only; saving writes CONFIG)
CONFIG_READ = CONFIG if os.path.exists(CONFIG) or not PROFILE else os.path.join(CONFIG_HOME, "vimvibe", "config.toml")

# Small UI state that is not a setting but should survive between opens and between the two overlays (the normal one
# and the one over popups): whether the search panel was hidden, which mouse mode was last used. Kept next to the logs.
STATE_HOME = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
STATE = os.path.join(STATE_HOME, f"vimvibe-{PROFILE}" if PROFILE else "vimvibe", "ui-state.json")

DEFAULT_ACCENT = "#3b82f6"


def icon_path():
    """The vimvibe icon (SVG): next to the scripts when installed, packaging/icons/ in the source tree; "" if absent."""
    here = os.path.dirname(os.path.abspath(__file__))
    for p in (os.path.join(here, "vimvibe.svg"), os.path.join(here, "..", "packaging", "icons", "vimvibe.svg")):
        if os.path.exists(p):
            return os.path.normpath(p)
    return ""


DEFAULTS = {
    "ui": {
        "theme": "Blue",            # preset the colours below came from (informational; the colours are what count)
        "accent": DEFAULT_ACCENT,   # label background
        "label_text": "auto",       # label text colour; auto = black or white, whichever reads on the label
        "label_border": "auto",     # label outline; auto = a soft dark edge
        "selected": "auto",         # selected element / label highlight; auto = the label colour
        "font": "",                 # font family for labels and panel; empty = the desktop's font
        "label_font_size": 0,       # label text size in points; 0 = from the desktop font
        "panel_font_size": 0,       # result rows text size in points; 0 = from the desktop font
        "label_scale": 1.0,         # overall label size (padding and, with automatic font size, text), 0.6–2.0
        "label_radius": 3,          # label corner radius in px
        "uppercase": True,          # show labels as SA (true) or sa (false); typing is case-insensitive either way
        "panel": "auto",            # search panel position: auto | top | center | bottom
        "panel_theme": "dark",      # dark | light
        "panel_opacity": 0.96,      # 0.5–1.0
        "panel_width": 640,
        "rows": 9,                  # result rows shown at once (Ctrl+1..9 reach the first nine)
        "hint_line": True,          # show the key hint line under the search field
        "hide_panel_until_typing": False,  # labels only until you type (Shortcat's "hide query pane")
        "dim": 0,                   # darken the screen behind the labels, percent 0–60
        "start_hidden": False,      # open with the search panel hidden (the hide/show key brings it back)
        "remember_panel": True,     # a hidden panel stays hidden on the next opens until the hide/show key brings it back
    },
    "hints": {"delay_ms": 0, "after_input": False, "auto_activate": False},
    "behavior": {"continuous": False, "continuous_delay_ms": 500,
                 "double_tap_ms": 250,       # Enter pressed twice within this many ms double-clicks (0 = off: Enter clicks at once)
                 "click_with": "pointer",    # Enter clicks with a real pointer click (like a mouse) or "semantic" (the app's action first)
                 "insert_after_field": True,  # after a text field is clicked/focused, typing goes to the app and Esc comes back
                 "double_esc_close": True},  # Esc must be pressed twice to close vimvibe (one Esc only steps back / warns)
    "scroll": {
        "keys": "hjkl",              # layout of the direction keys: hjkl (Vim) or ijkl
        "hjkl": "scroll",            # Space + H/J/K/L: "scroll" or "arrows" (Space + Ctrl + H/J/K/L does the other)
        "distance": 1.0,             # mouse-wheel notches per press (1 notch is about 3 lines)
        "fast": 4,                   # Shift multiplies the distance by this
        "smooth": True,              # glide through the scroll like a smooth-scrolling mouse wheel instead of jumping
        "smooth_ms": 220,            # how long a glide takes to settle
        "edge_keys": True,           # Space + g g = top, Space + Shift+G = bottom
        "edge_notches": 600.0,       # how far a jump to top/bottom travels; the app stops at the end
        "edge_ms": 600,              # how long that jump takes
        "natural": False,            # touchpad-style direction
        "invert_horizontal": False,  # swap left and right for H / L
    },
    "edit": {
        "step": 3,                   # edit mode: arrow presses per J / K while not selecting (3 = about one wheel notch)
    },
    "clipboard": {
        "enabled": True,             # copy / paste keys and the clipboard history picker
    },
    "mouse": {
        "enabled": True,             # master switch for the keyboard mouse (the grid and H J K L movement)
        "open_in": "search",         # what vimvibe opens in: search | grid
        "ocr": True,                 # label the text on screen (needs spectacle + tesseract) before the grid is used
        "screen_width": 0,           # logical screen width, only to convert OCR pixels on a scaled display; 0 = 1:1
        "fallback_grid": True,       # an app with nothing to label (no accessibility tree) opens in the mouse grid
        "stay_after_click": True,    # a click made from the mouse modes keeps the mode open (leave with Esc Esc or the shortcut)
        "remember_mode": False,      # instead: open in the mode (search, grid, pointer movement) that was used last
        "scope": "window",           # what the grid covers at first: window | screen
        "cols": 5, "rows": 5,        # cells per grid level
        "alphabet": "abcdefghijklmnopqrstuvwxyz",  # letters the cell names are made of (row letter + column letter)
        "max_depth": 4,              # how many times a cell can be divided again
        "keys": "hjkl",              # direction keys for pointer movement: hjkl or ijkl
        "speed": 500,                # pointer speed in px/s
        "fast": 3,                   # Shift multiplies the speed by this (Alt slows it down to a quarter)
        "accelerate": True,          # speed up while a key is held
    },
    "ocr": {                         # the OCR layer for apps that expose nothing (switched on/off by [mouse] ocr)
        "lang": "eng",               # tesseract language(s), e.g. "eng+deu" (each needs its traineddata installed)
        "min_confidence": 55.0,      # 0-100: lower finds more text, and more noise
        "timeout_ms": 8000,          # give up after this long and open the grid instead
    },
    "search": {"windows": True, "apps": True, "panel": True},
    # key bindings: action -> "Ctrl+Space" or a list; absent = the default in vimvibe_keys.py (the table starts empty so
    # that only what the user changed is written, and later releases can improve the defaults)
    "keys": {},
    "accessibility": {"enable_on_start": True, "offer_restart": True},  # offer_restart: ask to restart Chromium apps that show nothing
    "apps": {"exclude": []},
}

# Colour presets for the Settings window: each sets the label/selection colours and the panel theme.
PRESETS = {
    "Blue": {"accent": "#3b82f6", "label_text": "auto", "label_border": "auto", "selected": "auto", "panel_theme": "dark"},
    "Shortcat": {"accent": "#facc15", "label_text": "#000000", "label_border": "#8a8a8a", "selected": "#86efac", "panel_theme": "dark"},
    "Nord": {"accent": "#88c0d0", "label_text": "#2e3440", "label_border": "#4c566a", "selected": "#a3be8c", "panel_theme": "dark"},
    "Dracula": {"accent": "#bd93f9", "label_text": "#282a36", "label_border": "#44475a", "selected": "#50fa7b", "panel_theme": "dark"},
    "Gruvbox": {"accent": "#fabd2f", "label_text": "#282828", "label_border": "#504945", "selected": "#b8bb26", "panel_theme": "dark"},
    "Solarized light": {"accent": "#268bd2", "label_text": "#fdf6e3", "label_border": "#93a1a1", "selected": "#859900", "panel_theme": "light"},
    "High contrast": {"accent": "#ffff00", "label_text": "#000000", "label_border": "#000000", "selected": "#00ff00", "panel_theme": "dark"},
}

PANEL_THEMES = {
    "dark": {"bg": (22, 24, 30), "field": (12, 13, 17), "text": (235, 238, 245), "dim": (170, 176, 190),
             "role": (140, 146, 160), "disabled": (120, 125, 138), "key_bg": (48, 52, 62), "key_fg": (225, 228, 235),
             "border": (255, 255, 255, 30)},
    "light": {"bg": (246, 247, 250), "field": (255, 255, 255), "text": (20, 22, 28), "dim": (90, 96, 110),
              "role": (110, 116, 130), "disabled": (160, 164, 172), "key_bg": (225, 228, 235), "key_fg": (40, 44, 52),
              "border": (0, 0, 0, 40)},
}


def read_config():
    """The config file merged over DEFAULTS (unknown keys are kept, so the daemon's settings survive a save)."""
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        import tomllib
        with open(CONFIG_READ, "rb") as f:
            for section, values in tomllib.load(f).items():
                if isinstance(values, dict):
                    cfg.setdefault(section, {}).update(values)
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as e:
        print(f"ignoring {CONFIG_READ}: {e}", file=sys.stderr)
    return cfg


def read_state():
    """The remembered UI state (a dict; empty when nothing was saved yet or the file is unreadable)."""
    try:
        with open(STATE) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_state(**changes):
    """Merge `changes` into the remembered UI state. Failures are ignored: losing this state only loses a convenience."""
    state = read_state()
    state.update(changes)
    try:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        tmp = STATE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(state, f)
        os.replace(tmp, STATE)
    except OSError:
        pass


def write_config(cfg):
    """Write the config as TOML (only strings, numbers, booleans and string lists are used)."""
    def val(v):
        """TOML literal for one value."""
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return repr(v)
        if isinstance(v, list):
            return "[" + ", ".join(val(x) for x in v) + "]"
        return json.dumps(str(v), ensure_ascii=False)  # a JSON string is a valid TOML basic string
    lines = ["# vimvibe settings — written by the Settings window (Ctrl+Shift+,); safe to edit by hand.", ""]
    for section, values in cfg.items():
        lines.append(f"[{section}]")
        lines += [f"{k} = {val(v)}" for k, v in values.items()]
        lines.append("")
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    tmp = CONFIG + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(lines))
    os.replace(tmp, CONFIG)


EXPORT_FORMAT = "vimvibe-settings"  # marks a JSON file as a vimvibe settings export


def export_settings(path, version=""):
    """Write every setting to a JSON file: the full config (defaults filled in, so the file documents every option),
    the key bindings as they are in effect (not only the changed ones), and whether vimvibe starts at login. Keys a
    later release adds are filled from its defaults on import, so an old export stays usable."""
    import vimvibe_keys as keys
    cfg = read_config()
    data = {
        "format": EXPORT_FORMAT, "format_version": 1, "vimvibe_version": version, "profile": PROFILE or "stable",
        "config": {s: v for s, v in cfg.items() if s != "keys"},
        "keys": {a: keys.effective(cfg.get("keys"), a) for a in keys.DEFAULTS},
        "launch_at_login": os.path.exists(AUTOSTART),
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def import_settings(path):
    """Read a JSON export and make it the current settings (config.toml is rewritten). Sections and values are merged
    over the defaults; key bindings equal to the defaults are dropped again so later releases can improve them; values
    of the wrong type are ignored. Returns the export's dict (the caller decides about `launch_at_login`). Raises
    ValueError for a file that is not a vimvibe export."""
    import vimvibe_keys as keys
    with open(path) as f:
        data = json.load(f)
    if not isinstance(data, dict) or data.get("format") != EXPORT_FORMAT or not isinstance(data.get("config"), dict):
        raise ValueError("not a vimvibe settings export")
    cfg = json.loads(json.dumps(DEFAULTS))
    for section, values in data["config"].items():
        if not isinstance(values, dict):
            continue
        dest = cfg.setdefault(section, {})
        for k, v in values.items():
            if k in dest and dest[k] is not None and type(dest[k]) is not type(v) and not (isinstance(dest[k], float) and isinstance(v, int)):
                continue  # e.g. a string where a number belongs: keep the default
            dest[k] = v
    cfg["keys"] = {}
    for action, combo in (data.get("keys") or {}).items():
        if action in keys.DEFAULTS and isinstance(combo, (str, list)):
            combo = [combo] if isinstance(combo, str) else [str(c) for c in combo]
            if combo != keys.DEFAULTS[action]:
                cfg["keys"][action] = combo
    write_config(cfg)
    return data


AUTOSTART = os.path.join(CONFIG_HOME, "autostart", "vimvibe.desktop")


def readable_on(c):
    """Black or white, whichever reads better on colour c."""
    lum = 0.2126 * c.redF() + 0.7152 * c.greenF() + 0.0722 * c.blueF()
    return QColor("#0b0d12") if lum > 0.6 else QColor("#ffffff")


def colour(value, fallback):
    """A QColor from a setting ("auto" or invalid -> fallback)."""
    c = QColor(value) if isinstance(value, str) and value and value != "auto" else QColor()
    return c if c.isValid() else QColor(fallback)


def number(value, default, lo, hi):
    """A setting as a number clamped to [lo, hi] (default when it isn't a number)."""
    try:
        return max(lo, min(hi, type(default)(value)))
    except (TypeError, ValueError):
        return default


class Theme:
    """Everything the overlay draws with, resolved once from the settings: colours, fonts, label metrics, panel look."""

    def __init__(self, cfg, accent_override=None):
        """Resolve `cfg["ui"]` (with an optional one-run colour override) into concrete colours, fonts and sizes."""
        ui = {**DEFAULTS["ui"], **cfg.get("ui", {})}
        self.accent = colour(accent_override or os.environ.get("VIMVIBE_ACCENT") or ui["accent"], DEFAULT_ACCENT)
        self.label_fg = colour(ui["label_text"], readable_on(self.accent).name())
        self.label_border = colour(ui["label_border"], "#000000")
        if ui["label_border"] in ("", "auto"):
            self.label_border.setAlpha(110)
        self.selected = colour(ui["selected"], self.accent.lighter(125).name())
        self.selected_fg = readable_on(self.selected) if ui["selected"] not in ("", "auto") else self.label_fg
        self.uppercase = bool(ui["uppercase"])
        self.radius = number(ui["label_radius"], 3, 0, 12)
        scale = number(ui["label_scale"], 1.0, 0.6, 2.0)
        base_font = QFont(QApplication.font())
        if ui["font"]:
            base_font.setFamily(ui["font"])
        base = QApplication.font().pointSizeF()
        label_pt = number(ui["label_font_size"], 0, 0, 40) or base * 0.95 * scale
        row_pt = number(ui["panel_font_size"], 0, 0, 40) or base * 1.1
        self.label_font = QFont(base_font); self.label_font.setBold(True); self.label_font.setPointSizeF(label_pt)
        self.label_fm = QFontMetricsF(self.label_font)
        self.pad_x, self.pad_y = 5 * scale, 2 * scale
        self.row_font = QFont(base_font); self.row_font.setPointSizeF(row_pt)
        self.small_font = QFont(base_font); self.small_font.setPointSizeF(row_pt * 0.82)
        self.key_font = QFont(base_font); self.key_font.setBold(True); self.key_font.setPointSizeF(row_pt * 0.9)
        self.field_font = QFont(base_font); self.field_font.setPointSizeF(row_pt * 1.25)
        self.row_h = max(28, int(QFontMetricsF(self.row_font).height() * 1.75))
        pt = PANEL_THEMES.get(ui["panel_theme"], PANEL_THEMES["dark"])
        opacity = number(ui["panel_opacity"], 0.96, 0.5, 1.0)
        self.panel_bg = QColor(*pt["bg"], int(255 * opacity))
        self.panel_field = QColor(*pt["field"])
        self.panel_text, self.panel_dim, self.panel_role = QColor(*pt["text"]), QColor(*pt["dim"]), QColor(*pt["role"])
        self.panel_disabled, self.key_bg, self.key_fg = QColor(*pt["disabled"]), QColor(*pt["key_bg"]), QColor(*pt["key_fg"])
        self.panel_border = QColor(*pt["border"])
        self.panel_width = number(ui["panel_width"], 640, 420, 1200)
        self.rows = number(ui["rows"], 9, 3, 15)
        self.hint_line = bool(ui["hint_line"])
        self.hide_panel_until_typing = bool(ui["hide_panel_until_typing"])
        self.dim = number(ui["dim"], 0, 0, 60)
        self.position = ui["panel"]

    def label_text(self, hint):
        """The label as displayed (upper- or lower-case)."""
        return hint.upper() if self.uppercase else hint.lower()

    def label_size(self, hint):
        """(width, height) of the label for `hint`."""
        return (self.label_fm.horizontalAdvance(self.label_text(hint)) + 2 * self.pad_x,
                self.label_fm.height() + 2 * self.pad_y)

    def draw_label(self, p, rect, hint, typed=0, selected=False):
        """Draw one label in `rect`: background, outline, text with the first `typed` letters dimmed (Vimium-style)."""
        path = QPainterPath(); path.addRoundedRect(rect, self.radius, self.radius)
        p.fillPath(path, self.selected if selected else self.accent)
        p.setPen(QPen(QColor(255, 255, 255) if selected else self.label_border, 1.5 if selected else 1))
        p.drawPath(path)
        p.setFont(self.label_font)
        fg = self.selected_fg if selected else self.label_fg
        dim = QColor(fg); dim.setAlpha(110)
        x = rect.x() + self.pad_x
        for j, ch in enumerate(self.label_text(hint)):
            p.setPen(dim if j < typed and not selected else fg)
            cw = self.label_fm.horizontalAdvance(ch)
            p.drawText(QRectF(x, rect.y(), cw + 1, rect.height()), Qt.AlignVCenter | Qt.AlignLeft, ch)
            x += cw
