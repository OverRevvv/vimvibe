"""vimvibe key bindings: the actions the overlay's keys trigger, their defaults, and the parser/matcher for the `[keys]`
table of config.toml. Shared by the overlay (matching key presses) and the Settings window (the Keys tab).

A binding is a string like "Ctrl+Shift+Return" or a list of them (the first one is shown in hints). Modifiers are
Ctrl, Alt, Shift and Meta; the key is anything `QKeySequence` understands ("Space", "Return", "Escape", "Tab", ",", "R").
The row shortcuts (Ctrl+1…9) and the modifier taps are modifier-only strings ("Ctrl", "Ctrl+Shift", "Alt")."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence



def iv(x):
    """A Qt enum or flag as a plain int (PySide6's flags don't convert with int())."""
    return x.value if hasattr(x, "value") else int(x)


CTRL, ALT, SHIFT, META = iv(Qt.ControlModifier), iv(Qt.AltModifier), iv(Qt.ShiftModifier), iv(Qt.MetaModifier)
MODS = (("Ctrl", CTRL), ("Alt", ALT), ("Shift", SHIFT), ("Meta", META))
MOD_MASK = CTRL | ALT | SHIFT | META
MOD_NAMES = {"ctrl": CTRL, "control": CTRL, "alt": ALT, "shift": SHIFT, "meta": META, "super": META}
MOD_KEYS = tuple(iv(k) for k in (Qt.Key_Control, Qt.Key_Alt, Qt.Key_Shift, Qt.Key_Meta, Qt.Key_AltGr))

# (action, what it does, defaults, kind): kind "key" = a key combination; "mods" = modifiers used with the digits 1-9;
# "tap" = one modifier tapped on its own (empty = off)
ACTIONS = [
    ("toggle_panel", "Hide / show the search panel (labels stay). Plain Space only hides it while the search is empty", ["Space", "Ctrl+Space"], "key"),
    ("click", "Click the selected element", ["Return", "Enter"], "key"),
    ("right_click", "Right click", ["Ctrl+Return", "Ctrl+Enter"], "key"),
    ("double_click", "Double click (also: tap Enter twice)", [], "key"),
    ("middle_click", "Middle click", ["Shift+Return", "Shift+Enter", "Ctrl+Alt+Return", "Ctrl+Alt+Enter"], "key"),
    ("close", "Close", ["Escape"], "key"),
    ("settings", "Open Settings", ["Ctrl+,", "Ctrl+Shift+,"], "key"),
    ("refresh", "Re-read the window", ["Ctrl+R"], "key"),
    ("mouse_grid", "Mouse: show / hide the zooming grid", ["Ctrl+G"], "key"),
    ("mouse_move", "Mouse: move the pointer with H J K L (on / off)", ["Ctrl+M"], "key"),
    ("mouse_place", "Mouse: leave the pointer here, no click", ["Space"], "key"),
    ("mouse_scope", "Mouse grid: window or whole screen", ["Ctrl+Shift+G"], "key"),
    ("mouse_back", "Mouse grid: zoom out one step", ["Backspace"], "key"),
    ("copy_text", "Copy the selected element's text to the clipboard", ["Ctrl+Y"], "key"),
    ("paste_into", "Click the selected element, then paste the clipboard into it", ["Ctrl+Shift+V"], "key"),
    ("clip_history", "Clipboard history: pick an earlier copy and paste it", ["Ctrl+Shift+H"], "key"),
    # Edit mode (Ctrl+E, Vimium-like: H J K L arrows, V / Y / P select, copy, paste) is switched off while it is reworked:
    # the action is commented out, so no key starts it. The code (palette `enter_edit`, daemon `edit_start`) stays.
    # ("edit_mode", "Edit mode: H J K L arrow keys, U / D Home / End, V select, Y copy, P paste (Esc leaves)", ["Ctrl+E"], "key"),
    ("jump_input", "Search: show only the text fields; again = the next one (Enter focuses it, Esc returns)", ["Ctrl+I"], "key"),
    ("mouse_insert", "Mouse movement: click here and type (Esc returns to vimvibe)", ["Ctrl+I"], "key"),
    ("next", "Select the next result", ["Down", "Tab", "Ctrl+N"], "key"),
    ("prev", "Select the previous result", ["Up", "Shift+Tab", "Ctrl+P"], "key"),
    ("page_down", "Select a page further down", ["PgDown"], "key"),
    ("page_up", "Select a page further up", ["PgUp"], "key"),
    ("row_act", "Act on result row 1–9 (modifiers + digit)", ["Ctrl"], "mods"),
    ("row_select", "Select result row 1–9 (modifiers + digit)", ["Ctrl+Shift"], "mods"),
    ("tap_labels", "Tap to clear the search and show every label", ["Alt"], "tap"),
    ("tap_hover", "Tap to hover the selected element (twice: focus it); off by default", [], "tap"),
]
DEFAULTS = {name: list(default) for name, _, default, _ in ACTIONS}
KIND = {name: kind for name, _, _, kind in ACTIONS}
TITLE = {name: title for name, title, _, _ in ACTIONS}

# keys Qt reports for a shifted symbol, mapped to the key they sit on (Ctrl+Shift+1 arrives as Ctrl+Shift+Exclam)
SHIFTED = {iv(a): iv(b) for a, b in (
    (Qt.Key_Exclam, Qt.Key_1), (Qt.Key_At, Qt.Key_2), (Qt.Key_NumberSign, Qt.Key_3), (Qt.Key_Dollar, Qt.Key_4),
    (Qt.Key_Percent, Qt.Key_5), (Qt.Key_AsciiCircum, Qt.Key_6), (Qt.Key_Ampersand, Qt.Key_7), (Qt.Key_Asterisk, Qt.Key_8),
    (Qt.Key_ParenLeft, Qt.Key_9), (Qt.Key_Less, Qt.Key_Comma))}
K_ENTER, K_RETURN, K_BACKTAB, K_TAB, K_1, K_9 = (iv(k) for k in (Qt.Key_Enter, Qt.Key_Return, Qt.Key_Backtab, Qt.Key_Tab, Qt.Key_1, Qt.Key_9))


def canon(key, mods):
    """(key, modifiers) of a key press in the form bindings are stored in: keypad Enter is Return, Shift+Tab arrives as
    Backtab, shifted symbols are folded onto their key. Modifiers are an int."""
    mods = iv(mods) & MOD_MASK
    key = iv(key)
    if key == K_ENTER:
        key = K_RETURN
    elif key == K_BACKTAB:
        key, mods = K_TAB, mods | SHIFT
    elif key in SHIFTED:
        key = SHIFTED[key]
    return key, mods


def parse_mods(text):
    """Modifier bits of "Ctrl+Shift" (None if a part is not a modifier)."""
    bits = 0
    for part in text.replace(" ", "").split("+"):
        if not part:
            continue
        if part.lower() not in MOD_NAMES:
            return None
        bits |= int(MOD_NAMES[part.lower()])
    return bits


def parse_key(text):
    """(key, modifiers) of "Ctrl+Shift+Return", or None when it can't be read."""
    text = text.strip()
    # the key is the last part; a "+" key is written "Ctrl++" (the empty part before it)
    if text == "+" or text.endswith("++"):
        head, last = text[:-1].rstrip("+"), "+"
    else:
        head, _, last = text.rpartition("+")
        if not head and not _:
            last = text
    mods = parse_mods(head) if head else 0
    if mods is None or not last:
        return None
    seq = QKeySequence(last, QKeySequence.PortableText)
    if seq.count() != 1:
        return None
    combo = seq[0]
    if iv(combo.keyboardModifiers()):
        return None
    key, mods = canon(combo.key(), mods)
    return (key, mods) if key not in MOD_KEYS and key != iv(Qt.Key_unknown) else None


def format_key(key, mods):
    """The binding string for a (key, modifiers) pair, e.g. "Ctrl+Shift+Return"."""
    parts = [name for name, bit in MODS if mods & bit]
    parts.append(QKeySequence(key).toString(QKeySequence.PortableText))  # the key alone, no modifiers
    return "+".join(parts)


def format_mods(mods):
    """"Ctrl+Shift" for modifier bits; "" for none."""
    return "+".join(name for name, bit in MODS if mods & bit)


def as_list(value):
    """A config value (string, list, or missing) as a list of strings."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return []


def effective(cfg_keys, action):
    """The bindings of `action` as strings: the configured ones, or the defaults when it is not configured. An empty
    list in the file means the action is deliberately unbound."""
    if isinstance(cfg_keys, dict) and action in cfg_keys:
        return as_list(cfg_keys[action])
    return list(DEFAULTS[action])


class KeyMap:
    """The overlay's key bindings, resolved from `[keys]`: `match` turns a key press into an action name."""

    def __init__(self, cfg_keys=None):
        """Parse every action's bindings; an unreadable one is skipped (and reported in `problems`)."""
        self.keys = {}      # (key, mods) -> [actions]: one key can serve a search action and a mouse-mode action
        self.row_act = self.row_select = 0
        self.tap = {}       # action -> modifier key that is tapped
        self.problems = []
        self.strings = {}
        for action, _, _, kind in ACTIONS:
            values = effective(cfg_keys, action)
            self.strings[action] = values
            for v in values:
                if kind == "key":
                    parsed = parse_key(v)
                    if parsed is None:
                        self.problems.append(f"{action}: can't read “{v}”")
                    else:
                        self.keys.setdefault(parsed, [])
                        if action not in self.keys[parsed]:
                            self.keys[parsed].append(action)
                elif kind == "mods":
                    bits = parse_mods(v)
                    if bits is None or not bits:
                        self.problems.append(f"{action}: need modifiers like Ctrl or Ctrl+Shift, not “{v}”")
                    elif action == "row_act":
                        self.row_act = bits
                    else:
                        self.row_select = bits
                elif kind == "tap":
                    mod = {"ctrl": iv(Qt.Key_Control), "control": iv(Qt.Key_Control), "alt": iv(Qt.Key_Alt), "shift": iv(Qt.Key_Shift)}.get(v.lower())
                    if mod is None:
                        self.problems.append(f"{action}: only Ctrl, Alt or Shift can be tapped, not “{v}”")
                    else:
                        self.tap[action] = mod

    def match(self, key, mods, mouse=False):
        """The action bound to this key press, or None. Digits with the row modifiers give ("row_act"|"row_select", n).
        `mouse` says the grid / pointer movement is active: a key shared by a search action and a mouse action (Space:
        hide the panel / leave the pointer) gives the one that belongs to the current place."""
        key, mods = canon(key, mods)
        if K_1 <= key <= K_9:
            # exact modifier match, so Ctrl+Shift+1 is "select" even though Ctrl+1 is "act"
            for name, bits in (("row_act", self.row_act), ("row_select", self.row_select)):
                if bits and bits == mods:
                    return (name, key - K_1)
        actions = self.keys.get((key, mods), [])
        own = [a for a in actions if a not in (SEARCH_ONLY if mouse else MOUSE_ONLY)]
        return (own or actions or [None])[0]

    def label(self, action):
        """The first binding of `action` for hint lines ("Ctrl+Space"); empty when unbound."""
        v = self.strings.get(action) or []
        return v[0] if v else ""

    def tapped_action(self, key):
        """The action a tap of modifier `key` triggers, or None."""
        for action, k in self.tap.items():
            if k == iv(key):
                return action
        return None


def conflicts(cfg_keys):
    """{(key, mods): [actions]} for key combinations bound to more than one action (what the Keys tab warns about),
    plus the row-modifier clashes keyed by their modifier bits."""
    seen = {}
    for action, _, _, kind in ACTIONS:
        if kind != "key":
            continue
        for v in effective(cfg_keys, action):
            parsed = parse_key(v)
            if parsed is not None:
                seen.setdefault(parsed, [])
                if action not in seen[parsed]:
                    seen[parsed].append(action)
    return {k: v for k, v in seen.items() if clash(v)}


# Actions that only work in one place can share a key with those of the other place: "Space" hides the panel in the
# search and leaves the pointer in the mouse modes. Everything else (click, close, ...) works in both.
MOUSE_ONLY = {"mouse_place", "mouse_back", "mouse_scope", "mouse_insert"}
SEARCH_ONLY = {"toggle_panel", "next", "prev", "page_down", "page_up", "refresh", "settings", "copy_text", "paste_into", "jump_input"}


def clash(actions):
    """Whether some two of `actions` (bound to one key) can be active at the same time."""
    for i, a in enumerate(actions):
        for b in actions[i + 1:]:
            if (a in MOUSE_ONLY and b in SEARCH_ONLY) or (b in MOUSE_ONLY and a in SEARCH_ONLY):
                continue
            return True
    return False


def is_plain_text_key(key, mods):
    """A binding that would swallow normal typing: a letter, digit or symbol with no Ctrl/Alt/Meta."""
    return not (mods & (CTRL | ALT | META)) and iv(Qt.Key_Space) <= key <= iv(Qt.Key_AsciiTilde)
