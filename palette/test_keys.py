"""Tests for the key bindings: `QT_QPA_PLATFORM=offscreen python3 -m unittest palette/test_keys.py` (from the repo root,
or `python3 -m unittest test_keys` inside palette/)."""
import os, sys, unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import Qt

import vimvibe_keys as K

NONE = 0


class KeyTests(unittest.TestCase):
    def test_parse_round_trip(self):
        """A key combination survives parse -> text -> parse."""
        for text in ("Ctrl+Space", "Return", "Ctrl+,", "Ctrl+Shift+,", "Shift+Tab", "Alt+Return", "F5", "Ctrl++"):
            parsed = K.parse_key(text)
            self.assertIsNotNone(parsed, text)
            self.assertEqual(K.parse_key(K.format_key(*parsed)), parsed, text)

    def test_unreadable(self):
        """Text that is not a key combination parses to nothing instead of raising."""
        for text in ("", "Ctrl", "Ctrl+", "Hyper+Q", "Ctrl+Shift"):
            self.assertIsNone(K.parse_key(text), text)

    def test_defaults_resolve_without_problems(self):
        """The built-in bindings are valid and conflict-free."""
        m = K.KeyMap(None)
        self.assertEqual(m.problems, [])
        self.assertEqual(m.match(Qt.Key_Space, Qt.ControlModifier), "toggle_panel")
        self.assertEqual(m.match(Qt.Key_Enter, Qt.KeypadModifier), "click")  # keypad Enter, keypad flag ignored
        self.assertEqual(m.match(Qt.Key_Backtab, Qt.ShiftModifier), "prev")
        self.assertEqual(m.match(Qt.Key_Less, Qt.ControlModifier | Qt.ShiftModifier), "settings")
        self.assertEqual(m.match(Qt.Key_3, Qt.ControlModifier), ("row_act", 2))
        self.assertEqual(m.match(Qt.Key_NumberSign, Qt.ControlModifier | Qt.ShiftModifier), ("row_select", 2))
        self.assertIsNone(m.match(Qt.Key_A, Qt.NoModifier))

    def test_user_bindings_replace_defaults(self):
        """A [keys] entry replaces the default for that action; an empty list unbinds it."""
        m = K.KeyMap({"toggle_panel": ["Ctrl+H"], "close": [], "tap_hover": []})
        self.assertEqual(m.match(Qt.Key_H, Qt.ControlModifier), "toggle_panel")
        self.assertIsNone(m.match(Qt.Key_Space, Qt.ControlModifier))
        self.assertIsNone(m.match(Qt.Key_Escape, Qt.NoModifier))
        self.assertNotIn("tap_hover", m.tap)
        self.assertEqual(m.label("close"), "")

    def test_bad_values_are_reported_not_fatal(self):
        """Unreadable or unusable bindings are collected in `problems` (no exception) and bind nothing."""
        m = K.KeyMap({"click": ["Nonsense+Q"], "tap_hover": ["Meta"], "row_act": ["Q"]})
        self.assertEqual(len(m.problems), 3)
        self.assertEqual(m.match(Qt.Key_Return, Qt.NoModifier), None)

    def test_conflicts_and_typing_keys(self):
        """Two actions on one key, or an action on a plain typing key, are flagged."""
        self.assertEqual(K.conflicts(None), {})
        self.assertEqual(list(K.conflicts({"next": ["Return"]}).values()), [["click", "next"]])
        self.assertTrue(K.is_plain_text_key(*K.parse_key("a")))
        # Space hides the panel in the search and leaves the pointer in the mouse modes: not a clash
        self.assertEqual(K.conflicts(None), {})
        self.assertEqual(K.DEFAULTS["toggle_panel"][0], "Space")
        self.assertFalse(K.is_plain_text_key(*K.parse_key("Ctrl+A")))
        self.assertFalse(K.is_plain_text_key(*K.parse_key("Return")))


if __name__ == "__main__":
    unittest.main()
