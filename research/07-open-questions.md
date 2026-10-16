# 07 — Open questions & blockers

| # | Question / blocker | Hypotheses | Next experiment |
|---|---|---|---|
| Q1 | **BLOCKER:** No Shortcat binary — how does it really click, score, and generate hints? | AX press vs synthetic click; static scoring weights | Mac plan 05 §1–2 |
| Q2 | REA MCP in Claude Code | RESOLVED: tools load after restart (08 R8) | — |
| Q3 | Is Ghidra needed? | Hopper works on a small ELF; limits on large Mach-O unknown | Try a larger local binary; Mac-side decision |
| Q4 | `Control` key semantics: "focuses results" (v0.9.3) vs "tap = hover" (docs) | Behaviour changed or docs sections describe different phases | Mac black-box test |
| Q5 | `Cmd+Number` acts vs selects (docs vs v0.10.2 changelog) | Doc summary imprecise | Mac test; re-read page raw |
| Q6 | Does Shortcat use OCR in 0.12.x? | No (AX only) | Mac: Vision framework link, Screen Recording permission |
| Q7 | AT-SPI coverage | PARTIAL: Qt (Konsole, Dolphin, KCalc) and Firefox OK with a11y enabled; GTK4, Chromium/Electron untested | Experiment 1 remainder (08) |
| Q8 | AT-SPI extents on Wayland | ANSWERED: window-relative extents + KWin clientGeometry = correct screen position (08 R9); HiDPI untested | Test scale 125/150% |
| Q9 | Focused window on Plasma Wayland? | PARTIAL: AT-SPI ACTIVE works (08 R4) | Test with overlay present |
| Q10 | Overlay on KWin Wayland | PARTIAL: PySide6 plain window got focus + transparency (08 R11); Tauri, layer-shell, click-through, shortcut-activation untested (need sudo dnf) | Experiment 6 remainder |
| Q11 | Global shortcut on Plasma 6.7 | ANSWERED for kglobalaccel D-Bus (08 R12); XDG portal untested; real-keypress focus untested | Manual keypress test |
| Q12 | RemoteDesktop/libEI permission persistence on KDE | One-time grant, restore token | Experiment 7 |
| Q13 | Provenance and accuracy of `~/Downloads/linux-shortcat-roadmap.md` (GNOME-oriented) | Plausible but unreviewed; verify each claim before relying | Cross-check against portal docs and experiments |
| Q14 | Public docs read via summarising fetch | Paraphrase errors possible | Re-read key pages raw when finalising spec |
| Q15 | Hint label algorithm, duplicate handling, ranking weights, no-match UI | Unknown | Mac black-box + REA |
| Q16 | Hint length: docs say 1–2 chars (Selection) vs 1–3 letters (Getting started) | Doc inconsistency or length grows with element count | Mac observation |
