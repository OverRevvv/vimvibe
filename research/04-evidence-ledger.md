# 04 — Evidence ledger

Class: C=CONFIRMED, S=SUPPORTED INFERENCE, U=UNVERIFIED, X=UNSUPPORTED. "Obs" = observed directly / inferred. All web pages read via summarising fetch (paraphrase risk) on 2026-10-13.

| ID | Question | Finding | Source / location | Obs | Class | Limitations | Next action |
|---|---|---|---|---|---|---|---|
| E-001 | Host OS/desktop | Fedora 44, Plasma 6.7.5, Wayland | `cat /etc/fedora-release`, `$XDG_SESSION_TYPE`, `plasmashell --version` | Observed | C | This session only | — |
| E-002 | REA version/location | rea 6.4.0 (`rea-agents`), found via fnm shell dir | `rea --version`, `readlink -f` | Observed | C | PATH only valid in fnm-initialised shells | Decide if permanent PATH needed |
| E-003 | REA readiness | `healthy:false`: no Ghidra, no IDA, stale skill, client registrations drifted | `rea doctor --json` | Observed | C | Only audit-wide scope run | Ask user to approve `rea setup` |
| E-004 | REA MCP in Claude Code | Not registered; no REA tools in this session | `claude mcp list/get rea` | Observed | C | Registration file content not dumped | Approve `rea setup`, restart |
| E-005 | Native provider | Hopper present at /opt/hopper/bin/Hopper, runtime probe ready | doctor | Observed | C | No analysis run; licence limits unknown | Test on a real target |
| E-006 | macOS ops on Linux | Mach-O/plist/signature/arch/Swift-demangle/native-UI ops unavailable | `rea capabilities` (`unsupported_host`) | Observed | C | | Do these on Mac |
| E-007 | Local Shortcat artifact | None found | `ls /opt`, find ~ depth 3 | Observed | C | Search not exhaustive | Request from Mac owner |
| E-010 | Core mechanism | Uses macOS Accessibility API (VoiceOver's), indexes elements/menus/apps/windows | shortcat.app/docs; HN comment by developer | Observed (vendor statement) | C | Vendor claim; not binary-verified | Mac: check linked frameworks/strings |
| E-011 | OCR use | Developer said OCR was only a future plan; no OCR in changelog | HN 33222384; /changelog | Observed | X (for "uses OCR") | 2022 comment; 2025 build unchecked | Mac: look for Vision framework |
| E-012 | Activation shortcut | Default `Cmd+Shift+Space`, configurable | /docs/configuration-options; changelog 0.10.1 | Observed | C | | |
| E-013 | Hint labels | Auto 1–2 char labels, black-on-yellow, shown after delay (default 2 s) | /docs/features/selection; config | Observed | C | Generation algorithm unknown | Mac: observe label assignment |
| E-014 | Actions | Enter=default, Enter×2=double, Ctrl+Enter=right, Ctrl tap=hover, Cmd+Enter=new tab, Shift+Enter=multi | /docs/features/actions | Observed | C | Window-switching section "TODO" | |
| E-015 | Result navigation keys | Tab/Shift+Tab/Ctrl+N/Ctrl+P (v0.11.2), arrows, Cmd+digit | changelog; selection doc | Observed | C | | |
| E-016 | Matching | Fuzzy + synonyms + abbreviations + role words | home; search doc; changelog 0.9.3 | Observed | C | Exact algorithm unknown | Mac: black-box tests |
| E-017 | Ranking signals | Shorter text, cursor proximity, visible boost | changelog 0.5.0/0.7.4/0.11.1 | Observed | C (existence) / U (weights) | Old entries may be superseded | Mac: black-box tests |
| E-018 | Modes | Windows, apps, menu bar, emoji (`:`), continuous (alpha), arrow/scroll chords (alpha) | home; changelog; feature docs | Observed | C | Alpha status as of docs date | |
| E-019 | Limits | Depends on app AX quality; WebViews/complex UIs may not fully enumerate; "not labelled" elements | /docs/compatibility, /common-issues | Observed | C | | |
| E-020 | Click mechanics | Default click is "usually at element midpoint" | /docs/features/actions | Observed | S that coordinate clicks are used; U whether AX press is used instead | Wording only | Mac: xrefs to `AXUIElementPerformAction` vs `CGEventPost` |
| E-021 | Conflict: `Control` | v0.9.3 "`Control` focuses results" vs docs "`Ctrl` tap = hover" | changelog; actions doc | Observed | U | Possibly changed in later versions | Test on Mac |
| E-022 | Closed source | "It won't be open source" | HN | Observed | C | 2022 | |
| E-030 | AT-SPI on this machine | Bus reachable; `Atspi` GI importable | gdbus call; python import | Observed | C | Tree content not yet dumped | Experiment 1 (03) |
| E-031 | Wayland extents / active window / overlay / portals on Plasma | Plausible approaches listed | 03; roadmap file [SECONDARY] | Inferred | U | No testing; secondary file provenance unknown | Experiments 2–7 |
| E-032 | Tooling gaps | No tesseract/ydotool/xdotool | `rpm -q` | Observed | C | | Install only if experiments need them |
| E-040 | AT-SPI default state | `IsEnabled=false`; apps only appear after enabling | `gdbus` Get/Set org.a11y.Status | Observed | C | One session | Set flag at startup; test persistence |
| E-041 | Wayland extents | Frame screen extents (0,0,w,h); child extents window-relative | 08 R3 | Observed | C | 3 apps | Find KWin geometry source |
| E-042 | Active window | `STATE_ACTIVE` identifies focused frame | 08 R4 | Observed | C (1 sample) | Not tested with overlay | Capture before overlay |
| E-043 | DoAction | Returns True on KCalc; node refs go stale | 08 R5 | Observed | S | Effect unverified | Test on Dolphin/Firefox |
| E-044 | KWin geometry source | KWin script exposes frameGeometry/active/UUID per window; delivered via callDBus | 08 R7 | Observed | C (maximized windows only) | Floating-window offsets untested | Test with moved window |
| E-045 | REA MCP + Hopper | MCP tools load after restart; Hopper opened /usr/bin/true, 98 procs | 08 R8 | Observed | C | Tiny sample; licence limits unknown | Try larger binary |
| E-046 | Screen position formula | KWin clientGeometry origin + AT-SPI WINDOW extents matches real widgets (scale 1.0) | 08 R9 | Observed | C | HiDPI untested | Test fractional scale |
| E-047 | DoAction effect | AT-SPI do_action drove KCalc 7×6=42 | 08 R10 | Observed | C | KCalc only | Test Dolphin/Firefox |
| E-048 | Overlay on KWin Wayland (PySide6 plain window) | Translucent fullscreen window gets focus and renders at screen coords | 08 R11 | Observed | C (terminal-launched) | Not via global shortcut; no layer-shell; no click-through | Install devel pkgs, retest |
| E-049 | kglobalaccel registration | doRegister/setShortcut/unregister work from a plain client; signal globalShortcutPressed(s,s,x) | 08 R12 | Observed | C | Portal path untested; conflict-handling UX untested | Test real keypress |
| E-050 | Focus on shortcut activation | Palette became active window and focused entry while KCalc was active (synthetic trigger) | 08 R13 | Observed | C (synthetic) / U (real keypress) | No activation token | Manual keypress test |
| E-051 | Rust core prototype | atspi-crate enumeration+nucleo matcher+DoAction works: KCalc 7×6=42; Dolphin toggle flips state; 20–45 ms per window | research/09 | Observed | C | 2 Qt apps + blank Firefox | Test GTK4, Chromium, big trees |
