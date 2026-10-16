# 00 — Environment & REA readiness

Collected 2026-10-13 with read-only commands. Nothing was installed or reconfigured.

| Item | Result | Command |
|---|---|---|
| OS | Fedora release 44 | `cat /etc/fedora-release` |
| Kernel | Linux 7.2.9-200.fc44.x86_64 | harness env |
| Session | `wayland`, `XDG_CURRENT_DESKTOP=KDE` | `echo $XDG_SESSION_TYPE` |
| Plasma | plasmashell 6.7.5; kwin 6.7.5 (rpm `kwin`) | `plasmashell --version`, `rpm -q kwin` |
| Node / npm | v24.21.0 / 11.19.0 (via fnm) | |
| Claude Code | 2.1.296 at `~/.local/bin/claude` | `claude --version` |
| REA | 6.4.0, package `rea-agents`, `rea.mjs` under fnm node-versions/v24.21.0 | `rea --version` |
| `rea` on PATH | Yes, but only via the fnm per-shell dir (`/run/user/1000/fnm_multishells/.../bin/rea`) — works only in shells where fnm is initialised | `command -v rea` |
| Rust | rustc/cargo 1.98.1 (rpm) | |
| Python | python3 with `gi` + `Atspi 2.0` typelib importable | |
| Screenshots | `spectacle` present; `xdg-desktop-portal` 1.22.1 and `xdg-desktop-portal-kde` 6.7.5 installed | `rpm -q` |
| Not installed | tesseract, xdotool, ydotool, Ghidra | |

## REA doctor (`rea doctor --json`) — `healthy: false`
Healthy: node, host (`fedora 44`), Hopper (`/opt/hopper/bin/Hopper`), `hopper-demo-runtime` (strategy=direct, ready).

Failing:
- `ghidra`: `GHIDRA_INSTALL_DIR is not set` (missing_analysis_engine). Not installed.
- `ida-registration`: not configured (missing_analysis_engine).
- `skill:identity`: installed REA skill is stale (config_drift) → `rea setup`.
- `registration:claude_code` (`~/.claude.json`), codex, copilot_cli, opencode, vscode: all `config_drift` → remediation "run `rea setup`, restart client".

Hopper binary exists and the private-display probe is ready; I did **not** launch an analysis, so Hopper licensing/limits (demo) are unverified.

## MCP integration status (verified separately from the CLI)
- `claude mcp list` shows only `claude.ai Claude Docs`. `claude mcp get rea` → "No MCP server named rea".
- **This session exposes no REA MCP tools.** The CLI works; the MCP integration does not reach this session.
- Cause is consistent with doctor's `config_drift`, but the exact registration content was not inspected or changed. Fix (`rea setup` + restart Claude Code) modifies Claude config → **needs your approval**; not done.

## REA capabilities on this host (`rea capabilities`)
Available: `inspect_artifact`, `extract_artifact`, `decode_interface_builder`, `inspect_keyed_archive`, `trace_dylib_resolution`, managed-artifact ops, and Hopper-backed native ops (`list_procedures`, `list_strings`, `procedure_pseudo_code`, `procedure_assembly`, `procedure_callers/callees/references`, `read_bytes`, `analyze_function`, …).

Unavailable (`unsupported_host`, requires macOS): `inspect_macho`, `inspect_plist`, `inspect_signature`, `list_architectures`, `inspect_asset_catalog`, `demangle_swift`, `observe_native_ui`, `observe_native_calls`, `inspect_native_dispatch_metadata`, `capture_native_ui_scenario`.
Caveat: DMG child inventory "automatically uses a read-only native macOS mount" — so DMG inspection on Linux is limited.
Important consequence: Mach-O/plist/signature inspection and Swift demangling would run best **on the Mac**.

## Local Shortcat artifacts
None. No Shortcat `.app`/`.dmg`/Mach-O on this machine (searched `/opt`, applications, `~` depth 3).
Related local file: `~/Downloads/linux-shortcat-roadmap.md` (23 KB, unknown provenance; targets GNOME 50, not KDE). Treated as a **secondary, unverified** source — see 03.

## Update — REA setup (approved, run 2026-10-13)
- Ran `rea setup --client claude_code --yes` with the **stable** binary first on PATH, so the registration doesn't depend on the temporary fnm shell dir: `/home/OverRevvv/.local/share/fnm/node-versions/v24.21.0/installation/bin/rea mcp`, env `HOPPER_LAUNCHER_PATH=/opt/hopper/bin/Hopper`.
- Also installed the skill at `~/.claude/skills/reverse-engineer-anything`. Backup: `~/.claude.json.rea.backup`.
- `claude mcp get rea` → ✔ Connected (user scope). **The already-running session doesn't expose the tools; restart Claude Code to load them.** MCP tool schemas not yet inspected.
- Ghidra/IDA still unconfigured (unchanged; not requested).
