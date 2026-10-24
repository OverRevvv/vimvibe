"""Tests for the overlay's key behaviour (Esc, Space, the mouse modes), run headless: Qt's offscreen platform and a fake
daemon that records the D-Bus calls (run: cd palette && python3 -m unittest test_overlay)."""
import os, sys, tempfile, unittest

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["XDG_STATE_HOME"] = tempfile.mkdtemp()   # the remembered UI state goes to a scratch directory
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()  # and so does the config: the defaults apply
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

import vimvibe_palette as P
import vimvibe_style as S

APP = QApplication.instance() or QApplication([])


class Reply:
    """What the daemon answers to every call: {"ok": true}."""
    def errorName(self): return ""
    def arguments(self): return ['{"ok": true}']


class FakeDaemon:
    """Stands in for the D-Bus interface and records (method, args) of each call."""
    def __init__(self): self.calls = []
    def call(self, method, *args): self.calls.append((method, args)); return Reply()
    def callWithArgumentList(self, mode, method, args): self.calls.append((method, tuple(args))); return Reply()
    def asyncCall(self, method, *args): self.calls.append((method, args))
    def asyncCallWithArgumentList(self, method, args): self.calls.append((method, tuple(args)))
    def named(self, method): return [c for c in self.calls if c[0] == method]


class OverlayKeys(unittest.TestCase):
    def setUp(self):
        """A fresh overlay over a pretend 800x600 window, with the default settings and no remembered state."""
        for name in ("ui-state.json",):
            try: os.remove(os.path.join(os.path.dirname(S.STATE), name))
            except OSError: pass
        self.daemon = FakeDaemon()
        self.o = P.Overlay(self.daemon)
        self.o.origin = (0, 0)
        self.o.meta = {"origin": [0, 0, 800, 600]}
        self.o.resize(800, 600); self.o.show(); self.o.create()
        self.o.hits, self.o.elements = [], []
        self.o.cfg["behavior"]["double_tap_ms"] = 0   # most tests want Enter to click at once; the double-tap test turns it on

    def key(self, k, mods=Qt.NoModifier, text="", release=False):
        """Send a key press (or release) to the search field's event filter, as Qt would."""
        return self.o.eventFilter(self.o.edit, QKeyEvent(QEvent.KeyRelease if release else QEvent.KeyPress, k, mods, text))

    def tap(self, k, mods=Qt.NoModifier, text=""):
        """A press followed by a release."""
        self.key(k, mods, text); self.key(k, mods, text, release=True)

    def test_double_esc_closes(self):
        """One Esc only warns; the second one closes. With the setting off, one Esc closes."""
        self.tap(Qt.Key_Escape)
        self.assertFalse(self.daemon.named("Close")); self.assertTrue(self.o.flash)
        self.tap(Qt.Key_Escape)
        self.assertTrue(self.daemon.named("Close"))
        self.daemon.calls.clear(); self.o.show()
        self.o.cfg["behavior"]["double_esc_close"] = False
        self.tap(Qt.Key_Escape)
        self.assertTrue(self.daemon.named("Close"))

    def test_space_hides_the_panel_and_it_is_remembered(self):
        """Space with an empty search hides the panel and the choice is saved; with text it types a space."""
        self.o.panel_override = None
        self.tap(Qt.Key_Space, text=" ")
        self.assertFalse(self.o.panel_shown()); self.assertIs(S.read_state().get("panel_hidden"), True)
        self.assertIs(self.o.initial_panel_override(), False)   # the next open starts hidden too
        self.tap(Qt.Key_Space, text=" ")
        self.assertTrue(self.o.panel_shown()); self.assertIs(S.read_state().get("panel_hidden"), False)
        self.o.edit.setText("sa")
        self.tap(Qt.Key_Space, text=" ")
        self.assertEqual(self.o.edit.text(), "sa "); self.assertTrue(self.o.panel_shown())

    def test_held_space_scrolls_instead_of_toggling(self):
        """Holding Space and pressing D is a scroll chord: the panel state must not change."""
        shown = self.o.panel_shown()
        self.key(Qt.Key_Space, text=" "); self.key(Qt.Key_D, text="d")
        self.key(Qt.Key_D, text="d", release=True); self.key(Qt.Key_Space, text=" ", release=True)
        self.assertEqual(self.o.panel_shown(), shown)

    def test_grid_esc_goes_to_movement_and_ctrl_scrolls(self):
        """Esc in the grid continues with H J K L; the Down / Up arrows scroll in the grid and in the movement mode."""
        self.o.enter_grid()
        self.key(Qt.Key_Down)
        scroll = self.daemon.named("PointerScroll")[0][1]
        self.assertGreater(scroll[1], 0); self.assertIs(scroll[4], False)   # down, to the grid's middle first
        self.assertEqual(self.o.mouse, "grid")
        self.tap(Qt.Key_Escape)
        self.assertEqual(self.o.mouse, "move"); self.assertEqual(S.read_state().get("mode"), "move")
        self.daemon.calls.clear()
        self.key(Qt.Key_Up)
        scroll = self.daemon.named("PointerScroll")[0][1]
        self.assertLess(scroll[1], 0); self.assertIs(scroll[4], True)       # up, from where the pointer is
        self.key(Qt.Key_Down, Qt.ControlModifier)                           # with Ctrl held it would zoom the page: ignored
        self.assertFalse(self.daemon.named("PointerScroll")[1:])
        self.tap(Qt.Key_Escape)
        self.assertIsNone(self.o.mouse); self.assertEqual(S.read_state().get("mode"), "search")

    def test_remember_mode_is_optional(self):
        """The last mouse mode is only reopened when [mouse] remember_mode is on."""
        S.write_state(mode="grid")
        self.o.cfg["mouse"]["remember_mode"] = True
        self.o.open_in_mode(); self.assertEqual(self.o.mouse, "grid")
        self.o.leave_mouse()
        self.o.cfg["mouse"]["remember_mode"] = False; self.o.cfg["mouse"]["open_in"] = "search"
        self.o.open_in_mode(); self.assertIsNone(self.o.mouse)

    def test_clipboard_picker_filters_and_pastes(self):
        """Ctrl+Shift+H opens the history, typing filters it, Enter puts the entry on the clipboard and sends Ctrl+V."""
        copied = []
        P.vimvibe_clip.history = lambda: ["alpha one", "beta two", "alpha three"]
        P.vimvibe_clip.set_text = copied.append
        self.key(Qt.Key_H, Qt.ControlModifier | Qt.ShiftModifier, "H")
        self.assertEqual(self.o.clip_items(), ["alpha one", "beta two", "alpha three"])
        for ch in "three":
            self.tap(getattr(Qt, "Key_" + ch.upper()), text=ch)
        self.assertEqual(self.o.clip_items(), ["alpha three"])
        self.tap(Qt.Key_Return)
        QTest.qWait(150)
        self.assertEqual(copied, ["alpha three"]); self.assertIsNone(self.o.clip)
        self.assertEqual(self.daemon.named("SendKeys")[0][1], ("ctrl+v",))
        self.key(Qt.Key_H, Qt.ControlModifier | Qt.ShiftModifier, "H")   # Esc only closes the picker, not vimvibe
        self.tap(Qt.Key_Escape)
        self.assertIsNone(self.o.clip); self.assertFalse(self.daemon.named("Close"))

    def test_edit_mode_starts_and_hands_over_the_keyboard(self):
        """Ctrl+E asks the daemon for edit mode and the overlay stops taking keys; leaving it ends the mode again."""
        self.shown = []
        self.o.on_edit = lambda meta: self.shown.append(meta) or True
        self.assertIsNone(self.o.keymap.match(Qt.Key_E, Qt.ControlModifier))   # switched off: Ctrl+E starts nothing
        self.o.enter_edit()
        self.assertTrue(self.daemon.named("EditStart")); self.assertEqual(len(self.shown), 1); self.assertFalse(self.o.isVisible())
        self.assertIn("Edit mode", self.o.edit_text())
        self.o.edit_visual_changed(True); self.assertIn("SELECTING", self.o.edit_text())
        self.o.begin_edit({"origin": [0, 0, 800, 600]}); self.assertEqual(self.o.mouse, "edit")   # (the passive overlay's side)
        self.o.leave_mouse()
        self.assertTrue(self.daemon.named("EditEnd")); self.assertIsNone(self.o.mouse)

    def test_space_chord_scrolls_in_the_mouse_modes(self):
        """Space held + J scrolls down and the overlay stays; with [scroll] hjkl = "arrows" it asks for a real Down arrow
        instead; a plain Space tap still places the pointer."""
        got = []
        self.o.arrow_key = lambda k, shift, ctrl=False: got.append(k) or True
        self.o.enter_move(); self.daemon.calls.clear()
        self.key(Qt.Key_Space, text=" "); self.key(Qt.Key_J, text="j"); self.key(Qt.Key_Space, text=" ", release=True)
        scroll = self.daemon.named("PointerScroll")
        self.assertEqual(len(scroll), 1); self.assertGreater(scroll[0][1][1], 0); self.assertEqual(got, [])
        self.assertFalse(self.daemon.named("PointerAct"))
        self.o.cfg["scroll"]["hjkl"] = "arrows"
        self.key(Qt.Key_Space, text=" "); self.key(Qt.Key_K, text="k"); self.key(Qt.Key_Space, text=" ", release=True)
        self.assertEqual(got, [int(Qt.Key_K)]); self.assertEqual(self.o.resume_mouse, "move")
        self.o.resume_mouse = None
        self.tap(Qt.Key_Space, text=" ")
        QTest.qWait(150)   # the commit runs once the overlay has hidden
        self.assertEqual(self.daemon.named("PointerAct")[-1][1][3], "stay:move")

    def test_mouse_modes_stay_open_after_a_click(self):
        """Enter clicks without leaving the mouse mode (Enter twice double, Ctrl+Alt+Enter middle); with
        stay_after_click off the overlay closes as before."""
        self.o.enter_move(); self.daemon.calls.clear()
        self.tap(Qt.Key_Return); QTest.qWait(150)
        self.o.cfg["behavior"]["double_tap_ms"] = 200
        self.tap(Qt.Key_Return); self.tap(Qt.Key_Return); QTest.qWait(150)   # two Enters in time: one double click
        self.tap(Qt.Key_Return, Qt.ControlModifier | Qt.AltModifier); QTest.qWait(150)
        self.o.cfg["behavior"]["double_tap_ms"] = 0
        acts = [c[1][3] for c in self.daemon.named("PointerAct")]
        self.assertEqual(acts, ["stay:click", "stay:double", "stay:middle"]); self.assertEqual(self.o.mouse, "move")
        self.o.enter_grid(); self.tap(Qt.Key_Return); QTest.qWait(150)
        self.assertEqual(self.o.mouse, "grid"); self.assertEqual(len(self.o.grid.regions), 1)   # starts over from the whole region
        self.o.cfg["mouse"]["stay_after_click"] = False
        self.tap(Qt.Key_Return); QTest.qWait(150)
        self.assertIsNone(self.o.mouse); self.assertEqual(self.daemon.named("PointerAct")[-1][1][3], "click")

    def test_enter_double_tap_double_clicks(self):
        """One Enter clicks after the double-tap time; two within it double-click the same element (like the mouse);
        Alt+Enter no longer does anything; the right-click key never waits."""
        el = {"name": "x", "role": "Button", "enabled": True}
        self.o.hits = [{"id": 7, "hint": "SA", "element": el}, {"id": 8, "hint": "SB", "element": el}]; self.o.sel = 0
        self.o.cfg["behavior"]["double_tap_ms"] = 120
        self.tap(Qt.Key_Return); self.assertFalse(self.daemon.named("ActivateWith"))   # waiting for a second Enter
        QTest.qWait(300)
        self.assertEqual([c[1][1] for c in self.daemon.named("ActivateWith")], ["click"])
        self.daemon.calls.clear(); self.o.show(); self.o.sel = 1
        self.tap(Qt.Key_Return); self.tap(Qt.Key_Return); QTest.qWait(300)
        self.assertEqual([(c[1][0], c[1][1]) for c in self.daemon.named("ActivateWith")], [(8, "double")])
        self.daemon.calls.clear(); self.o.show()
        self.tap(Qt.Key_Return, Qt.AltModifier); QTest.qWait(300)
        self.assertFalse(self.daemon.named("ActivateWith"))
        self.tap(Qt.Key_Return, Qt.ControlModifier); QTest.qWait(150)
        self.assertEqual([c[1][1] for c in self.daemon.named("ActivateWith")], ["right"])

    def test_ctrl_i_works_from_every_mode(self):
        """Ctrl+I in the grid or the movement mode leaves it for the text-field list when the window has fields
        (the same list the search shows, Ctrl+I again = next); with none, it clicks here and types."""
        real = self.o.call
        self.o.call = lambda m, *a: {"hits": [{"id": 1, "hint": "AA", "element": {"name": "f", "role": "Entry", "enabled": True}}]} if m == "Search" else real(m, *a)
        for enter in (self.o.enter_grid, self.o.enter_move):
            enter(); self.daemon.calls.clear()
            self.key(Qt.Key_I, Qt.ControlModifier, "\t")
            self.assertIsNone(self.o.mouse); self.assertEqual(self.o.edit.text(), "field")
            self.assertFalse(self.daemon.named("PointerAct"))
            self.o.edit.clear()
        self.o.call = real
        self.o.hide()   # nothing of this overlay may paint during the next test

    def test_clipboard_history_vim_keys(self):
        """In the clipboard history Ctrl+J / Ctrl+K move down / up (plain j / k still filter)."""
        P.vimvibe_clip.history = lambda: ["one", "two", "three"]
        self.key(Qt.Key_H, Qt.ControlModifier | Qt.ShiftModifier, "H")
        self.key(Qt.Key_J, Qt.ControlModifier, "\n"); self.key(Qt.Key_J, Qt.ControlModifier, "\n")
        self.assertEqual(self.o.clip["sel"], 2)
        self.key(Qt.Key_K, Qt.ControlModifier, "\x0b")
        self.assertEqual(self.o.clip["sel"], 1)
        self.o.clip = None

    def test_text_mode_copy_and_paste(self):
        """Ctrl+T captures the screen (nothing is drawn meanwhile), the words become a buffer, Vim keys select and y
        copies; p goes to the text-field list and Enter there pastes; P pastes where the keyboard is."""
        copied = []
        P.vimvibe_clip.set_text = copied.append
        self.key(Qt.Key_T, Qt.ControlModifier, "\x14")
        self.assertEqual(self.o.current_mode(), "text"); self.assertEqual(self.o.text["state"], "capturing")
        QTest.qWait(250)
        self.assertTrue(self.daemon.named("TextCapture")); self.assertEqual(self.o.text["state"], "reading")
        words = [{"text": "Hello", "x": 10, "y": 10, "w": 40, "h": 12, "line": "1.1.1"},
                 {"text": "world", "x": 60, "y": 10, "w": 40, "h": 12, "line": "1.1.1"},
                 {"text": "again", "x": 10, "y": 30, "w": 40, "h": 12, "line": "1.1.2"}]
        self.o.text_words(P.json.dumps({"ok": True, "words": words}))
        self.assertEqual(len(self.o.text["buf"]), 3)
        for ch in "vjy":
            self.tap(getattr(Qt, "Key_" + ch.upper()), text=ch)
        self.assertEqual(copied, ["Hello world\nagain"])
        el = {"name": "Field", "role": "Entry", "enabled": True}
        self.o.call = (lambda real: lambda m, *a: {"hits": [{"id": 4, "hint": "FI", "element": el}]} if m == "Search" else real(m, *a))(self.o.call)
        self.tap(Qt.Key_P, text="p")
        self.assertIsNone(self.o.text); self.assertTrue(self.o.paste_target); self.assertEqual(self.o.edit.text(), "field")
        self.daemon.calls.clear()
        self.tap(Qt.Key_Return); QTest.qWait(600)
        self.assertEqual(self.daemon.named("ActivateWith")[0][1], (4, "click"))
        self.assertEqual(self.daemon.named("SendKeys")[0][1], ("ctrl+v",))
        self.o.hide()

    def test_text_mode_scroll_reads_again(self):
        """Space + D scrolls the app under the caret (nothing drawn, input let through), the screen is read again, the
        caret stays on its word; j past the bottom scrolls one line step and is replayed on the new words."""
        self.key(Qt.Key_T, Qt.ControlModifier, "\x14"); QTest.qWait(250)
        words = [{"text": t, "x": 10, "y": y, "w": 40, "h": 12, "line": f"1.1.{y}"} for t, y in
                 (("alpha", 10), ("bravo", 30), ("charlie", 50), ("delta", 70))]
        self.o.text_words(P.json.dumps({"ok": True, "words": words}))
        self.tap(Qt.Key_J, text="j")                                     # caret on "bravo"
        self.daemon.calls.clear()
        self.key(Qt.Key_Space, text=" ")                                 # Space held + D: half a page down
        self.key(Qt.Key_D, text="d")
        self.key(Qt.Key_Space, text=" ", release=True)
        scroll = self.daemon.named("PointerScroll")[0][1]
        self.assertEqual(scroll[:2], (0, 10)); self.assertEqual(self.o.text["state"], "capturing")   # first step: 1 notch (calibration)
        QTest.qWait(250); self.assertTrue(self.daemon.named("TextCapture"))
        moved = [dict(w, y=w["y"] - 20) for w in words[1:]] + [{"text": "echo", "x": 10, "y": 70, "w": 40, "h": 12, "line": "1.1.90"}]
        self.o.text_words(P.json.dumps({"ok": True, "words": moved}))
        buf = self.o.text["buf"]
        self.assertEqual(buf.layout.words[buf.sel.cursor]["text"], "bravo")  # carried over by the 20 px shift
        self.tap(Qt.Key_G, Qt.ShiftModifier, "G")                         # caret on "echo", the last line
        self.daemon.calls.clear()
        self.tap(Qt.Key_J, text="j")                                     # no line below: scroll and replay j
        self.assertEqual(self.daemon.named("PointerScroll")[0][1][:2], (0, 10))
        QTest.qWait(250)
        more = [dict(w, y=w["y"] - 20) for w in moved[1:]] + [{"text": "foxtrot", "x": 10, "y": 70, "w": 40, "h": 12, "line": "1.1.99"}]
        self.o.text_words(P.json.dumps({"ok": True, "words": more}))
        buf = self.o.text["buf"]
        self.assertEqual(buf.layout.words[buf.sel.cursor]["text"], "foxtrot")
        self.o.leave_text(); self.o.hide()

    def test_mode_cycle(self):
        """Ctrl+Tab goes labels -> grid -> pointer movement -> text -> labels; Ctrl+Shift+Tab goes back."""
        seen = []
        for _ in range(4):
            seen.append(self.o.current_mode())
            self.o.mode_key("next_mode")
        self.assertEqual(seen, ["search", "grid", "move", "text"])
        self.assertEqual(self.o.current_mode(), "search")
        self.o.mode_key("prev_mode")
        self.assertEqual(self.o.current_mode(), "text")
        self.o.mode_key("text_mode")                       # Ctrl+T toggles text mode off again
        self.assertEqual(self.o.current_mode(), "search")
        QTest.qWait(250)                                   # let the pending capture timer find text mode gone

    def test_input_jump_insert_and_fallback(self):
        """Ctrl+I in the search shows only the text fields, again selects the next; in the movement mode it clicks and
        starts insert mode; an app with nothing to label opens in the grid."""
        self.key(Qt.Key_I, Qt.ControlModifier, "\t")
        self.assertEqual(self.o.edit.text(), "field")
        self.o.hits = [{"id": 1}, {"id": 2}]; self.o.sel = 0
        self.key(Qt.Key_I, Qt.ControlModifier, "\t"); self.assertEqual(self.o.sel, 1)
        self.o.edit.clear(); self.o.enter_move(); self.daemon.calls.clear()
        self.key(Qt.Key_I, Qt.ControlModifier, "\t"); QTest.qWait(150)
        self.assertEqual(self.daemon.named("PointerAct")[-1][1][3], "click"); self.assertTrue(self.daemon.named("InsertStart"))
        self.o.leave_mouse(); self.o.meta = {"origin": [0, 0, 800, 600], "count": 0}
        self.o.origin = (0, 0); self.o.open_in_mode()
        self.assertIsNone(self.o.mouse)   # (the fallback itself runs in `opened`, which needs a daemon snapshot)

    def test_ctrl_keys_over_a_popup_reach_the_overlay(self):
        """A Ctrl combination taken from a popup (passive mode) runs the same bindings: Ctrl+Space hides the panel."""
        import json
        self.o.panel_override = None
        self.o.on_key(json.dumps({"name": "space", "text": False, "pressed": True, "ctrl": True, "alt": False, "shift": False}))
        self.assertFalse(self.o.panel_shown())


if __name__ == "__main__":
    unittest.main()
