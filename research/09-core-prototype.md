# 09 — Rust core prototype (approved 2026-10-14)

Location: `core/` (crate `vimvibe-core`, edition 2024). Deps: `atspi` 0.30 (zbus, tokio), `nucleo-matcher` 0.3, `clap`, `tokio`, `serde`. Build output kept outside the repo (CARGO_TARGET_DIR in scratch); `.gitignore` has `target/`. Nothing committed.

## What it does
`status | apps | list | search | act` (see core/README.md). Enumerates the focused (or `--app`) window, matches, and activates through AT-SPI `Action.DoAction(0)`.

## Verified results (live, Plasma 6.7.5 Wayland)
| Check | Result |
|---|---|
| Unit tests (matcher) | 7 pass: fuzzy/prefix, role words, role-word fallback, synonyms, disabled-last, description-substring, empty-query order |
| `--enable-a11y` | Flips `org.a11y.Status.IsEnabled` false→true via `atspi::connection::set_session_accessibility` |
| KCalc | 26 visible actionable elements in ~20 ms; `search btn clear` → Clear, All clear; `search delete` → Clear (synonym) |
| `act` 7 × 6 = | seven, multiply, six, equals → display shows **42** (screenshot) |
| Dolphin | After window clipping: 50 elements in ~40 ms (release). Before clipping 399 elements incl. virtualised rows at y≈5772 reported as Showing |
| Dolphin `act check search` | Search checkbox `Checked` flips True/False via Toggle (verified with AT-SPI state) |
| Budget | `--timeout-ms 5` returns partial results marked TRUNCATED |
| Firefox (about:blank) | 19 elements, 4–14 ms; no page content to test links |

## Bugs found and fixed during the run
1. Role names: atspi names push buttons `Button`, not `PushButton` → zero buttons found until fixed.
2. Virtualised lists report off-screen rows as Showing → clip to window bounds.
3. Fuzzy match on long descriptions was too loose (")" matched "clear") → description matches substring-only.
4. Unnamed input fields were dropped → kept as `(unlabeled entry)` so role searches reach them (mirrors Shortcat's "not labelled").

## Gaps and observations (unresolved)
- Some controls expose no action: Dolphin Back/Forward/Open Menu show no Action (disabled or unsupported) → need the libEI/pointer fallback or `grab_focus`.
- After toggling Dolphin's Search, its editable Text/ComboBox nodes still reported `Showing=false` (search bar not visible in the tree); cause not determined (lazy a11y update or different widget). Not a core-tool bug as far as seen.
- KCalc's display value isn't exposed, so results of actions can't always be read back.
- Menu items inside closed menus are excluded (not Showing) → menu-bar search needs open-menu handling.
- No screen coordinates: rects are window-relative; the KWin script for the window origin is not integrated yet.
- Not run: GTK4 app, Chromium/Electron, HiDPI scaling, large trees (Firefox with real page), concurrency limits under load.
- No git commit was made.

## Update 2026-10-15 — `serve` mode and palette front end
- `vimvibe-core serve`: enumerates the target window once, then answers JSON lines on stdin (`{"q":"text"}` → ranked hits, `{"act":N}` → DoAction/focus on hit N, `{"quit":true}`). Verified by piping (KCalc: Seven → Press succeeded).
- Focused-window detection fixed: several apps flag a frame `Active` (the Plasma on-screen keyboard always did, picking a 0-element window). Candidates are now ranked (showing, has children, non-empty title). Still a heuristic; KWin's active window would be the authoritative source.
- `palette/vimvibe_palette.py` (PySide6): registers `Meta+Shift+Space` through kglobalaccel (`doRegister`/`setShortcut` via gdbus), receives `globalShortcutPressed`, starts `serve`, and shows the palette only after the core reports ready. Race found and fixed: showing first made the palette enumerate itself.
- Verified (synthetic trigger via `Component.invokeShortcut`): hotkey signal received; palette visible, active window, search field focused; status line shows the correct target (Konsole, 10 elements). Enter/Esc/arrow/Tab/Ctrl+N/P and buffered Enter are implemented but **not yet exercised with real key input** (no synthetic-input tool here); a real keypress of the chord is also untested.
- KWin geometry integration was not needed for the palette and is deferred to the hint-overlay phase.
- Process note: a full-screen capture taken for verification caught an unrelated private window; it was deleted immediately. Further checks use state logging, not screenshots.

## Update 2026-10-15 (2) — element-discovery strategies and KWin integration
Measured on this machine (release build, 3 runs each, warm; accessibility enabled). Times are for the whole enumeration incl. per-element calls.

| App | Elements | walk | cache | collection |
|---|---|---|---|---|
| KCalc (Qt) | 27 | 4 ms | not exposed by Qt → falls back | 10–13 ms (54: extra closed-menu/popup items) |
| Dolphin (Qt) | 50 | 38–47 ms | not exposed | 58–66 ms (242: extra items) |
| Chrome, local page of 3200 links/buttons | 222 visible | ~200 ms | **~100 ms** (9430 items in one call) | 280–310 ms |
| Firefox, same page (throw-away profile) | 231 visible | 80–99 ms (first run caught the page unrendered: 22) | **75–86 ms** | not run |

Findings:
- `cache` (`org.a11y.atspi.Cache.GetItems`): one call returns role/name/state for the app's whole tree; filtered locally; only survivors need an extents call. Output identical to the walk on Chrome, Firefox, and the Qt fallbacks (0 differing lines). Chrome and Firefox expose it; Qt does not (→ `auto` falls through to the walk).
- `collection` (`Collection.GetMatches`): **not faster than the walk in any measurement**, and checks only each element's own `Showing`, so it also returns items in closed menus/popups. Kept as an opt-in `--strategy collection` (possibly useful later for menu-bar search); removed from `auto`. Two pitfalls found: the `atspi` crate's `ObjectMatchRule` sends roles as a plain list while the wire protocol uses 4×i32 bitmasks (so it silently matched nothing), and roles ≥128 (e.g. `PushButtonMenu`) cannot be expressed. The request is now built by hand through zbus.
- Actions are no longer fetched per element (an extra round trip each); `activate` looks the action up live. `--with-actions` restores the column for listing.
- Remaining cost in `cache` is mostly the per-candidate extents call. Idea: defer extents to displayed hits only; needs a check that `Showing` is trustworthy for virtualised Qt lists (it was not for Dolphin).
- `auto` = cache → walk.

KWin bridge (`src/kwin.rs`, subcommands `focus`, `watch [secs]`):
- A KWin script reports the active window (`pid`, `resourceClass`, `caption`, `clientGeometry`) via D-Bus `callDBus` to a service owned by the core (`org.vimvibe.Bridge.p<pid>`, unique per process; a shared name let a one-shot query steal a watcher's reports). No journalctl parsing (cf. hints).
- One-shot `active_window()`: 2–32 ms (first call higher). Persistent `watch()`: reports on activation, caption and geometry changes; verified by moving focus KCalc ⇄ Konsole with a KWin script. It does not emit the initial state; a daemon should call the one-shot at start.
- Window selection now matches the AT-SPI app by **PID** (`GetConnectionUnixProcessID` on the a11y bus), then Active/caption. Verified: with Konsole focused the on-screen-keyboard frame scores 15 vs 36; with KCalc focused KCalc wins.
- `serve` now reports `origin` (KWin clientGeometry) and per-hit `screen` = origin + window-relative rect. Verified: KCalc "Seven" rect (8, 214) → screen (371, 372) with origin (363, 158); activating it worked.
- Not covered: HiDPI/fractional scaling, multi-monitor, XWayland windows, non-KDE compositors (the bridge is KDE-only; `XDG_CURRENT_DESKTOP` gate).
- Cleanup note: all test browsers used throw-away profiles under the scratchpad; the user's own browser sessions were not touched.

## Update 2026-10-15 (3) — resident daemon (`vimvibe-core daemon`)
Architecture: one resident process; UIs are thin D-Bus clients. The daemon keeps the AT-SPI connection and a KWin focus watcher warm, registers the global shortcut itself (kglobalaccel; default Meta+Shift+Space, a user's own rebinding wins), and **snapshots the focused window when the shortcut fires, before any UI exists**. That removes the race found earlier (the palette listing itself) by construction.

D-Bus API, session bus, `org.vimvibe.Daemon` at `/org/vimvibe/Daemon`:
- `Trigger() → json` snapshot + emit `Opened(json)`; toggles (closes) when a snapshot is open. Also the integration point for non-KDE desktops: bind any key to `gdbus call … Trigger`.
- `Search(q) → json` hits `[{score, element, screen}]` (screen = KWin origin + window-relative rect).
- `Activate(i) → json` closes the snapshot first (target regains focus), then DoAction/focus on hit `i` of the last Search.
- `Close()`, `Status() → json`; signals `Opened(json)`, `Closed()`.
- `palette/vimvibe_palette.py` is now a thin client of this API (no hotkey code, no subprocess).

Verified (synthetic hotkey via `Component.invokeShortcut`, focus moved by a KWin script):
- Trigger 13–15 ms warm (≈40 ms first, cold); focus lookup 0 ms from the cache; of the ~11 ms spent finding the window, most is looking up every AT-SPI app's PID (candidate: cache bus-name→PID).
- Idle: 10 MB RSS, 9 threads, **0 CPU ticks in 10 s**; no polling anywhere.
- Hotkey path → `Opened`; second trigger → `Closed`; Search/Activate on KCalc ("Seven" → screen (371, 372), Press succeeded); Activate/Search after close return clean errors.
- Palette: shown on `Opened`, active window, field focused, status line names the right target; focus cache keeps the real target while the palette has focus (reports for the palette window are ignored).
- SIGTERM: shortcut unregistered, KWin script unloaded, script file removed. Second daemon instance refuses to start (bus name is single-owner).
- `packaging/vimvibe-daemon.service` is a systemd user unit (written, not installed).

Known gaps:
- **Keystrokes typed between the hotkey and the palette appearing go to the target app** (no keyboard grab). A layer-shell surface with exclusive keyboard focus (what hints uses) would fix it; untested here (layer-shell-qt/gtk-layer-shell not installed).
- Typing into the palette, Enter/Esc/arrow handling, and a real keypress of the chord are still untested (no synthetic-input tool here; needs the user at the keyboard).
- AT-SPI must be enabled before the target app starts; the daemon only reports it in `Status`, it does not enable it yet (first-run setup step still to build).
- Window lookup scans every AT-SPI app per trigger; fine now (≈11 ms), could be cached.
- KDE only for shortcut + focus watcher; elsewhere falls back to the active-frame heuristic and the `Trigger` method.

## Update 2026-10-15 (4) — first-run setup check (`vimvibe-core doctor`)
Purpose: most "it finds nothing" outcomes are setup, not bugs (08 R1: AT-SPI is off by default here; apps started before it was enabled never appear — the Linux counterpart of Shortcat's Accessibility permission step). `doctor` explains the state and the exact fix.

Checks (each prints ok / info / warn / FAIL, optional `fix:` line; `--json` for tooling; exit code 1 only when a FAIL exists):
1. Session: KDE+Wayland ok; X11 or non-KDE → warn (shortcut/focus tracking are KDE-only; prints the `Trigger` D-Bus command to bind elsewhere).
2. AT-SPI bus reachable, and `org.a11y.Status.IsEnabled`. FAIL when off.
3. KWin scripting works (one-shot window list).
4. Every open normal window vs. the accessibility bus, matched by **PID** (same mechanism as window selection). Missing ones are reported with a toolkit guess from the libraries mapped in `/proc/<pid>/maps` (icudtl.dat/v8 → Chromium/Electron, libxul → Firefox, libjvm → Java, libQt → Qt, libgtk → GTK) and the matching hint from the vimium-everywhere compatibility table. The toolkit label is a heuristic and says "looks like".
5. Default shortcut free or ours (KDE reports an owned shortcut as unavailable to everyone, so the daemon's own status is asked first).
6. Daemon running, shortcut registered, focus watcher active.
7. Optional environment file; reminder that the keyboard-grab overlay is untested.
Fixes are opt-in: `--fix` sets `IsEnabled=true` (system-wide setting; apps must be restarted); `--fix-env` writes `~/.config/environment.d/50-vimvibe-accessibility.conf` (QT_LINUX_ACCESSIBILITY_ALWAYS_ON, GNOME_ACCESSIBILITY, ACCESSIBILITY_ENABLED; next login). Nothing else is ever modified.
Privacy: window titles are never read or printed (only class and PID); the KWin list script reports no captions (it only flags the palette window).

Verified here (6 open apps; user's own windows):
- a11y OFF, no daemon: FAIL on accessibility with the fix line, exit 1, apps check skipped.
- `--fix`: turned it on; reported 2 apps not visible (the user's Chrome and a Qt-WebEngine app, both started earlier), which matches the earlier finding that already-running Chrome never appears; Konsole and Firefox were visible. Hints printed per toolkit.
- Daemon running: shortcut + daemon ok. Found and fixed a bug: a running daemon's own shortcut was reported as "bound to another action".
- `--fix-env` tested with `XDG_CONFIG_HOME` pointed at a scratch dir; the user's real config was not touched. JSON output contains no window titles (grep for known titles: 0 hits).
- Flags restored afterwards (accessibility off).
Limits: Flatpak/Snap apps may be misreported (different PID namespaces; the output says so); the app check is KDE-only (needs KWin's window list); no GTK4/Electron coverage yet.

## Update 2026-10-15 (5) — GTK4 and Electron tests
Test subjects: a purpose-built **GTK4 + libadwaita 1.9** app (PyGObject, GTK 4.22: buttons, check box, switch, entry, dropdown, tabs, header-bar menu button, a 2000-row ListView; it logs each activation so effects are verified without screenshots) and **VS Code 1.141 (Electron)** in a throw-away profile and scratch workspace. No installed GNOME GTK4 app existed (`gnome-disks` is GTK3); Discord/Spotify/Telegram Flatpaks were deliberately not touched (signed-in accounts). Everything was closed afterwards; the user's own Chrome and Firefox were never touched.

### GTK4 findings
- Exposes neither the AT-SPI **Cache** nor **Collection**; the tree walk is the only path (7–18 ms for 15–32 elements).
- **`Switch` (role 130) was silently invisible**: the `atspi` crate's `Role` enum stops at 129, so the typed `get_role` fails. Fixed with a raw `GetRole` fallback. (Same crate limit would break a whole-app `Cache.GetItems` decode if an app had a role ≥130; not hit so far.)
- **Duplicates**: one control appears as two nodes at the same rect with the same name (MenuButton = Button + ToggleButton, DropDown = ComboBox + ToggleButton). `collapse_twins` keeps the twin that has an action.
- **Name from content**: list rows and popover menu items have no accessible name of their own; the text is in a child label. Now derived from descendants (depth 2, from the cache when available) — ARIA-style name-from-content. Result: the 2000-row ListView exposes only its ~17 visible rows (virtualisation handled).
- **Actions are uneven**: buttons `click` ✔ (logged `clicked:Delete`, `clicked:Save`); switch `toggle` ✔ (`switch:True`); **check boxes have no action and `grab_focus` is NotSupported**; **page tabs have no action**; list rows only offer `listitem.scroll-to`. New activation ladder: preferred action name (click/press/activate/toggle/…; never scroll/menu helpers) → **Selection on the parent** (`select_child`) → focus → a clear error. Tabs and list rows now work via Selection (`tab:1`, `tab:2` logged). **GTK4 check boxes cannot be activated semantically**: they need the pointer-click fallback (screen coordinates are already available from the KWin bridge). That fallback (RemoteDesktop portal / libei) is the main open item.
- Quirk: elements may report x = -1 (as hints also noted); harmless with centre-based clipping.
- Entry placeholders are not exposed, so GTK4 entries appear as "(unlabeled entry)".

### Electron (VS Code) findings
- Appears on the bus without special flags. First launch exposed **2 nodes** (empty); with `--force-renderer-accessibility` **439–530 nodes**, 79–106 actionable elements (menus, title-bar buttons, activity-bar tabs, tree items, links). Two later launches **without** the flag (one with a fresh profile) were also full (471 nodes), so "needs the flag" is not deterministic; cause not found (timing or one-time Chromium initialisation). The flag is still the safe recommendation.
- Same observation with Chrome (throw-away profile, no flag): on the bus, 4 nodes, 0 elements.
- Activation works: "Toggle Panel" opened the Terminal panel (12 new elements, Terminal entry, Hide Panel…). Electron's default action has an **empty name**; handled.
- **The cache can lag the live tree.** On VS Code the cache path returned 103 elements vs 106 from the walk, consistently: 3 buttons missing from `GetItems`. Every node declares a child count, so nodes whose cached children are fewer than declared mark an incomplete subtree (4 of 533 nodes here). **Repair**: read those nodes' live children and walk only the ones the cache lacks. After the fix: cache = walk = 106 (0 differing lines), at ≈9 ms vs ≈30 ms.
- Speed: cache ≈8–10 ms vs walk ≈30 ms on VS Code (3×).

### Other changes this round
- `pick_action` (+2 unit tests; 9 pass); `switch` role word; "did action '(default)'" for unnamed actions.
- Doctor: **Flatpak false positive fixed** (the ZapZap Flatpak is on the bus but its PID differs; now matched by app name vs window class, only against bus entries whose PID is not another listed window's; the first version wrongly hid the user's Chrome behind a same-named scratch instance, caught and fixed). New "on the bus but empty tree" check (verified with Chrome); system helper windows (`skipTaskbar`) are ignored. Wording about the VS Code flag softened to match the evidence.

### Still open
- Pointer-click fallback (GTK4 check boxes, anything without action/selection/focus).
- Matcher junk tail: scattered-letter fuzzy matches on long labels (e.g. `check` → "Get Started with Accessibility Features") should be filtered; changes ranking, so left for a deliberate pass with tests.
- Cache path assumes node roles ≤129; GTK4 Switch (130) shows the crate limit.
- HiDPI, multi-monitor, Wayland-native Electron (`--ozone-platform=wayland` was not tested separately), Flatpak-sandboxed Electron apps, large real-world pages.

## Update 2026-10-15 (6) — pointer-click fallback
Why: GTK4 check boxes have no action, no selection path and no `grab_focus` (update 5); nothing semantic can activate them.

Design (`src/pointer.rs`):
- Wayland offers clients no input injection and no pointer read-back, so the sanctioned route is the **XDG RemoteDesktop portal** (via `ashpd` 0.13, features `tokio`, `remote_desktop`, `screencast`). The desktop shows **one consent dialog**; approval persists through a restore token (`~/.local/state/vimvibe/pointer-token`, mode 0600, it is a credential). Later sessions start silently.
- The dialog is only ever opened by `vimvibe-core pointer-setup`. `click`, `act` and the daemon call `connect(false)`, which refuses when no token exists, so nothing pops up mid-use. We never touch the dialog programmatically: it is the user's consent. (Not tried: KWin's own `org.kde.KWin.EIS.RemoteDesktop.connectToEIS`, which exists but is meant for the portal backend; it would bypass the consent flow.)
- Absolute motion needs a ScreenCast stream (a second dialog), so motion is **relative with a closed loop**: read the real cursor from KWin (`workspace.cursorPos` via the bridge), send the difference, re-read, repeat until within 1 px (max 8 rounds, error if not within 3 px). Pointer acceleration or scaling does not matter because every step is measured. The cursor is **restored** afterwards.
- Activation ladder (`model.rs`, daemon, `act`): preferred action → Selection on parent → focus → pointer click at the element centre (KWin client origin + rect centre). The last rung is signalled by a typed `NeedsPointer` error; `--no-pointer` disables it, `--force-pointer` exercises it for testing.
- `--app` runs now get screen geometry too (`fill_geometry`: PID → KWin window list, active window preferred).
- Daemon: connects lazily on first need; `Status.pointer` reports `ready` / `set up (connects on first use)` / `not set up`; `Activate` returns `"via":"semantic"|"pointer"`. Doctor has a `pointer` check.

Verified (user approved the dialog once; clicks only inside a purpose-built GTK4 test window, raised first):
- Without a token: `click` and `act` refuse with a message naming the fix, no dialog (checked).
- With the token: second session starts silently. GTK4 check box toggled `True`/`False` alternately across **10 pointer activations** (2 via the CLI, 8 via the daemon, every one logged correctly by the app). Click point (377, 218) = window origin (303, 104) + element centre (74, 114), as computed.
- `--force-pointer` on 10 targets across the window (Save at the x=-1 edge, Cancel, Delete, Apply, switch, three tabs, a list row, the check box): **9 of 9 loggable controls hit the right one** (the list row does not log).
- Cursor restored to the exact starting position (710, 482) after every run.
- Timing: ≈101 ms per pointer activation through the daemon (dominated by deliberate waits: 20 ms press, 40 ms before restoring, 12 ms between motion rounds, plus a KWin script read per round); semantic activation stays ≈0.3 ms.
- Non-click elements still use the semantic path (`"via":"semantic"`).

Bugs found and fixed on the way:
- KWin reported a **fractional window position** (175.07) and the strict integer parser rejected the whole window list; geometry is now rounded in all three KWin scripts (this could also have broken focus tracking).
- All KWin sessions in one process shared one D-Bus name, so in the daemon every one-shot query (cursor, window list, and the focus fallback) failed silently while the watcher held it. Names are now unique per session.

Limits / open:
- Scale factor was 1.0; HiDPI and fractional scaling untested (cursor positions are logical pixels on both ends, which should cancel, unverified). Multi-monitor and rotated outputs untested.
- Clicks assume the target window is on top at that spot (it is focused and the palette is closed first). A window with a popup or tooltip over the element would receive the click instead.
- With several windows of one app and none active, `--app` takes the first KWin window of that PID.
- Only left click (right/double exist in the CLI, not yet in the daemon API); drag and scroll not implemented.
- Revoke the grant any time in System Settings → Security & Privacy → Remote Control (or delete the token file).
- Chrome/Electron elements outside the viewport, and elements hidden behind overlays, are not detected before clicking.

## Update 2026-10-16 (7) — live keyboard test, two daemon bugs, flag overlay

### Live test with the real shortcut (user at the keyboard)
- Meta+Shift+Space opens the palette with keyboard focus in the field (CONFIRMED in the palette's debug log, 8 opens).
- **Bug 1, focus watcher dead (fixed).** Every open targeted the window focused when the daemon started. Cause: the tokio task that consumed KWin reports captured only `session.rx` (Rust 2021+ disjoint closure capture), so the rest of the `Session`, including the zbus connection that owns the bridge name, was dropped; KWin's `callDBus` reports went nowhere. Fix: move the whole session into the task. Verified: switching windows by KWin script updates `Status().focus`, then Trigger → Search "save" → Activate clicks Save in the GTK4 app.
- **Bug 2, Enter never activated (fixed).** `Activate` took `u32`; Qt/Python clients send a plain int as `i32`, so zbus rejected every call ("Signature mismatch"). The method now takes `i32` and rejects negative indexes.
- **Bug 3, disabled elements were clicked (fixed).** A disabled Konsole "Copy" button was clicked through the pointer fallback. `Element::activate` now refuses disabled elements.
- Test hygiene: a leftover KWin test script of mine stayed loaded and interfered with the daemon's script; test scripts are now unloaded after each use.
- Still untested: keystrokes typed between the chord and the overlay appearing (no keyboard grab yet).

### Flag overlay (palette rewrite, Shortcat-style)
- One transparent fullscreen window on the target window's screen holds the search panel and draws a flag on matched elements: numbered pills (`⌃1`…`⌃9`, same numbers as the rows, Ctrl+digit activates) with outlines for the rows on screen, a filled highlight for the selected one, faint outlines for the other matches. Positions come from `Search`'s `screen` field (KWin window origin + AT-SPI extents).
- The panel goes where it hides the fewest flags (above / top / middle / bottom / below the target window); while typing it moves only if it would hide the selected element. It shrinks to its row count.
- Mouse: click a row or a flagged element to activate; click elsewhere to dismiss; wheel moves the selection.
- Colour: blue (`#3b82f6`) by default; `--accent COLOR`, `$VIMVIBE_ACCENT`, or `[ui] accent = "..."` in `~/.config/vimvibe/config.toml`; badge text switches to black on light accents.
- Verified by rendering only the overlay window's own pixels (`--snapshot`, transparent elsewhere; nothing of the screen behind is captured): GTK4 test app, queries "", "save", "item 3", blue and orange. Element boxes line up with the controls' positions from `list`. Scale 1, single 1366×768 screen only.
- Limits: a normal (non layer-shell) fullscreen window, so panels/notifications may sit above it and the compositor may animate it; HiDPI and multi-monitor untested; flags for elements scrolled out of view are skipped (clipped to the screen, not to the window's viewport).

### Letter labels on every element (Shortcat "hints"), replacing the numbered flags
Shortcat behaviour, from its public docs (shortcat.app/docs/features/selection, /configuration-options; CONFIRMED as documentation, not observed by us): every element gets a 1–2 character hint "usually based on the first few words of its label"; black-on-yellow; shown after a delay (default 2 s; options immediately … 5 s, or "after input"); typing a hint selects the element; Option clears the query and shows all labels; the selected element is highlighted light green; Cmd+number picks one of the top 10 results. From the user's screenshots (SUPPORTED INFERENCE): labels sit at the element's right edge, vertically centred, and overlap freely in dense areas; while typing, only labels starting with the typed letters stay visible.

What we built:
- `core/src/hints.rs`: unique 2–3 character hints per element, in reading order. Candidates, best first: initials of the first two words (Pull requests → PR), first-word prefixes (CH, PRO), three initials, first letter + later letters, then free combos. Nameless elements (and the enumerator's "(unlabeled …)" placeholders) get free combos (AA, AB…). No single letters: labels share the search field, so a one-letter label would hijack every one-letter search. Deterministic, so a window keeps its labels across triggers. 10 000 elements in ~21 ms (release, unit test).
- Daemon: `Elements()` returns every element with id, hint, and screen rectangle; `Search` hits carry `id` and `hint`, and a query equal to a hint puts that element first; `ActivateId(id)` for clicked labels.
- Overlay: a label on every element (accent colour, default blue; text black or white for contrast), right edge and vertically centred, shifted left inside its element when two would collide; typed letters dimmed (as in Vimium) and labels not matching the typed prefix hidden; the selected element filled; rows show label, role, ⌃ and number; tapping Alt clears the query and shows all labels; clicking a label activates it. Config `[hints] delay_ms` (default 0, Shortcat uses 2000) and `auto_activate` (default false; true = Vimium-style, a complete unique label clicks without Enter).
- Verified on the GTK4 test app: 32 elements → 32 labels (SA Save, MM Main menu, CA Cancel, EF Enable feature, LL Long list, AA for the nameless entry…); `Search("ca")` + `Activate(0)` clicked Cancel; `ActivateId(13)` selected the Advanced tab; overlay images rendered from the window's own pixels for the empty query, `i` and `ca`.
- Not done: Ctrl+Enter right click (the daemon only exposes left click), Space → arrow-key scroll, "after input" delay mode, label layering for overlapping labels; untested on large real windows (Chrome/VS Code) with the overlay.

## Update 2026-10-16 (8) — Shortcat features, excluded apps, settings, packaging

Shortcat's documented features (docs: features/actions, arrow-scroll, continuous-mode, using-shortcat-efficiently,
configuration-options, compatibility, common-issues; changelog) were mapped one by one; the parity table is in the
top-level README. Implemented this round (all tested on the GTK4 test app unless noted):
- **Excluded apps** (`[apps] exclude` in `~/.config/vimvibe/config.toml`, `core/src/config.rs`): matched against the
  KWin class (and its short form), the process name and the AT-SPI app name; checked **before** the tree is read; the
  daemon emits `Refused` and the overlay shows a notification. Verified: excluded GtkTest → `{"excluded":"GtkTest"}` and
  one `Refused` signal; the daemon re-reads the file on every trigger.
- **Actions**: `ActivateWith(id, click|right|double|middle|hover|focus)`. Verified right click and double click through
  the portal (double click on a GTK4 check box registers once in the app's log), focus on a GTK4 entry (GTK4 refuses
  `grab_focus` → falls back to a click, for text fields only), unknown action rejected.
- **Window switching**: other normal windows (incl. minimised) from a KWin script become `Window` results; raised by
  internal id (validated as a UUID before it goes into the script). Verified: "konsole" → Window result.
- **Refresh** (`Refresh()`, Ctrl+R) re-reads the same window. Verified.
- **Bug fixed**: when the focused window's app is not on the accessibility bus (here the user's Chrome started before
  a11y was on), the daemon fell back to an unrelated "active" accessible (plasma-keyboard) and opened an empty palette.
  Now it only accepts a PID match or an exact title match and otherwise refuses with an explanation.
- **Overlay**: Ctrl+Enter right, Alt+Enter double, Shift+Enter middle, tap Ctrl hover, double-tap Ctrl focus,
  Ctrl+Shift+n select, Ctrl+R, label delay incl. "after input", continuous mode (re-trigger after N ms; stops on text
  fields/menus/windows), panel position, label size, right-click on a label. The key handling itself is untested with a
  real keyboard (no synthetic input here).
- **Settings window** (`vimvibe_settings.py`): five tabs; saving writes valid TOML (verified with quotes/backslashes in
  app names, parsed by Python and by the daemon) and the XDG autostart entry for "launch at login".
- **Packaging**: `install.sh` (build + install to `~/.local`, `--uninstall`), launcher `vimvibe`
  (start/stop/restart/status/settings/doctor/logs/open). Verified in a scratch `$HOME`: install, start, status, logs,
  stop (no processes left), doctor.
- Plan for menus, tray, launcher, other desktops: research/11.

## Update 2026-10-16 (9) — first user run from source: fixes

User report: pressing the shortcut over Plasma's application launcher showed labels but the launcher closed; Dolphin and
the image viewer failed; the terminal filled with "ExcessNotificationGeneration".
- Cause of the failures (CONFIRMED with `doctor`): session accessibility was **off** (my test cleanup turns it off), so
  apps were invisible and every press sent a "can't read this window" notification until KDE rate-limited them.
  Fixes: the daemon turns accessibility on at start (`[accessibility] enable_on_start`, default true; verified log line
  and `status`); with it off, Trigger now says so explicitly (verified); identical notifications are sent at most once
  per 15 s.
- Plasma launcher: its popup (plasmashell) closes when another window takes the keyboard, so the snapshot's elements
  disappear. The daemon now refuses plasmashell/KRunner focus with an explanation (KWin class list; the live case is
  untested because opening the launcher needs the user). Real support needs a non-focus source (planned: `.desktop`
  app search, StatusNotifierItem tray, research/11).
- Quit: second global shortcut **Meta+Shift+Q** (checked free with kglobalaccel `isGlobalShortcutAvailable`), D-Bus
  `Quit()`, signal `Quitting`; the overlay exits on `Quitting` or when the daemon's bus name disappears. Verified with
  kglobalaccel `invokeShortcut quit` (the same path as a key press): daemon and overlay exit, key released; overlay also
  exits after `kill -9` of the daemon; `invokeShortcut toggle` still opens the overlay. `vimvibe stop` uses `Quit`.

## Update 2026-10-16 (10) — user report: unlabelled title bars, Places click, start menu

- **Title-bar buttons had no labels** (Dolphin, Gwenview, Okular): KWin draws server-side decorations, so close /
  maximize / minimize are not in the app's AT-SPI tree. Added `decor.rs`: positions estimated from KWin frame vs client
  geometry and `kwinrc [org.kde.kdecoration2] ButtonsOnLeft/Right` (Breeze default "MS" / "HIAX"; help hidden), only
  for windows with a server-side border; activation runs KWin ops (`closeWindow`, `minimized`, `slotWindowMaximize`,
  `onAllDesktops`, `keepAbove/Below`, `slotWindowOperations`), never a click. Verified on a Dolphin window (frame
  211..1155): Close label at 1128..1148, matching the user's screenshot; maximize → 1366×768, again → 944×598;
  minimize → focus moves; the minimised window is found as a Window result "(minimized)" and raised.
- **Places → Pictures did nothing**: Qt list items expose only a "Toggle" action, which changes selection without
  opening the place, and vimvibe reported success. Now, when a pointer click is available, list/tree/table items whose
  only actions are toggle/select are clicked instead, and focusing a non-text element is no longer counted as
  activation. Verified: Dolphin navigated to Pictures.
- **Start menu**: plasmashell popups close when the overlay takes the keyboard (unchanged). Instead of refusing, the
  overlay now opens in **launcher mode** over them: installed applications (`apps.rs`, XDG `.desktop`, NoDisplay /
  OnlyShowIn honoured, localised names, GenericName/Keywords searchable) and open windows. Apps are also results in
  every window when typing (setting `[search] apps`). Verified: "calculator" → KCalc → launched; then its "Close
  window" label closed it. Launcher mode itself not yet seen live (needs the user to open the start menu).
- **Ranking**: with an empty query, results were sorted by position and windows (position 0,0) came first. Empty query
  now lists only the window's own elements (title-bar buttons last); while typing, windows/apps rank 60 points below
  an equal element of the current window.
- Overlay: crowded labels (adjacent 20 px title-bar buttons) move below/above the element instead of overlapping.
- Open time with apps + windows: 24–28 ms warm (first open after boot 77 ms), vs ~15 ms without them.

## Update 2026-10-16 (11) — labels on the open start menu (passive overlay)

User report: the start menu closes as soon as vimvibe opens. Plasma's popups hide when they lose keyboard focus, and
every way of showing a normal window takes it.
- Measured: a Qt window with `WindowDoesNotAcceptFocus` / `WA_ShowWithoutActivating` / `Tool` is still activated by
  KWin on Wayland (the launcher closes). A **layer-shell surface with keyboard interactivity None** is not: shown full
  screen (1366×768, layer Overlay) while the launcher kept focus. layer-shell-qt 6.7.5 is installed with Plasma (only
  its -devel package is missing; 10 §4 was wrong to call it not installed); Python reaches it through
  `LayerShellQt::Window::get(QWindow*)` via ctypes, the rest are Qt properties (layer, anchors, keyboardInteractivity,
  exclusionZone, scope).
- Keys without focus: the AT-SPI registry's keystroke listener (what screen readers use). Qt 6 sends every key press
  to the registry with `NotifyListenersSync` and waits for "consumed". Findings: `RegisterKeystrokeListener` answers
  `false` on Wayland but the listener is stored and called; events go *to* the registry as `(uinnisb)` but the registry
  calls listeners with `(uiuuisb)` (seen with dbus-monitor; introspection data says `(uiuuisb)` for both); listeners
  match exact modifier masks, so plain/Shift/CapsLock/NumLock masks are registered and Ctrl/Alt/Super pass through;
  calls to a vanished listener count as not consumed (keys flow again if vimvibe dies), but the registry keeps dead
  entries until logout (8 from my first experiment remain this session; cost not measurable).
- Built: daemon popup mode (focus class plasmashell/krunner) reads the popup's own elements (Kickoff: 31 elements,
  geometry from KWin), registers the listener while open, forwards keys as a `Key` signal, handles Esc itself, and
  releases after 60 s without a key; overlay `Router` sends passive opens to a layer-shell overlay (`make_passive`).
  The panel can now sit beside a narrow target.
- Verified, with the launcher opened through `org.kde.PlasmaShell.activateLauncherMenu` and keys injected the way Qt
  sends them (`NotifyListenersSync`): menu keeps focus while the overlay shows 31 labels; "s","h" consumed and the
  overlay's selection follows (SL → SD); Ctrl+p not consumed; Esc closes and releases (next key not consumed);
  "Graphics" activated through Kickoff's own Press action, menu stayed open and switched category. Not yet verified
  with real key presses (needs the user).

## Update 2026-10-16 (12) — taskbar, typing over the start menu, nested menus

User report: the taskbar had no labels; typing `in` over the start menu went into Kickoff's own search instead of
vimvibe; opening vimvibe over Konsole's Split View submenu closed the menu.
- **Keys over popups weren't reaching vimvibe.** The earlier test called the registry's `NotifyListenersSync` directly,
  bypassing Qt. Qt's AT-SPI bridge installs its key-forwarding filter only while some client is registered for
  accessibility events (from recollection of Qt's `qspiapplicationadaptor`/`atspiadaptor` sources; SUPPORTED
  INFERENCE, not read on this machine). Nothing was registered, so Qt never forwarded keys. Now the daemon registers
  `object:state-changed:showing` (needed for menus anyway), which turns Qt's forwarding on. Real key presses
  **still need the user to verify**: no synthetic keyboard input is available here.
- **Open menus**: Qt leaves popup menus out of the tree (the app lists only its frame; the menu button has no
  children). With the event registered, Qt emits `object:state-changed:showing` on a `popup menu` object whose size
  equals KWin's popup surface (Dolphin: 312×400). `popups.rs` tracks showing menus; the daemon pairs them with KWin
  popup surfaces (new `kwin::surfaces`: dock/popup/window with frame geometry) of the focused app by size and moves
  their entries into the snapshot's coordinates; any open popup → passive overlay.
  - Deadlock found and fixed: awaiting a D-Bus call inside the signal-draining loop stalled the whole connection
    (Trigger timed out after 25 s); role lookups now run in spawned tasks.
  - Qt menu entries carry no Showing/Visible state while open, and actions shared with other menus (Dolphin's
    hamburger menu reuses menu-bar actions) report geometry from *that* menu (widths 240/286/327 in a 304-wide menu).
    Entries are taken from the menu's direct children; mismatched widths get their row rebuilt by hit-testing
    `GetAccessibleAtPoint` every 4 px down the menu's middle (Qt answers from the menu itself). Result for Dolphin's
    hamburger menu: 11 entries, y 158..520, one row each; snapshot 51–56 ms.
  - Nested: activating "Configure" opened its submenu (pointer click; the parent stayed open); the next trigger found
    2 menus and labelled the submenu's entries at (724, 461..587).
- **Panels**: plasmashell's AT-SPI windows paired with KWin dock surfaces by size (panel 911×62 at (228,706)):
  21 elements (launcher, desktops, tasks, tray icons). Labelled in every snapshot (`[search] panel`).

## Update 2026-10-16 (13) — settings shortcut, theming, scrolling

- **How Shortcat scrolls** (docs "Arrow Keys / Scroll", alpha; changelog 0.11.0; CONFIRMED as documentation): while
  Shortcat is active, hold Space and tap H J K L (or I J K L, chosen in preferences) to send arrow keys to the target;
  hold Space + Cmd + those keys to send scroll events under the pointer; tapping Ctrl moves the pointer to a result's
  midpoint "to position for scrolling". Designed for continuous mode.
- **vimvibe**: hold Space + H J K L (or I J K L) scrolls; Shift ×4. Daemon `ScrollStart(id)` parks the pointer over
  the selected element (when a query is typed) or the window centre, `Scroll(dx, dy)` sends wheel clicks through the
  RemoteDesktop portal, `ScrollEnd()` restores the pointer; on Space release the overlay calls `Refresh`. During the
  scroll the overlay sets `WindowTransparentForInput` so the wheel events reach the app below.
  - Measured on Dolphin (300 files, icon view): `NotifyPointerAxisDiscrete` scrolls exactly and reverses exactly
    (30 clicks down: first visible file-160 → 140, 30 up: back to 160). `NotifyPointerAxis` (smooth) was unreliable
    (both signs scrolled down); only discrete is used. Overlay test with real overlay code and synthetic key events
    (Space, J×3, release; step 10): view moved 3 rows (160 → 145), query stayed empty, pointer restored to
    (1010, 486), labels re-read (65 → 60).
  - Arrow keys are not sent: that needs the portal's keyboard device (a new consent); planned.
- **Settings shortcut**: third kglobalaccel action `settings` with Ctrl+Shift+Comma and Ctrl+Shift+Less (the same
  keys with Shift on most layouts); `OpenSettings` signal; the overlay process opens one Settings window. Verified with
  `invokeShortcut settings`: a 760×708 window appeared and was active; it closes with the daemon.
- **Theming** (`palette/vimvibe_style.py`): presets (Blue, Shortcat, Nord, Dracula, Gruvbox, Solarized light, High
  contrast), label background/text/outline/selected colours, font, label font size, overall size, radius, case;
  panel style/opacity/width/rows/font size/hint line/hide-until-typing; screen dim. The Settings preview draws with
  the same `Theme.draw_label` the overlay uses. Verified by rendering the Settings window offscreen and the overlay
  window's own pixels with the Shortcat preset.

## Update 2026-10-16 (14) — Space + H/J/K/L arrow keys (keyboard permission)

- Why a permission: Wayland gives no client a way to inject keys into another; the sanctioned route is the
  RemoteDesktop portal's keyboard device (separate from the pointer device in the consent dialog). uinput (root) and
  AT-SPI `GenerateKeyboardEvent` (X11 only) are not options.
- `pointer-setup` now asks for pointer + keyboard and records the granted devices next to the token
  (`granted-devices`); later sessions request exactly those, so the existing pointer-only grant keeps working with no
  surprise dialog. `doctor` reports whether the keyboard is allowed.
- Focus problem: keys go to the focused window, which is the overlay while it is open. Arrow mode therefore closes the
  overlay (the app gets the keyboard back) and takes the physical H J K L / I, Space and Esc keys through the AT-SPI
  keystroke listener (new mode `MODE_ARROWS`, matched by X keycode so other layouts work); H/J/K/L presses become
  arrow keysyms through the portal; Ctrl/Alt masks are registered so physical modifiers combine with the injected
  arrow (Space+Shift+J = Shift+Down); everything else, including the injected arrows, passes. Space release ends the
  mode and reopens the overlay; Esc ends it; the 60 s idle release still applies.
- Safety check: only apps that forward keys to the registry (Qt, GTK 3) can be handled; elsewhere (Chromium, GTK 4)
  the user's J would be typed into the app. `ArrowStart` taps Shift through the portal and requires the listener to see
  it within 400 ms, otherwise it reopens the overlay and explains. Scrolling moved to Space+Ctrl+H/J/K/L (Shortcat:
  Space+Cmd); without the keyboard grant Space+H/J/K/L falls back to scrolling with a notice.
- Verified without the keyboard grant (current state): Space+J ×3 → fallback notice + scroll (Dolphin 300 → 295),
  Space+Ctrl+J ×3 → scroll (295 → 285), query untouched. Unit test for HJKL/IJKL keycode mapping (19 tests pass).
- After the user granted pointer + keyboard (`granted-devices` = `pointer,keyboard`, doctor OK), tested with real
  key presses typed into Dolphin through the portal (new `vimvibe-core key` test command), i.e. the same path as the
  user's own keys:
  - First attempt failed (bug): the overlay called `ArrowStart` with a blocking call while still visible, so the Shift
    check was satisfied by vimvibe's own window and the arrows and the user's keys went to the frozen overlay; the
    60 s idle release then fired (that safety net works). Fixed: the overlay hides first and calls asynchronously; the
    daemon waits until KWin reports the target app active again before the check.
  - Then: Space+J in the overlay → overlay hidden, Dolphin focused, ↓ (selection file-295 → 290, one row); `j j j`
    typed into Dolphin → consumed and turned into ↓×3 (290 → 275, no type-ahead jump); Space released → overlay
    reopened with a fresh snapshot.
  - GTK4 test app (no key forwarding): the Shift check failed, the user got "dev.vimvibe.GtkTest doesn't share its key
    presses with accessibility …", the overlay reopened, and no listener stayed registered.

## Update 2026-10-16 (15) — scrolling did nothing for the user: Ctrl + wheel

User report: scrolling doesn't happen at all. Reproduced with real key presses typed through the portal into the real
overlay (my earlier overlay test sent Qt key events straight to the widget, which hid this): Space+Ctrl+J ×3 → 0 px.
Isolated: the daemon scrolling alone moves Dolphin ~10 px per wheel step; the same overlay scroll path driven by real
Space+J (no Ctrl) moves it ~1 row; with Ctrl held the wheel is ignored (apps treat Ctrl+wheel as zoom; Dolphin neither
scrolled nor zoomed for 3 steps). So the Space+Ctrl chord (a straight copy of Shortcat's Space+Cmd) cannot work on
Linux; Shift+wheel is horizontal and Alt+wheel is "back" in some browsers, so no modifier is safe.
- Scrolling is now Space + D / U (no modifier; Shift ×4), default 5 wheel steps per press (3 steps ≈ 33 px in Dolphin
  was barely visible). Space + H/J/K/L stays arrow keys and now also takes Ctrl (Space+Ctrl+J = Ctrl+Down).
  D / U also work while arrow mode is on (the daemon scrolls the window centre; pointer restored at the end).
- Verified with real key presses: Space+D ×3 → ~95 px down, Space+U ×3 → back up, pointer restored, overlay reopened;
  Space+J (arrow mode) then D D → Dolphin selected file-295 and scrolled, pointer restored on Space release.

## Update 2026-10-16 (16) — Space+HJKL scrolls again, scroll settings, dev/stable profiles

- **User report**: Space + J/K/H/L "did not work" (D/U did). The screenshot's `^[[B ^[[A ^[[D ^[[C` were arrow keys
  arriving in the user's terminal: HJKL had become *arrow keys* (update 14) and the target window was Konsole, so
  nothing scrolled. The first version (HJKL = scroll) was what they wanted. HJKL now **scrolls** by default
  (`[scroll] hjkl = "scroll"`), arrow keys moved to Space + Ctrl + HJKL; the setting swaps them. Ctrl is also held
  physically when the first arrow is injected (measured: Ctrl+Down moves Dolphin's focus without selecting), so the
  chord that *enters* arrow mode sends no arrow; later presses are plain.
- Verified with real key presses typed through the portal into the real overlay (Dolphin, 300 files): Space+J ×3 →
  scrolled ~2 rows, Space+K ×2 → back, nothing selected; natural=true reverses the direction (also with smooth off);
  Space+Ctrl+J, release Ctrl, J J J → selection moved 3 rows (arrow mode); pointer restored.
- **Scroll settings** (daemon applies them per press, reading config each time): distance (`step`), Shift multiplier
  (`fast`), smooth animation (`smooth`, `smooth_ms`: clicks scheduled on an ease-out cubic, unit-tested), natural
  direction, swapped left/right (`invert_horizontal`). Settings window group "Scrolling and arrow keys".
  Horizontal direction was not verified in an app (the Dolphin icon view has no horizontal scrolling): H = left,
  L = right as in Vim; "swap" is there for the opposite expectation.
- **Profiles** (`VIMVIBE_PROFILE=dev`): own D-Bus name (`org.vimvibe.DaemonDev`), kglobalaccel component
  (`vimvibe-dev`, keys Meta+Alt+Space / Meta+Alt+Q / Ctrl+Alt+, checked free), settings dir (`~/.config/vimvibe-dev`,
  read-fallback to the installed settings, never written), logs; the pointer/keyboard grant is shared (the portal
  identifies the app, not the profile). `dev.sh` runs the source tree as `dev`; the launcher finds each daemon by
  bus name (`busctl status`) and overlay by script path + profile. Verified in a scratch HOME: installed + dev
  running together, the dev toggle shortcut opened only the dev snapshot, stopping dev left the installed one and its
  shortcuts registered. `install.sh` is an in-place upgrade (stops a running installed copy, reinstalls, restarts it;
  verified: new daemon pid, version 0.2.0). Version bumped to 0.2.0 (`vimvibe version`).
