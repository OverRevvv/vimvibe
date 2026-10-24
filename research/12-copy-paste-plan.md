# 12 — Plan: copying text from anywhere on screen

Status: **milestone 1 done** (the selection model, `palette/vimvibe_select.py`, 11 tests in `test_select.py`);
milestones 2–4 not built. Written 2026-10-24 after OCR (tesseract) became part of vimvibe.

## Why this comes back

Copy and paste was tried twice:

1. **Pointer press-and-drag selection.** This was dropped: holding the button through the portal stole keyboard focus, so
   letters leaked into the app.
2. **Edit mode** (H J K L as arrows, V to select, Y to copy, through KWin key grabs). Built, then switched off: it only
   works where Shift+arrows select (text fields, editors), and keys did not reach every app reliably.

What is left today is small: Ctrl+Y copies a result's name, Ctrl+Shift+V pastes into a field, and Ctrl+Shift+H picks
from Klipper's history. What users want is Vimium's visual mode for the whole desktop: **put a caret on any text you
can see, extend a selection with the keyboard, and copy it**, including text in apps with no accessibility tree.

## Design: select by labels, not by moving a caret

Moving a real caret depends on each app. Instead, vimvibe can read the text itself and do the selection in its own
overlay. The app is never touched, so this works the same in every app.

1. **Copy mode** opens (new action `copy_mode`, default **Ctrl+Shift+C**, available from every mode like Ctrl+I).
2. **Text source, best first:**
   - **AT-SPI Text interface.** For accessible apps, this gives the exact characters and per-character extents
     (`get_text`, `get_character_extents` / `get_range_extents`). It is exact, fast and needs no screenshot. It
     covers Qt, GTK, Firefox, and Chromium with the flag.
   - **OCR fallback.** Reuse `ocr.rs`, but keep **words** (level 5) with their lines instead of merging them into
     phrases, so any word can be a start or end point. The same `[ocr]` settings apply.
3. **Pick the start.** Every word gets a label, using the same label code (`hints.rs`) and drawing as the click
   labels. Typing a label puts a block caret on that word.
4. **Extend.** Vim keys move the end of the selection inside vimvibe's own model of the text:
   - `w`/`b` move by words, `j`/`k` by lines, `0`/`$` to the line start and end;
   - `v` toggles between character and line selection;
   - a second label jumps the end point to that word.

   The selection is drawn as a highlight in the overlay.
5. **Copy.** `y` or Enter puts the selected text on the clipboard with the existing `vimvibe_clip.set_text` (Klipper)
   and shows a short "Copied N characters" flash. **Esc** cancels.
6. **Paste** stays as it is: Ctrl+Shift+V into a field, or the history picker.

## What has to be built

| Piece | Where | Notes |
|---|---|---|
| `Text(id)` / `TextRegion()` D-Bus methods | `daemon.rs` | Returns words with screen rectangles and line numbers for the window. Tries AT-SPI Text first, then OCR. |
| Accessible text walk | `enumerate.rs` | Collect objects with the Text interface (labels, paragraphs, documents) and their word boxes. Bounded like the element walk. |
| OCR words mode | `ocr.rs` | `read_words()`: same pipeline, no phrase merging, keeps the (block, paragraph, line) numbers so line moves work. |
| Selection model | new `palette/vimvibe_select.py` | Pure logic over a list of words: start, end, word/line motions, extraction of the text with line breaks. Unit-tested like `vimvibe_mouse.py`. |
| Copy-mode drawing and keys | `vimvibe_palette.py` | Word labels, caret, highlight; `copy_mode` action in `vimvibe_keys.py`. |
| Settings | `[copy]` | `source = "auto" \| "accessibility" \| "ocr"`, `join_lines = "newline" \| "space"`, `trim = true`; Settings → Mouse & copy; export/import comes for free. |
| Docs | `docs/using.md`, `docs/architecture.md`, `docs/configuration.md` | |

## Risks and how to check them

- **OCR accuracy on small or styled text.** Measure on the apps people actually use (Spotify, Electron apps, games)
  and record the results here. Possible mitigations:
  - an `[ocr] scale` option that upscales the screenshot 2× before recognition;
  - per-language data.
- **Speed.** OCR takes about 2 s for the screen. It could be faster:
  - cropping to the window (needs a crop step: PNG decode or tesseract's `--psm` with a region);
  - caching the result for the snapshot.
- **Accessible text extents** are window-relative and sometimes stale. The same origin handling as the elements
  applies. Test on Firefox, Kate, Chrome.
- **Privacy.** The text stays in memory and the screenshot is deleted, as with OCR today. Only the selection reaches
  the clipboard, and only when the user presses `y`.

## Milestones

1. ✅ `vimvibe_select.py` with tests, driven by fixed word lists. `Layout` sorts words into reading order and lines
   (by tesseract's line numbers when given, otherwise by vertical overlap); `Selection` holds anchor and cursor and
   implements `w b j k 0 $ gg G` with counts (`j`/`k` keep the column), `jump` for a second label, line mode, and
   `text()` / `rects()` for copying and drawing.
2. OCR words mode plus `TextRegion()`, then copy mode working on OCR text only. This alone covers every app.
3. AT-SPI Text source for exact text in accessible apps.
4. Settings, docs, and the measurements recorded here.
