"""Tests for the keyboard-mouse grid (run: cd palette && python3 -m unittest test_mouse)."""
import unittest

from vimvibe_mouse import Grid, clean_alphabet


class GridTests(unittest.TestCase):
    def test_labels_are_row_then_column(self):
        g = Grid((0, 0, 500, 500))
        names = [n for n, _ in g.cells()]
        self.assertEqual(names[:6], ["aa", "ab", "ac", "ad", "ae", "ba"])
        self.assertEqual(len(names), 25)
        self.assertEqual(g.cell(1, 2), (200.0, 100.0, 100.0, 100.0))

    def test_typing_zooms_recursively(self):
        g = Grid((100, 50, 500, 500))
        self.assertEqual(g.type("b"), "pending")
        self.assertEqual(g.type("C"), "zoom")  # case-insensitive
        self.assertEqual(g.region, (300.0, 150.0, 100.0, 100.0))
        self.assertEqual(g.depth, 1)
        g.type("a"); g.type("a")
        self.assertEqual(g.region, (300.0, 150.0, 20.0, 20.0))
        self.assertEqual(g.center(), (310.0, 160.0))

    def test_unknown_letters_are_ignored_and_back_undoes(self):
        g = Grid((0, 0, 500, 500))
        self.assertIsNone(g.type("z"))      # no row z in a 5×5 grid
        g.type("a")
        self.assertIsNone(g.type("z"))      # no column z either
        self.assertTrue(g.back())           # pending letter dropped
        self.assertEqual(g.pending, "")
        self.assertFalse(g.back())          # nothing to undo at the top
        g.type("c"); g.type("c")
        self.assertTrue(g.back())
        self.assertEqual(g.region, (0.0, 0.0, 500.0, 500.0))

    def test_depth_and_size_limits(self):
        g = Grid((0, 0, 500, 500), max_depth=2)
        for ch in "aaaa":
            g.type(ch)
        self.assertFalse(g.can_zoom())
        self.assertIsNone(g.type("a"))
        small = Grid((0, 0, 20, 20))        # 4 px cells: too small to divide
        self.assertFalse(small.can_zoom())

    def test_click_zoom(self):
        g = Grid((0, 0, 500, 500))
        self.assertTrue(g.zoom_to((450, 10)))
        self.assertEqual(g.region, (400.0, 0.0, 100.0, 100.0))
        self.assertFalse(g.zoom_to((10, 10)))

    def test_alphabet_and_size_are_sanitised(self):
        self.assertEqual(clean_alphabet("AASDF!", 2), "asdf")
        self.assertEqual(clean_alphabet("a", 2), "abcdefghijklmnopqrstuvwxyz")
        g = Grid((0, 0, 400, 400), cols=9, rows=9, alphabet="asdf")
        self.assertEqual((g.cols, g.rows), (4, 4))
        self.assertEqual(g.label(3, 3), "ff")


if __name__ == "__main__":
    unittest.main()
