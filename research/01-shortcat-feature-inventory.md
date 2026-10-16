# 01 — Shortcat feature inventory (public sources only)

Status tags: CONFIRMED / SUPPORTED INFERENCE / UNVERIFIED / UNSUPPORTED (see 04 for IDs).
Sources: [Home](https://shortcat.app/) · [Docs intro](https://shortcat.app/docs) · [Search](https://shortcat.app/docs/features/search) · [Selection](https://shortcat.app/docs/features/selection) · [Actions](https://shortcat.app/docs/features/actions) · [Arrow/Scroll](https://shortcat.app/docs/features/arrow-scroll) · [Continuous](https://shortcat.app/docs/features/continuous-mode) · [Config](https://shortcat.app/docs/configuration-options) · [Compatibility](https://shortcat.app/docs/compatibility) · [Common issues](https://shortcat.app/docs/common-issues) · [Use cases](https://shortcat.app/docs/example-use-cases) · [Changelog](https://shortcat.app/changelog) · [HN thread](https://hn.svelte.dev/item/33222384) (developer comments, 2022 — may be outdated).
Pages were read through a summarising fetch tool, so wording is paraphrased, not verbatim.

Product: v0.12.2 (2025-07-03), macOS 13+, Apple Silicon + Intel, closed source (developer: "It won't be open source"), `brew install shortcat`.

## A. Search interface
| Feature | Status | Notes |
|---|---|---|
| Activation: default `Cmd+Shift+Space`, configurable | CONFIRMED | Config page; changelog v0.10.1. Can't clash with Spotlight's shortcut. |
| Type immediately without waiting for hints is the intended flow | CONFIRMED | Developer on HN. |
| Result list shown; Enter activates selected result | CONFIRMED | Search/Selection docs. |
| Floating overlay vs normal window | UNVERIFIED | Docs mention "panel" (changelog v0.10.1 "Panel shifts on Tab"), yellow labels drawn on target UI, "overlay" fix v0.7.11. Exact window type not documented. |
| Focus goes to field immediately | SUPPORTED INFERENCE | "activate and type" flow; not stated explicitly. |
| Duplicate-label handling | UNVERIFIED | Hints are auto 1–2 char labels; collision policy not documented. |
| No-match behaviour | UNVERIFIED | Not documented. |
| Dismiss without action: `Esc` | SUPPORTED INFERENCE | `Esc` documented only for Continuous Mode; empty-query Backspace "exits scope" (v0.10.1). |
| Enter with empty query clicks at cursor | CONFIRMED | Changelog v0.9.3. |
| Reopening the app triggers activation | CONFIRMED | v0.12.0. |

## B. Element discovery
| Feature | Status |
|---|---|
| Buttons, links, StaticText, RadioButton, MenuItem, Window, Application, TextArea, Dock items searchable by role word | CONFIRMED (Search doc list, "and others") |
| Checkbox & radio pressing | CONFIRMED (v0.6.2) |
| Table headers, outline headers, tabs in WebViews | CONFIRMED (v0.4.3, v0.10.4, v0.11.0) |
| Menu bar items (frontmost app), with shortcuts shown | CONFIRMED (v0.5.0, v0.10.0) |
| Minimized windows indexed; window switching by title | CONFIRMED (v0.10.0, home page) |
| iframes enumerated | CONFIRMED (v0.6.3) |
| Text fields focus | CONFIRMED (home page) |
| Toolbar controls, lists, tabs outside web content | UNVERIFIED (not individually listed) |
| Bookmarks / Recent Items menus deliberately ignored | CONFIRMED (v0.10.1) |

## C. Keyboard interaction
| Feature | Status |
|---|---|
| `Enter` default action (click / press / activate / raise window) | CONFIRMED |
| `Enter`×2 double-click; `Ctrl+Enter` right-click; `Ctrl` tap hover (moves cursor to element midpoint) | CONFIRMED (Actions doc) |
| `Cmd+Enter` open link in new tab; `Shift+Enter` multi-select | CONFIRMED |
| `Tab`/`Shift+Tab`/`Ctrl+N`/`Ctrl+P` move through results | CONFIRMED (v0.11.2) |
| Arrow keys move through filtered list | CONFIRMED |
| Hold `Cmd` shows top-10; `Cmd+Number` acts; `Cmd+Shift+Num` selects | CONFIRMED (Selection doc + v0.10.2) — note changelog and doc phrasing differ slightly on "act vs select"; unreconciled. |
| `Option` clears query and re-shows hint labels | CONFIRMED |
| `Control` focuses results (v0.9.3) vs `Ctrl` tap = hover (Actions doc) | **CONFLICT** — recorded in 07 |
| Arrow-key chords: hold `Space` + `HJKL`/`IJKL`; with `Space+Cmd` for scroll; alpha | CONFIRMED (alpha). Docs say Space+Cmd "sends arrow key event", direction mapping/scroll semantics not stated. |
| Continuous mode (alpha): stays active, 500 ms then reindex, `Cmd+R` reindex, `Esc` exits; auto-exits on focused TextField or opened Menu | CONFIRMED |
| Hint label delay setting (default 2 s; immediately…5 s; after input) | CONFIRMED |
| Window-switch key docs | UNVERIFIED — Actions doc marks section "TODO" |
| Focus restoration after dismiss, multi-window behaviour | UNVERIFIED |
| "Launch at login" option | CONFIRMED |

## D. Matching & ranking
| Feature | Status |
|---|---|
| Fuzzy search | CONFIRMED (home) |
| Synonyms ("delete"→remove/clear/destroy), also for emoji | CONFIRMED (home, v0.9.3, v0.10.0) |
| Abbreviations e.g. "btn" | CONFIRMED (Search doc) |
| Role-based filtering (typing "button") incl. subroles | CONFIRMED (v0.5.2) |
| Multi-word queries | CONFIRMED |
| Accent-insensitive; non-Latin matched by Latin query (experimental, 2013) | CONFIRMED |
| Ranking signals: shorter text higher (v0.5.0), proximity to cursor (v0.7.4), visible-element boost (v0.11.1) | CONFIRMED as changelog statements; current weights UNVERIFIED |
| Prefix/substring algorithm specifics | UNVERIFIED |
| Recently-used / per-app preferences | UNVERIFIED (none documented) |
| Emoji mode: prefix `:` | CONFIRMED |

## E. Accessibility & fallbacks
| Claim | Status |
|---|---|
| Uses macOS Accessibility API (same as VoiceOver) | CONFIRMED (official docs; developer on HN) |
| Needs Accessibility permission | CONFIRMED (Common issues; v0.12.0 re-grant) |
| OCR / image recognition currently used | UNSUPPORTED by available evidence — developer: "plans to use ML/OCR … down the road"; changelog has no OCR. Shipped state of 2025 build unknown. |
| Coordinate clicking | SUPPORTED INFERENCE (default action is "usually a click at the element's midpoint"; hover moves the cursor) — implementation unverified |
| Unactionable cases: apps with poor AX (e.g. Little Snitch cells unlabeled), elements shown as "not labelled", slow-responding/complex UIs and WebViews may not fully enumerate, 5 s enumeration timeout (v0.8.3), own UI slow | CONFIRMED |

Internals (hint algorithm, scoring weights, how clicks are synthesised, caching) are **not publicly known**; only the Mac investigation (05) can address them.

## Addendum — Getting-started and "Using Shortcat efficiently" docs (read 2026-10-14)
Sources: [Getting started](https://shortcat.app/docs/getting-started/), [Using Shortcat efficiently](https://shortcat.app/docs/getting-started/using-shortcat-efficiently). Paraphrased via summarising fetch.
- CONFIRMED: Activation shows, in **one list**, the active window's UI elements, the current app's menus, and all open windows and apps (not separate modes at activation time).
- CONFIRMED: Intended workflow is "activate, type immediately, Enter". **Enter pressed before results finish loading is buffered** and applied to the first result once filtering/scoring completes.
- CONFIRMED: Query refinement by appending an element type word (`link`, `btn`, `radio`, `check`) or part of the hint. Very short queries filter poorly. One or two words recommended.
- CONFIRMED: Hints are 1–3 letters (docs elsewhere say 1–2); black on yellow; appear after delay (default 2 s) or "immediately"/"after input". Docs disagree on 1–2 vs 1–3 — recorded as a conflict (Q16).
- CONFIRMED: `Cmd+Num` works only when fewer than 10 results; `Cmd+Shift+Num` selects for complex actions.
- CONFIRMED: On a Window `Enter` raises the window and brings its app forward; on an Application it brings the app forward.
- CONFIRMED: First launch shows a Welcome screen and requests Accessibility permission; app should live in `/Applications` for updates.
- Design takeaways for Linux: (1) unified result list with role badges; (2) buffered-Enter; (3) role/type words in the query; (4) hint delay setting; (5) first-run check that AT-SPI is enabled (our R1 finding mirrors Shortcat's Accessibility-permission step).
