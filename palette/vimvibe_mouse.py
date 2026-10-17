"""vimvibe keyboard mouse: the zooming grid. The region (the target window or the whole screen) is divided into rows ×
columns cells named by two letters (row letter, column letter: aa ab ac … ba bb …). Typing a cell's name zooms into it,
and the cell is divided again, as deep as the settings allow; the pointer goes to the middle of the current region.

Pure logic with no Qt widgets, so it is unit-tested headlessly (test_mouse.py); the overlay draws it."""

MIN_CELL = 6.0   # a cell narrower than this (px) is not divided any further


def clean_alphabet(text, need):
    """The label letters: lower-case, no repeats, letters and digits only; the default alphabet when `text` has fewer
    than `need` usable characters."""
    seen = []
    for ch in str(text).lower():
        if ch.isascii() and ch.isalnum() and ch not in seen:
            seen.append(ch)
    return "".join(seen) if len(seen) >= need else "abcdefghijklmnopqrstuvwxyz"


class Grid:
    """A stack of regions: `regions[-1]` is the one on screen, divided into rows × cols cells."""

    def __init__(self, bounds, cols=5, rows=5, alphabet="abcdefghijklmnopqrstuvwxyz", max_depth=4):
        """`bounds` is (x, y, w, h). Cols and rows are limited by the alphabet (a label letter per row and column)."""
        self.alphabet = clean_alphabet(alphabet, 2)
        self.cols = max(2, min(int(cols), len(self.alphabet)))
        self.rows = max(2, min(int(rows), len(self.alphabet)))
        self.max_depth = max(1, int(max_depth))
        self.regions = [tuple(float(v) for v in bounds)]
        self.pending = ""   # the first letter of a cell name, typed but not completed

    @property
    def region(self):
        """The region that is divided now: (x, y, w, h)."""
        return self.regions[-1]

    @property
    def depth(self):
        """How many times the grid was zoomed (0 = the whole starting region)."""
        return len(self.regions) - 1

    def center(self):
        """The point the pointer goes to: the middle of the current region."""
        x, y, w, h = self.region
        return (x + w / 2, y + h / 2)

    def can_zoom(self):
        """Whether a cell can still be divided (depth limit, and cells must stay big enough to tell apart)."""
        x, y, w, h = self.region
        return self.depth < self.max_depth and w / self.cols >= MIN_CELL and h / self.rows >= MIN_CELL

    def cell(self, row, col):
        """Rectangle of the cell at (row, col) of the current region."""
        x, y, w, h = self.region
        cw, ch = w / self.cols, h / self.rows
        return (x + col * cw, y + row * ch, cw, ch)

    def label(self, row, col):
        """Two-letter name of a cell: row letter, then column letter."""
        return self.alphabet[row] + self.alphabet[col]

    def cells(self):
        """Every cell of the current region as (label, (x, y, w, h)), row by row."""
        return [(self.label(r, c), self.cell(r, c)) for r in range(self.rows) for c in range(self.cols)]

    def type(self, ch):
        """Feed one typed character. Returns "zoom" (a cell was chosen and is now the region), "pending" (first letter
        taken) or None (not a letter that means anything here)."""
        ch = ch.lower()
        if not self.can_zoom():
            return None
        if not self.pending:
            if ch in self.alphabet[:self.rows]:
                self.pending = ch
                return "pending"
            return None
        if ch in self.alphabet[:self.cols]:
            self.regions.append(self.cell(self.alphabet.index(self.pending), self.alphabet.index(ch)))
            self.pending = ""
            return "zoom"
        return None

    def zoom_to(self, point):
        """Zoom into the cell under `point` (a click on the grid). Returns whether anything changed."""
        if not self.can_zoom():
            return False
        x, y, w, h = self.region
        px, py = point
        if not (x <= px < x + w and y <= py < y + h):
            return False
        col = min(self.cols - 1, int((px - x) / (w / self.cols)))
        row = min(self.rows - 1, int((py - y) / (h / self.rows)))
        self.regions.append(self.cell(row, col))
        self.pending = ""
        return True

    def back(self):
        """Undo the last step: the pending letter, or else zoom out one level. Returns whether anything changed."""
        if self.pending:
            self.pending = ""
            return True
        if self.depth:
            self.regions.pop()
            return True
        return False
