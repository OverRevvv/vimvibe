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

    def text(self, join_lines="newline", only=None):
        """The selected text: words of a line joined by a space, lines joined by a newline (or by a space with
        `join_lines="space"`). `only(word)` can leave words out (a selection inside a scrolled document skips the
        still parts of the screen that lie between its ends). Empty for an empty layout."""
        if not len(self.layout):
            return ""
        lo, hi = self.range()
        lay, out = self.layout, []
        for line in lay.lines:
            picked = [lay.words[i]["text"].strip() for i in line if lo <= i <= hi and (only is None or only(lay.words[i]))]
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


def estimate_shift(old, new, tolerance=4):
    """How far the text moved between two readings of the screen (after a scroll): the (dx, dy) that most words share.
    Words are paired by identical text at nearly the same x (a vertical scroll keeps the column). Only words that
    occur exactly once in each reading count: repeated words ("Row" on every row of a list) would pair with the wrong
    copy and vote for "nothing moved" (measured on a list). The displacement most pairs agree on within `tolerance` px
    wins, but a moving group beats a still one: a scroll moves one part of the screen (a list, a page) while the rest
    (other windows, toolbars) stays, and the still part must not outvote what was scrolled (measured: a terminal beside
    a scrolled list). None when fewer than 3 pairs agree (the content changed, or the scroll went past everything
    that was on screen)."""
    def unique(words):
        """Words of 2+ characters whose text occurs once, by text."""
        seen = {}
        for w in words:
            if len(w["text"]) >= 2:
                seen.setdefault(w["text"], []).append(w)
        return {t: ws[0] for t, ws in seen.items() if len(ws) == 1}

    olds, news = unique(old), unique(new)
    votes = [(news[t]["x"] - w["x"], news[t]["y"] - w["y"]) for t, w in olds.items()
             if t in news and abs(news[t]["x"] - w["x"]) <= tolerance]
    best, best_key = [], None
    for _, dy in votes:
        agree = [v for v in votes if abs(v[1] - dy) <= tolerance]
        key = (len(agree) >= 3 and abs(dy) > tolerance, len(agree))  # moving groups of 3+ first, then size
        if best_key is None or key > best_key:
            best, best_key = agree, key
    if len(best) < 3:
        return None
    dys = sorted(v[1] for v in best)
    dxs = sorted(v[0] for v in best)
    return dxs[len(dxs) // 2], dys[len(dys) // 2]


def moved_region(old, new, shift, tolerance=4):
    """The rectangle (x0, y0, x1, y1) of the new reading that the scroll moved by `shift`: around the unique words
    that moved by it. The caret is kept inside it, so it never jumps out of the scrolled list into a toolbar or another
    window. None when the shift is (about) zero or nothing moved by it."""
    dx, dy = shift
    if abs(dy) <= tolerance and abs(dx) <= tolerance:
        return None
    olds = {w["text"]: w for w in old}
    boxes = [n for n in new if n["text"] in olds and abs(n["x"] - olds[n["text"]]["x"] - dx) <= tolerance
             and abs(n["y"] - olds[n["text"]]["y"] - dy) <= tolerance]
    if not boxes:
        return None
    return (min(w["x"] for w in boxes), min(w["y"] for w in boxes),
            max(w["x"] + w["w"] for w in boxes), max(w["y"] + w["h"] for w in boxes))


def scrolled_region(old, new, shift, tolerance=4):
    """The screen box (x0, y0, x1, y1) of the area a scroll moved: around the words that moved by `shift`, stretched
    up and down by the scroll distance plus a line, which is where the newly revealed lines appear. None when nothing
    moved."""
    box = moved_region(old, new, shift, tolerance)
    if box is None:
        return None
    line = max((w["h"] for w in new), default=12) * 1.5
    reach = abs(shift[1]) + line
    return (box[0] - tolerance, box[1] - reach, box[2] + tolerance, box[3] + reach)


class Document:
    """Phase A of research/12: text mode's memory across scrolls, so a selection can span many screens.

    The part of the screen that scrolls (found at the first scroll, `region`) becomes a document that grows: every
    word in it gets a document y (`dy`, screen y + `offset`, where `offset` is how far the content has scrolled up
    since it started). A line already in the document keeps its first reading; only lines that scrolled into view are
    added. Words outside the region (other windows, toolbars) are taken fresh from each reading (`static`).
    `view()` gives the words for a Buffer: document words at their screen position now, which may be off screen.

    Line keys from tesseract restart in every reading, so they are namespaced by reading (`r3:1.1.2`)."""

    def __init__(self, words):
        """Start from the first reading: nothing has scrolled yet, so every word is still screen text."""
        self.reading = 1
        self.region = None
        self.view_h = 0  # height of the scrolled area as measured (the overlay keeps steps within half of it)
        self.offset = 0
        self.doc = []
        self.static = self._tag(words)

    def _tag(self, words):
        """Copies of a reading's words with their line keys namespaced by this reading."""
        return [dict(w, line=f"r{self.reading}:{w['line']}") if "line" in w else dict(w) for w in words]

    @staticmethod
    def _inside(w, region):
        """Whether word w's centre lies in the region box."""
        cx, cy = w["x"] + w["w"] / 2, w["y"] + w["h"] / 2
        return region[0] <= cx <= region[2] and region[1] <= cy <= region[3]

    def __len__(self):
        """Words known: on screen now plus the scrolled document."""
        return len(self.static) + len(self.doc)

    def view(self):
        """Words for a Buffer: the still screen words, then the document words where they are on screen now."""
        return [dict(w, doc=False) for w in self.static] + [dict(w, y=w["dy"] - self.offset, doc=True) for w in self.doc]

    def target(self, w):
        """Remember where word `w` (from the current view) is, to find it again after the next update."""
        cx, cy = w["x"] + w["w"] / 2, w["y"] + w["h"] / 2
        if w.get("doc"):
            return ("doc", cx, w["dy"] + w["h"] / 2)
        return ("screen", cx, cy, self.offset)

    def resolve(self, target, layout):
        """The index in `layout` (built from `view()`) of the word a `target` stands for: a document word by its
        document position, a screen word by its screen position (a screen word that has become part of the scrolled
        region counts as a document word at the offset it was seen with)."""
        if target[0] == "screen" and self.region is not None and self._inside({"x": target[1], "y": target[2], "w": 0, "h": 0}, self.region):
            target = ("doc", target[1], target[2] + target[3])
        pool = [i for i, w in enumerate(layout.words) if bool(w.get("doc")) == (target[0] == "doc")] or range(len(layout))

        def dist(i):
            """Distance from the target to word i's centre (document coordinates for document words)."""
            w = layout.words[i]
            y = (w["dy"] if target[0] == "doc" and "dy" in w else w["y"]) + w["h"] / 2
            return (w["x"] + w["w"] / 2 - target[1]) ** 2 + (y - target[2]) ** 2

        return min(pool, key=dist)

    def update(self, new, shift, region):
        """Merge the reading taken after a scroll. `shift` (from `estimate_shift` against the previous view's
        on-screen words) and `region` (from `scrolled_region`) say how far and where the content moved. Returns False
        when the shift is unknown: the scroll went past everything that was on screen, so the new reading can't be
        placed in the document (the caller starts a new one)."""
        if shift is None:
            return False
        self.reading += 1
        new = self._tag(new)
        if region is not None:
            if self.region is None:  # the first scroll: what the scrolled area showed before starts the document
                self.doc = [dict(w, dy=w["y"]) for w in self.static if self._inside(w, region)]
            self.region = region
            self.offset -= shift[1]
        if self.region is None:  # nothing has scrolled yet: still all screen text
            self.static = new
            return True
        self.static = [w for w in new if not self._inside(w, self.region)]
        buckets = {}
        for e in self.doc:
            buckets.setdefault(int(e["dy"] // 16), []).append(e)
        for w in new:
            if not self._inside(w, self.region):
                continue
            d = w["y"] + self.offset
            near = [e for k in (int(d // 16) - 1, int(d // 16), int(d // 16) + 1) for e in buckets.get(k, ())]
            if any(abs(e["x"] - w["x"]) <= 6 and abs(e["dy"] - d) <= max(4, w["h"] / 2) for e in near):
                continue  # already known: the first reading is kept
            e = dict(w, dy=d)
            self.doc.append(e)
            buckets.setdefault(int(d // 16), []).append(e)
        return True


def nearest_word(layout, x, y, region=None):
    """Index of the word whose centre is nearest to the point (x, y), among the words inside `region` (x0, y0, x1,
    y1; all words when None or when none is inside); None for an empty layout."""
    if not len(layout):
        return None
    pool = range(len(layout))
    if region:
        x0, y0, x1, y1 = region
        inside = [i for i in pool if x0 - 2 <= layout.center_x(i) <= x1 + 2
                  and y0 - 2 <= layout.words[i]["y"] + layout.words[i]["h"] / 2 <= y1 + 2]
        pool = inside or pool
    return min(pool, key=lambda i: (layout.words[i]["x"] + layout.words[i]["w"] / 2 - x) ** 2
               + (layout.words[i]["y"] + layout.words[i]["h"] / 2 - y) ** 2)


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

    Returned actions: ("copy", text), ("paste_field",), ("paste_here",), ("leave",), ("message", text), and
    ("scroll", direction, key) when j / k hit the edge of the screen: the overlay scrolls the app, reads the screen
    again and replays the key (Space + J K E Y D U F B scroll in the overlay itself)."""

    def __init__(self, words, alphabet=LABEL_ALPHABET, join_lines="newline", screen=None):
        """Build the buffer over `words` (see Layout) with the caret on the first word. `screen` (w, h) is the visible
        area: words of a scrolled document can lie outside it (they are still selectable and copied, but get no `f`
        label)."""
        self.layout = Layout(words)
        self.screen = screen
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

    def visible(self, i):
        """Whether word i is on screen now (always, without a known screen size)."""
        if self.screen is None:
            return True
        w = self.layout.words[i]
        return w["y"] + w["h"] > 0 and w["y"] < self.screen[1]

    def _copy(self, lo, hi):
        """The text of words lo..hi (inclusive) as a copy action, keeping the current selection untouched. When both
        ends are in the scrolled document, only document words are copied: the still parts of the screen (a toolbar,
        another window) that sort between them in reading order are not part of the text."""
        keep = (self.sel.anchor, self.sel.cursor, self.sel.mode)
        words = self.layout.words
        only = (lambda w: w.get("doc")) if words[lo].get("doc") and words[hi].get("doc") else None
        self.sel.anchor, self.sel.cursor, self.sel.mode = lo, hi, "word"
        text = self.sel.text(self.join_lines, only)
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
            before = self.sel.cursor
            self.sel.move(motion, count)
            self._moved()
            if motion in "jk" and self.sel.cursor == before:  # no line further down / up on screen: scroll, like Vim
                return ("scroll", 1 if motion == "j" else -1, key)
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
            shown = [i for i in range(len(self.layout)) if self.visible(i)]
            self.labels = dict(zip(word_labels(len(shown), self.alphabet), shown))
            self.typed = ""
            return None
        if key == "/":
            self.search = ""
            return None
        if key in ("n", "N") and self.last_search:
            return self._find(self.last_search, 1 if key == "n" else -1)
        return None

    def restore(self, doc, anchor, cursor, visual, mode):
        """After a scroll: put the caret and, while selecting, the anchor back on the words they were on (`anchor` /
        `cursor` from `Document.target` before the update), and the selection mode."""
        if not len(self):
            return
        c = doc.resolve(cursor, self.layout)
        a = doc.resolve(anchor, self.layout) if visual else c
        self.sel.anchor, self.sel.cursor, self.sel.goal_x = a, c, None
        self.visual, self.sel.mode = visual, mode if visual else "word"

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
            lo, hi = self.sel.range()
            res = self._copy(lo, hi)
            size = len(res[1]) if res[0] == "copy" else 0
            return (f"-- {state} --{pending} · {size} characters · [h j k l w b 0 $] extend · [Space+J K D U] scroll · "
                    f"[y] copy · [Esc] stop selecting")
        return (f"-- {state} --{pending} · [h j k l w b 0 $ gg G] move · [v V] select · [y] copy · "
                f"[p] paste into a field · [P] paste here · [f] jump · [/] search · [Space+J K D U] scroll · [Esc] back")
