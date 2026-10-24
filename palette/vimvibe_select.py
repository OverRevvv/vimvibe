"""vimvibe copy mode: the selection model. Copy mode (research/12) reads the words on screen (from the app's
accessible text or from OCR), lets the user put a caret on one by typing its label, extends the selection with Vim
motions, and copies the selected text. This file is that logic over a plain list of words: reading order, motions,
the selected range, the text it stands for, and the rectangles to highlight.

Pure logic with no Qt widgets, so it is unit-tested headlessly (test_select.py); the overlay draws it.

A word is a dict: {"text": str, "x": int, "y": int, "w": int, "h": int} in screen pixels, plus an optional "line" key
(any hashable, e.g. tesseract's (block, paragraph, line)) that says which words share a line. Without "line", lines
are worked out from the words' vertical positions."""


def _overlap(a, b):
    """How much of the shorter word's height two words share vertically (0..1); 1 means the same line for sure."""
    top, bottom = max(a["y"], b["y"]), min(a["y"] + a["h"], b["y"] + b["h"])
    return max(0, bottom - top) / max(1, min(a["h"], b["h"]))


class Layout:
    """The words in reading order, grouped into lines: `words[i]` is the i-th word on screen (top to bottom, left to
    right), `lines` holds the word indexes of each line, `line_of[i]` the line of word i."""

    def __init__(self, words):
        """Sort `words` into lines. Words with a "line" key are grouped by it; the others join the line they overlap
        vertically by at least half their height, so slightly uneven baselines stay on one line."""
        words = [w for w in words if str(w.get("text", "")).strip()]
        groups = []  # [key, [words]]
        for w in sorted(words, key=lambda w: (w["y"], w["x"])):
            key = w.get("line")
            for g in groups:
                if key is not None and g[0] == key:
                    g[1].append(w); break
                if key is None and g[0] is None and any(_overlap(w, o) >= 0.5 for o in g[1]):
                    g[1].append(w); break
            else:
                groups.append([key, [w]])
        # lines top to bottom by their highest word, words in a line left to right
        rows = sorted((sorted(g[1], key=lambda w: w["x"]) for g in groups), key=lambda ws: min(w["y"] for w in ws))
        self.words, self.lines, self.line_of = [], [], []
        for n, row in enumerate(rows):
            self.lines.append(list(range(len(self.words), len(self.words) + len(row))))
            self.words.extend(row)
            self.line_of.extend([n] * len(row))

    def __len__(self):
        """Number of words."""
        return len(self.words)

    def center_x(self, i):
        """Horizontal middle of word i (what vertical motions try to keep)."""
        w = self.words[i]
        return w["x"] + w["w"] / 2


class Selection:
    """A selection over a Layout: `anchor` is where it started, `cursor` the end that moves. Both are word indexes.
    In "line" mode whole lines between them are selected (Vim's V)."""

    MOTIONS = ("w", "b", "j", "k", "0", "$", "gg", "G")

    def __init__(self, layout, start=0):
        """Put the caret on word `start` (clamped to the layout); nothing beyond that word is selected yet."""
        self.layout = layout
        self.anchor = self.cursor = self._clamp(start)
        self.mode = "word"
        self.goal_x = None  # remembered column for j / k, so moving through a short line does not lose it

    def _clamp(self, i):
        """A valid word index (0 for an empty layout)."""
        return max(0, min(int(i), len(self.layout) - 1)) if len(self.layout) else 0

    def jump(self, i):
        """Move the cursor to word i (the second label typed); the anchor stays."""
        self.cursor = self._clamp(i)
        self.goal_x = None

    def restart(self, i):
        """Start a new selection at word i."""
        self.anchor = self.cursor = self._clamp(i)
        self.goal_x = None

    def toggle_line_mode(self):
        """Switch between selecting words and selecting whole lines; returns the new mode."""
        self.mode = "line" if self.mode == "word" else "word"
        return self.mode

    def move(self, motion, count=1):
        """Move the cursor by a Vim motion, `count` times: w / b next / previous word (across lines), j / k the word
        nearest the same column on the next / previous line, 0 / $ start / end of the line, gg / G first / last word.
        Returns False for an unknown motion or an empty layout (nothing changes)."""
        if motion not in self.MOTIONS or not len(self.layout):
            return False
        lay, n = self.layout, len(self.layout)
        for _ in range(max(1, int(count))):
            line = lay.line_of[self.cursor]
            if motion == "w":
                self.cursor = min(n - 1, self.cursor + 1)
            elif motion == "b":
                self.cursor = max(0, self.cursor - 1)
            elif motion in ("j", "k"):
                target = line + (1 if motion == "j" else -1)
                if not 0 <= target < len(lay.lines):
                    break
                if self.goal_x is None:
                    self.goal_x = lay.center_x(self.cursor)
                self.cursor = min(lay.lines[target], key=lambda i: abs(lay.center_x(i) - self.goal_x))
                continue  # keep goal_x for the next vertical move
            elif motion == "0":
                self.cursor = lay.lines[line][0]
            elif motion == "$":
                self.cursor = lay.lines[line][-1]
            elif motion == "gg":
                self.cursor = 0
            elif motion == "G":
                self.cursor = n - 1
            self.goal_x = None
        return True

    def range(self):
        """The selected word indexes as (first, last), inclusive; in line mode widened to whole lines."""
        lo, hi = sorted((self.anchor, self.cursor))
        if self.mode == "line" and len(self.layout):
            lay = self.layout
            lo, hi = lay.lines[lay.line_of[lo]][0], lay.lines[lay.line_of[hi]][-1]
        return lo, hi

    def text(self, join_lines="newline"):
        """The selected text: words of a line joined by a space, lines joined by a newline (or by a space with
        `join_lines="space"`). Empty for an empty layout."""
        if not len(self.layout):
            return ""
        lo, hi = self.range()
        lay, out = self.layout, []
        for line in lay.lines:
            picked = [lay.words[i]["text"].strip() for i in line if lo <= i <= hi]
            if picked:
                out.append(" ".join(picked))
        return ("\n" if join_lines == "newline" else " ").join(out)

    def rects(self):
        """One highlight rectangle (x, y, w, h) per selected line part, spanning its first to last selected word."""
        if not len(self.layout):
            return []
        lo, hi = self.range()
        lay, out = self.layout, []
        for line in lay.lines:
            picked = [lay.words[i] for i in line if lo <= i <= hi]
            if picked:
                x0 = min(w["x"] for w in picked); y0 = min(w["y"] for w in picked)
                x1 = max(w["x"] + w["w"] for w in picked); y1 = max(w["y"] + w["h"] for w in picked)
                out.append((x0, y0, x1 - x0, y1 - y0))
        return out


def parse_count(prefix):
    """The repeat count typed before a motion ("5" in "5w"); 1 when nothing (or "0", which is itself a motion) was typed."""
    digits = "".join(ch for ch in str(prefix) if ch.isdigit())
    return int(digits) if digits and int(digits) > 0 else 1
