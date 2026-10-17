//! Title-bar buttons of server-side decorated windows (close, maximize, minimize, window menu, on all desktops,
//! keep above). KWin draws them, so they are not in the app's accessibility tree; we add them as elements so they get
//! labels too. Their positions are estimated from the frame and client geometry and the user's button layout in
//! `kwinrc` (good enough to place a label on the right button); activating one runs the KWin operation directly, so
//! the estimate never decides where a click lands.

use crate::kwin::FocusInfo;

pub struct Button {
    pub op: &'static str,
    pub name: &'static str,
    /// Relative to the client area origin (so the title bar has negative y), like AT-SPI window extents.
    pub rect: (i32, i32, i32, i32),
}

/// Breeze's defaults: window menu + on all desktops on the left; help, minimize, maximize, close on the right.
const DEFAULT_LEFT: &str = "MS";
const DEFAULT_RIGHT: &str = "HIAX";

/// The user's title-bar button layout (left, right) from kwinrc, or Breeze's defaults.
fn layout() -> (String, String) {
    let path = std::env::var_os("XDG_CONFIG_HOME")
        .map(std::path::PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|h| std::path::PathBuf::from(h).join(".config")))
        .map(|d| d.join("kwinrc"));
    let text = path.and_then(|p| std::fs::read_to_string(p).ok()).unwrap_or_default();
    parse_layout(&text)
}

/// Read `ButtonsOnLeft`/`ButtonsOnRight` from the `[org.kde.kdecoration2]` group of kwinrc text.
fn parse_layout(kwinrc: &str) -> (String, String) {
    let (mut left, mut right) = (DEFAULT_LEFT.to_string(), DEFAULT_RIGHT.to_string());
    let mut in_group = false;
    for line in kwinrc.lines().map(str::trim) {
        if line.starts_with('[') {
            in_group = line == "[org.kde.kdecoration2]";
        } else if in_group {
            if let Some(v) = line.strip_prefix("ButtonsOnLeft=") {
                left = v.to_string();
            } else if let Some(v) = line.strip_prefix("ButtonsOnRight=") {
                right = v.to_string();
            }
        }
    }
    (left, right)
}

/// Button letter from the layout string to (KWin operation, label); None for buttons we don't offer or the window
/// doesn't allow (`ops` lists what it allows).
fn describe(c: char, ops: &str) -> Option<(&'static str, &'static str)> {
    Some(match c {
        'X' if ops.contains('X') => ("close", "Close window"),
        'A' if ops.contains('A') => ("maximize", "Maximize window"),
        'I' if ops.contains('I') => ("minimize", "Minimize window"),
        'M' => ("menu", "Window menu"),
        'S' => ("alldesktops", "On all desktops"),
        'F' => ("above", "Keep above others"),
        'B' => ("below", "Keep below others"),
        _ => return None, // help, shade, application menu, spacers: not offered
    })
}

/// Buttons of the focused window, or none when it has no server-side title bar.
pub fn buttons(f: &FocusInfo) -> Vec<Button> {
    let (left, right) = layout();
    compute(f, &left, &right)
}

/// Place the buttons of `left` from the frame's left edge and of `right` from its right edge, square and vertically
/// centred in the title bar.
fn compute(f: &FocusInfo, left: &str, right: &str) -> Vec<Button> {
    let title = f.y - f.fy; // title bar height (plus the top border)
    if !f.ops.contains('D') || title < 12 || f.fw <= 0 {
        return vec![];
    }
    let side = (f.x - f.fx).max(0);
    let size = (title as f32 * 0.72).round() as i32;
    let gap = (title as f32 * 0.12).round() as i32;
    let margin = (title as f32 * 0.25).round() as i32;
    let y = f.fy + (title - size) / 2;
    let mut out = vec![];
    let mut push = |c: char, x: i32| {
        if let Some((op, name)) = describe(c, &f.ops) {
            out.push(Button { op, name, rect: (x - f.x, y - f.y, size, size) });
            true
        } else {
            false // help/shade/app-menu buttons are usually hidden, so they are not counted
        }
    };
    let mut x = f.fx + side + margin;
    for c in left.chars() {
        if push(c, x) {
            x += size + gap;
        }
    }
    let mut x = f.fx + f.fw - side - margin - size;
    for c in right.chars().rev() {
        if push(c, x) {
            x -= size + gap;
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    // A sample focused window with a title bar, used by the tests below.
    fn focus() -> FocusInfo {
        FocusInfo { pid: 1, class: "x".into(), caption: "c".into(), x: 213, y: 113, w: 940, h: 560, id: "{a}".into(), fx: 213, fy: 85, fw: 940, fh: 588, ops: "XAID".into() }
    }

    // With KDE's default button layout the close button is the rightmost one.
    #[test]
    fn default_layout_places_close_rightmost() {
        let b = compute(&focus(), "MS", "HIAX");
        let names: Vec<_> = b.iter().map(|b| b.name).collect();
        assert_eq!(names, ["Window menu", "On all desktops", "Close window", "Maximize window", "Minimize window"]);
        let close = &b[2];
        assert!(close.rect.1 < 0, "title bar is above the client area");
        assert!(close.rect.0 + close.rect.2 <= 940 && close.rect.0 > 880, "close sits at the right edge: {:?}", close.rect);
    }

    // Windows that draw their own title bar (no KWin decoration) get no extra buttons.
    #[test]
    fn no_buttons_without_server_side_decoration() {
        let mut f = focus();
        f.ops = "XAI".into();
        assert!(compute(&f, "MS", "HIAX").is_empty());
    }

    // The left/right button layout strings are read from the [org.kde.kdecoration2] section of kwinrc.
    #[test]
    fn reads_kwinrc() {
        let (l, r) = parse_layout("[General]\nx=1\n[org.kde.kdecoration2]\nButtonsOnLeft=X\nButtonsOnRight=IA\n");
        assert_eq!((l.as_str(), r.as_str()), ("X", "IA"));
    }
}
