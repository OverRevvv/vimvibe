#!/usr/bin/env python3
"""vimvibe palette: the overlay UI for the vimvibe daemon (`vimvibe-core daemon`), plus its Settings window.

The daemon owns the global shortcuts and snapshots the focused window when one fires, so this process only shows the
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
  hold Space + H J K L     arrow keys in the app (needs keyboard permission); release Space to come back
  hold Space+Ctrl + H J K L  scroll (the selected element, or the window); release Space to see new labels
  tap Alt                  clear the search, show all labels  Ctrl+R       re-read the window
  Ctrl+,  (anywhere: Ctrl+Shift+,)  Settings                  Esc          close (also ends continuous mode)
Mouse: click a label or a row to activate it, click anywhere else to close, wheel moves the selection.

  vimvibe_palette.py                 run the overlay (keep it running; it waits for the shortcut)
  vimvibe_palette.py --settings      open the Settings window on its own
  testing: [--accent COLOR] [--trigger] [--query TEXT] [--quit-after N] [--snapshot FILE]

All settings live in ~/.config/vimvibe/config.toml (see README.md); --accent and $VIMVIBE_ACCENT override the colour.
"""
import argparse, json, os, sys

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer, Slot
from PySide6.QtDBus import QDBusConnection, QDBusInterface, QDBusPendingCallWatcher, QDBusServiceWatcher
from PySide6.QtGui import QColor, QFontMetricsF, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget

from vimvibe_style import DEFAULT_ACCENT, DEFAULTS, Theme, read_config, write_config

SERVICE, PATH, IFACE = "org.vimvibe.Daemon", "/org/vimvibe/Daemon", "org.vimvibe.Daemon"
DEBUG = bool(os.environ.get("VIMVIBE_DEBUG"))
PAD = 14
TAP_MS = 350        # a modifier released within this time, with no other key, counts as a tap
# after acting on these, continuous mode stops: the user is about to type, or a menu/another window takes over
STOP_CONTINUOUS = {"Entry", "PasswordText", "Text", "Terminal", "DocumentText", "ComboBox", "SpinButton", "Window", "Application",
                   "Menu", "MenuBar", "PushButtonMenu"}
# hold-Space scroll keys -> (dx, dy) in wheel clicks; Shortcat offers both layouts
SCROLL_KEYS = {
    "hjkl": {Qt.Key_H: (-1, 0), Qt.Key_J: (0, 1), Qt.Key_K: (0, -1), Qt.Key_L: (1, 0)},
    "ijkl": {Qt.Key_J: (-1, 0), Qt.Key_K: (0, 1), Qt.Key_I: (0, -1), Qt.Key_L: (1, 0)},
}


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
        self.on_settings = None  # set by the Router: open the Settings window
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
        self.space_down = False   # Space is held: H J K L scroll instead of typing
        self.space_used = False   # ... and was used for scrolling (so releasing it types no space)
        self.scrolling = False
        self.arrowing = False     # arrow mode: the overlay is hidden and the daemon turns H J K L into arrow keys
        self.edit = QLineEdit(self)
        self.default_placeholder = "Search for elements, or type a label"
        self.edit.setFrame(False)
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
        """Re-read config.toml and rebuild the theme (colours, fonts, sizes) and the search field's look."""
        self.cfg = read_config()
        self.t = Theme(self.cfg, self.accent_override)
        self.edit.setFont(self.t.field_font)
        self.edit.setStyleSheet(f"background: transparent; color: {self.t.panel_text.name()};")

    def send(self, method, *args):
        """Fire-and-forget D-Bus call to the daemon (PySide's asyncCall takes no arguments, hence the list form)."""
        self.daemon.asyncCallWithArgumentList(method, list(args))

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
        self.space_down = self.space_used = self.arrowing = self.scrolling = False  # a fresh open ends any key mode
        self.meta = json.loads(payload)
        self.place_screen()
        self.elements = (self.call("Elements") or {}).get("elements", [])
        self.layout_labels()
        self.edit.blockSignals(True); self.edit.clear(); self.edit.blockSignals(False)
        self.labels_on = False
        self.set_placeholder()
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
        self.end_scroll(refresh=False)
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
            self.move_sel(self.t.rows)
        elif name in ("Page_Up", "Prior"):
            self.move_sel(-self.t.rows)
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

    def set_placeholder(self):
        """Search field placeholder; empty while the panel is hidden until typing (nothing should float on screen)."""
        if self.t.hide_panel_until_typing:
            self.edit.setPlaceholderText("")
        else:
            self.edit.setPlaceholderText("Search applications and windows" if self.meta.get("launcher") else self.default_placeholder)

    # --- layout -------------------------------------------------------------------
    def place_screen(self):
        """Cover the screen that holds the target window."""
        o = self.meta.get("origin")  # [x, y, w, h] of the target window, logical screen px
        scr = QGuiApplication.screenAt(QPointF(o[0] + o[2] / 2, o[1] + o[3] / 2).toPoint()) if o and o[2] > 0 else None
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
        left inside its element if there is room, then just below or above it; otherwise they overlap like Shortcat's."""
        self.rects, self.labels = {}, {}
        W, H = self.width(), self.height()
        placed = []
        for e in self.elements:
            r = self.local_rect(e.get("screen"))
            if not r:
                continue
            self.rects[e["id"]] = r
            if not e.get("hint"):
                continue
            w, h = self.t.label_size(e["hint"])
            x = r.right() - w - 1 if r.width() >= w + 2 else r.center().x() - w / 2
            y = r.center().y() - h / 2
            clamp = lambda x, y: QRectF(min(max(x, 1), W - w - 1), min(max(y, 1), H - h - 1), w, h)
            lr = clamp(x, y)
            clear = lambda q: not any(o.intersects(q) for o in placed)
            if not clear(lr):
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

    def header_h(self):
        """Height of the panel above the rows: search field, plus the hint line when shown."""
        return PAD + 44 + (22 if self.t.hint_line else 8)

    def panel_height(self, rows):
        """Height of the search panel for `rows` result rows."""
        return self.header_h() + max(1, rows) * self.t.row_h + 30 + PAD

    def panel_shown(self):
        """Whether the panel is drawn now (hidden until typing, when that is set)."""
        return not (self.t.hide_panel_until_typing and not self.edit.text())

    def place_panel(self, keep_if_clear=False):
        """Put the panel where it hides the fewest labels: above, at the top, middle or bottom of, beside, or below the
        target window ([ui] panel = "top"/"center"/"bottom" pins it). The selected element must stay visible; with
        keep_if_clear the panel only moves when it would hide it, so it does not jump around while typing."""
        W, H = self.width(), self.height()
        o = self.meta.get("origin")
        if o and o[2] > 0:
            wx, wy, ww, wh = o[0] - self.origin[0], o[1] - self.origin[1], o[2], o[3]
        else:
            wx, wy, ww, wh = 0, 0, W, H
        rows = self.t.rows
        w = min(self.t.panel_width, W - 2 * PAD)
        h = self.panel_height(min(rows, max(1, len(self.hits))))
        x = max(PAD, min(wx + ww / 2 - w / 2, W - w - PAD))
        pinned = {"top": wy + PAD, "center": wy + wh * 0.5 - h / 2, "bottom": wy + wh - h - PAD}.get(self.t.position)
        if pinned is not None:
            if keep_if_clear and not self.panel.isEmpty():
                return
            y = max(PAD, min(pinned, H - self.panel_height(rows) - PAD))
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
                sw = min(self.t.panel_width, side_w)
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
        elif self.sel >= self.top + self.t.rows:
            self.top = self.sel - self.t.rows + 1
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
        self.end_scroll(refresh=False)
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

    # --- scrolling (hold Space + H J K L) --------------------------------------------
    def start_scroll(self):
        """Begin scrolling: the daemon parks the pointer over the selected element (when something is typed) or the
        middle of the window, and this window stops taking pointer input so the wheel events reach the app below."""
        target = self.hits[self.sel]["id"] if (self.hits and self.edit.text()) else -1
        res = self.call("ScrollStart", target)
        if not res or not res.get("ok"):
            notify("vimvibe can't scroll here", (res or {}).get("error", "the daemon did not answer"))
            return False
        self.scrolling = True
        self.labels_on = False  # positions go stale as the content moves; new labels come after Space is released
        self.windowHandle().setFlag(Qt.WindowTransparentForInput, True)
        self.update()
        return True

    def end_scroll(self, refresh=True):
        """Finish scrolling: pointer back where it was, input back to this window, and re-read the window so labels
        match the scrolled content."""
        if not self.scrolling:
            return
        self.scrolling = False
        self.daemon.asyncCall("ScrollEnd")
        if self.windowHandle():
            self.windowHandle().setFlag(Qt.WindowTransparentForInput, False)
        if refresh:
            self.daemon.asyncCall("Refresh")

    def scroll_key(self, k, shift):
        """A scroll key while Space is held; Shift scrolls four times as far."""
        dx, dy = SCROLL_KEYS.get(self.cfg["scroll"].get("keys", "hjkl"), SCROLL_KEYS["hjkl"]).get(k, (0, 0))
        if not (dx or dy):
            return False
        if not self.scrolling and not self.start_scroll():
            return True
        step = max(1, int(self.cfg["scroll"].get("step", 3))) * (4 if shift else 1)
        self.send("Scroll", dx * step, dy * step)
        return True

    def arrow_key(self, k, shift):
        """Space + a direction key: hand the keyboard back to the app and let the daemon send arrow keys (it takes the
        physical H J K L until Space is released, then reopens the overlay). Without keyboard permission this
        scrolls instead; in apps that don't share key presses with accessibility it explains why it can't."""
        dx, dy = SCROLL_KEYS.get(self.cfg["scroll"].get("keys", "hjkl"), SCROLL_KEYS["hjkl"]).get(k, (0, 0))
        if not (dx or dy):
            return False
        if self.arrowing:
            return True
        status = self.call("Status") or {}
        if not status.get("keyboard"):
            notify("Arrow keys need keyboard permission", "Scrolling instead. Allow the keyboard once with "
                   "`vimvibe-core pointer-setup` (or Settings → Accessibility & setup).")
            return self.scroll_key(k, shift)
        # hide first so the app gets the keyboard back, then let the daemon take over without blocking this window
        self.arrowing = True
        self.labels_on = False
        self.hide()
        watcher = QDBusPendingCallWatcher(self.daemon.asyncCallWithArgumentList("ArrowStart", [dx, dy]), self)
        watcher.finished.connect(self.arrow_started)
        return True

    def arrow_started(self, watcher):
        """Answer to ArrowStart: on refusal (the app doesn't share key presses), explain; the daemon reopens."""
        msg = watcher.reply()
        args = msg.arguments() if msg is not None else []
        res = json.loads(args[0]) if args and args[0] else {}
        watcher.deleteLater()
        if not res.get("ok"):
            self.arrowing = False
            notify("vimvibe can't send arrow keys here", res.get("error", "the daemon did not answer"))

    def eventFilter(self, obj, ev):
        """Keys typed into the search field: Esc, Enter variants, Ctrl+digit, navigation, Space-scrolling, Settings,
        and modifier taps."""
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
            if k == Qt.Key_Space and not ctrl and not alt:
                if not ev.isAutoRepeat():
                    self.space_down, self.space_used = True, False
                return True  # typed on release, unless it was used to scroll
            if self.space_down and not alt:
                # Space + H J K L: arrow keys to the app; Space + Ctrl + H J K L: scroll (Shortcat: Space+Cmd)
                if self.scroll_key(k, shift) if ctrl else self.arrow_key(k, shift):
                    self.space_used = True
                    return True
            if k == Qt.Key_Escape:
                self.dismiss(); return True
            if ctrl and k in (Qt.Key_Comma, Qt.Key_Less):
                self.dismiss()
                if self.on_settings:
                    self.on_settings()
                return True
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
                    Qt.Key_PageDown: self.t.rows, Qt.Key_PageUp: -self.t.rows}.get(k)
            if ctrl and k == Qt.Key_N: step = 1
            if ctrl and k == Qt.Key_P: step = -1
            if step:
                self.move_sel(step); return True
        elif t == QEvent.KeyRelease and ev.key() == Qt.Key_Space and not ev.isAutoRepeat():
            if self.arrowing:  # Space came back to us before the daemon took over the keys: end arrow mode here
                self.arrowing = self.space_down = False
                self.send("ArrowEnd", True)
                return True
            if self.space_down:
                self.space_down = False
                if self.space_used:
                    self.end_scroll()
                else:
                    self.edit.insert(" ")
            return True
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
        return QRectF(self.panel.x() + PAD, self.panel.y() + self.header_h() + i * self.t.row_h,
                      self.panel.width() - 2 * PAD, self.t.row_h)

    def mousePressEvent(self, ev):
        """Click on a row or a label activates it (right button: right click); anywhere else closes."""
        p = ev.position()
        right = ev.button() == Qt.RightButton
        if self.panel_shown():
            for i in range(min(self.t.rows, len(self.hits) - self.top)):
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
        hint = {e["id"]: e["hint"].upper() for e in self.elements}
        return [i for i in self.labels if hint.get(i, "").startswith(q)]

    def paintEvent(self, _):
        """Draw the dimmed backdrop, the selected element's highlight, the labels, then the panel on top."""
        if self.origin is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.t.dim and not self.scrolling:
            p.fillRect(self.rect(), QColor(0, 0, 0, int(255 * self.t.dim / 100)))
        if self.scrolling:
            self.paint_scroll_banner(p)
            return
        self.paint_selected(p)
        self.paint_labels(p)
        if self.panel_shown():
            self.paint_panel(p)

    def paint_scroll_banner(self, p):
        """While scrolling: a small banner instead of labels and panel (they would be stale)."""
        keys = self.cfg["scroll"].get("keys", "hjkl").upper()
        text = f"Scrolling — hold Space+Ctrl, {' '.join(keys)} (Shift: faster) · release Space for new labels"
        p.setFont(self.t.small_font)
        w = QFontMetricsF(self.t.small_font).horizontalAdvance(text) + 32
        r = QRectF((self.width() - w) / 2, 24, w, 34)
        path = QPainterPath(); path.addRoundedRect(r, 10, 10)
        p.fillPath(path, self.t.panel_bg)
        p.setPen(QPen(self.t.accent, 2)); p.drawPath(path)
        p.setPen(self.t.panel_text); p.drawText(r, Qt.AlignCenter, text)

    def paint_selected(self, p):
        """Filled highlight around the selected result's element."""
        if not self.hits:
            return
        r = self.rects.get(self.hits[self.sel]["id"])
        if r:
            fill = QColor(self.t.selected); fill.setAlpha(80)
            p.setPen(QPen(self.t.selected, 2)); p.setBrush(fill)
            p.drawRoundedRect(r.adjusted(-2, -2, 2, 2), 4, 4)
            p.setBrush(Qt.NoBrush)

    def paint_labels(self, p):
        """Draw the labels that are visible now; the part already typed is dimmed, the selected one highlighted."""
        typed = len(hint_prefix(self.edit.text()) or "")
        sel_id = self.hits[self.sel]["id"] if self.hits else None
        ids = self.shown_labels()
        if sel_id is not None and sel_id in self.labels and sel_id not in ids and self.labels_on:
            ids.append(sel_id)
        hint = {e["id"]: e["hint"] for e in self.elements}
        for eid in ids:
            self.t.draw_label(p, self.labels[eid], hint.get(eid, ""), typed, eid == sel_id)

    def paint_panel(self, p):
        """Draw the search panel: field frame, hint line, result rows (name, role, label, Ctrl+n) and footer."""
        t = self.t
        pr = QRectF(self.panel); pr.setHeight(self.panel_height(min(t.rows, len(self.hits))))
        p.setBrush(Qt.NoBrush)
        path = QPainterPath(); path.addRoundedRect(pr, 14, 14)
        p.fillPath(path, t.panel_bg)
        p.setPen(QPen(t.panel_border, 1)); p.drawPath(path)
        fr = QRectF(pr.x() + PAD, pr.y() + PAD, pr.width() - 2 * PAD, 44)
        fp = QPainterPath(); fp.addRoundedRect(fr, 9, 9)
        p.fillPath(fp, t.panel_field)
        p.setPen(QPen(t.accent, 2)); p.drawPath(fp)
        if t.hint_line:
            p.setFont(t.small_font); p.setPen(t.panel_dim)
            keys = self.cfg["scroll"].get("keys", "hjkl").upper()
            p.drawText(QRectF(pr.x() + PAD + 4, pr.y() + PAD + 44, pr.width() - 2 * PAD, 22), Qt.AlignVCenter,
                       f"[Enter] click · tap [Alt] all labels · [Space+{keys}] arrows · [Space+Ctrl+{keys}] scroll · [Ctrl+,] settings")
        fm = QFontMetricsF(t.row_font)
        sfm = QFontMetricsF(t.small_font)
        for i in range(min(t.rows, len(self.hits) - self.top)):
            idx = self.top + i
            h = self.hits[idx]; e = h["element"]
            rr = self.row_rect(i)
            if idx == self.sel:
                sp = QPainterPath(); sp.addRoundedRect(rr.adjusted(0, 1, 0, -1), 7, 7)
                c = QColor(t.selected); c.setAlpha(75); p.fillPath(sp, c)
            kh = rr.height() - 12
            nr = QRectF(rr.right() - 28, rr.y() + 6, 24, kh)
            cr = QRectF(nr.x() - 28, nr.y(), 24, kh)
            for kr, txt in ((cr, "⌃"), (nr, str(i + 1) if i < 9 else "")):
                if not txt:
                    continue
                kp = QPainterPath(); kp.addRoundedRect(kr, 5, 5)
                p.fillPath(kp, t.key_bg)
                p.setFont(t.key_font); p.setPen(t.key_fg)
                p.drawText(kr, Qt.AlignCenter, txt)
            right = cr.x() - 10
            if h.get("hint"):
                lw, lh = t.label_size(h["hint"])
                lr = QRectF(right - lw, rr.center().y() - lh / 2, lw, lh)
                t.draw_label(p, lr, h["hint"])
                right = lr.x() - 10
            role = e["role"] + ("" if e["enabled"] else " · disabled")
            rw = sfm.horizontalAdvance(role)
            p.setFont(t.small_font); p.setPen(t.panel_role)
            p.drawText(QRectF(right - rw, rr.y(), rw + 2, rr.height()), Qt.AlignVCenter, role)
            p.setFont(t.row_font)
            p.setPen(t.panel_text if e["enabled"] else t.panel_disabled)
            avail = right - rw - 16 - (rr.x() + 10)
            p.drawText(QRectF(rr.x() + 10, rr.y(), avail, rr.height()), Qt.AlignVCenter,
                       fm.elidedText(e["name"] or "(unlabeled)", Qt.ElideRight, avail))
        n = self.meta.get("count", 0)
        ms = (self.meta.get("ms") or {}).get("total")
        tail = f" in {ms / 1000:.2f}s" if isinstance(ms, (int, float)) else ""
        trunc = " (truncated)" if self.meta.get("truncated") else ""
        wins = f" + {self.meta['windows']} windows" if self.meta.get("windows") else ""
        cont = " · continuous" if self.cfg["behavior"].get("continuous") else ""
        p.setFont(t.small_font); p.setPen(t.panel_dim)
        if self.meta.get("launcher"):
            foot = f"{self.meta.get('apps', 0)} applications · {self.meta.get('windows', 0)} windows — type to launch or switch"
        else:
            foot = f"Found {n} elements{tail}{trunc}{wins} · {self.meta.get('app', '')}{cont}"
        p.drawText(QRectF(pr.x() + PAD + 4, pr.bottom() - PAD - 26, pr.width() - 2 * PAD, 26), Qt.AlignVCenter, foot)


class Router(QObject):
    """Sends each open to the right overlay: the normal one (takes the keyboard) or the passive one (layer-shell, for
    popups that must keep the keyboard). The passive one is created on first use. Also owns the Settings window."""
    def __init__(self, daemon, accent):
        """Create the normal overlay now; the passive one when first needed."""
        super().__init__()
        self.daemon, self.accent = daemon, accent
        self.normal = Overlay(daemon, accent)
        self.normal.on_settings = self.open_settings
        self._passive = None
        self.current = self.normal
        self.settings = None

    def passive(self):
        """The passive overlay, created the first time a popup needs it."""
        if self._passive is None:
            self._passive = Overlay(self.daemon, self.accent, passive=True)
            self._passive.on_settings = self.open_settings
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

    @Slot()
    def open_settings(self):
        """Show the Settings window (Ctrl+Shift+, anywhere, or Ctrl+, in the overlay); one window, raised if open."""
        from vimvibe_settings import SettingsWindow
        for o in (self.normal, self._passive):
            if o is not None and o.isVisible():
                o.hide()
        if self.settings is None:
            self.settings = SettingsWindow(read_config, write_config, DEFAULTS)
        else:
            self.settings.load(read_config())
        self.settings.show()
        self.settings.raise_()
        self.settings.activateWindow()


def desktop_entry_installed():
    """Whether a vimvibe.desktop entry is in an XDG applications directory (installed by install.sh)."""
    dirs = [os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")]
    dirs += (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":")
    return any(os.path.isfile(os.path.join(d, "applications", "vimvibe.desktop")) for d in dirs if d)


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
    app.setApplicationName("vimvibe")
    if desktop_entry_installed():
        # names our windows "vimvibe"; Qt also registers that app id with the desktop portal, which only works when a
        # matching vimvibe.desktop exists (install.sh adds it), otherwise the portal logs an error
        app.setDesktopFileName("vimvibe")
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
              bus.connect(SERVICE, PATH, IFACE, "OpenSettings", router, "1open_settings()"),
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
