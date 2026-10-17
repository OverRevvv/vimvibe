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
        for text in ("Ctrl+Space", "Return", "Ctrl+,", "Ctrl+Shift+,", "Shift+Tab", "Alt+Return", "F5", "Ctrl++"):
            parsed = K.parse_key(text)
            self.assertIsNotNone(parsed, text)
            self.assertEqual(K.parse_key(K.format_key(*parsed)), parsed, text)

    def test_unreadable(self):
        for text in ("", "Ctrl", "Ctrl+", "Hyper+Q", "Ctrl+Shift"):
            self.assertIsNone(K.parse_key(text), text)

    def test_defaults_resolve_without_problems(self):
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
        m = K.KeyMap({"toggle_panel": ["Ctrl+H"], "close": [], "tap_hover": []})
        self.assertEqual(m.match(Qt.Key_H, Qt.ControlModifier), "toggle_panel")
        self.assertIsNone(m.match(Qt.Key_Space, Qt.ControlModifier))
        self.assertIsNone(m.match(Qt.Key_Escape, Qt.NoModifier))
        self.assertNotIn("tap_hover", m.tap)
        self.assertEqual(m.label("close"), "")

    def test_bad_values_are_reported_not_fatal(self):
        m = K.KeyMap({"click": ["Nonsense+Q"], "tap_hover": ["Meta"], "row_act": ["Q"]})
        self.assertEqual(len(m.problems), 3)
        self.assertEqual(m.match(Qt.Key_Return, Qt.NoModifier), None)

    def test_conflicts_and_typing_keys(self):
        self.assertEqual(K.conflicts(None), {})
        self.assertEqual(list(K.conflicts({"next": ["Return"]}).values()), [["click", "next"]])
        self.assertTrue(K.is_plain_text_key(*K.parse_key("a")))
        self.assertFalse(K.is_plain_text_key(*K.parse_key("Ctrl+A")))
        self.assertFalse(K.is_plain_text_key(*K.parse_key("Return")))


if __name__ == "__main__":
    unittest.main()
