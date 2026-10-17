//! User settings shared by the daemon and the overlay: `$XDG_CONFIG_HOME/vimvibe/config.toml`.
//!
//! The daemon only reads the parts it enforces (which apps are off limits, whether other windows are searchable);
//! the overlay reads the rest (colour, label delay, continuous mode, ...). The file is re-read on every trigger, so
//! edits apply without a restart. A missing or broken file means defaults (a broken one is reported once per trigger).

use serde::Deserialize;
use std::path::PathBuf;

#[derive(Debug, Default, Deserialize)]
#[serde(default)]
pub struct Config {
    pub apps: Apps,
    pub search: Search,
    pub accessibility: Accessibility,
    pub scroll: Scroll,
    pub mouse: Mouse,
}

#[derive(Debug, Deserialize)]
#[serde(default)]
pub struct Scroll {
    /// "hjkl" (Vim) or "ijkl" (arrow layout): which physical keys mean left/down/up/right with Space held.
    pub keys: String,
    /// What Space + H/J/K/L do: "scroll" (default) or "arrows" (send arrow keys; needs the keyboard permission).
    /// The other action is on Space + Ctrl + H/J/K/L.
    pub hjkl: String,
    /// Distance per press, in mouse-wheel notches (1 notch ≈ 3 lines).
    pub distance: f64,
    /// Glide through a scroll like a smooth-scrolling mouse wheel instead of jumping; `smooth_ms` is how long a glide
    /// takes to settle.
    pub smooth: bool,
    pub smooth_ms: u64,
    /// Space + g g jumps to the top and Space + Shift+G to the bottom (like Vimium).
    pub edge_keys: bool,
    /// How far (notches) and how fast (ms) a jump to the top/bottom travels; the app stops at the end of the content.
    pub edge_notches: f64,
    pub edge_ms: u64,
    /// Natural scrolling: down moves the content up, like a touchpad.
    pub natural: bool,
    /// Swap left and right for H / L.
    pub invert_horizontal: bool,
    /// Shift multiplies the distance by this.
    pub fast: i32,
}

impl Default for Scroll {
    /// Vim keys scroll; one notch per press gliding for 220 ms, Shift = 4×, gg / G jump over 600 ms.
    fn default() -> Self {
        Scroll { keys: "hjkl".into(), hjkl: "scroll".into(), distance: 1.0, smooth: true, smooth_ms: 220, edge_keys: true, edge_notches: 600.0, edge_ms: 600, natural: false, invert_horizontal: false, fast: 4 }
    }
}

/// Keyboard mouse control (the grid and H J K L pointer movement). Only the master switch matters to the daemon; the
/// grid size, alphabet and speeds are read by the overlay.
#[derive(Debug, Deserialize)]
#[serde(default)]
pub struct Mouse {
    pub enabled: bool,
}

impl Default for Mouse {
    /// On by default; turning it off makes the daemon refuse every `Pointer*` call.
    fn default() -> Self {
        Mouse { enabled: true }
    }
}

#[derive(Debug, Deserialize)]
#[serde(default)]
pub struct Accessibility {
    /// Turn desktop accessibility on when the daemon starts (vimvibe can't see any app without it).
    pub enable_on_start: bool,
    /// When vimvibe is opened over a Chromium-based app that was started without `--force-renderer-accessibility` (so it
    /// shows nothing), offer to restart it with the flag.
    pub offer_restart: bool,
}

impl Default for Accessibility {
    /// Accessibility is turned on at daemon start unless the user opts out.
    fn default() -> Self {
        Accessibility { enable_on_start: true, offer_restart: true }
    }
}

#[derive(Debug, Default, Deserialize)]
#[serde(default)]
pub struct Apps {
    /// Apps vimvibe must never read or act on (password managers, banking, terminals, ...). Matched case-insensitively
    /// against the accessibility app name, the window class (`org.kde.konsole` also matches `konsole`) and the
    /// process name.
    pub exclude: Vec<String>,
}

#[derive(Debug, Deserialize)]
#[serde(default)]
pub struct Search {
    /// Offer the other open windows as results (Shortcat-style window switching).
    pub windows: bool,
    /// Offer installed applications as results (type a name, Enter launches it).
    pub apps: bool,
    /// Label the desktop's panels too (Plasma's taskbar, tray, clock).
    pub panel: bool,
}

impl Default for Search {
    /// Window switching, app launching and panel labels are all on by default.
    fn default() -> Self {
        Search { windows: true, apps: true, panel: true }
    }
}

/// The profile this process runs as: empty for the installed ("stable") vimvibe, or a short name such as `dev` from
/// `$VIMVIBE_PROFILE`. A profile has its own D-Bus name, KDE shortcut component and default keys, settings directory
/// and logs, so a development build can run next to the installed one without touching it. Only lower-case letters
/// and digits are kept.
pub fn profile() -> String {
    std::env::var("VIMVIBE_PROFILE").unwrap_or_default().to_lowercase().chars().filter(|c| c.is_ascii_alphanumeric()).collect()
}

/// `vimvibe` for the stable profile, `vimvibe-<profile>` otherwise: the name of the settings and state directories.
pub fn dir_name() -> String {
    match profile().as_str() {
        "" => "vimvibe".into(),
        p => format!("vimvibe-{p}"),
    }
}

/// `$XDG_CONFIG_HOME` (or `~/.config`).
fn config_home() -> PathBuf {
    std::env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".config")))
        .unwrap_or_else(|| PathBuf::from(".config"))
}

/// Location of this profile's settings file: `$XDG_CONFIG_HOME/vimvibe[-profile]/config.toml`.
pub fn path() -> PathBuf {
    config_home().join(dir_name()).join("config.toml")
}

/// The file settings are read from: this profile's own, or — for a profile that has none yet — the installed
/// vimvibe's, so a development build starts with your settings (it never writes to them).
fn read_path() -> PathBuf {
    let own = path();
    if own.exists() { own } else { config_home().join("vimvibe").join("config.toml") }
}

/// Read the settings file; defaults when it is missing, defaults plus a warning when it can't be parsed.
pub fn load() -> Config {
    let p = read_path();
    match std::fs::read_to_string(&p) {
        Ok(s) => toml::from_str(&s).unwrap_or_else(|e| {
            eprintln!("ignoring {}: {e}", p.display());
            Config::default()
        }),
        Err(_) => Config::default(),
    }
}

/// Process name of a PID (`/proc/<pid>/comm`), lower-cased.
fn comm(pid: u32) -> Option<String> {
    std::fs::read_to_string(format!("/proc/{pid}/comm")).ok().map(|s| s.trim().to_lowercase())
}

impl Apps {
    /// The exclude entry that matches this app, if any.
    pub fn excluded(&self, app: &str, class: Option<&str>, pid: Option<u32>) -> Option<String> {
        if self.exclude.is_empty() {
            return None;
        }
        let mut names = vec![app.to_lowercase()];
        if let Some(c) = class.filter(|c| !c.is_empty()) {
            let c = c.to_lowercase();
            names.extend(c.rsplit('.').next().map(str::to_string)); // org.kde.konsole -> konsole
            names.push(c);
        }
        names.extend(pid.and_then(comm));
        self.exclude.iter().find(|e| names.iter().any(|n| !n.is_empty() && n == &e.trim().to_lowercase())).cloned()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn profile_names_are_clean() {
        // SAFETY: tests in this crate don't read the environment concurrently
        unsafe { std::env::set_var("VIMVIBE_PROFILE", "De-v!") };
        assert_eq!(profile(), "dev");
        assert_eq!(dir_name(), "vimvibe-dev");
        unsafe { std::env::remove_var("VIMVIBE_PROFILE") };
        assert_eq!(dir_name(), "vimvibe");
    }

    #[test]
    fn parses_and_matches() {
        let c: Config = toml::from_str("[apps]\nexclude = [\"KeePassXC\", \"konsole\"]\n[ui]\naccent = \"red\"\n").unwrap();
        assert!(c.search.windows, "unknown sections are ignored and defaults kept");
        assert_eq!(c.apps.excluded("keepassxc", None, None).as_deref(), Some("KeePassXC"));
        assert_eq!(c.apps.excluded("whatever", Some("org.kde.konsole"), None).as_deref(), Some("konsole"));
        assert_eq!(c.apps.excluded("dolphin", Some("org.kde.dolphin"), None), None);
    }
}
