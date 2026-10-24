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
  Enter, Enter (twice)     double click                       Shift+Enter  middle click
  (tap Ctrl to hover / twice to focus is off by default: bind tap_hover in Settings → Keys)
  Ctrl+1..9                act on row n                       Ctrl+Shift+1..9  select row n
  ↑ ↓ / Tab / Ctrl+N Ctrl+P  move the selection               PageUp / PageDown  by a page
  hold Space + H J K L     scroll left / down / up / right (the selected element, or the window); Shift = faster
  hold Space + D / U       scroll down / up                   Space + g g / Shift+G   jump to the top / bottom
  hold Space+Ctrl + H J K L  arrow keys in the app (needs keyboard permission; the first press only switches the mode
                           on, keep Space held and use H J K L); Settings can swap the two actions
  release Space            vimvibe comes back with fresh labels
  tap Alt                  clear the search, show all labels  Ctrl+R       re-read the window
  Ctrl+,  (anywhere: Ctrl+Shift+,)  Settings                  Esc          steps back from the mouse modes; Esc twice closes (also ends continuous mode) — [behavior] double_esc_close
  Space / Ctrl+Space       hide / show the search panel (labels stay); plain Space only while the search is empty; remembered
  Ctrl+G                   mouse grid: type a cell's two letters to zoom in, Enter clicks the middle, Space only moves there,
                           Backspace zooms out, Ctrl+Shift+G window/screen, Esc -> pointer movement
  Ctrl+M                   mouse movement: hold H J K L to move the pointer (Shift faster, Alt precise), Enter clicks
  Arrows, PgUp/PgDn (D / U in movement)  (in either mouse mode) scroll under the pointer without leaving the mode; Esc in the grid -> movement
All of these (except the Space+H J K L scrolling family and the mouse movement keys) can be rebound in Settings → Keys ([keys] in config.toml);
the ones above are the defaults.
Mouse: click a label or a row to activate it, click anywhere else to close, wheel moves the selection.

  vimvibe_palette.py                 run the overlay (keep it running; it waits for the shortcut)
  vimvibe_palette.py --settings      open the Settings window on its own
  testing: [--accent COLOR] [--trigger] [--query TEXT] [--quit-after N] [--snapshot FILE]

All settings live in ~/.config/vimvibe/config.toml (see README.md); --accent and $VIMVIBE_ACCENT override the colour.
"""
import argparse, json, math, os, sys, time

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer, Slot
from PySide6.QtDBus import QDBus, QDBusConnection, QDBusInterface, QDBusPendingCallWatcher, QDBusServiceWatcher
from PySide6.QtGui import QColor, QFontMetricsF, QIcon, QGuiApplication, QKeyEvent, QKeySequence, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox, QWidget

import vimvibe_clip
from vimvibe_keys import KeyMap, iv
from vimvibe_mouse import Grid
from vimvibe_style import DEFAULT_ACCENT, DEFAULTS, PROFILE, Theme, icon_path, number, read_config, read_state, write_config, write_state

# the daemon's bus name carries the profile ("...DaemonDev"); the interface name is the same for every profile
SERVICE, PATH, IFACE = "org.vimvibe.Daemon" + PROFILE.capitalize(), "/org/vimvibe/Daemon", "org.vimvibe.Daemon"
DEBUG = bool(os.environ.get("VIMVIBE_DEBUG"))
PAD = 14
GG_S = 0.5          # the second g of "gg" must come within this many seconds
MOVE_TICK_MS = 16   # pointer movement (H J K L) updates this often
DOUBLE_ESC_S = 0.7   # a second Esc within this many seconds closes vimvibe (when double Esc is on)
FLASH_MS = 1500     # how long a short on-screen message ("Press Esc again") stays
TAP_MS = 350        # a modifier released within this time, with no other key, counts as a tap
# after acting on these, continuous mode stops: the user is about to type, or a menu/another window takes over
STOP_CONTINUOUS = {"Entry", "PasswordText", "Text", "Terminal", "DocumentText", "ComboBox", "SpinButton", "Window", "Application",
                   "Menu", "MenuBar", "PushButtonMenu"}
# Space scroll keys -> (dx, dy). No modifier on purpose: apps treat Ctrl+wheel as zoom (measured: Dolphin does not
# scroll at all with Ctrl held), Shift+wheel as horizontal, Alt+wheel as "back" in some browsers.
# X key names the daemon reports for a Ctrl / Alt combination typed over a popup -> Qt keys (single characters are
# converted directly)
PASSIVE_KEYS = {"space": Qt.Key_Space, "Return": Qt.Key_Return, "KP_Enter": Qt.Key_Enter, "Tab": Qt.Key_Tab,
                "ISO_Left_Tab": Qt.Key_Backtab, "Down": Qt.Key_Down, "Up": Qt.Key_Up, "Page_Down": Qt.Key_PageDown,
                "Page_Up": Qt.Key_PageUp, "comma": Qt.Key_Comma, "BackSpace": Qt.Key_Backspace, "Escape": Qt.Key_Escape}
# keys that scroll in the mouse modes: no modifier is needed (a held Ctrl would turn the wheel into page zoom); Shift or
# Page Up / Down scroll further
MOUSE_SCROLL_KEYS = {iv(Qt.Key_Up): (0, -1), iv(Qt.Key_Down): (0, 1), iv(Qt.Key_Left): (-1, 0), iv(Qt.Key_Right): (1, 0),
                     iv(Qt.Key_PageUp): (0, -1), iv(Qt.Key_PageDown): (0, 1)}
SCROLL_LETTERS = {Qt.Key_D: (0, 1), Qt.Key_U: (0, -1)}
# hold-Space arrow keys -> direction; Shortcat offers both layouts
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
        subprocess.Popen(["notify-send", "-a", "vimvibe", "-i", icon_path() or "input-keyboard", "-t", "4000", summary, body],
                         stderr=subprocess.DEVNULL)
    print(f"{summary}: {body}", file=sys.stderr, flush=True)


def make_passive(widget, exclusive=False):
    """Turn `widget` (not yet shown) into a full-screen layer-shell overlay, using the
    layer-shell-qt library Plasma itself ships (no Python bindings exist, so its one entry point is called through
    ctypes and the rest are ordinary Qt properties). By default it never takes the keyboard: popups that close on focus
    loss (Plasma's launcher) stay open under it and keys arrive from the daemon instead (Key signal). With `exclusive`
    it takes the keyboard and keeps it whatever is clicked below (a pointer click for text selection must not move the
    keys to the app), so no key reaches the app while vimvibe is open. Returns False when layer-shell-qt is unavailable."""
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
        lw.setProperty("keyboardInteractivity", 1 if exclusive else 0)  # Exclusive: keeps the keyboard / None: never takes it
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
        self.on_edit = None      # set by the Router: show the edit mode banner (callable(meta) -> bool)
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
        self.enter_timer = QTimer(self); self.enter_timer.setSingleShot(True)  # waits for a possible second Enter (double click)
        self.enter_timer.timeout.connect(self.enter_fire)
        self.enter_pending = None   # what the waiting Enter will do if no second one comes: a callable taking the action name
        self.space_down = False   # Space is held: H J K L scroll instead of typing
        self.space_used = False   # ... and was used for scrolling (so releasing it types no space)
        self.scrolling = False
        self.refreshing = False   # after scrolling: the window is being re-read, so nothing stale is drawn meanwhile
        self.last_g = 0.0         # time of the last "g" while Space is held (gg = top)
        self.arrowing = False     # arrow mode: the overlay is hidden and the daemon turns H J K L into arrow keys
        self.panel_override = None  # the panel toggle key: True/False forces it shown/hidden, None = the default rule
        self.mouse = None         # keyboard mouse: None, "grid" (zooming grid) or "move" (H J K L moves the pointer)
        self.grid = None
        self.grid_scope = "window"
        self.esc_at = 0.0         # time of the last Esc that only armed the "press Esc again to close" step
        self.flash = ""           # a short message drawn over the overlay for FLASH_MS
        self.flash_timer = QTimer(self, singleShot=True, timeout=self.clear_flash)
        self.clip = None          # the clipboard history picker while open: {"all": entries, "filter": str, "sel": int, "top": int}
        self.last_regrab = 0.0    # time of the last keyboard take-back (see regrab_keyboard)
        self.resume_mouse = None  # "grid" / "move": the mouse mode to re-enter when the overlay reopens after arrow keys
        self.mspace_down = self.mspace_used = False  # mouse modes: Space held (a scroll chord) and whether it was used
        self.edit_visual = False  # edit mode: arrows select text (V toggles it)
        self.scroll_timer = QTimer(self, singleShot=True, timeout=self.mouse_scroll_done)  # pointer input back after a mouse-mode scroll
        self.held = []            # pointer movement: direction keys held now, as (dx, dy)
        self.move_mods = 0        # modifiers last seen (Shift = fast, Alt = precise)
        self.move_since = self.move_last = 0.0
        self.move_rem = [0.0, 0.0]
        self.move_timer = QTimer(self, interval=MOVE_TICK_MS, timeout=self.move_tick)
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
        self.layered = False  # a layer-shell surface that keeps the keyboard (the normal overlay)
        if passive:
            self.passive = make_passive(self)
        else:
            self.layered = make_passive(self, exclusive=True)

    def load_settings(self):
        """Re-read config.toml and rebuild the theme (colours, fonts, sizes) and the search field's look."""
        self.cfg = read_config()
        self.t = Theme(self.cfg, self.accent_override)
        self.keymap = KeyMap(self.cfg.get("keys"))
        for problem in self.keymap.problems:
            print("keys:", problem, file=sys.stderr, flush=True)
        self.edit.setFont(self.t.field_font)
        self.sync_field()

    def send(self, method, *args):
        """Fire-and-forget D-Bus call to the daemon (PySide's asyncCall takes no arguments, hence the list form)."""
        self.daemon.asyncCallWithArgumentList(method, list(args))

    def call(self, method, *args):
        """Blocking D-Bus call to the daemon; returns its JSON answer (None on error). The argument-list form is used
        because PySide's `call(method, *args)` only accepts a handful of arguments (PointerScroll has five)."""
        msg = self.daemon.callWithArgumentList(QDBus.Block, method, list(args))
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
        self.space_down = self.space_used = self.arrowing = self.scrolling = False  # a fresh open ends any edit mode
        self.leave_mouse()
        was_refresh, self.refreshing = self.refreshing, False
        self.meta = json.loads(payload)
        self.panel_override = self.initial_panel_override()
        self.sync_field()
        self.place_screen()
        self.elements = (self.call("Elements") or {}).get("elements", [])
        self.layout_labels()
        self.edit.blockSignals(True); self.edit.clear(); self.edit.blockSignals(False)
        self.labels_on = False
        self.set_placeholder()
        self.query("")
        self.place_panel()
        self.edit.show()  # edit mode hid it
        if self.isVisible():  # re-read after scrolling: already on screen, don't show it again (KWin would animate it)
            self.update()
        elif self.passive or self.layered:
            self.show()  # layer surface anchored to every edge; no activation (the passive one leaves the keyboard to the popup)
        else:
            self.showFullScreen()
            self.raise_()
            self.activateWindow()
        if not self.passive:
            self.edit.setFocus()
        if was_refresh:
            if not self.cfg["hints"].get("after_input"):
                self.reveal_labels()  # the labels pop in at once, no delay
            return
        self.open_in_mode()
        if (self.mouse is None and not self.passive and not self.meta.get("launcher") and self.mouse_enabled()
                and self.cfg["mouse"].get("fallback_grid", True) and int(self.meta.get("count", 9)) <= 1):
            # the app shows vimvibe nothing to label (no accessibility tree): the mouse grid works in every app
            self.enter_grid()
            self.show_flash("This app exposes no elements to label: using the mouse grid (Esc leaves it)")
        if self.resume_mouse:  # back from Space + H J K L arrow keys: carry on in the mouse mode they were used in
            mode, self.resume_mouse = self.resume_mouse, None
            self.enter_move() if mode == "move" else self.enter_grid()
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
        self.enter_cancel()
        try:
            self.end_scroll(refresh=False)
            self.leave_mouse()
        finally:  # whatever the cleanup does, the overlay must go away (a stuck overlay blocks the next open)
            self.clip = None
            self.hide()

    @Slot(str)
    def refused(self, payload):
        """Daemon signal: it could not open (excluded app, unreadable window); tell the user why."""
        meta = json.loads(payload)
        self.refreshing = False
        if meta.get("restart"):
            QTimer.singleShot(0, lambda: self.offer_restart(meta["restart"]))
            return
        if meta.get("excluded"):
            notify("vimvibe is off for this app", f"Excluded by the rule “{meta['excluded']}” in your vimvibe settings.")
        elif meta.get("unsupported"):
            notify("vimvibe can't use this popup yet", meta.get("error", ""))
        else:
            notify("vimvibe can't read this window", meta.get("error", ""))

    def offer_restart(self, app):
        """A Chromium-based app (Chrome, Brave, Edge, an Electron app) was started without accessibility, so vimvibe sees
        nothing in it and nothing can change that from outside: offer to restart it with the flag (tabs come back)."""
        name = app.get("app") or "This app"
        box = QMessageBox(QMessageBox.Question, "vimvibe",
                          f"{name} isn't sharing its page with vimvibe yet.",
                          QMessageBox.NoButton)
        box.setInformativeText(f"Browsers built on Chromium only do that when they are started with accessibility on. "
                               f"Restart {name} now with it? Your tabs come back, and vimvibe makes {name} start this way "
                               f"from the menu from now on.")
        yes = box.addButton("Restart it", QMessageBox.AcceptRole)
        box.addButton("Not now", QMessageBox.RejectRole)
        box.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        box.exec()
        if box.clickedButton() is not yes:
            return
        res = self.call("RestartWithAccessibility", int(app["pid"]))
        if res and res.get("ok"):
            notify(f"{name} restarted", "Press the vimvibe shortcut again once it is back.")
        else:
            notify(f"vimvibe could not restart {name}", (res or {}).get("error", "the daemon did not answer"))

    def on_key(self, payload):
        """A key typed over a popup (passive mode): the daemon consumed it before the popup saw it."""
        k = json.loads(payload)
        name = k.get("name", "")
        if self.clip is not None:  # the picker takes every key, plain or with Ctrl
            qt = PASSIVE_KEYS.get(name) or (QKeySequence(name.upper())[0].key() if len(name) == 1 else None)
            if qt is not None:
                mods = (Qt.ControlModifier if k.get("ctrl") else Qt.NoModifier) | (Qt.AltModifier if k.get("alt") else Qt.NoModifier)
                self.clip_key(iv(qt), mods, " " if name == "space" else (name if len(name) == 1 else ""))
            return
        if k.get("ctrl") or k.get("alt"):
            # a Ctrl / Alt combination was taken from the popup too (nothing typed may change it): run it through the
            # same handler as a key typed into the overlay, so the bindings (Ctrl+Space, Ctrl+N, Ctrl+1, ...) work
            qt = PASSIVE_KEYS.get(name) or (QKeySequence(name.upper())[0].key() if len(name) == 1 else None)
            if qt is not None:
                mods = (Qt.ControlModifier if k.get("ctrl") else Qt.NoModifier) | (Qt.AltModifier if k.get("alt") else Qt.NoModifier) \
                    | (Qt.ShiftModifier if k.get("shift") else Qt.NoModifier)
                self.eventFilter(self.edit, QKeyEvent(QEvent.KeyPress, qt, mods, name if len(name) == 1 else ""))
                self.eventFilter(self.edit, QKeyEvent(QEvent.KeyRelease, qt, mods, ""))
            return
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
            self.space_tapped()
        elif name == "Escape":  # only the first of two Esc presses arrives here: the daemon closes on the second
            self.close_pressed()
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
        if self.t.hide_panel_until_typing or not self.panel_shown():
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
        if self.panel_override is not None:
            return self.panel_override
        return not (self.t.hide_panel_until_typing and not self.edit.text())

    def toggle_panel(self):
        """The hide/show key: hide the search panel (labels and typing keep working) or bring it back. The choice is
        remembered (see `initial_panel_override`) so it stays the same on the next opens and in the other overlay."""
        self.panel_override = not self.panel_shown()
        if self.cfg["ui"].get("remember_panel", True):
            write_state(panel_hidden=not self.panel_override)
        self.sync_field()
        self.update()

    def initial_panel_override(self):
        """Whether the panel starts forced hidden (False), forced shown (True) or by the default rule (None). A choice
        made with the hide/show key wins over the "open with the panel hidden" setting, when remembering is on."""
        start_hidden = bool(self.cfg["ui"].get("start_hidden"))
        saved = read_state().get("panel_hidden") if self.cfg["ui"].get("remember_panel", True) else None
        if saved is None:
            return False if start_hidden else None
        if saved:
            return False
        return True if start_hidden else None

    def space_tapped(self):
        """Space was pressed and released on its own. When it is bound to hide/show the panel it does that - but only
        while the panel is hidden or the search is empty, so a space can still be typed into a query ("new folder")."""
        if self.keymap.match(Qt.Key_Space, Qt.NoModifier) == "toggle_panel" and (not self.panel_shown() or not self.edit.text()):
            self.toggle_panel()
        else:
            self.edit.insert(" ")

    def close_pressed(self):
        """The close key (Esc by default). With double Esc on, the first press only warns and the second one within
        DOUBLE_ESC_S closes; the mouse modes step back first (grid -> pointer movement -> search) as before."""
        if self.mouse == "grid":
            self.enter_move()  # leaving the grid hands the pointer over to H J K L, no Ctrl+M needed
            return
        if self.mouse == "move":
            self.leave_mouse(remember=True)
            return
        now = time.monotonic()
        if not self.cfg["behavior"].get("double_esc_close", True) or now - self.esc_at <= DOUBLE_ESC_S:
            self.esc_at = 0.0
            self.dismiss()
            return
        self.esc_at = now
        self.show_flash("Press Esc again to close vimvibe")

    def show_flash(self, text):
        """Draw a short message on the overlay (it clears itself)."""
        self.flash = text
        self.flash_timer.start(FLASH_MS)
        self.update()

    def clear_flash(self):
        """The message ran out."""
        self.flash = ""
        self.update()

    def open_in_mode(self):
        """Choose what vimvibe opens in: the mode used last when [mouse] remember_mode is on, else [mouse] open_in."""
        mc = self.cfg["mouse"]
        mode = read_state().get("mode") if mc.get("remember_mode") else mc.get("open_in")
        if mode in ("grid", "move"):
            self.grid_scope = mc.get("scope", "window")
            self.enter_grid() if mode == "grid" else self.enter_move()

    def sync_field(self):
        """The search field is a real widget over the panel: make its text invisible while the panel is hidden."""
        color = self.t.panel_text.name() if self.panel_shown() and self.clip is None else "transparent"
        self.edit.setStyleSheet(f"background: transparent; color: {color};")
        self.set_placeholder()

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
        self.sync_field()
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

    def enter_tap(self, run):
        """A plain Enter: with `[behavior] double_tap_ms` > 0 it waits that long for a second Enter. Once more within the
        time is a double click, like the mouse; otherwise the single click goes out when the time is up. `run(action)`
        performs the click ("click" or "double") on the target chosen now, so moving the selection while waiting
        changes nothing. Other click keys (right, middle) never wait. An Enter held down (key repeat) counts once."""
        wait = int(self.cfg["behavior"].get("double_tap_ms", 250))
        if wait <= 0:
            run("click")
        elif self.enter_pending is not None:  # second Enter in time
            pending, self.enter_pending = self.enter_pending, None
            self.enter_timer.stop()
            pending("double")
        else:
            self.enter_pending = run
            self.enter_timer.start(wait)

    def enter_fire(self):
        """The wait for a second Enter ran out: do the single click."""
        pending, self.enter_pending = self.enter_pending, None
        if pending is not None:
            pending("click")

    def enter_cancel(self):
        """Forget a waiting Enter (the overlay is closing or being dismissed)."""
        self.enter_timer.stop()
        self.enter_pending = None

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
        self.enter_cancel()
        self.end_scroll(refresh=False)
        self.leave_mouse()
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
            # the old labels are wrong once the content has moved: draw nothing until the new ones arrive, then show
            # them all at once (never the stale ones, never a staggered fade-in)
            self.refreshing = True
            self.labels_on = False
            self.update()
            QTimer.singleShot(4000, self.stop_refreshing)
            self.daemon.asyncCall("Refresh")

    def stop_refreshing(self):
        """Safety net: the re-read never answered (window closed, error), so draw normally again."""
        if self.refreshing:
            self.refreshing = False
            self.update()

    def scroll_key(self, k, shift, direction=None):
        """Space + D / U (or a given `direction`): scroll; Shift scrolls four times as far."""
        dx, dy = direction or SCROLL_LETTERS.get(k, (0, 0))
        if not (dx or dy):
            return False
        if not self.scrolling and not self.start_scroll():
            return True
        sc = self.cfg["scroll"]
        # distance is in wheel notches; the daemon takes tenths of a notch and glides through them
        step = round(max(0.1, float(sc.get("distance", 1.0))) * 10 * (max(1, int(sc.get("fast", 4))) if shift else 1))
        self.send("Scroll", dx * step, dy * step)
        return True

    def edge_key(self, direction):
        """Space + g g (top, -1) / Space + Shift+G (bottom, 1): one long glide that the app stops at the end of its content."""
        if not self.scrolling and not self.start_scroll():
            return True
        self.send("ScrollEdge", direction)
        return True

    def space_chord(self, k, ctrl, alt, shift, repeat=False):
        """A key pressed while Space is held. D / U scroll; g g and Shift+G jump to the top and bottom (like Vimium). H J K L (or I J K L) do what [scroll] hjkl says — scroll by
        default, arrow keys when set to "arrows" — and Ctrl swaps to the other action (Alt always means arrow keys, as
        a modifier for them). Returns whether the key was used."""
        if k in SCROLL_LETTERS and not ctrl and not alt:
            return self.scroll_key(k, shift)
        if k == Qt.Key_G and not ctrl and not alt and self.cfg["scroll"].get("edge_keys", True):
            if repeat:
                return True
            if shift:
                return self.edge_key(1)
            now = time.monotonic()
            if now - self.last_g < GG_S:
                self.last_g = 0.0
                return self.edge_key(-1)
            self.last_g = now
            return True
        direction = SCROLL_KEYS.get(self.cfg["scroll"].get("keys", "hjkl"), SCROLL_KEYS["hjkl"]).get(k)
        if not direction:
            return False
        arrows = (self.cfg["scroll"].get("hjkl", "scroll") == "arrows") != ctrl or alt
        return self.arrow_key(k, shift, ctrl) if arrows else self.scroll_key(k, shift, direction)

    def arrow_key(self, k, shift, ctrl=False):
        """Space + a direction key (`ctrl`: the Ctrl chord that swaps the action): hand the keyboard back to the app and let the daemon send arrow keys (it takes the
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
            return self.scroll_key(k, shift, (dx, dy))
        # hide first so the app gets the keyboard back, then let the daemon take over without blocking this window
        self.arrowing = True
        self.labels_on = False
        self.hide()
        # entered with Ctrl held: that Ctrl would turn the first arrow into Ctrl+arrow, so only switch the mode on
        # (the next H J K L presses are plain arrows)
        first = (0, 0) if ctrl else (dx, dy)
        watcher = QDBusPendingCallWatcher(self.daemon.asyncCallWithArgumentList("ArrowStart", list(first)), self)
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

    # --- keyboard mouse: zooming grid and H J K L pointer movement -----------------------
    def mouse_enabled(self):
        """The mouse features are on in Settings, and this overlay can take keys (a passive one over a popup can't)."""
        return bool(self.cfg["mouse"].get("enabled", True)) and not self.passive

    def enter_grid(self):
        """Show the grid over the target window (or the whole screen, per the scope) and start taking its keys."""
        if not self.mouse_enabled() or self.origin is None:
            return
        self.stop_move()
        mc = self.cfg["mouse"]
        screen = QRectF(self.rect())
        bounds, o = screen, self.meta.get("origin")
        if self.grid_scope == "window" and o and o[2] > 0:
            win = QRectF(o[0] - self.origin[0], o[1] - self.origin[1], o[2], o[3]).intersected(screen)
            if win.width() >= 60 and win.height() >= 60:
                bounds = win
        self.grid = Grid((bounds.x(), bounds.y(), bounds.width(), bounds.height()),
                         number(mc.get("cols"), 5, 2, 26), number(mc.get("rows"), 5, 2, 26),
                         str(mc.get("alphabet", "")), number(mc.get("max_depth"), 4, 1, 10))
        self.mouse = "grid"
        write_state(mode="grid")
        self.update()

    def enter_move(self):
        """H J K L pointer movement, starting from where the pointer is (or the grid's centre when coming from the grid).
        The overlay stops taking pointer input so what is under the pointer reacts (hover) as it moves."""
        if not self.mouse_enabled():
            return
        if self.grid:
            cx, cy = self.grid.center()
            res = self.call("PointerAct", cx + self.origin[0], cy + self.origin[1], False, "goto")
        else:
            res = self.call("PointerMotion", 0.0, 0.0)  # checks the permission before the mode starts
        if not res or not res.get("ok"):
            notify("vimvibe can't move the pointer", (res or {}).get("error", "the daemon did not answer"))
            return
        self.grid = None
        self.mouse = "move"
        write_state(mode="move")
        self.held, self.move_rem = [], [0.0, 0.0]
        self.windowHandle().setFlag(Qt.WindowTransparentForInput, True)
        self.update()

    def stop_move(self):
        """Stop moving the pointer (keys released, mode left)."""
        self.move_timer.stop()
        self.held = []

    def leave_mouse(self, remember=False):
        """Back to the search (Esc in the movement mode, the mode key again), or the end of the mouse mode when the
        overlay closes. `remember` records "search" as the last mode (only for a deliberate step back, not for cleanup)."""
        self.mspace_down = False
        if self.mouse is None:
            return
        if self.mouse == "edit":  # the daemon's edit mode may still run (Esc / I end it there and arrive here)
            self.send("EditEnd")
            self.edit_visual = False
        if remember:
            write_state(mode="search")
        self.stop_move()
        self.mouse, self.grid = None, None
        if self.windowHandle():
            self.windowHandle().setFlag(Qt.WindowTransparentForInput, False)
        self.update()

    # --- clipboard: copy / paste keys, text selection with the pointer, the history picker ---------------------
    def clip_enabled(self):
        """Whether the clipboard features are on ([clipboard] enabled)."""
        return bool(self.cfg.get("clipboard", {}).get("enabled", True))

    def copy_text(self):
        """Copy the selected result's text (its name) to the clipboard; the overlay stays open."""
        hit = self.hits[self.sel] if self.hits else None
        text = ((hit or {}).get("element") or {}).get("name", "")
        if not text:
            self.show_flash("Nothing to copy")
            return
        vimvibe_clip.set_text(text)
        self.show_flash("Copied: " + vimvibe_clip.one_line(text, 40))

    def paste_into(self):
        """Click the selected result (that focuses a text field) and then paste the clipboard into it. The click runs
        first; the paste waits until the app has taken the keyboard back."""
        if not self.hits:
            return
        self.act("click")
        QTimer.singleShot(400, lambda: self.sent_keys(self.call("SendKeys", "ctrl+v"), "paste"))

    def send_keys(self, combo, what):
        """Press `combo` in the app below. The overlay hides itself first: it has the keyboard, and a blocking D-Bus
        call would not let it process the daemon's "closed" signal until the keys were already sent to it."""
        self.hide()
        QTimer.singleShot(60, lambda: self.sent_keys(self.call("SendKeys", combo), what))

    def sent_keys(self, res, what):
        """Answer to SendKeys: tell the user when it failed (no keyboard permission)."""
        if not res or not res.get("ok"):
            notify(f"vimvibe can't {what}", (res or {}).get("error", "the daemon did not answer"))

    def enter_edit(self):
        """Edit mode (Vimium-like): the daemon takes H J K L, U / D, V, Y, P and Esc / I system-wide and turns them into
        arrow keys, Home / End, selecting, Ctrl+C and Ctrl+V in the app. This overlay holds the keyboard, so it hides and
        the passive layer overlay (which never takes the keyboard) shows the banner until the mode ends and the daemon
        closes everything."""
        res = self.call("EditStart")
        if not res or not res.get("ok"):
            notify("vimvibe can't start edit mode", (res or {}).get("error", "the daemon did not answer"))
            return
        if not self.on_edit or not self.on_edit(self.meta):
            self.send("EditEnd")
            notify("vimvibe can't start edit mode", "it needs the layer-shell overlay, which isn't available here")
            return
        self.stop_move()
        self.leave_mouse()
        self.hide()

    def begin_edit(self, meta):
        """(Passive overlay) show the edit mode banner over the screen of the window `meta` describes, letting the
        pointer and the keyboard through."""
        self.meta = meta
        self.place_screen()
        self.grid, self.mouse, self.edit_visual = None, "edit", False
        self.edit.hide()
        self.show()
        self.windowHandle().setFlag(Qt.WindowTransparentForInput, True)
        self.update()

    def edit_visual_changed(self, visual):
        """Daemon signal: edit mode started / ended selecting (the banner says so)."""
        self.edit_visual = bool(visual)
        self.update()

    def edit_text(self):
        """Banner for edit mode."""
        sel = "SELECTING — H J K L extend · Y copy · V stop" if self.edit_visual else "[V] select · [Y] copy · [P] paste"
        return f"Edit mode — [H J K L] arrows · [Shift+J K] page · [Shift+H L] word · [U D] Home End · {sel} · [Esc] or [I] exit"

    def open_clip(self):
        """Open the clipboard history picker (newest first); Esc closes it, Enter pastes the chosen entry."""
        items = vimvibe_clip.history()
        if not items:
            self.show_flash("The clipboard history is empty")
            return
        self.clip = {"all": items, "filter": "", "sel": 0, "top": 0}
        self.sync_field()
        self.update()

    def clip_items(self):
        """The picker's entries that contain what was typed (case-insensitive)."""
        f = self.clip["filter"].lower()
        return [t for t in self.clip["all"] if f in t.lower()]

    def clip_key(self, key, mods, text):
        """A key pressed while the picker is open (everything is consumed): move, filter by typing, Enter / Ctrl+digit
        pastes the entry, Esc closes the picker."""
        c, items, rows = self.clip, self.clip_items(), self.t.rows
        mods = iv(mods)
        action = self.keymap.match(key, mods)
        if key == iv(Qt.Key_Escape) or action == "clip_history":
            self.clip = None
            self.sync_field()
        elif key in (iv(Qt.Key_Return), iv(Qt.Key_Enter)):
            self.clip_choose(c["sel"])
        elif isinstance(action, tuple):  # Ctrl+1..9: paste that visible row
            self.clip_choose(c["top"] + action[1])
        elif action in ("next", "prev", "page_down", "page_up") and items:
            step = {"next": 1, "prev": -1, "page_down": rows, "page_up": -rows}[action]
            c["sel"] = (c["sel"] + step) % len(items)
            c["top"] = min(c["top"], c["sel"]) if c["sel"] < c["top"] else max(c["top"], c["sel"] - rows + 1)
        elif key == iv(Qt.Key_Backspace):
            c["filter"], c["sel"], c["top"] = c["filter"][:-1], 0, 0
        elif text and text.isprintable() and not mods & (iv(Qt.ControlModifier) | iv(Qt.AltModifier) | iv(Qt.MetaModifier)):
            c["filter"], c["sel"], c["top"] = c["filter"] + text, 0, 0
        self.update()
        return True

    def clip_choose(self, row):
        """Paste picker entry `row`: put it on the clipboard, then press Ctrl+V in the app (this closes vimvibe)."""
        items = self.clip_items()
        if not 0 <= row < len(items):
            return
        vimvibe_clip.set_text(items[row])
        self.clip = None
        self.send_keys("ctrl+v", "paste")

    def mouse_commit(self, action):
        """Click (or just leave the pointer) at the grid's centre, or where H J K L put it. With [mouse] stay_after_click
        (the default) the mouse mode carries on afterwards; otherwise the overlay closes."""
        if self.mouse == "grid":
            cx, cy = self.grid.center()
            where = (cx + self.origin[0], cy + self.origin[1], False)
        else:
            where = (0.0, 0.0, True)
        if self.cfg["mouse"].get("stay_after_click", True):
            self.windowHandle().setFlag(Qt.WindowTransparentForInput, True)  # the click must reach the app, not this window
            QTimer.singleShot(50, lambda: self.mouse_stay_done(self.call("PointerAct", *where, "stay:" + action)))
            return
        self.leave_mouse()
        self.hide()
        QTimer.singleShot(60, lambda: self.mouse_done(self.call("PointerAct", *where, action)))

    def mouse_stay_done(self, res):
        """The click of a mouse mode that stays open went out: report errors; the grid starts over from the whole
        region for the next target (the movement mode just continues). The app was activated by the click, which the
        deactivation handler answers by taking the keyboard back."""
        self.mouse_done(res)
        if self.mouse == "grid":
            self.enter_grid()
            self.windowHandle().setFlag(Qt.WindowTransparentForInput, False)

    def event(self, ev):
        """While a mouse mode is active, losing the keyboard (a click in the app below activates it) is answered by
        taking it back, so the mode keeps working without interruption."""
        if ev.type() == QEvent.WindowDeactivate and self.mouse in ("grid", "move") and self.isVisible():
            self.stop_move()  # the key releases of held direction keys will go to the app: don't keep drifting
            QTimer.singleShot(80, self.regrab_keyboard)
        return super().event(ev)

    def regrab_keyboard(self):
        """Take the keyboard back after the app below was clicked (the click activated that window) by asking to be
        activated again, with no hiding or flicker. Only while a mouse mode is still active and the overlay isn't."""
        now = time.monotonic()
        if now - self.last_regrab < 1.0:  # never loop if the compositor won't give the keyboard back
            return
        if self.mouse in ("grid", "move") and self.isVisible() and not self.isActiveWindow():
            self.last_regrab = now
            self.windowHandle().requestActivate()  # asking again is enough: the overlay never leaves the screen
            self.activateWindow()
            self.edit.setFocus()

    def jump_input(self):
        """Ctrl+I in every mode (labels, grid, pointer movement): show only the window's text fields (the query "field");
        pressed again, select the next one (Enter focuses it and starts typing; Esc brings vimvibe back). Like Vimium's
        gi. From a mouse mode the fields are looked up first: when there are some the mode is left for the field list;
        when the app exposes none (nothing to label), it falls back to clicking where the pointer is and typing there."""
        if self.mouse:
            found = (self.call("Search", "field") or {}).get("hits", [])
            if not found:
                self.mouse_insert()
                return
            self.leave_mouse()
        if self.edit.text().strip().lower() != "field":
            self.edit.setText("field")
            if not self.hits:
                self.show_flash("No text fields found")
        else:
            self.move_sel(1)

    def mouse_insert(self):
        """Pointer movement: click where the pointer is (that focuses a text field under it) and let the user type; the
        daemon takes Esc until then and opens vimvibe again. In the grid it clicks the grid's middle."""
        if self.mouse == "grid":
            cx, cy = self.grid.center()
            where = (cx + self.origin[0], cy + self.origin[1], False)
        else:
            where = (0.0, 0.0, True)
        self.leave_mouse()
        self.hide()
        QTimer.singleShot(60, lambda: self.insert_after_click(self.call("PointerAct", *where, "click")))

    def insert_after_click(self, res):
        """The click for insert mode went out: start insert mode (Esc comes back here)."""
        self.mouse_done(res)
        if res and res.get("ok"):
            ins = self.call("InsertStart")
            if not ins or not ins.get("ok"):
                notify("vimvibe can't return after typing", (ins or {}).get("error", "the daemon did not answer"))

    def mouse_done(self, res):
        """Answer to PointerAct: tell the user when it failed (no permission, feature off)."""
        if res and not res.get("ok"):
            print("pointer action failed:", res.get("error"), file=sys.stderr, flush=True)
            notify("vimvibe could not use the pointer", res.get("error", ""))

    def move_tick(self):
        """Every few ms while a direction key is held: send the distance travelled since the last tick (whole pixels,
        the remainder carries over). Speed grows the longer the key is held; Shift is faster, Alt precise."""
        now = time.monotonic()
        dt, self.move_last = min(now - self.move_last, 0.05), now
        dx, dy = sum(d[0] for d in self.held), sum(d[1] for d in self.held)
        if not (dx or dy):
            return
        mc = self.cfg["mouse"]
        speed = number(mc.get("speed"), 500, 50, 6000)
        if mc.get("accelerate", True):
            speed *= 1 + 3 * min(1.0, (now - self.move_since) / 0.8)
        if self.move_mods & iv(Qt.ShiftModifier):
            speed *= number(mc.get("fast"), 3, 1, 20)
        elif self.move_mods & iv(Qt.AltModifier):
            speed *= 0.25
        n = math.hypot(dx, dy)
        self.move_rem[0] += dx / n * speed * dt
        self.move_rem[1] += dy / n * speed * dt
        ix, iy = int(self.move_rem[0]), int(self.move_rem[1])
        self.move_rem[0] -= ix
        self.move_rem[1] -= iy
        if ix or iy:
            self.send("PointerMotion", float(ix), float(iy))

    def mouse_scroll(self, direction, fast):
        """An arrow key / Page Up / Page Down (or D / U) in the grid or movement mode: scroll what is under the pointer, without
        leaving the mode. In the grid the pointer first goes to the grid's middle (that is what will scroll); in the
        movement mode it is already where it should be. The overlay lets the wheel through for a moment."""
        sc = self.cfg["scroll"]
        step = round(max(0.1, float(sc.get("distance", 1.0))) * 10 * (max(1, int(sc.get("fast", 4))) if fast else 1))
        if self.grid:
            cx, cy = self.grid.center()
            where = (cx + self.origin[0], cy + self.origin[1], False)
        else:
            where = (0.0, 0.0, True)
        # click-through first: the wheel events must not find this window under the pointer (the grid takes input)
        self.windowHandle().setFlag(Qt.WindowTransparentForInput, True)
        res = self.call("PointerScroll", direction[0] * step, direction[1] * step, *where)
        if not res or not res.get("ok"):
            notify("vimvibe can't scroll here", (res or {}).get("error", "the daemon did not answer"))
            self.mouse_scroll_done()
            return True
        self.scroll_timer.start(700)
        return True

    def mouse_scroll_done(self):
        """The glide is over: the grid takes pointer input again (the movement mode never gives it up)."""
        if self.mouse != "move" and self.windowHandle():
            self.windowHandle().setFlag(Qt.WindowTransparentForInput, False)

    def mouse_event(self, ev):
        """A key event while the grid or pointer movement is active. Everything is consumed here, so nothing leaks into
        the search field; Esc goes back to the search."""
        if self.mouse == "edit":  # edit mode: the app has the keyboard, the daemon takes the keys
            return True
        k, t = iv(ev.key()), ev.type()
        mods = self.move_mods = iv(ev.modifiers())
        if k in (iv(Qt.Key_Control), iv(Qt.Key_Alt), iv(Qt.Key_Shift), iv(Qt.Key_Meta)):
            return True
        direction = SCROLL_KEYS.get(self.cfg["mouse"].get("keys", "hjkl"), SCROLL_KEYS["hjkl"]).get(k)
        space_place = k == iv(Qt.Key_Space) and self.keymap.match(Qt.Key_Space, Qt.NoModifier, mouse=True) == "mouse_place"
        if t == QEvent.KeyRelease:
            if space_place and not ev.isAutoRepeat() and self.mspace_down:
                self.mspace_down = False
                if not self.mspace_used:  # a plain Space tap leaves the pointer here (a chord was a scroll)
                    self.mouse_commit("move")
                return True
            if self.mouse == "move" and direction in self.held and not ev.isAutoRepeat():
                self.held.remove(direction)
                if not self.held:
                    self.move_timer.stop()
            return True
        if space_place:  # decided on release: tap = place the pointer, hold + H J K L / D U = scroll
            if not ev.isAutoRepeat():
                self.mspace_down, self.mspace_used = True, False
            return True
        if self.mspace_down and direction:  # Space + H J K L: scroll ← ↓ ↑ → (the overlay stays); [scroll] hjkl = "arrows" sends real arrows
            self.mspace_used = True
            if self.cfg["scroll"].get("hjkl", "scroll") == "arrows":
                self.resume_mouse = self.mouse  # real arrow keys hide the overlay; it comes back in this mode when Space is let go
                if not self.arrow_key(k, bool(mods & iv(Qt.ShiftModifier))):
                    self.resume_mouse = None
                return True
            return self.mouse_scroll(direction, bool(mods & iv(Qt.ShiftModifier)))
        if self.mspace_down and k in SCROLL_LETTERS:  # Space + D / U: scroll up / down (wheel)
            self.mspace_used = True
            return self.mouse_scroll(SCROLL_LETTERS[k], bool(mods & iv(Qt.ShiftModifier)))
        # the arrow keys / Page Up / Page Down (and D / U in the movement mode) scroll without leaving the mode; key
        # repeat keeps the glide going. Never with Ctrl held: the app would see Ctrl + wheel and zoom the page instead.
        held_mod = mods & (iv(Qt.ControlModifier) | iv(Qt.AltModifier) | iv(Qt.MetaModifier))
        scroll = None if held_mod else MOUSE_SCROLL_KEYS.get(k)
        if scroll is None and self.mouse == "move" and not held_mod:
            scroll = SCROLL_LETTERS.get(k)
        if scroll:
            return self.mouse_scroll(scroll, bool(mods & iv(Qt.ShiftModifier)) or k in (iv(Qt.Key_PageUp), iv(Qt.Key_PageDown)))
        action = self.keymap.match(ev.key(), ev.modifiers(), mouse=True)
        click = {"click": "click", "right_click": "right", "double_click": "double", "middle_click": "middle"}.get(action)
        if action == "close":
            self.close_pressed()
        elif action == "mouse_grid":
            self.leave_mouse(remember=True) if self.mouse == "grid" else self.enter_grid()
        elif action == "mouse_move":
            self.leave_mouse(remember=True) if self.mouse == "move" else self.enter_move()
        elif action == "mouse_place":
            self.mouse_commit("move")
        elif action == "clip_history" and self.clip_enabled():
            self.open_clip()
        elif action == "edit_mode":
            self.enter_edit()
        elif action == "jump_input":
            self.jump_input()
        elif click:
            if click == "click":
                if not ev.isAutoRepeat():
                    self.enter_tap(self.mouse_commit)
            else:
                self.mouse_commit(click)
        elif self.mouse == "grid":
            if action == "mouse_back":
                if self.grid.back():
                    self.update()
            elif action == "mouse_scope":
                self.grid_scope = "screen" if self.grid_scope == "window" else "window"
                self.enter_grid()
            elif len(ev.text()) == 1 and not iv(ev.modifiers()) & (iv(Qt.ControlModifier) | iv(Qt.AltModifier) | iv(Qt.MetaModifier)):
                if self.grid.type(ev.text()):
                    self.update()
        elif direction and not ev.isAutoRepeat():  # movement: the direction is held until its key is released
            if direction not in self.held:
                if not self.held:
                    self.move_since = self.move_last = time.monotonic()
                self.held.append(direction)
            self.move_timer.start()
        return True

    def eventFilter(self, obj, ev):
        """Keys typed into the search field: Esc, Enter variants, Ctrl+digit, navigation, Space-scrolling, Settings,
        and modifier taps."""
        if obj is not self.edit:
            return super().eventFilter(obj, ev)
        # Order matters: keyboard-mouse mode swallows everything first; then modifier-only presses (for taps); then
        # rebindable actions, Space handling (a held Space turns H J K L into scrolling), result rows, and finally
        # the key release side (end of Space / end of a modifier tap).
        t = ev.type()
        if self.clip is not None and t in (QEvent.KeyPress, QEvent.KeyRelease):  # the picker takes every key
            return self.clip_key(ev.key(), ev.modifiers(), ev.text()) if t == QEvent.KeyPress else True
        if self.mouse and t in (QEvent.KeyPress, QEvent.KeyRelease):
            return self.mouse_event(ev)
        if t == QEvent.KeyPress:
            k, mods = ev.key(), ev.modifiers()
            ctrl, alt, shift = bool(mods & Qt.ControlModifier), bool(mods & Qt.AltModifier), bool(mods & Qt.ShiftModifier)
            if iv(k) in (iv(Qt.Key_Control), iv(Qt.Key_Alt), iv(Qt.Key_Shift)):
                if not ev.isAutoRepeat():
                    self.tap = {iv(k): ev.timestamp()} if self.keymap.tapped_action(k) else {}
                return False
            self.tap = {}  # another key: the modifier was used as a modifier, not tapped
            action = self.keymap.match(k, mods)
            if action in ("mouse_grid", "mouse_move"):
                if not ev.isAutoRepeat():
                    self.enter_grid() if action == "mouse_grid" else self.enter_move()
                return True
            if action == "toggle_panel" and not (k == Qt.Key_Space and not ctrl and not alt):  # Ctrl+Space and the like act at once
                if not ev.isAutoRepeat():
                    self.toggle_panel()
                return True
            if k == Qt.Key_Space and not alt:
                if not ev.isAutoRepeat():
                    self.space_down, self.space_used = True, False
                return True  # typed on release, unless it was used to scroll
            if self.space_down:
                if self.space_chord(k, ctrl, alt, shift, ev.isAutoRepeat()):
                    self.space_used = True
                    return True
            if isinstance(action, tuple):  # a result row: Ctrl+1..9 acts on it, Ctrl+Shift+1..9 only selects it
                row = self.top + action[1]
                if row < len(self.hits):
                    if action[0] == "row_select":
                        self.move_sel(0, absolute=row)
                    else:
                        self.act("click", row=row)
                return True
            if action == "close":
                self.close_pressed(); return True
            if action == "settings":
                self.dismiss()
                if self.on_settings:
                    self.on_settings()
                return True
            click = {"click": "click", "right_click": "right", "double_click": "double", "middle_click": "middle"}.get(action)
            if click:
                if click == "click" and not ev.isAutoRepeat():
                    if self.hits and 0 <= self.sel < len(self.hits):  # the target is fixed now, not when the wait ends
                        eid = self.hits[self.sel]["id"]
                        self.enter_tap(lambda a, eid=eid: self.act(a, eid=eid))
                elif click != "click":
                    self.act(click)
                return True
            if action == "refresh":
                self.daemon.asyncCall("Refresh"); return True
            if action == "edit_mode":
                self.enter_edit(); return True
            if action == "jump_input":
                self.jump_input(); return True
            if self.clip_enabled() and action in ("copy_text", "paste_into", "clip_history"):
                {"copy_text": self.copy_text, "paste_into": self.paste_into, "clip_history": self.open_clip}[action](); return True
            step = {"next": 1, "prev": -1, "page_down": self.t.rows, "page_up": -self.t.rows}.get(action)
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
                    self.space_tapped()  # a plain Space tap: hide/show the panel, or type a space
            return True
        elif t == QEvent.KeyRelease and iv(ev.key()) in (iv(Qt.Key_Control), iv(Qt.Key_Alt), iv(Qt.Key_Shift)) and not ev.isAutoRepeat():
            k = iv(ev.key())
            pressed = self.tap.pop(k, None)
            if pressed is not None and ev.timestamp() - pressed <= TAP_MS:
                tapped = self.keymap.tapped_action(k)
                if tapped == "tap_labels":
                    self.show_all_labels()
                elif tapped == "tap_hover" and self.hits:
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
        if self.mouse == "grid":  # click a cell to zoom into it, right click zooms out
            if (self.grid.back() if right else self.grid.zoom_to((p.x(), p.y()))):
                self.update()
            return
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
        self.paint_content(p)
        if self.flash:  # a short message ("Press Esc again to close") above everything else
            self.banner(p, self.flash, self.panel if self.panel_shown() else None)

    def paint_content(self, p):
        """The mode-specific drawing: scroll banner, grid, pointer-movement banner, or labels + panel."""
        if self.t.dim and not self.scrolling and self.mouse is None:
            p.fillRect(self.rect(), QColor(0, 0, 0, int(255 * self.t.dim / 100)))
        if self.clip is not None:
            self.paint_clip(p)
            return
        if self.scrolling:
            self.paint_scroll_banner(p)
            return
        if self.refreshing:
            return
        if self.mouse == "edit":
            self.banner(p, self.edit_text(), None)
            return
        if self.mouse == "grid":
            self.paint_grid(p)
            return
        if self.mouse == "move":
            self.banner(p, self.move_text(), None)
            return
        self.paint_selected(p)
        self.paint_labels(p)
        if self.panel_shown():
            self.paint_panel(p)

    def paint_clip(self, p):
        """The clipboard history picker: a box in the middle with what was typed to filter, then the visible entries
        (numbered for Ctrl+digit), the chosen one highlighted."""
        t, c = self.t, self.clip
        items = self.clip_items()
        fm = QFontMetricsF(t.row_font)
        w = min(self.width() - 40, t.panel_width)
        h = 40 + t.row_h * max(1, min(t.rows, len(items))) + 30
        r = QRectF((self.width() - w) / 2, max(30.0, (self.height() - h) / 3), w, h)
        path = QPainterPath(); path.addRoundedRect(r, 12, 12)
        p.fillPath(path, t.panel_bg)
        p.setPen(QPen(t.accent, 2)); p.drawPath(path)
        p.setFont(t.small_font); p.setPen(t.panel_dim)
        p.drawText(QRectF(r.x() + 14, r.y() + 8, w - 28, 24), Qt.AlignVCenter,
                   "Clipboard history — " + (c["filter"] + "▏" if c["filter"] else "type to filter") + "   ·   Enter paste · Esc back")
        for i, text in enumerate(items[c["top"]:c["top"] + t.rows]):
            row = QRectF(r.x() + 8, r.y() + 36 + i * t.row_h, w - 16, t.row_h)
            chosen = c["top"] + i == c["sel"]
            if chosen:
                rp = QPainterPath(); rp.addRoundedRect(row, 6, 6); p.fillPath(rp, t.selected)
            p.setFont(t.row_font); p.setPen(t.selected_fg if chosen else t.panel_text)
            p.drawText(row.adjusted(10, 0, -10, 0), Qt.AlignVCenter,
                       f"{i + 1}  " + fm.elidedText(vimvibe_clip.one_line(text), Qt.ElideRight, int(w - 70)))
        if not items:
            p.setFont(t.row_font); p.setPen(t.panel_dim)
            p.drawText(QRectF(r.x() + 18, r.y() + 36, w - 36, t.row_h), Qt.AlignVCenter, "No entry matches")

    def paint_scroll_banner(self, p):
        """While scrolling: a small banner instead of labels and panel (they would be stale)."""
        edge = " · G G top · Shift+G bottom" if self.cfg["scroll"].get("edge_keys", True) else ""
        self.banner(p, f"Scrolling — hold Space, {' '.join(self.cfg['scroll'].get('keys', 'hjkl').upper())} or D / U (Shift: faster){edge} · release Space for new labels", None)

    def key_text(self, *parts):
        """Banner text from (action, what it does) pairs, skipping the unbound ones: "[Enter] click · [Esc] back"."""
        return " · ".join(f"[{self.keymap.label(a)}] {what}" for a, what in parts if self.keymap.label(a))

    def move_text(self):
        """Banner for move mode: the configured movement keys plus the rebindable click/grid/back keys."""
        keys = " ".join(self.cfg["mouse"].get("keys", "hjkl").upper())
        return f"Mouse — [{keys}] move · [Shift] faster · [Alt] precise · [↑ ↓ ← →] scroll · [Space+H J K L] scroll · " + self.key_text(
            ("click", "click"), ("right_click", "right click"), ("mouse_place", "stay here"), ("mouse_grid", "grid"), ("close", "back")) \
            + " · " + self.key_text(("edit_mode", "edit mode"), ("clip_history", "clipboard history"))

    def grid_text(self):
        """Banner for grid mode; the hint depends on whether another zoom level exists and which scope Ctrl+Shift+G switches to."""
        g = self.grid
        zoom = "type a cell's two letters" if g.can_zoom() else "deepest level"
        scope = "screen" if self.grid_scope == "window" else "window"
        return f"Grid — {zoom} · [↑ ↓ ← →] scroll · [Space+H J K L] scroll · " + self.key_text(
            ("mouse_back", "zoom out"), ("click", "click"), ("right_click", "right click"), ("mouse_place", "stay here"),
            ("mouse_move", "H J K L"), ("mouse_scope", scope), ("close", "pointer movement"))

    def banner(self, p, text, avoid):
        """A one-line message in a pill at the top of the screen (the bottom when `avoid` would be covered)."""
        p.setFont(self.t.small_font)
        w = min(self.width() - 40, QFontMetricsF(self.t.small_font).horizontalAdvance(text) + 32)
        r = QRectF((self.width() - w) / 2, 24, w, 34)
        if avoid is not None and r.intersects(avoid):
            r.moveBottom(self.height() - 24)
        path = QPainterPath(); path.addRoundedRect(r, 10, 10)
        p.fillPath(path, self.t.panel_bg)
        p.setPen(QPen(self.t.accent, 2)); p.drawPath(path)
        p.setPen(self.t.panel_text); p.drawText(r, Qt.AlignCenter, text)

    def paint_grid(self, p):
        """The mouse grid: everything outside the region dimmed, the region divided into labelled cells (after the first
        letter only that row keeps its labels), a cross at the middle where the pointer will go."""
        g, t = self.grid, self.t
        x, y, w, h = g.region
        region = QRectF(x, y, w, h)
        outside = QPainterPath(); outside.addRect(QRectF(self.rect()))
        inner = QPainterPath(); inner.addRect(region)
        p.fillPath(outside.subtracted(inner), QColor(0, 0, 0, 120))
        tint = QColor(t.accent); tint.setAlpha(28)
        p.fillRect(region, tint)
        line = QColor(t.accent); line.setAlpha(190)
        p.setPen(QPen(line, 1))
        for c in range(1, g.cols):
            p.drawLine(QPointF(x + w * c / g.cols, y), QPointF(x + w * c / g.cols, y + h))
        for r in range(1, g.rows):
            p.drawLine(QPointF(x, y + h * r / g.rows), QPointF(x + w, y + h * r / g.rows))
        p.setPen(QPen(t.accent, 2)); p.setBrush(Qt.NoBrush); p.drawRect(region)
        cx, cy = g.center()
        arm = min(14.0, w / 2, h / 2)
        for pen in (QPen(QColor(0, 0, 0, 200), 4), QPen(QColor(255, 255, 255), 2)):
            p.setPen(pen)
            p.drawLine(QPointF(cx - arm, cy), QPointF(cx + arm, cy)); p.drawLine(QPointF(cx, cy - arm), QPointF(cx, cy + arm))
        if g.can_zoom():
            for r in range(g.rows):
                for c in range(g.cols):
                    label = g.label(r, c)
                    if g.pending and not label.startswith(g.pending):
                        continue
                    lw, lh = t.label_size(label)
                    cell = QRectF(*g.cell(r, c))
                    if cell.width() >= lw + 4 and cell.height() >= lh + 2:
                        t.draw_label(p, QRectF(cell.center().x() - lw / 2, cell.center().y() - lh / 2, lw, lh), label, len(g.pending))
        self.banner(p, self.grid_text(), region)

    def paint_selected(self, p):
        """Filled highlight around the selected result's element."""
        if not self.hits or not self.edit.text():  # nothing typed: no element is "chosen" yet, so none is highlighted
            return
        r = self.rects.get(self.hits[self.sel]["id"])
        if r:
            big = r.width() * r.height() > 0.25 * self.width() * self.height()  # a huge link / image: outline only
            fill = QColor(self.t.selected); fill.setAlpha(0 if big else 80)
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
        # layout, top to bottom: rounded panel -> search field frame -> hint line -> result rows -> footer line
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
            keys, km = self.cfg["scroll"].get("keys", "hjkl").upper(), self.keymap
            hint = [f"[{km.label('click') or 'Enter'}] click"]
            if km.label("tap_labels"):
                hint.append(f"tap [{km.label('tap_labels')}] all labels")
            hint += [f"[Space+{keys}] scroll", f"[Space+Ctrl+{keys}] arrows"]
            if km.label("toggle_panel"):
                hint.append(f"[{km.label('toggle_panel')}] hide panel")
            if self.mouse_enabled() and km.label("mouse_grid"):
                hint.append(f"[{km.label('mouse_grid')}] mouse grid")
            if km.label("settings"):
                hint.append(f"[{km.label('settings')}] settings")
            p.drawText(QRectF(pr.x() + PAD + 4, pr.y() + PAD + 44, pr.width() - 2 * PAD, 22), Qt.AlignVCenter,
                       QFontMetricsF(t.small_font).elidedText(" · ".join(hint), Qt.ElideRight, int(pr.width() - 2 * PAD - 8)))
        fm = QFontMetricsF(t.row_font)
        sfm = QFontMetricsF(t.small_font)
        for i in range(min(t.rows, len(self.hits) - self.top)):
            idx = self.top + i
            h = self.hits[idx]; e = h["element"]
            rr = self.row_rect(i)
            if idx == self.sel:
                sp = QPainterPath(); sp.addRoundedRect(rr.adjusted(0, 1, 0, -1), 7, 7)
                c = QColor(t.selected); c.setAlpha(75); p.fillPath(sp, c)
            # right to left inside a row: Ctrl+n key caps, then the letter label, then the role, then the name
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
        self.normal.on_edit = self.start_edit
        self._passive = None
        self.current = self.normal
        self.settings = None

    def passive(self):
        """The passive overlay, created the first time a popup needs it."""
        if self._passive is None:
            self._passive = Overlay(self.daemon, self.accent, passive=True)
            self._passive.on_settings = self.open_settings
        return self._passive

    def start_edit(self, meta):
        """Edit mode began: show its banner in the passive overlay. False when layer-shell isn't available."""
        p = self.passive()
        if not p.passive:
            return False
        self.current = p
        p.begin_edit(meta)
        return True

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

    @Slot(bool)
    def edit_mode(self, visual):
        """Daemon signal: edit mode started / ended selecting."""
        for o in (self.normal, self._passive):
            if o is not None:
                o.edit_visual_changed(visual)

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


def transfer_settings(export_path, import_path):
    """`--export FILE` / `--import FILE`: copy the settings to or from JSON (the launcher's `vimvibe export|import`).
    Returns the process exit code."""
    from vimvibe_style import export_settings, import_settings
    try:
        if export_path:
            import shutil, subprocess
            core = os.environ.get("VIMVIBE_CORE") or shutil.which("vimvibe-core") or ""
            version = subprocess.run([core, "--version"], capture_output=True, text=True).stdout.strip() if core else ""
            export_settings(export_path, version)
            print(f"settings exported to {export_path}")
        else:
            import_settings(import_path)
            print(f"settings imported from {import_path} (launch at login is only changed from the Settings window)")
        return 0
    except (OSError, ValueError) as e:
        print(f"vimvibe: {e}", file=sys.stderr)
        return 1


def main():
    """Entry point: the Settings window with --settings, otherwise the resident overlay connected to the daemon."""
    ap = argparse.ArgumentParser(description="vimvibe overlay (keep running) or, with --settings, its Settings window")
    ap.add_argument("--settings", action="store_true", help="open the Settings window")
    ap.add_argument("--export", metavar="FILE", help="write every setting to a JSON file and exit")
    ap.add_argument("--import", dest="import_file", metavar="FILE", help="replace the settings with an exported JSON file and exit")
    ap.add_argument("--accent", help=f"label/highlight colour for this run (default {DEFAULT_ACCENT})")
    ap.add_argument("--trigger", action="store_true", help="ask the daemon to open the overlay once (testing)")
    ap.add_argument("--query", default="", help="with --trigger: type this into the search field (testing)")
    ap.add_argument("--quit-after", type=int, default=0, help="exit after N seconds (testing)")
    ap.add_argument("--snapshot", help="after opening, save an image of this overlay window only (testing)")
    a = ap.parse_args()
    if a.export or a.import_file:  # settings transfer needs no window
        sys.exit(transfer_settings(a.export, a.import_file))
    app = QApplication(sys.argv)
    app.setApplicationName("vimvibe")
    if icon_path():
        app.setWindowIcon(QIcon(icon_path()))
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
              bus.connect(SERVICE, PATH, IFACE, "EditMode", router, "1edit_mode(bool)"),
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
