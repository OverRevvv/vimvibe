//! Installed applications (XDG `.desktop` entries) as results, so "firefox" + Enter launches Firefox — what people
//! open the start menu for. Read fresh on every open (a few hundred small files, a few milliseconds), honouring
//! NoDisplay/Hidden/OnlyShowIn/NotShowIn and user overrides in ~/.local/share/applications.

use std::collections::HashSet;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone)]
pub struct App {
    /// Desktop file id, e.g. `org.kde.dolphin.desktop` (`kde/foo.desktop` → `kde-foo.desktop`).
    pub id: String,
    pub name: String,
    /// GenericName and Keywords, used only for matching ("file manager" finds Dolphin).
    pub extra: String,
    pub path: PathBuf,
}

/// XDG data directories to search for `applications/`, the user's own first (it overrides system entries).
fn data_dirs() -> Vec<PathBuf> {
    let home = std::env::var_os("XDG_DATA_HOME")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".local/share")));
    let sys = std::env::var("XDG_DATA_DIRS").unwrap_or_else(|_| "/usr/local/share:/usr/share".into());
    home.into_iter().chain(sys.split(':').filter(|s| !s.is_empty()).map(PathBuf::from)).collect()
}

/// Names in `$XDG_CURRENT_DESKTOP` (lower-case), for OnlyShowIn/NotShowIn.
fn desktops() -> Vec<String> {
    std::env::var("XDG_CURRENT_DESKTOP").unwrap_or_default().split(':').map(|s| s.to_lowercase()).collect()
}

/// Localised value of `key` for the current language (`Name[de]`), else the plain one.
fn pick<'a>(entries: &'a [(String, String)], key: &str, langs: &[String]) -> Option<&'a str> {
    for l in langs {
        let k = format!("{key}[{l}]");
        if let Some((_, v)) = entries.iter().find(|(kk, _)| *kk == k) {
            return Some(v);
        }
    }
    entries.iter().find(|(k, _)| k == key).map(|(_, v)| v.as_str())
}

/// Read one `.desktop` file; None for non-applications and entries hidden on this desktop.
fn parse(path: &Path, id: String, langs: &[String], current: &[String]) -> Option<App> {
    let text = std::fs::read_to_string(path).ok()?;
    let mut entries = vec![];
    let mut in_main = false;
    for line in text.lines().map(str::trim) {
        if line.starts_with('[') {
            in_main = line == "[Desktop Entry]";
        } else if in_main {
            if let Some((k, v)) = line.split_once('=') {
                entries.push((k.trim().to_string(), v.trim().to_string()));
            }
        }
    }
    let get = |k: &str| entries.iter().find(|(kk, _)| kk == k).map(|(_, v)| v.as_str());
    let yes = |k: &str| get(k).is_some_and(|v| v.eq_ignore_ascii_case("true"));
    if get("Type") != Some("Application") || yes("NoDisplay") || yes("Hidden") {
        return None;
    }
    let listed = |k: &str| get(k).map(|v| v.split(';').filter(|s| !s.is_empty()).map(|s| s.to_lowercase()).collect::<Vec<_>>());
    if let Some(only) = listed("OnlyShowIn") {
        if !only.iter().any(|d| current.contains(d)) {
            return None;
        }
    }
    if let Some(not) = listed("NotShowIn") {
        if not.iter().any(|d| current.contains(d)) {
            return None;
        }
    }
    let name = pick(&entries, "Name", langs)?.to_string();
    let extra = [pick(&entries, "GenericName", langs), pick(&entries, "Keywords", langs)]
        .into_iter()
        .flatten()
        .map(|s| s.replace(';', " "))
        .collect::<Vec<_>>()
        .join(" ");
    Some(App { id, name, extra, path: path.to_path_buf() })
}

/// Collect `.desktop` files below `dir` with their desktop-file ids (subdirectories become `dir-` prefixes).
fn scan(dir: &Path, prefix: &str, out: &mut Vec<(String, PathBuf)>) {
    let Ok(rd) = std::fs::read_dir(dir) else { return };
    for e in rd.flatten() {
        let p = e.path();
        let name = e.file_name().to_string_lossy().to_string();
        if p.is_dir() {
            scan(&p, &format!("{prefix}{name}-"), out);
        } else if name.ends_with(".desktop") {
            out.push((format!("{prefix}{name}"), p));
        }
    }
}

/// All launchable applications; earlier data dirs (the user's own) override later ones with the same id.
pub fn list() -> Vec<App> {
    let lang = std::env::var("LC_MESSAGES").or_else(|_| std::env::var("LANG")).unwrap_or_default();
    let base = lang.split('.').next().unwrap_or("").to_string();
    let mut langs = vec![base.clone()];
    if let Some((l, _)) = base.split_once('_') {
        langs.push(l.to_string());
    }
    let current = desktops();
    let mut seen = HashSet::new();
    let mut out = vec![];
    for d in data_dirs() {
        let mut files = vec![];
        scan(&d.join("applications"), "", &mut files);
        for (id, path) in files {
            if seen.insert(id.clone()) {
                // an override that hides an app still claims its id, so the system copy is not listed either
                if let Some(app) = parse(&path, id, &langs, &current) {
                    out.push(app);
                }
            }
        }
    }
    out.sort_by(|a, b| a.name.to_lowercase().cmp(&b.name.to_lowercase()));
    out
}

/// Start an application the way the desktop would (KDE: kioclient, which gives launch feedback; else gio).
pub fn launch(path: &Path) -> anyhow::Result<()> {
    let p = path.to_string_lossy().to_string();
    let mut cmd = if crate::kwin::on_kde() && which("kioclient") {
        let mut c = std::process::Command::new("kioclient");
        c.args(["exec", &p]);
        c
    } else {
        let mut c = std::process::Command::new("gio");
        c.args(["launch", &p]);
        c
    };
    let mut child = cmd.stdin(std::process::Stdio::null()).stdout(std::process::Stdio::null()).stderr(std::process::Stdio::null()).spawn()?;
    std::thread::spawn(move || child.wait()); // reap it; the launcher exits as soon as the app is started
    Ok(())
}

/// Whether an executable named `bin` is on `$PATH`.
fn which(bin: &str) -> bool {
    std::env::var_os("PATH").is_some_and(|p| std::env::split_paths(&p).any(|d| d.join(bin).is_file()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_and_filters() {
        let dir = std::env::temp_dir().join(format!("vv-apps-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let ok = dir.join("a.desktop");
        std::fs::write(&ok, "[Desktop Entry]\nType=Application\nName=Files\nName[de]=Dateien\nGenericName=File Manager\nKeywords=folder;explorer;\nExec=x\n").unwrap();
        let hidden = dir.join("b.desktop");
        std::fs::write(&hidden, "[Desktop Entry]\nType=Application\nName=Hidden\nNoDisplay=true\n").unwrap();
        let gnome = dir.join("c.desktop");
        std::fs::write(&gnome, "[Desktop Entry]\nType=Application\nName=G\nOnlyShowIn=GNOME;\n").unwrap();
        let kde = vec!["kde".to_string()];
        let a = parse(&ok, "a.desktop".into(), &["de_DE".into(), "de".into()], &kde).unwrap();
        assert_eq!(a.name, "Dateien");
        assert!(a.extra.contains("folder explorer"));
        assert!(parse(&hidden, "b".into(), &[], &kde).is_none());
        assert!(parse(&gnome, "c".into(), &[], &kde).is_none());
        std::fs::remove_dir_all(&dir).unwrap();
    }
}
