#!/usr/bin/env python3
"""vimvibe palette: the overlay UI for the vimvibe daemon (`vimvibe-core daemon`), plus its Settings window.

The daemon owns the global shortcut and snapshots the focused window when it fires, so this process only shows the
overlay on the `Opened` signal and forwards Search / Activate / Close over D-Bus. Anything that speaks the same D-Bus
API can replace this file.

The overlay works like Shortcat (and like Vimium's link hints, for the whole desktop): one transparent fullscreen
window on the target's screen holds a search panel, and every element of the target window gets a letter label
(assigned by the daemon: "Pull requests" → PR). Keys (see README.md):

  type a label or a name   narrow the results; labels that no longer match disappear
  Enter                    click the selected element         Ctrl+Enter   right click
  Alt+Enter                double click                       Shift+Enter  middle click
  tap Ctrl                 move the pointer onto it (hover)   tap Ctrl twice  give it keyboard focus
  Ctrl+1..9                act on row n                       Ctrl+Shift+1..9  select row n
  ↑ ↓ / Tab / Ctrl+N Ctrl+P  move the selection               PageUp / PageDown  by a page
  tap Alt                  clear the search, show all labels  Ctrl+R       re-read the window
  Esc                      close (also ends continuous mode)
Mouse: click a label or a row to activate it, click anywhere else to close, wheel moves the selection.

  vimvibe_palette.py                 run the overlay (keep it running; it waits for the shortcut)
  vimvibe_palette.py --settings      open the Settings window
  testing: [--accent COLOR] [--trigger] [--query TEXT] [--quit-after N] [--snapshot FILE]

All settings live in ~/.config/vimvibe/config.toml (see README.md); --accent and $VIMVIBE_ACCENT override the colour.
"""
import argparse, json, os, sys

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer, Slot
from PySide6.QtDBus import QDBusConnection, QDBusInterface, QDBusServiceWatcher
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget

SERVICE, PATH, IFACE = "org.vimvibe.Daemon", "/org/vimvibe/Daemon", "org.vimvibe.Daemon"
DEBUG = bool(os.environ.get("VIMVIBE_DEBUG"))
DEFAULT_ACCENT = "#3b82f6"
CONFIG = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "vimvibe", "config.toml")

ROWS = 9            # rows shown at once; also the Ctrl+1..9 range
ROW_H = 34
PANEL_W = 640
PAD = 14
TAP_MS = 350        # a modifier released within this time, with no other key, counts as a tap
# after acting on these, continuous mode stops: the user is about to type, or a menu/another window takes over
STOP_CONTINUOUS = {"Entry", "PasswordText", "Text", "Terminal", "DocumentText", "ComboBox", "SpinButton", "Window", "Application",
                   "Menu", "MenuBar", "PushButtonMenu"}

DEFAULTS = {
    "ui": {"accent": DEFAULT_ACCENT, "panel": "auto", "label_scale": 1.0},
    "hints": {"delay_ms": 0, "after_input": False, "auto_activate": False},
    "behavior": {"continuous": False, "continuous_delay_ms": 500},
    "search": {"windows": True, "apps": True},
    "apps": {"exclude": []},
}


def read_config():
    """The config file merged over DEFAULTS (unknown keys are kept, so the daemon's settings survive a save)."""
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        import tomllib
        with open(CONFIG, "rb") as f:
            for section, values in tomllib.load(f).items():
                if isinstance(values, dict):
                    cfg.setdefault(section, {}).update(values)
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as e:
        print(f"ignoring {CONFIG}: {e}", file=sys.stderr)
    return cfg


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
    lines = ["# vimvibe settings — written by `vimvibe_palette.py --settings`; safe to edit by hand.", ""]
    for section, values in cfg.items():
        lines.append(f"[{section}]")
        lines += [f"{k} = {val(v)}" for k, v in values.items()]
        lines.append("")
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    tmp = CONFIG + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(lines))
    os.replace(tmp, CONFIG)


def readable_on(c):
    """Black or white, whichever reads better on colour c."""
    lum = 0.2126 * c.redF() + 0.7152 * c.greenF() + 0.0722 * c.blueF()
    return QColor("#0b0d12") if lum > 0.6 else QColor("#ffffff")


def hint_prefix(text):
    """The query as a label prefix (letters/digits, spaces ignored, upper-case), or None when it can't be one."""
    q = "".join(text.split()).upper()
    return q if q == "" or (len(q) <= 3 and q.isalnum() and q.isascii()) else None


_last_notice = {}


def notify(summary, body):
    """A desktop notification (excluded app, unreadable window, failed action). The same notice is shown at most once
    every 15 s: pressing the shortcut repeatedly must not flood the desktop (KDE rate-limits and refuses them)."""
    import shutil, subprocess, time
    now = time.monotonic()
    if now - _last_notice.get((summary, body), -1e9) < 15:
        return
    _last_notice[(summary, body)] = now
    if shutil.which("notify-send"):
        subprocess.Popen(["notify-send", "-a", "vimvibe", "-i", "input-keyboard", "-t", "4000", summary, body],
                         stderr=subprocess.DEVNULL)
    print(f"{summary}: {body}", file=sys.stderr, flush=True)


def make_passive(widget):
    """Turn `widget` (not yet shown) into a full-screen layer-shell overlay that never takes the keyboard, using the
    layer-shell-qt library Plasma itself ships (no Python bindings exist, so its one entry point is called through
    ctypes and the rest are ordinary Qt properties). Popups that close on focus loss (Plasma's launcher) stay open
    under it; keys arrive from the daemon instead (Key signal). Returns False when layer-shell-qt is unavailable."""
    try:
        import ctypes, shiboken6
        lib = ctypes.CDLL("libLayerShellQtInterface.so.6")
        get = lib._ZN12LayerShellQt6Window3getEP7QWindow  # LayerShellQt::Window::get(QWindow*)
        get.restype, get.argtypes = ctypes.c_void_p, [ctypes.c_void_p]
        widget.winId()  # create the QWindow without showing it
        ptr = get(shiboken6.getCppPointer(widget.windowHandle())[0])
        if not ptr:
            return False
        lw = shiboken6.wrapInstance(ptr, QObject)
        lw.setProperty("scope", "vimvibe")
        lw.setProperty("layer", 3)                  # Overlay: above panels and popups
        lw.setProperty("anchors", 1 | 2 | 4 | 8)    # all edges: the whole screen
        lw.setProperty("exclusionZone", -1)         # don't push or get pushed by panels
        lw.setProperty("keyboardInteractivity", 0)  # None: never take the keyboard
        widget._layer = lw  # keep the wrapper alive
        return True
    except (OSError, AttributeError, ImportError, TypeError) as e:
        print(f"layer-shell overlay unavailable ({e}); popups will close when vimvibe opens", file=sys.stderr)
        return False


class Overlay(QWidget):
    def __init__(self, daemon, accent_override=None, passive=False):
        """Create the overlay window; `passive` makes it a layer-shell surface that never takes the keyboard."""
        super().__init__()
        self.passive = passive
        self.daemon = daemon
        self.accent_override = accent_override
        self.hits = []
        self.elements = []    # every element: {id, hint, name, role, enabled, screen}
        self.labels = {}      # id -> label rect (window coords)
        self.rects = {}       # id -> element rect (window coords)
        self.sel = 0
        self.top = 0          # first visible row
        self.meta = {}
        self.origin = None    # screen offset of this window (the screen it is on)
        self.labels_on = False
        self.panel = QRectF()
        self.tap = {}         # modifier key -> press time (ms), cleared when another key comes in between
        self.ctrl_taps = 0
        self.edit = QLineEdit(self)
        self.edit.setPlaceholderText("Search for elements, or type a label")
        self.default_placeholder = self.edit.placeholderText()
        self.edit.setFrame(False)
        self.edit.setStyleSheet("background: transparent; color: #eceef3;")
        f = self.edit.font(); f.setPointSizeF(f.pointSizeF() * 1.35); self.edit.setFont(f)
        self.edit.textChanged.connect(self.query)
        self.edit.installEventFilter(self)
        self.show_labels_timer = QTimer(self, singleShot=True, timeout=self.reveal_labels)
        self.ctrl_timer = QTimer(self, singleShot=True, timeout=self.ctrl_tapped)
        self.load_settings()

        self.setWindowTitle("vimvibe-palette")  # the daemon ignores focus moving to a window with this title
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        if passive:
            self.passive = make_passive(self)

    def load_settings(self):
        """Re-read config.toml: accent colour (and the text colour that reads on it) and the fonts."""
        self.cfg = read_config()
        ui = self.cfg["ui"]
        c = QColor(self.accent_override or os.environ.get("VIMVIBE_ACCENT") or ui.get("accent") or DEFAULT_ACCENT)
        if not c.isValid():
            print(f"unknown colour, using {DEFAULT_ACCENT}", file=sys.stderr)
            c = QColor(DEFAULT_ACCENT)
        self.accent, self.on_accent = c, readable_on(c)
        base = QApplication.font().pointSizeF()
        scale = max(0.6, min(2.0, float(ui.get("label_scale", 1.0))))
        self.row_font = QFont(QApplication.font()); self.row_font.setPointSizeF(base * 1.1)
        self.small_font = QFont(QApplication.font()); self.small_font.setPointSizeF(base * 0.9)
        self.key_font = QFont(QApplication.font()); self.key_font.setBold(True)
        self.label_font = QFont(QApplication.font()); self.label_font.setBold(True); self.label_font.setPointSizeF(base * 0.95 * scale)
        self.label_fm = QFontMetricsF(self.label_font)

    def call(self, method, *args):
        """Blocking D-Bus call to the daemon; returns its JSON answer (None on error)."""
        msg = self.daemon.call(method, *args)
        if msg.errorName():
            print(f"daemon {method} failed: {msg.errorMessage()}", file=sys.stderr, flush=True)
            return None
        a = msg.arguments()
        return json.loads(a[0]) if a and a[0] else None

    # --- daemon signals ---------------------------------------------------
    @Slot(str)
    def opened(self, payload):
        """Daemon signal: a snapshot is ready. Fetch the elements, lay out labels and panel, and show the overlay."""
        self.load_settings()  # settings apply on the next open, no restart
        self.meta = json.loads(payload)
        self.place_screen()
        self.elements = (self.call("Elements") or {}).get("elements", [])
        self.layout_labels()
        self.edit.blockSignals(True); self.edit.clear(); self.edit.blockSignals(False)
        self.labels_on = False
        self.edit.setPlaceholderText("Search applications and windows" if self.meta.get("launcher") else self.default_placeholder)
        self.query("")
        self.place_panel()
        if self.passive:
            self.show()  # layer surface anchored to every edge; no activation, the popup keeps the keyboard
        else:
            self.showFullScreen()
            self.raise_()
            self.activateWindow()
            self.edit.setFocus()
        if not self.cfg["hints"].get("after_input"):
            self.show_labels_timer.start(max(0, int(self.cfg["hints"].get("delay_ms", 0))))
        if DEBUG:
            QTimer.singleShot(600, lambda: print("overlay visible:", self.isVisible(), "active:", self.isActiveWindow(),
                                                 "field focus:", self.edit.hasFocus(), "size:", self.width(), self.height(),
                                                 "|", self.meta.get("app"), len(self.elements), "elements,",
                                                 len(self.labels), "labels,", self.meta.get("windows"), "windows", flush=True))

    @Slot()
    def closed(self):
        """Daemon signal: the snapshot was dropped; hide."""
        self.show_labels_timer.stop()
        self.hide()

    @Slot(str)
    def refused(self, payload):
        """Daemon signal: it could not open (excluded app, unreadable window); tell the user why."""
        meta = json.loads(payload)
        if meta.get("excluded"):
            notify("vimvibe is off for this app", f"Excluded by the rule “{meta['excluded']}” in your vimvibe settings.")
        elif meta.get("unsupported"):
            notify("vimvibe can't use this popup yet", meta.get("error", ""))
        else:
            notify("vimvibe can't read this window", meta.get("error", ""))

    def on_key(self, payload):
        """A key typed over a popup (passive mode): the daemon consumed it before the popup saw it."""
        k = json.loads(payload)
        name = k.get("name", "")
        if name in ("Return", "KP_Enter"):
            self.act("click")
        elif name == "BackSpace":
            self.edit.backspace()
        elif name in ("Down", "Tab", "KP_Down"):
            self.move_sel(1)
        elif name in ("Up", "ISO_Left_Tab", "KP_Up"):
            self.move_sel(-1)
        elif name in ("Page_Down", "Next"):
            self.move_sel(ROWS)
        elif name in ("Page_Up", "Prior"):
            self.move_sel(-ROWS)
        elif name == "space":
            self.edit.insert(" ")
        elif k.get("text") and len(name) == 1:
            self.edit.insert(name)
        if DEBUG:
            top = self.hits[self.sel] if self.hits else {}
            print("passive key:", name, "| query:", repr(self.edit.text()), "| selected:",
                  top.get("element", {}).get("role"), top.get("hint"), flush=True)

    def reveal_labels(self):
        """Show the letter labels (after the configured delay, or on the first key in "after input" mode)."""
        self.labels_on = True
        self.update()

    # --- layout -------------------------------------------------------------------
    def place_screen(self):
        """Cover the screen that holds the target window."""
        o = self.meta.get("origin")  # [x, y, w, h] of the target window, logical screen px
        scr = QGuiApplication.screenAt(QPointF(o[0] + o[2] / 2, o[1] + o[3] / 2).toPoint()) if o else None
        scr = scr or QGuiApplication.primaryScreen()
        if self.windowHandle() is None:
            self.create()
        self.windowHandle().setScreen(scr)
        g = scr.geometry()
        self.origin = (g.x(), g.y())
        self.setGeometry(g)

    def local_rect(self, screen):
        """Screen rectangle -> rectangle in this window's coordinates; None when it is empty or off this screen."""
        if not screen or screen[2] <= 0 or screen[3] <= 0:
            return None
        r = QRectF(screen[0] - self.origin[0], screen[1] - self.origin[1], screen[2], screen[3])
        return r if r.intersects(QRectF(self.rect())) else None

    def layout_labels(self):
        """Label rect per element: at the element's right edge, vertically centred (Shortcat's placement); a label
        wider than its element is centred on it. When two labels would land on the same spot the later one moves
        left inside its element if there is room, otherwise they overlap like Shortcat's do."""
        self.rects, self.labels = {}, {}
        W, H = self.width(), self.height()
        h = self.label_fm.height() + 4
        placed = []
        for e in self.elements:
            r = self.local_rect(e.get("screen"))
            if not r:
                continue
            self.rects[e["id"]] = r
            if not e.get("hint"):
                continue
            w = self.label_fm.horizontalAdvance(e["hint"]) + 10
            x = r.right() - w - 1 if r.width() >= w + 2 else r.center().x() - w / 2
            y = r.center().y() - h / 2
            clamp = lambda x, y: QRectF(min(max(x, 1), W - w - 1), min(max(y, 1), H - h - 1), w, h)
            lr = clamp(x, y)
            clear = lambda q: not any(o.intersects(q) for o in placed)
            if not clear(lr):
                # crowded (small buttons side by side): slide left inside the element, else just below it, else above
                cands = []
                q = QRectF(lr)
                for _ in range(3):
                    clash = next((o for o in placed if o.intersects(q)), None)
                    if not clash or clash.left() - w - 2 < r.left():
                        break
                    q.moveRight(clash.left() - 2)
                    cands.append(QRectF(q))
                cands += [clamp(r.center().x() - w / 2, r.bottom() + 1), clamp(r.center().x() - w / 2, r.top() - h - 1)]
                lr = next((c for c in cands if clear(c)), lr)
            placed.append(lr)
            self.labels[e["id"]] = lr

    def panel_height(self, rows):
        """Height of the search panel for `rows` result rows."""
        return PAD + 44 + 22 + max(1, rows) * ROW_H + 30 + PAD

    def place_panel(self, keep_if_clear=False):
        """Put the panel where it hides the fewest labels: above, at the top, middle or bottom of, or below the target
        window, centred on it ([ui] panel = "top"/"center"/"bottom" pins it). The selected element must stay visible;
        with keep_if_clear the panel only moves when it would hide it, so it does not jump around while typing."""
        W, H = self.width(), self.height()
        o = self.meta.get("origin")
        if o:
            wx, wy, ww, wh = o[0] - self.origin[0], o[1] - self.origin[1], o[2], o[3]
        else:
            wx, wy, ww, wh = 0, 0, W, H
        w = min(PANEL_W, W - 2 * PAD)
        h = self.panel_height(min(ROWS, max(1, len(self.hits))))
        x = max(PAD, min(wx + ww / 2 - w / 2, W - w - PAD))
        pinned = {"top": wy + PAD, "center": wy + wh * 0.5 - h / 2, "bottom": wy + wh - h - PAD}.get(self.cfg["ui"].get("panel"))
        if pinned is not None:
            if keep_if_clear and not self.panel.isEmpty():
                return
            y = max(PAD, min(pinned, H - self.panel_height(ROWS) - PAD))
        else:
            sel_rect = self.rects.get(self.hits[self.sel]["id"]) if self.hits else None
            labels = list(self.labels.values())

            def cost(pr):
                """How bad a panel position is: (hides the selected element, number of labels hidden)."""
                return (bool(sel_rect and pr.intersects(sel_rect)), sum(pr.intersects(l) for l in labels))

            if keep_if_clear and not self.panel.isEmpty():
                if not cost(QRectF(self.panel.x(), self.panel.y(), w, h))[0]:
                    return
            ys = [wy - h - PAD, wy + PAD, wy + wh * 0.5 - h / 2, wy + wh - h - PAD, wy + wh + PAD]
            cands = [(x, max(PAD, min(y, H - h - PAD)), w) for y in ys]
            # beside the target (narrow popups like the start menu leave room left or right)
            for side_x, side_w in ((wx + ww + PAD, W - (wx + ww) - 2 * PAD), (PAD, wx - 2 * PAD)):
                sw = min(PANEL_W, side_w)
                if sw >= 400:
                    for y in (wy, wy + wh * 0.5 - h / 2):
                        cands.append((side_x, max(PAD, min(y, H - h - PAD)), sw))
            x, y, w = min(cands, key=lambda c: (cost(QRectF(c[0], c[1], c[2], h)), c[2] < w, -c[1]))
        self.panel = QRectF(x, y, w, h)
        self.edit.setGeometry(int(x + PAD + 10), int(y + PAD + 6), int(w - 2 * PAD - 20), 32)

    # --- behaviour ---------------------------------------------------------
    def query(self, text):
        """Search field changed: ask the daemon for hits, keep the panel clear of the selection, maybe auto-activate."""
        res = self.call("Search", text) or {}
        self.hits = res.get("hits", [])
        self.sel, self.top = 0, 0
        if text and self.cfg["hints"].get("after_input"):
            self.labels_on = True
        if self.origin is not None and self.isVisible():
            self.place_panel(keep_if_clear=True)
        self.update()
        if self.cfg["hints"].get("auto_activate"):
            q = hint_prefix(text)
            if q and len(q) >= 2 and self.hits and self.hits[0].get("hint") == q and \
                    not any(l != q and l.startswith(q) for l in (e["hint"] for e in self.elements)):
                self.act("click")

    def move_sel(self, step, absolute=None):
        """Move the selection by `step` rows (or to row `absolute`), scrolling the visible rows with it."""
        if not self.hits:
            return
        self.sel = absolute if absolute is not None else (self.sel + step) % len(self.hits)
        if self.sel < self.top:
            self.top = self.sel
        elif self.sel >= self.top + ROWS:
            self.top = self.sel - ROWS + 1
        self.place_panel(keep_if_clear=True)
        self.update()

    def act(self, action="click", row=None, eid=None):
        """Run an action on a result row (default: the selected one) or on an element id (a clicked label)."""
        if eid is None:
            row = self.sel if row is None else row
            if not (0 <= row < len(self.hits)):
                return
            eid = self.hits[row]["id"]
        self.hide()  # let the target window regain focus before the action lands
        QTimer.singleShot(60, lambda: self.report(self.call("ActivateWith", eid, action), action))

    def report(self, res, action):
        """Result of an activation: show errors; in continuous mode, re-open after the app had time to react."""
        if res and not res.get("ok"):
            print("activation failed:", res.get("error"), file=sys.stderr, flush=True)
            notify("vimvibe could not do that", res.get("error", ""))
            return
        if DEBUG:
            print("activated:", res, flush=True)
        b = self.cfg["behavior"]
        if res and b.get("continuous") and action in ("click", "double") and res.get("role") not in STOP_CONTINUOUS:
            # continuous mode: re-read the window once the app has reacted, and come back
            QTimer.singleShot(max(100, int(b.get("continuous_delay_ms", 500))), lambda: self.daemon.asyncCall("Trigger"))

    def dismiss(self):
        """Close without acting (Esc, click outside)."""
        self.show_labels_timer.stop()
        self.hide()
        self.daemon.call("Close")

    def show_all_labels(self):
        """Shortcat's Option key: clear the query and bring every label back."""
        self.edit.clear()
        self.reveal_labels()

    def ctrl_tapped(self):
        """Ctrl was tapped once (hover the selected element) or twice (focus it)."""
        taps, self.ctrl_taps = self.ctrl_taps, 0
        self.act("focus" if taps >= 2 else "hover")

    def eventFilter(self, obj, ev):
        """Keys typed into the search field: Esc, Enter variants, Ctrl+digit, navigation, and modifier taps."""
        if obj is not self.edit:
            return super().eventFilter(obj, ev)
        t = ev.type()
        if t == QEvent.KeyPress:
            k, mods = ev.key(), ev.modifiers()
            ctrl, alt, shift = bool(mods & Qt.ControlModifier), bool(mods & Qt.AltModifier), bool(mods & Qt.ShiftModifier)
            if k in (Qt.Key_Control, Qt.Key_Alt):
                if not ev.isAutoRepeat():
                    self.tap = {k: ev.timestamp()}
                return False
            self.tap = {}  # another key: the modifier was used as a modifier, not tapped
            if k == Qt.Key_Escape:
                self.dismiss(); return True
            if k in (Qt.Key_Return, Qt.Key_Enter):
                self.act("right" if ctrl else "double" if alt else "middle" if shift else "click"); return True
            digit = {Qt.Key_1 + i: i for i in range(9)}
            digit.update({Qt.Key_Exclam: 0, Qt.Key_At: 1, Qt.Key_NumberSign: 2, Qt.Key_Dollar: 3, Qt.Key_Percent: 4,
                          Qt.Key_AsciiCircum: 5, Qt.Key_Ampersand: 6, Qt.Key_Asterisk: 7, Qt.Key_ParenLeft: 8})
            if ctrl and k in digit:
                row = self.top + digit[k]
                if row < len(self.hits):
                    if shift:
                        self.move_sel(0, absolute=row)
                    else:
                        self.act("click", row=row)
                return True
            if ctrl and k == Qt.Key_R:
                self.daemon.asyncCall("Refresh"); return True
            step = {Qt.Key_Down: 1, Qt.Key_Tab: 1, Qt.Key_Up: -1, Qt.Key_Backtab: -1,
                    Qt.Key_PageDown: ROWS, Qt.Key_PageUp: -ROWS}.get(k)
            if ctrl and k == Qt.Key_N: step = 1
            if ctrl and k == Qt.Key_P: step = -1
            if step:
                self.move_sel(step); return True
        elif t == QEvent.KeyRelease and ev.key() in (Qt.Key_Control, Qt.Key_Alt) and not ev.isAutoRepeat():
            k = ev.key()
            pressed = self.tap.pop(k, None)
            if pressed is not None and ev.timestamp() - pressed <= TAP_MS:
                if k == Qt.Key_Alt:
                    self.show_all_labels()
                elif self.hits:
                    self.ctrl_taps += 1  # wait briefly: a second tap means "focus" instead of "hover"
                    self.ctrl_timer.start(TAP_MS)
        return super().eventFilter(obj, ev)

    # --- mouse -------------------------------------------------------------------
    def row_rect(self, i):
        """Rectangle of visible result row `i` inside the panel."""
        return QRectF(self.panel.x() + PAD, self.panel.y() + PAD + 44 + 22 + i * ROW_H, self.panel.width() - 2 * PAD, ROW_H)

    def mousePressEvent(self, ev):
        """Click on a row or a label activates it (right button: right click); anywhere else closes."""
        p = ev.position()
        right = ev.button() == Qt.RightButton
        for i in range(min(ROWS, len(self.hits) - self.top)):
            if self.row_rect(i).contains(p):
                self.act("right" if right else "click", row=self.top + i); return
        if self.panel.contains(p):  # inside the panel's area: never dismiss on a stray click
            return
        for eid in self.shown_labels():  # a visible label
            if self.labels[eid].contains(p):
                self.act("right" if right else "click", eid=eid); return
        self.dismiss()

    def wheelEvent(self, ev):
        """Mouse wheel moves the selection."""
        self.move_sel(-1 if ev.angleDelta().y() > 0 else 1)

    # --- painting -------------------------------------------------------------
    def shown_labels(self):
        """Ids whose label is drawn now: all of them with an empty query, those starting with the typed text while it
        can still be a label, none otherwise (the selected element keeps its own)."""
        if not self.labels_on:
            return []
        q = hint_prefix(self.edit.text())
        if q is None:
            return []
        hint = {e["id"]: e["hint"] for e in self.elements}
        return [i for i in self.labels if hint.get(i, "").startswith(q)]

    def paintEvent(self, _):
        """Draw the selected element's highlight, the labels, then the panel on top."""
        if self.origin is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self.paint_selected(p)
        self.paint_labels(p)
        self.paint_panel(p)

    def paint_selected(self, p):
        """Filled highlight around the selected result's element."""
        if not self.hits:
            return
        r = self.rects.get(self.hits[self.sel]["id"])
        if r:
            fill = QColor(self.accent); fill.setAlpha(80)
            p.setPen(QPen(self.accent, 2)); p.setBrush(fill)
            p.drawRoundedRect(r.adjusted(-2, -2, 2, 2), 4, 4)
            p.setBrush(Qt.NoBrush)

    def paint_labels(self, p):
        """Draw the labels that are visible now; the part already typed is dimmed, the selected one outlined."""
        typed = len(hint_prefix(self.edit.text()) or "")
        sel_id = self.hits[self.sel]["id"] if self.hits else None
        ids = self.shown_labels()
        if sel_id is not None and sel_id in self.labels and sel_id not in ids and self.labels_on:
            ids.append(sel_id)
        hint = {e["id"]: e["hint"] for e in self.elements}
        p.setFont(self.label_font)
        border = QColor(0, 0, 0, 110)
        dim = QColor(self.on_accent); dim.setAlpha(110)
        for eid in ids:
            lr = self.labels[eid]
            selected = eid == sel_id
            path = QPainterPath(); path.addRoundedRect(lr, 3, 3)
            p.fillPath(path, QColor(self.accent).lighter(125) if selected else self.accent)
            p.setPen(QPen(QColor(255, 255, 255) if selected else border, 1.5 if selected else 1)); p.drawPath(path)
            # the part already typed is dimmed, like Vimium
            x = lr.x() + 5
            for j, ch in enumerate(hint.get(eid, "")):
                p.setPen(dim if j < typed and not selected else self.on_accent)
                cw = self.label_fm.horizontalAdvance(ch)
                p.drawText(QRectF(x, lr.y(), cw + 1, lr.height()), Qt.AlignVCenter | Qt.AlignLeft, ch)
                x += cw

    def paint_panel(self, p):
        """Draw the search panel: field frame, hint line, result rows (name, role, label, Ctrl+n) and footer."""
        pr = QRectF(self.panel); pr.setHeight(self.panel_height(min(ROWS, len(self.hits))))
        p.setBrush(Qt.NoBrush)
        path = QPainterPath(); path.addRoundedRect(pr, 14, 14)
        p.fillPath(path, QColor(22, 24, 30, 245))
        p.setPen(QPen(QColor(255, 255, 255, 30), 1)); p.drawPath(path)
        fr = QRectF(pr.x() + PAD, pr.y() + PAD, pr.width() - 2 * PAD, 44)
        fp = QPainterPath(); fp.addRoundedRect(fr, 9, 9)
        p.fillPath(fp, QColor(12, 13, 17))
        p.setPen(QPen(self.accent, 2)); p.drawPath(fp)
        p.setFont(self.small_font); p.setPen(QColor(170, 176, 190))
        p.drawText(QRectF(pr.x() + PAD + 4, pr.y() + PAD + 44, pr.width() - 2 * PAD, 22), Qt.AlignVCenter,
                   "[Enter] click · [Ctrl+Enter] right click · tap [Alt] all labels · tap [Ctrl] hover")
        fm = QFontMetricsF(self.row_font)
        sfm = QFontMetricsF(self.small_font)
        for i in range(min(ROWS, len(self.hits) - self.top)):
            idx = self.top + i
            h = self.hits[idx]; e = h["element"]
            rr = self.row_rect(i)
            if idx == self.sel:
                sp = QPainterPath(); sp.addRoundedRect(rr.adjusted(0, 1, 0, -1), 7, 7)
                c = QColor(self.accent); c.setAlpha(75); p.fillPath(sp, c)
            nr = QRectF(rr.right() - 28, rr.y() + 6, 24, ROW_H - 12)
            cr = QRectF(nr.x() - 28, nr.y(), 24, nr.height())
            for kr, txt in ((cr, "⌃"), (nr, str(i + 1))):
                kp = QPainterPath(); kp.addRoundedRect(kr, 5, 5)
                p.fillPath(kp, QColor(48, 52, 62))
                p.setFont(self.key_font); p.setPen(QColor(225, 228, 235))
                p.drawText(kr, Qt.AlignCenter, txt)
            right = cr.x() - 10
            if h.get("hint"):
                lw = self.label_fm.horizontalAdvance(h["hint"]) + 10
                lr = QRectF(right - lw, rr.center().y() - (self.label_fm.height() + 4) / 2, lw, self.label_fm.height() + 4)
                lp = QPainterPath(); lp.addRoundedRect(lr, 3, 3)
                p.fillPath(lp, self.accent)
                p.setFont(self.label_font); p.setPen(self.on_accent); p.drawText(lr, Qt.AlignCenter, h["hint"])
                right = lr.x() - 10
            role = e["role"] + ("" if e["enabled"] else " · disabled")
            rw = sfm.horizontalAdvance(role)
            p.setFont(self.small_font); p.setPen(QColor(140, 146, 160))
            p.drawText(QRectF(right - rw, rr.y(), rw + 2, ROW_H), Qt.AlignVCenter, role)
            p.setFont(self.row_font)
            p.setPen(QColor(235, 238, 245) if e["enabled"] else QColor(120, 125, 138))
            avail = right - rw - 16 - (rr.x() + 10)
            p.drawText(QRectF(rr.x() + 10, rr.y(), avail, ROW_H), Qt.AlignVCenter,
                       fm.elidedText(e["name"] or "(unlabeled)", Qt.ElideRight, avail))
        n = self.meta.get("count", 0)
        ms = (self.meta.get("ms") or {}).get("total")
        tail = f" in {ms / 1000:.2f}s" if isinstance(ms, (int, float)) else ""
        trunc = " (truncated)" if self.meta.get("truncated") else ""
        wins = f" + {self.meta['windows']} windows" if self.meta.get("windows") else ""
        cont = " · continuous" if self.cfg["behavior"].get("continuous") else ""
        p.setFont(self.small_font); p.setPen(QColor(170, 176, 190))
        if self.meta.get("launcher"):
            foot = f"{self.meta.get('apps', 0)} applications · {self.meta.get('windows', 0)} windows — type to launch or switch"
        else:
            foot = f"Found {n} elements{tail}{trunc}{wins} · {self.meta.get('app', '')}{cont}"
        p.drawText(QRectF(pr.x() + PAD + 4, pr.bottom() - PAD - 26, pr.width() - 2 * PAD, 26), Qt.AlignVCenter, foot)


class Router(QObject):
    """Sends each open to the right overlay: the normal one (takes the keyboard) or the passive one (layer-shell, for
    popups that must keep the keyboard). The passive one is created on first use."""
    def __init__(self, daemon, accent):
        """Create the normal overlay now; the passive one when first needed."""
        super().__init__()
        self.daemon, self.accent = daemon, accent
        self.normal = Overlay(daemon, accent)
        self._passive = None
        self.current = self.normal

    def passive(self):
        """The passive overlay, created the first time a popup needs it."""
        if self._passive is None:
            self._passive = Overlay(self.daemon, self.accent, passive=True)
        return self._passive

    @Slot(str)
    def opened(self, payload):
        """Show the snapshot in the overlay it needs (passive over popups), hiding the other."""
        want_passive = json.loads(payload).get("passive")
        target = self.passive() if want_passive else self.normal
        if want_passive and not target.passive:
            target = self.normal  # no layer-shell: fall back (the popup will close)
        for o in (self.normal, self._passive):
            if o is not None and o is not target:
                o.hide()
        self.current = target
        target.opened(payload)

    @Slot()
    def closed(self):
        """Hide both overlays."""
        for o in (self.normal, self._passive):
            if o is not None:
                o.closed()

    @Slot(str)
    def refused(self, payload):
        """Notify the user (the normal overlay owns the notification logic)."""
        self.normal.refused(payload)

    @Slot(str)
    def key(self, payload):
        """Daemon signal: a key typed over a popup goes to the passive overlay."""
        if self._passive is not None and self._passive.isVisible():
            self._passive.on_key(payload)


def main():
    """Entry point: the Settings window with --settings, otherwise the resident overlay connected to the daemon."""
    ap = argparse.ArgumentParser(description="vimvibe overlay (keep running) or, with --settings, its Settings window")
    ap.add_argument("--settings", action="store_true", help="open the Settings window")
    ap.add_argument("--accent", help=f"label/highlight colour for this run (default {DEFAULT_ACCENT})")
    ap.add_argument("--trigger", action="store_true", help="ask the daemon to open the overlay once (testing)")
    ap.add_argument("--query", default="", help="with --trigger: type this into the search field (testing)")
    ap.add_argument("--quit-after", type=int, default=0, help="exit after N seconds (testing)")
    ap.add_argument("--snapshot", help="after opening, save an image of this overlay window only (testing)")
    a = ap.parse_args()
    app = QApplication(sys.argv)
    if a.settings:
        from vimvibe_settings import SettingsWindow
        w = SettingsWindow(read_config, write_config, DEFAULTS)
        w.show()
        sys.exit(app.exec())
    app.setQuitOnLastWindowClosed(False)
    bus = QDBusConnection.sessionBus()
    daemon = QDBusInterface(SERVICE, PATH, IFACE, bus)
    if not daemon.isValid():
        sys.exit("vimvibe daemon not running (start it with: vimvibe-core daemon)")
    router = Router(daemon, a.accent)
    ok = all([bus.connect(SERVICE, PATH, IFACE, "Opened", router, "1opened(QString)"),
              bus.connect(SERVICE, PATH, IFACE, "Closed", router, "1closed()"),
              bus.connect(SERVICE, PATH, IFACE, "Refused", router, "1refused(QString)"),
              bus.connect(SERVICE, PATH, IFACE, "Key", router, "1key(QString)"),
              bus.connect(SERVICE, PATH, IFACE, "Quitting", app, "1quit()")])
    # the overlay is useless without the daemon: exit with it however it stops (quit shortcut, kill, crash)
    watcher = QDBusServiceWatcher(SERVICE, bus, QDBusServiceWatcher.WatchForUnregistration)
    watcher.serviceUnregistered.connect(lambda _: app.quit())
    print("connected to daemon signals:", ok, flush=True)
    if a.trigger:
        QTimer.singleShot(0, lambda: daemon.asyncCall("Trigger"))  # async: Opened must arrive through the normal event loop
        if a.query:
            QTimer.singleShot(700, lambda: router.current.edit.setText(a.query))
    if a.snapshot:
        # grabs only this window's own pixels (transparent elsewhere), never the screen behind it
        QTimer.singleShot(1500, lambda: router.current.grab().save(a.snapshot))
    if a.quit_after:
        QTimer.singleShot(a.quit_after * 1000, app.quit)
    app.exec()


if __name__ == "__main__":
    main()
