# 02 — REA investigation

## Target artifacts examined
**None.** No Shortcat binary, `.app`, `.dmg`, or Mach-O exists on this machine, and none was provided. Original-binary analysis **cannot yet be performed**; no REA analysis operation was run against any target. No REA findings are claimed. Everything in 01 comes from public web pages, not REA.

## What was actually exercised
| Tool | Result |
|---|---|
| `rea --version` | 6.4.0 |
| `rea --help` | Large command catalogue (inspect-artifact, extract-artifact, inspect-binary-layout, decompile, function, compare, evidence-export/import, decode-interface-builder, …) |
| `rea doctor --json` | `healthy:false` — see 00 |
| `rea capabilities` | Hopper-backed native ops available; macOS-only ops unavailable on Linux — see 00 |
| `rea providers` | Printed the same capability listing (no separate provider table seen); Ghidra and IDA unconfigured per doctor |
| REA MCP tools in this session | Exposed after restart (see 08 R8); `open_binary` + `binary_overview` tested on /usr/bin/true |

Not run: `inspect-artifact`, `inspect-binary-layout`, any Hopper session (no target to analyse; avoids needless launching of Hopper).

## Provider limitations on this host
- Ghidra: not installed (`GHIDRA_INSTALL_DIR` unset). Installing needs your approval.
- Hopper: present; capacity/licence limits untested.
- macOS-only operations (Mach-O header, plist, code signature, architectures, Swift demangle, asset catalogs, native UI observation) are unavailable here. These are exactly the cheap, high-value first steps for the Mac side.
- DMG: only partially supported on Linux (mount path is macOS-native).

## Unresolved questions REA could answer once an artifact exists
1. Is Shortcat Swift/ObjC? Which frameworks does it link (ApplicationServices/HIServices, Carbon hotkeys, Vision for OCR, ScreenCaptureKit)? — `inspect_macho`/`trace_dylib_resolution`/strings.
2. Which AX attributes does it request (`AXRole`, `AXTitle`, `AXDescription`, `AXPosition`, `AXPress`, …)? — strings + symbol references.
3. How is a click performed: `AXUIElementPerformAction` vs `CGEventPost`? — callers/xrefs of those symbols.
4. Is there any Vision/OCR code path? — imports, strings.
5. Scoring and synonym tables — data section/resources.
Conclusions from strings or symbols alone must be labelled as inference.

## Blocker & next step
Blocker: no artifact. Obtain one from the authorised Mac owner (see 05), preferably as a pre-analysed evidence bundle (`rea evidence-export`) or the raw `.app` copied with permission. Separately, to make MCP work here: `rea setup` then restart Claude Code (requires your OK).
