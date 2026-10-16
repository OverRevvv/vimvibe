# 05 — Mac investigation plan (separately authorised)

Assume nothing is installed on the Mac beyond macOS built-ins. Only inspect with the owner's consent; no bypassing of licence/SIP; static inspection first; don't run extracted scripts; don't upload the binary anywhere.

## 0. Prep
- Record macOS version, Shortcat version (About/`defaults read /Applications/Shortcat.app/Contents/Info CFBundleShortVersionString`), Mac arch.
- Option A (preferred if REA is installable on Mac): install REA there, run `rea doctor`, then run the sequence in §2 and `rea evidence-export` to JSON.
- Option B (no REA): use built-ins (`file`, `otool -L`, `otool -l`, `nm`, `strings`, `codesign -d --entitlements :-`, `plutil -p`, `lipo -info`) and save text output.

## 1. Cheap static facts (no execution)
1. `Contents/Info.plist` (bundle id `com.sproutcube.Shortcat`?, LSUIElement, minimum OS, usage strings).
2. Entitlements + signature (`codesign -dvv`, `-d --entitlements`), hardened runtime, sandbox on/off.
3. Binary architectures; linked frameworks (`otool -L`): look for ApplicationServices/HIServices, Carbon, Vision, ScreenCaptureKit, Sparkle.
4. Bundle resources: synonym lists, emoji data, localisation, nibs/storyboards (`rea decode-interface-builder`).
5. `strings` for `AX*` attribute names (`AXRole`, `AXTitle`, `AXPosition`, `AXPress`, `AXEnhancedUserInterface`, `AXManualAccessibility`), `CGEventPost`, `CGWarpMouseCursorPosition`, key names, hotkey APIs (`RegisterEventHotKey`, `CGEventTap`).
6. Preferences keys: `defaults read com.sproutcube.Shortcat` (user's own domain; contains no secrets expected — review before sharing).

## 2. REA operations (on the Mac)
`inspect-artifact` → `list_architectures`/`inspect_macho` → `trace_dylib_resolution` → Hopper `list_strings` / `list_procedures` filtered on AX/CG symbols → `procedure_callers` of `AXUIElementPerformAction`, `AXUIElementCopyAttributeValue`, `CGEventPost` → `procedure_pseudo_code` / `analyze_function` for the click path, the hint generator and the scorer → `demangle_swift` if Swift. Label every conclusion CONFIRMED only where code was read.

## 3. Black-box observations (screen recordings OK; no private data visible)
- Hint assignment: same screen twice; do labels change? How are collisions resolved?
- Search ordering: queries "ok", "save", "btn", "delete" in Finder/Safari/VS Code; note rank vs position/length.
- Duplicate labels, no-match state, Esc/Backspace behaviour, focus return, multi-window behaviour.
- `Control` conflict (E-021): tap vs hold.
- Does it click via AX press or by moving the cursor? Observe cursor movement on a button.
- Enumeration time on a heavy app; the 5 s timeout.
- Which apps expose no labels (compare with Accessibility Inspector).
- Menu search and window search lists; Dock items.
- Does it open when screen recording permission is absent (OCR/screenshot dependency)? Check System Settings → Privacy for what permissions Shortcat requests.
- Apple Accessibility Inspector tree for the same screens, to compare Shortcat's list against raw AX.

## 4. Transfer to Fedora
Text outputs, plists, `defaults` dumps, REA evidence JSON (`rea evidence-export` → `rea evidence-import` here), and screen recordings via scp/USB. Don't transfer the binary unless the owner agrees and licensing allows; hashes (`shasum -a 256`) suffice to cross-reference.

## 5. Highest-value artifacts
1. `otool -L` + `strings` + entitlements output. 2. Info.plist and `defaults` dump. 3. REA evidence for click path and scorer. 4. Short recordings for hint/ranking behaviour. 5. Accessibility Inspector screenshots for 3 apps.
