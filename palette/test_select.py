"""Tests for the copy-mode selection model (run: cd palette && python3 -m unittest test_select)."""
import unittest

from vimvibe_select import Layout, Selection, parse_count


def word(text, x, y, w=None, h=12, line=None):
    """A word box like the OCR or accessible-text readers produce."""
    d = {"text": text, "x": x, "y": y, "w": w or 8 * len(text), "h": h}
    if line is not None:
        d["line"] = line
    return d


# three lines of text, given out of order on purpose; the second line sits 2 px lower on its last word (uneven baseline)
PAGE = [
    word("world", 60, 10), word("Hello", 0, 10),
    word("second", 0, 30), word("line", 60, 30), word("here", 100, 32),
    word("third", 0, 50), word("and", 50, 50), word("last", 90, 50),
]


class LayoutTests(unittest.TestCase):
    def test_reading_order_and_lines(self):
        """Words are sorted top to bottom, left to right, and grouped into lines despite uneven baselines."""
        lay = Layout(PAGE)
        self.assertEqual([w["text"] for w in lay.words], ["Hello", "world", "second", "line", "here", "third", "and", "last"])
        self.assertEqual(lay.lines, [[0, 1], [2, 3, 4], [5, 6, 7]])
        self.assertEqual(lay.line_of[4], 1)

    def test_line_keys_win_over_positions(self):
        """With "line" keys (tesseract's numbers), words group by key even if their boxes do not overlap."""
        lay = Layout([word("a", 0, 0, line=(1, 1, 1)), word("b", 20, 9, line=(1, 1, 1)), word("c", 0, 40, line=(1, 1, 2))])
        self.assertEqual(lay.lines, [[0, 1], [2]])

    def test_blank_words_are_dropped(self):
        """Empty or whitespace-only words are not selectable."""
        self.assertEqual(len(Layout([word(" ", 0, 0), word("x", 10, 0)])), 1)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        """A selection over PAGE, starting on "world"."""
        self.s = Selection(Layout(PAGE), start=1)

    def test_word_motions_cross_lines(self):
        """w / b move word by word, also over line ends; counts repeat a motion."""
        self.s.move("w"); self.assertEqual(self.s.text(), "world\nsecond")
        self.s.move("w", 2); self.assertEqual(self.s.cursor, 4)
        self.s.move("b", 10); self.assertEqual(self.s.cursor, 0)  # clamped at the first word

    def test_vertical_motions_keep_the_column(self):
        """j / k go to the word nearest the same column, and remember it through lines."""
        s = Selection(Layout(PAGE), start=1)          # "world", centre x 80
        s.move("j"); self.assertEqual(s.layout.words[s.cursor]["text"], "line")
        s.move("j"); self.assertEqual(s.layout.words[s.cursor]["text"], "and")    # centre 62 is nearer 80 than "last" (106)
        s.move("k", 2); self.assertEqual(s.cursor, 1)
        self.assertTrue(s.move("k"))                  # no line above: stays
        self.assertEqual(s.cursor, 1)

    def test_line_edges_and_document_edges(self):
        """0 / $ go to the start / end of the line, gg / G to the first / last word."""
        s = Selection(Layout(PAGE), start=3)
        s.move("$"); self.assertEqual(s.cursor, 4)
        s.move("0"); self.assertEqual(s.cursor, 2)
        s.move("G"); self.assertEqual(s.cursor, 7)
        s.move("gg"); self.assertEqual(s.cursor, 0)

    def test_backwards_selection_and_jump(self):
        """A cursor before the anchor selects backwards; jump() moves only the cursor (the second label)."""
        s = Selection(Layout(PAGE), start=6)
        s.jump(3)
        self.assertEqual(s.range(), (3, 6))
        self.assertEqual(s.text(), "line here\nthird and")
        self.assertEqual(s.text(join_lines="space"), "line here third and")

    def test_line_mode(self):
        """Line mode (Vim's V) widens the selection to whole lines; toggling again goes back to words."""
        s = Selection(Layout(PAGE), start=3)
        self.assertEqual(s.toggle_line_mode(), "line")
        s.move("j")
        self.assertEqual(s.text(), "second line here\nthird and last")
        s.toggle_line_mode()
        self.assertEqual(s.range(), (3, 6))

    def test_highlight_rectangles(self):
        """One rectangle per selected line part, from its first to its last selected word."""
        s = Selection(Layout(PAGE), start=1)
        s.move("w", 2)
        self.assertEqual(s.rects(), [(60, 10, 40, 12), (0, 30, 92, 12)])

    def test_empty_layout_is_harmless(self):
        """No words: motions report nothing done and the text is empty."""
        s = Selection(Layout([]))
        self.assertFalse(s.move("w")); self.assertEqual(s.text(), ""); self.assertEqual(s.rects(), [])
        self.assertFalse(s.move("x"))

    def test_counts(self):
        """Typed digits before a motion are its count; nothing (or 0, itself a motion) means 1."""
        self.assertEqual(parse_count("12"), 12)
        self.assertEqual(parse_count(""), 1)
        self.assertEqual(parse_count("0"), 1)


if __name__ == "__main__":
    unittest.main()
