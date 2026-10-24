"""Tests for the copy-mode selection model (run: cd palette && python3 -m unittest test_select)."""
import unittest

from vimvibe_select import Buffer, Layout, Selection, parse_count, word_labels


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

    def test_vertical_motions_stay_in_their_column(self):
        """With two columns side by side, j / k move within the column the caret is in, not to the line that merely
        comes next in reading order."""
        cols = [word("left1", 0, 10), word("right1", 300, 12), word("left2", 0, 30), word("right2", 300, 50),
                word("left3", 0, 70)]
        s = Selection(Layout(cols), start=1)              # "right1"
        s.move("j"); self.assertEqual(s.layout.words[s.cursor]["text"], "right2")
        s = Selection(Layout(cols), start=0)              # "left1"
        s.move("j", 2); self.assertEqual(s.layout.words[s.cursor]["text"], "left3")
        s.move("k"); self.assertEqual(s.layout.words[s.cursor]["text"], "left2")

    def test_a_nearby_column_beats_a_far_one(self):
        """Measured on a real screen: from a button label, the list rows just left of its column (90 px) win over a
        terminal line beside the window (200 px), although the terminal line is closer vertically."""
        page = [word("Menu", 657, 201, 46), word("extending", 875, 236, 70), word("Row", 550, 320, 24), word("0", 580, 320, 8)]
        s = Selection(Layout(page), start=0)
        s.move("j"); self.assertIn(s.layout.words[s.cursor]["text"], ("Row", "0"))   # the "Row 0" line (its word nearest the column)

    def test_a_line_behind_a_window_is_not_in_its_column(self):
        """A wide line with words left and right of a window (a terminal behind it) does not catch j / k: the window's
        own next line does, even though it is further down."""
        page = [word("Plain", 600, 10), word("terminal", 0, 30), word("text", 900, 30), word("Menu", 600, 50)]
        s = Selection(Layout(page), start=0)
        s.move("j"); self.assertEqual(s.layout.words[s.cursor]["text"], "Menu")

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



def keys(buf, text):
    """Type each character of `text` into the buffer; returns the last action."""
    out = None
    for ch in text:
        out = buf.key(ch)
    return out


class BufferTests(unittest.TestCase):
    def setUp(self):
        """A text-mode buffer over PAGE (caret on "Hello")."""
        self.b = Buffer(PAGE)

    def test_moves_and_counts(self):
        """Vim motions with counts move the caret; without a selection only the caret word is selected."""
        keys(self.b, "2w")
        self.assertEqual(self.b.sel.range(), (2, 2))
        keys(self.b, "j$")
        self.assertEqual(self.b.layout.words[self.b.sel.cursor]["text"], "last")
        keys(self.b, "gg")
        self.assertEqual(self.b.sel.cursor, 0)
        keys(self.b, "G0")
        self.assertEqual(self.b.sel.cursor, 5)

    def test_visual_select_and_copy(self):
        """v starts a selection, motions extend it, y copies it and stops selecting."""
        keys(self.b, "lv")
        self.assertEqual(keys(self.b, "jy"), ("copy", "world\nsecond line"))
        self.assertIsNone(self.b.visual)
        self.assertEqual(self.b.sel.range(), (3, 3))   # back to just the caret

    def test_line_visual_and_enter(self):
        """V selects whole lines; Enter copies like y."""
        keys(self.b, "jV")
        self.assertEqual(self.b.key("Return"), ("copy", "second line here"))

    def test_yank_operators(self):
        """yy copies the line, yw / 2yw words from the caret, y$ to the line end, Y the line."""
        keys(self.b, "j")                               # caret on "second"
        self.assertEqual(keys(self.b, "yy"), ("copy", "second line here"))
        self.assertEqual(keys(self.b, "2yw"), ("copy", "second line"))
        keys(self.b, "l")
        self.assertEqual(keys(self.b, "y$"), ("copy", "line here"))
        self.assertEqual(self.b.key("Y"), ("copy", "second line here"))

    def test_paste_requests(self):
        """p asks to paste into a text field, P where the keyboard is."""
        self.assertEqual(self.b.key("p"), ("paste_field",))
        self.assertEqual(self.b.key("P"), ("paste_here",))

    def test_label_jump(self):
        """f shows a label per word; typing one moves the caret there; a wrong letter cancels."""
        self.b.key("f")
        labels = {v: k for k, v in self.b.labels.items()}
        keys(self.b, labels[6])
        self.assertEqual(self.b.sel.cursor, 6); self.assertIsNone(self.b.labels)
        self.b.key("f")
        self.assertEqual(self.b.key("1"), None)          # not a letter: ignored, still jumping
        self.assertEqual(self.b.key("q"), ("message", "No such label"))   # no label starts with q

    def test_search(self):
        """/ then Enter jumps to the next word containing the text (wrapping); n / N repeat it."""
        for k in "/LIN":
            self.b.key(k)
        self.b.key("Return")
        self.assertEqual(self.b.sel.cursor, 3)
        self.b.key("n")
        self.assertEqual(self.b.sel.cursor, 3)           # the only match: wraps onto itself
        self.assertEqual(keys(self.b, "/zzz") or self.b.key("Return"), ("message", "Not found: zzz"))

    def test_escape_steps_back(self):
        """Esc drops a pending count, then the selection, then asks to leave text mode."""
        keys(self.b, "v3")
        self.assertIsNone(self.b.key("Escape")); self.assertEqual(self.b.pending, "")
        self.assertIsNone(self.b.key("Escape")); self.assertIsNone(self.b.visual)
        self.assertEqual(self.b.key("Escape"), ("leave",))

    def test_empty_screen(self):
        """No words: a message, and Esc still leaves."""
        b = Buffer([])
        self.assertEqual(b.key("w")[0], "message")
        self.assertEqual(b.key("Escape"), ("leave",))

    def test_word_labels(self):
        """Labels are distinct, equally long, two letters while they fit."""
        self.assertEqual(word_labels(3), ["aa", "as", "ad"])
        many = word_labels(700)
        self.assertEqual(len(set(many)), 700); self.assertEqual({len(x) for x in many}, {3})


if __name__ == "__main__":
    unittest.main()
