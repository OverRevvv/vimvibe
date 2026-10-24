"""vimvibe copy mode: the selection model. Copy mode (research/12) reads the words on screen (from the app's
accessible text or from OCR), lets the user put a caret on one by typing its label, extends the selection with Vim
motions, and copies the selected text. This file is that logic over a plain list of words: reading order, motions,
the selected range, the text it stands for, and the rectangles to highlight; `Buffer` turns typed Vim keys into those
moves and into copy / paste requests for the overlay (text mode).

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

    def line_top(self, line):
        """Top edge of a line (its highest word)."""
        return min(self.words[i]["y"] for i in self.lines[line])

    def line_span(self, line):
        """Horizontal extent (left, right) of a line."""
        return (min(self.words[i]["x"] for i in self.lines[line]),
                max(self.words[i]["x"] + self.words[i]["w"] for i in self.lines[line]))

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
                if self.goal_x is None:
                    self.goal_x = lay.center_x(self.cursor)
                target = self._vertical(line, motion == "j")
                if target is None:
                    break
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

    def _vertical(self, line, down):
        """The line j (down) / k (up) goes to. A screen often has columns side by side (a sidebar next to a page,
        two windows), whose lines interleave in reading order; so each line below / above is scored by its vertical
        distance plus twice its horizontal distance from the remembered column (free within COLUMN_SLACK), and the
        lowest score wins: a line further down in the same column beats the next line in a neighbouring one.
        Horizontal distance is measured to the line's nearest word, not its full width: a terminal line running
        behind a window on both sides is not "in" the window's column."""
        lay, top = self.layout, self.layout.line_top(line)
        cands = [n for n in range(len(lay.lines)) if (lay.line_top(n) > top + 2 if down else lay.line_top(n) < top - 2)]
        if not cands:
            return None

        def gap(n):
            """Horizontal distance from the column to the line's nearest word (0 = a word covers the column)."""
            return min(max(0.0, lay.words[i]["x"] - self.goal_x, self.goal_x - (lay.words[i]["x"] + lay.words[i]["w"]))
                       for i in lay.lines[n])

        return min(cands, key=lambda n: abs(lay.line_top(n) - top) + 2 * max(0.0, gap(n) - COLUMN_SLACK))

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


COLUMN_SLACK = 48  # px: a line whose nearest word is this close to the caret's column counts as being in that column
LABEL_ALPHABET = "asdfghjklqwertyuiopzxcvbnm"  # home row first: the most-used labels are the easiest to type


def word_labels(n, alphabet=LABEL_ALPHABET):
    """`n` distinct labels of equal length for the `f` jump: two letters for up to len(alphabet)² words, three beyond."""
    letters = "".join(dict.fromkeys(ch for ch in str(alphabet).lower() if ch.isalpha())) or LABEL_ALPHABET
    size = 1
    while len(letters) ** size < n:
        size += 1
    size = max(2, size)
    out = []
    for i in range(n):
        label, v = "", i
        for _ in range(size):
            v, r = divmod(v, len(letters))
            label = letters[r] + label
        out.append(label)
    return out


class Buffer:
    """Text mode: the words read from the screen as a read-only Vim buffer. `key()` takes one typed key and returns
    what the overlay must do, or None when the key only changed the buffer (moved, selected...):

      h b / l w e      previous / next word        j k        line below / above (same column)
      0 ^ / $          start / end of the line     gg / G     first / last word        a count repeats: 5w, 3j
      v / V            select words / whole lines (again: stop selecting)
      y                copy the selection; without one: yy line, yw word, y$ / y0 to the line end / start; Y line
      p / P            paste into a text field (the overlay lets you pick it) / where the keyboard is now
      f                labels on every word: type one to jump there   / n N    search, next / previous match
      Esc              stop the label jump, search, count or selection; with nothing left, leave text mode

    Returned actions: ("copy", text), ("paste_field",), ("paste_here",), ("leave",), ("message", text)."""

    def __init__(self, words, alphabet=LABEL_ALPHABET, join_lines="newline"):
        """Build the buffer over `words` (see Layout) with the caret on the first word."""
        self.layout = Layout(words)
        self.sel = Selection(self.layout)
        self.alphabet, self.join_lines = alphabet, join_lines
        self.visual = None        # None, "word" or "line"
        self.pending = ""         # a count and/or an operator waiting for the rest of the command ("5", "g", "y")
        self.labels = None        # the `f` jump: label -> word index, while active
        self.typed = ""           # letters of a label typed so far
        self.search = None        # the query while typing after "/"
        self.last_search = ""

    def __len__(self):
        """Number of words in the buffer."""
        return len(self.layout)

    # --- helpers -------------------------------------------------------------------------------------------
    def _moved(self):
        """After a motion: without a selection the selection is just the caret, so the anchor follows."""
        if self.visual is None:
            self.sel.restart(self.sel.cursor)

    def _copy(self, lo, hi):
        """The text of words lo..hi (inclusive) as a copy action, keeping the current selection untouched."""
        keep = (self.sel.anchor, self.sel.cursor, self.sel.mode)
        self.sel.anchor, self.sel.cursor, self.sel.mode = lo, hi, "word"
        text = self.sel.text(self.join_lines)
        self.sel.anchor, self.sel.cursor, self.sel.mode = keep
        return ("copy", text) if text else ("message", "Nothing to copy")

    def _line_bounds(self):
        """First and last word index of the caret's line."""
        line = self.layout.lines[self.layout.line_of[self.sel.cursor]]
        return line[0], line[-1]

    def _find(self, query, step):
        """Move the caret to the next (`step` 1) or previous (-1) word containing `query`, wrapping around."""
        q, n = query.lower(), len(self.layout)
        for k in range(1, n + 1):
            i = (self.sel.cursor + step * k) % n
            if q in self.layout.words[i]["text"].lower():
                self.sel.jump(i)
                self._moved()
                return None
        return ("message", f"Not found: {query}")

    # --- keys ----------------------------------------------------------------------------------------------
    def key(self, key):
        """Handle one key: a printable character ("w", "$", "G") or a name ("Escape", "Return", "BackSpace")."""
        if not len(self.layout):
            return ("leave",) if key == "Escape" else ("message", "No text was found on the screen")
        if self.labels is not None:
            return self._label_key(key)
        if self.search is not None:
            return self._search_key(key)
        if key == "Escape":
            if self.pending:
                self.pending = ""
                return None
            if self.visual:
                self.visual = None
                self.sel.mode = "word"
                self._moved()
                return None
            return ("leave",)
        if key == "Return":
            return self.visual_copy() if self.visual else None
        if len(key) != 1:
            return None
        if key == "y" and self.visual:
            self.pending = ""
            return self.visual_copy()
        count_text = "".join(ch for ch in self.pending if ch.isdigit())
        op = "".join(ch for ch in self.pending if not ch.isdigit())
        if key.isdigit() and (key != "0" or count_text) and not op:
            self.pending += key
            return None
        count = parse_count(count_text)
        self.pending = ""
        if op == "g":
            if key == "g":
                self.sel.move("gg"); self._moved()
            return None
        if op == "y":
            lo, hi = self._line_bounds()
            cur = self.sel.cursor
            spans = {"y": (lo, hi), "w": (cur, min(cur + count - 1, len(self.layout) - 1)), "e": (cur, cur), "l": (cur, cur),
                     "$": (cur, hi), "0": (lo, cur), "^": (lo, cur)}
            return self._copy(*spans[key]) if key in spans else None
        motion = {"h": "b", "b": "b", "l": "w", "w": "w", "e": "w", "j": "j", "k": "k", "0": "0", "^": "0", "$": "$", "G": "G"}.get(key)
        if motion:
            self.sel.move(motion, count)
            self._moved()
            return None
        if key in "gy":
            self.pending = count_text + key
            return None
        if key == "v" or key == "V":
            want = "word" if key == "v" else "line"
            if self.visual == want:
                self.visual = None
                self.sel.mode = "word"
                self._moved()
            else:
                self.visual = want
                self.sel.mode = want
            return None
        if key == "Y":
            return self._copy(*self._line_bounds())
        if key in ("p", "P"):
            return ("paste_field",) if key == "p" else ("paste_here",)
        if key in ("f", "s"):
            self.labels = dict(zip(word_labels(len(self.layout), self.alphabet), range(len(self.layout))))
            self.typed = ""
            return None
        if key == "/":
            self.search = ""
            return None
        if key in ("n", "N") and self.last_search:
            return self._find(self.last_search, 1 if key == "n" else -1)
        return None

    def visual_copy(self):
        """`y` while selecting: copy the selection and stop selecting (Vim leaves visual mode after a yank)."""
        action = self._copy(*self.sel.range())
        self.visual = None
        self.sel.mode = "word"
        self._moved()
        return action

    def _label_key(self, key):
        """A key while the `f` labels are shown: letters pick a word; Esc or a wrong letter cancels."""
        if key == "Escape":
            self.labels = None
            return None
        if key == "BackSpace":
            self.typed = self.typed[:-1]
            return None
        if len(key) != 1 or not key.isalpha():
            return None
        self.typed += key.lower()
        if self.typed in self.labels:
            self.sel.jump(self.labels[self.typed])
            self._moved()
            self.labels = None
        elif not any(lbl.startswith(self.typed) for lbl in self.labels):
            self.labels = None
            return ("message", "No such label")
        return None

    def _search_key(self, key):
        """A key while typing a search after "/": Enter jumps to the next match, Esc cancels."""
        if key == "Escape":
            self.search = None
            return None
        if key == "BackSpace":
            if not self.search:
                self.search = None
            else:
                self.search = self.search[:-1]
            return None
        if key == "Return":
            query, self.search = self.search, None
            if not query:
                return None
            self.last_search = query
            return self._find(query, 1)
        if len(key) == 1 and key.isprintable():
            self.search += key
        return None

    def status(self):
        """One line for the banner: the state, what is pending, and the main keys."""
        if not len(self.layout):
            return "Text mode — no text was found on the screen · [Esc] back"
        if self.labels is not None:
            return f"Jump — type a word's label{(': ' + self.typed.upper()) if self.typed else ''} · [Esc] cancel"
        if self.search is not None:
            return f"/{self.search}▏ · [Enter] find · [Esc] cancel"
        state = {"word": "VISUAL", "line": "VISUAL LINE"}.get(self.visual, "TEXT")
        pending = f"  {self.pending}" if self.pending else ""
        if self.visual:
            return f"-- {state} --{pending} · [h j k l w b 0 $] extend · [y] copy · [Esc] stop selecting"
        return (f"-- {state} --{pending} · [h j k l w b 0 $ gg G] move · [v V] select · [y] copy · "
                f"[p] paste into a field · [P] paste here · [f] jump · [/] search · [Esc] back")
