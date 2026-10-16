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
}

#[derive(Debug, Deserialize)]
#[serde(default)]
pub struct Scroll {
    /// "hjkl" (Vim) or "ijkl" (arrow layout): which physical keys mean left/down/up/right with Space held.
    pub keys: String,
}

impl Default for Scroll {
    /// Vim keys, like Shortcat's default.
    fn default() -> Self {
        Scroll { keys: "hjkl".into() }
    }
}

#[derive(Debug, Deserialize)]
#[serde(default)]
pub struct Accessibility {
    /// Turn desktop accessibility on when the daemon starts (vimvibe can't see any app without it).
    pub enable_on_start: bool,
}

impl Default for Accessibility {
    /// Accessibility is turned on at daemon start unless the user opts out.
    fn default() -> Self {
        Accessibility { enable_on_start: true }
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

/// Location of the settings file: `$XDG_CONFIG_HOME/vimvibe/config.toml`.
pub fn path() -> PathBuf {
    std::env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".config")))
        .unwrap_or_else(|| PathBuf::from(".config"))
        .join("vimvibe")
        .join("config.toml")
}

/// Read the settings file; defaults when it is missing, defaults plus a warning when it can't be parsed.
pub fn load() -> Config {
    let p = path();
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
    fn parses_and_matches() {
        let c: Config = toml::from_str("[apps]\nexclude = [\"KeePassXC\", \"konsole\"]\n[ui]\naccent = \"red\"\n").unwrap();
        assert!(c.search.windows, "unknown sections are ignored and defaults kept");
        assert_eq!(c.apps.excluded("keepassxc", None, None).as_deref(), Some("KeePassXC"));
        assert_eq!(c.apps.excluded("whatever", Some("org.kde.konsole"), None).as_deref(), Some("konsole"));
        assert_eq!(c.apps.excluded("dolphin", Some("org.kde.dolphin"), None), None);
    }
}
