# 10 — Prior-art analysis: vimium-everywhere, swiftmouse, hints

Method: shallow clones read statically (nothing built or run); one live AT-SPI experiment on this machine (Collection interface). Evidence tags as in 04. Statements about speed that come from a README are marked *(author claim)*, not measured by us.
Repos at the commits read: vimium-everywhere `0e93670` (2026-05-30, GPL-3), swiftmouse `4c19d08` (2024-07-20, **no LICENSE file**), hints `1b23d72` (2026-06-27, GPL-3, ~4.3k lines Python).

**Licensing consequence:** we take ideas and published protocols only. No code is copied: swiftmouse has no licence (all rights reserved by default) and the other two are GPL-3, which would bind vimvibe's licence (not chosen yet).

## 1. What each one actually does (CONFIRMED by reading code)

### vimium-everywhere (AutoHotkey, X11 only)
- One AHK script (~9 KB) on AHK_X11. Element discovery = AHK `WinGet ControlList` + `ControlGetPos`, which walks AT-SPI recursively *per call*. Author: 0–3 s per window, "no way to improve" apart from precomputing; lists with >1000 children are skipped.
- Two modes: "normal" (continuous background rebuild on every key/mouse event + 300 ms title polling, so `f` appears instant; CPU-hungry, buggy) and "simple" (build on hotkey; recommended by the author).
- Hints drawn as a transparent AHK GUI with buttons; selection confirmed with Space. Needs a compositor.
- README is the most useful part: a per-toolkit compatibility matrix (Firefox `GNOME_ACCESSIBILITY=1`; Chromium/Electron `ACCESSIBILITY_ENABLED=1` + `--force-renderer-accessibility`; Qt `QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1`; Java needs the ATK bridge; Tk/Wine/games unsupported). Windows support was dropped.
- Pros: tiny, simple-mode is zero background cost. Cons: X11 only, slow tree walk, depends on an obscure runtime, no Wayland.

### swiftmouse (Rust, screenshot-based, no accessibility tree)
- Global trigger: a D-Bus method `com.quexten.swiftmouse.Run` that the user binds in their DE (zbus). Screenshot through PipeWire (`scap`), fallback to the screenshot portal, fallback to `xcap`.
- Vision pipeline in `daemon.rs`: 3×3 edge kernel on a 2× downsample, rayon-parallel, flood-fill connected components into boxes, heuristics: height ≤15 px → text, large boxes (>300 px) → images/video, nearby text boxes merged into lines → "links". UI mode keys: a=image, o=lines, e=boxes, u=links. Click via RemoteDesktop portal (ashpd), with a persisted restore token.
- README claim: ~100 ms for 1080p, 300–400 ms for 4k on an i7 mobile *(author claim)*.
- Observations: it never reads labels, so there is no "type the name of the button"; hints are positional. Code reads as an early prototype (debug files written to `/tmp/screenshot.png` on every trigger, large commented-out blocks, the downsampled map allocated square `width/2 × width/2`, last commit July 2024).
- Pros: works on anything visible, including apps with no a11y; no per-app setup; the portal-based capture/click stack needs no root. Cons: no semantics (cannot search by name or role), false positives/negatives on gradients and dark themes, video/image areas need heuristics, screenshots are privacy-sensitive, cost scales with pixels.

### hints (Python/GTK3, most complete)
- Architecture: client `hints` ↔ warm daemon `hintsd` over a Unix socket (pickle messages, polled every 10 ms via GLib timeout). The daemon pre-imports GTK/AT-SPI, pre-warms Cairo fonts, caches the active accessible via an AT-SPI `window:activate` listener (so no tree search per trigger) and reuses one overlay window.
- Discovery: backends in order `atspi`, then `opencv` (screenshot → grayscale → Canny → dilate → contours → bounding boxes; the same idea as swiftmouse but in OpenCV and window-cropped).
- AT-SPI backend: uses the **Collection interface** (`get_matches` with a `MatchRule`: states SENSITIVE+SHOWING; roles = *everything except* containers/text) which is one D-Bus round trip; falls back to recursive child walk if the app lacks Collection. Elements with window-relative x or y < 0 are dropped.
- Geometry: on Wayland or GTK4 it uses window-relative extents plus the focused window origin; elsewhere SCREEN coordinates. Per-toolkit special case (GTK4 `-1` offsets). Focused-window origin on Plasma comes from a KWin script (`clientGeometry`, `pid`, `resourceClass`) loaded over D-Bus, with **output read back by parsing `journalctl`** (slow, fragile). This confirms our own finding (08 R9) that the origin must be KWin `clientGeometry`.
- Matching the AT-SPI window to the compositor's focused window is done by **PID**, to ignore tray apps that keep a stale ACTIVE state and `mutter-x11-frames`. (Our prototype had the same trap with `plasma-keyboard`; PID matching is the better fix than my title heuristic.)
- Overlay: GTK3 POPUP window; on Wayland `gtk-layer-shell` (OVERLAY layer, anchored top-left with margins, `KeyboardMode.EXCLUSIVE`); on X11 a seat keyboard grab; GNOME needs a shell extension. Hint labels are uniform-length strings from `itertools.product(alphabet, repeat=ceil(log n / log |alphabet|))`; overlapping hints are put on "layers" by greedy colouring and toggled with Space.
- Actions: **clicks are synthetic mouse events through `uinput`** (two virtual devices, relative + absolute), so it works on X11 and Wayland but needs `/dev/uinput` permission → a `sudo` setup script. Modifiers pick the action (shift=right click, alt=drag, ctrl=hover, digit=repeat). hjkl move/scroll the pointer with speed ramp-up via a tiny keyboard-intercepting window. It never calls the AT-SPI `DoAction`.
- Pros: broadest compositor coverage (X11, GNOME, sway, Hyprland, niri, KDE), mouse-like actions, layering, a warm daemon. Cons: Python+GTK3+OpenCV+numpy footprint, root setup, polling loop, pickle IPC, journalctl hack, geometry heuristics, drops partially visible elements, no text search (letters only), no semantic ranking.

## 2. Comparison

| Dimension | vimium-everywhere | swiftmouse | hints | vimvibe (target) |
|---|---|---|---|---|
| Discovery | AT-SPI via AHK walk | pixels only | AT-SPI (Collection) + OpenCV fallback | AT-SPI (Collection/BFS) + optional pixel fallback |
| Search by name | no | no | no (letters) | **yes** (fuzzy, roles, synonyms) |
| Wayland | no | yes (portals) | yes (layer-shell, per-compositor) | yes (Plasma first) |
| Actions | AHK click | portal click | uinput mouse | **AT-SPI DoAction first**, input fallback |
| Needs root | no | no | **yes (uinput)** | no (target) |
| Latency model | rebuild on demand or poll | screenshot per trigger | warm daemon + cached window | warm daemon + event-driven cache |
| Footprint | AHK_X11 | Rust + egui | Python+GTK3+cv2 | Rust core (≈ one small binary) |

## 3. Design decisions this supports for vimvibe

1. **Semantic first, pixels as a last resort.** Both pixel tools and the AT-SPI tool prove users want coverage of apps with no a11y; but pixels lose the one thing Shortcat is about (names). Tier 1 = AT-SPI; Tier 2 (later, optional crate feature) = edge/contour boxes for hint-only mode (no name search) on windows where Tier 1 returns nothing.
2. **Use Collection `get_matches` when available, BFS otherwise.** Measured here (UNIT: KCalc, Qt): Collection present, 30 matches in 2 ms in one call. Our BFS already takes ~4 ms on KCalc and ~40 ms on Dolphin, so the win is for large trees (browsers, IDEs). Both paths must clip to window bounds (my Dolphin finding: virtualised rows report Showing off-screen). Open: does Firefox/Chromium implement Collection and is it faster than BFS? Needs a test.
3. **Warm daemon, event-driven, no polling.** Keep the process resident (hints), but replace its 10 ms poll with the D-Bus/zbus event loop; subscribe to AT-SPI `window:activate` and a persistent KWin script (signal → D-Bus `callDBus`, not journalctl) to know the focused window and geometry before any trigger. Zero CPU when idle (vimium's continuous rebuild is the cautionary tale).
4. **Match AT-SPI window ↔ compositor window by PID (+ title)**, not by "first ACTIVE frame".
5. **Do the action semantically.** `DoAction`/`GrabFocus` avoids uinput's root requirement and Wayland pointer-warp problems (swiftmouse/hints both need synthetic pointers). Fallback ladder: DoAction → AT-SPI `Component` focus → RemoteDesktop portal/libei pointer click at element centre (restore-token pattern from swiftmouse; no root) → uinput only if the user opts in.
6. **Overlay**: Plasma and wlroots support `wlr-layer-shell` (hints relies on it); GNOME needs an extension; X11 needs a keyboard grab. Keep hint rendering behind a trait so the Plasma layer-shell path can ship first.
7. **Hint labels**: use a variable-length prefix-free scheme (home-row keys first, shortest codes for the nearest/highest-ranked elements) instead of fixed-width `product()`; apply overlap layering like hints; keep "type the name" as the primary path, hints secondary (matches Shortcat docs: hints appear after a delay).
8. **Low-end machines**: Rust, no GUI toolkit in the core, bounded time budget with TRUNCATED results (already in prototype), cap on nodes, skip hidden subtrees, optional prefetch only for the focused window and only on idle. Pixel Tier 2 must stay off by default (costly on 4k, per swiftmouse's own figures).
9. **Compatibility onboarding**: ship vimium-everywhere's toolkit matrix as an in-app "doctor" (a11y flag, `--force-renderer-accessibility` for Chromium/Electron, Firefox/Qt env flags, Java bridge), because most "doesn't work" reports will be a11y not being enabled.
10. **Don't drop partially visible elements** (hints does): clip instead (we already do).

## 3b. Measured afterwards (see 09, update 2)
- Collection `get_matches` (hints' fast path) was **not** faster than our concurrent tree walk on Qt or Chrome, and returned closed-menu items. The AT-SPI **Cache** (`GetItems`) was: ~2× faster on Chrome (≈100 ms vs ≈200 ms, 222 visible of 9430 nodes) and slightly faster on Firefox, but Qt does not expose it, so the walk stays as fallback.
- PID matching and a KWin bridge (reports over our own D-Bus service, no journalctl) are implemented and verified on Plasma 6.

## 3c. GTK4 / Electron results (see 09, update 5)
hints' README admits GTK4 needs special handling (extents, `-1` offsets); our measurements agree it is the hardest toolkit: no Cache/Collection, nameless list rows, switch role outside the crate's enum, check boxes with no action and no focus. A semantic-first design therefore needs the pointer fallback that hints (uinput) and swiftmouse (RemoteDesktop portal) already have. Electron works well once its tree exists, and Chromium's cache can lag the live tree (repairable from declared child counts).

## 4. Unverified / to measure on this machine
- Very large trees (a real 10k-node page), Wayland-native and Flatpak Electron apps.
- Whether `wlr-layer-shell` with exclusive keyboard focus works on this KWin 6.7 as hints assumes (needs `layer-shell-qt`/gtk-layer-shell; not installed).
- RemoteDesktop portal click path (needs the user to approve a prompt once).
- All speed figures quoted above for swiftmouse/hints/vimium are author claims.
