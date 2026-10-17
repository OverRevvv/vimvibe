//! Chromium-based programs (Chrome, Brave, Edge, Vivaldi, Electron apps such as VS Code, Discord, Slack …) only build their
//! accessibility tree when started with `--force-renderer-accessibility`. Measured: no screen-reader signal on the
//! accessibility bus, no environment variable and no event registration turns it on afterwards, so vimvibe makes sure
//! the flag is there: it adds it to the menu launchers (`doctor --fix-chrome`), and offers to restart a running
//! program that lacks it (the program is recognised by what it is, not by its name, so any Chromium engine works).

use std::ffi::OsString;
use std::path::{Path, PathBuf};
use std::time::Duration;

pub const FLAG: &str = "--force-renderer-accessibility";

/// Whether the program at `exe` is built on Chromium: it sits next to the files every Chromium/Electron/CEF build ships.
pub fn is_chromium_exe(exe: &Path) -> bool {
    let Some(dir) = exe.parent() else { return false };
    dir.join("icudtl.dat").exists() && ["chrome_100_percent.pak", "resources.pak", "chrome_crashpad_handler", "v8_context_snapshot.bin"].iter().any(|f| dir.join(f).exists())
}

/// The file a launcher's program name leads to (searching `$PATH`, following symlinks): `/usr/bin/google-chrome-stable`
/// is `/opt/google/chrome/google-chrome`.
fn resolve_program(prog: &str) -> Option<PathBuf> {
    let p = Path::new(prog);
    let found = if p.is_absolute() {
        Some(p.to_path_buf())
    } else {
        std::env::var_os("PATH").and_then(|paths| std::env::split_paths(&paths).map(|d| d.join(prog)).find(|c| c.exists()))
    };
    found.and_then(|f| f.canonicalize().ok())
}

/// The launcher text with the flag added after the program of every `Exec=` line of a Chromium-based program (`None`
/// when it is not one, or every line already has the flag). `is_chromium` decides by program name or path.
pub fn with_flag(desktop: &str, is_chromium: impl Fn(&str) -> bool) -> Option<String> {
    let mut changed = false;
    let lines: Vec<String> = desktop
        .lines()
        .map(|line| {
            let Some(cmd) = line.strip_prefix("Exec=") else { return line.to_string() };
            let mut parts = cmd.splitn(2, ' ');
            let prog = parts.next().unwrap_or("");
            let rest = parts.next().unwrap_or("");
            if rest.contains(FLAG) || !is_chromium(prog) {
                return line.to_string();
            }
            changed = true;
            format!("Exec={prog} {FLAG}{}{rest}", if rest.is_empty() { "" } else { " " })
        })
        .collect();
    changed.then(|| lines.join("\n") + "\n")
}

/// Copy each Chromium-based program's system launcher into `~/.local/share/applications` with the flag added (the copy
/// wins over the system one; a launcher the user already has there is never touched). Returns what was written.
pub fn fix_launchers() -> anyhow::Result<Vec<PathBuf>> {
    let home = std::env::var_os("XDG_DATA_HOME").map(PathBuf::from).or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".local/share"))).unwrap_or_default();
    let target = home.join("applications");
    let mut written = vec![];
    for dir in ["/usr/share/applications", "/usr/local/share/applications", "/var/lib/flatpak/exports/share/applications"] {
        let Ok(entries) = std::fs::read_dir(dir) else { continue };
        for e in entries.flatten() {
            let name = e.file_name();
            if !name.to_string_lossy().ends_with(".desktop") || target.join(&name).exists() {
                continue;
            }
            let Ok(text) = std::fs::read_to_string(e.path()) else { continue };
            if let Some(fixed) = with_flag(&text, |prog| resolve_program(prog).is_some_and(|p| is_chromium_exe(&p))) {
                std::fs::create_dir_all(&target)?;
                std::fs::write(target.join(&name), fixed)?;
                written.push(target.join(&name));
            }
        }
    }
    Ok(written)
}

/// A running Chromium-based program's main process, as needed to start it again.
pub struct Running {
    pub exe: PathBuf,
    pub args: Vec<String>,
    pub env: Vec<(OsString, OsString)>,
    pub cwd: PathBuf,
}

/// The arguments of a process from its `/proc/<pid>/cmdline`. Normally NUL-separated, but Chromium's main process rewrites
/// its command line into one string with spaces; that is split again here, a piece that is not an option or a URL going
/// back onto the option before it (`--user-data-dir=/my dir`).
fn split_cmdline(raw: &[u8]) -> Vec<String> {
    let parts: Vec<String> = raw.split(|&b| b == 0).filter(|a| !a.is_empty()).map(|a| String::from_utf8_lossy(a).into_owned()).collect();
    if parts.len() != 1 || !parts[0].contains(' ') {
        return parts;
    }
    let mut args: Vec<String> = vec![];
    for piece in parts[0].split(' ').filter(|p| !p.is_empty()) {
        match args.last_mut() {
            Some(prev) if !piece.starts_with('-') && !piece.contains("://") && prev.starts_with("--") && prev.contains('=') => {
                prev.push(' ');
                prev.push_str(piece);
            }
            _ => args.push(piece.to_string()),
        }
    }
    args
}

/// The main process `pid` when it is Chromium-based and was started without the flag (helper processes, which carry
/// `--type=`, and processes that already have the flag are not it).
pub fn lacks_flag(pid: u32) -> Option<Running> {
    use std::os::unix::ffi::OsStringExt;
    let raw = std::fs::read(format!("/proc/{pid}/cmdline")).ok()?;
    let args = split_cmdline(&raw);
    if args.is_empty() || args.iter().any(|a| a.starts_with("--type=") || a.starts_with(FLAG)) {
        return None;
    }
    let exe = std::fs::read_link(format!("/proc/{pid}/exe")).ok()?;
    let exe = PathBuf::from(exe.to_string_lossy().trim_end_matches(" (deleted)"));
    if !is_chromium_exe(&exe) {
        return None;
    }
    let env = std::fs::read(format!("/proc/{pid}/environ"))
        .map(|b| b.split(|&c| c == 0).filter_map(|kv| kv.iter().position(|&c| c == b'=').map(|i| (OsString::from_vec(kv[..i].to_vec()), OsString::from_vec(kv[i + 1..].to_vec())))).collect())
        .unwrap_or_default();
    let cwd = std::fs::read_link(format!("/proc/{pid}/cwd")).unwrap_or_else(|_| PathBuf::from("/"));
    Some(Running { exe, args, env, cwd })
}

/// Every process that descends from `pid` (a browser's helper, GPU and renderer processes).
fn descendants(pid: u32) -> Vec<u32> {
    let mut parent = std::collections::HashMap::new();
    for e in std::fs::read_dir("/proc").into_iter().flatten().flatten() {
        let Ok(p) = e.file_name().to_string_lossy().parse::<u32>() else { continue };
        // "pid (comm) S ppid …": the name may contain spaces and parentheses, so read after the last ')'
        let ppid = std::fs::read_to_string(e.path().join("stat")).ok().and_then(|t| t.rsplit_once(')').and_then(|(_, rest)| rest.split_whitespace().nth(1).and_then(|v| v.parse::<u32>().ok())));
        if let Some(pp) = ppid {
            parent.insert(p, pp);
        }
    }
    let mut found = vec![pid];
    let mut i = 0;
    while i < found.len() {
        let cur = found[i];
        found.extend(parent.iter().filter(|(_, pp)| **pp == cur).map(|(p, _)| *p));
        i += 1;
    }
    found.remove(0);
    found
}

/// Quit the program (SIGTERM, which Chromium treats as a normal quit) and start it again with the flag, the same
/// arguments and environment; browsers also get `--restore-last-session` so the tabs come back.
pub async fn restart(pid: u32) -> anyhow::Result<String> {
    use std::os::unix::process::CommandExt;
    let r = lacks_flag(pid).ok_or_else(|| anyhow::anyhow!("process {pid} is not a Chromium-based program that needs the flag"))?;
    let name = r.exe.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default();
    let family = descendants(pid);
    let status = std::process::Command::new("kill").args(["-TERM", &pid.to_string()]).status()?;
    anyhow::ensure!(status.success(), "could not ask {name} to quit");
    // the helpers must be gone too, or the new start finds the old session ("Opening in existing browser session")
    let alive = |p: &u32| Path::new(&format!("/proc/{p}")).exists();
    for _ in 0..100 {
        if !alive(&pid) && !family.iter().any(alive) {
            break;
        }
        tokio::time::sleep(Duration::from_millis(100)).await;
    }
    anyhow::ensure!(!alive(&pid), "{name} did not quit (does it show a dialog?); close it yourself and start it again");
    tokio::time::sleep(Duration::from_millis(1500)).await; // let it release its profile lock
    let browser = ["chrome", "chromium", "brave", "edge", "vivaldi", "opera"].iter().any(|b| name.to_lowercase().contains(b));
    let mut cmd = std::process::Command::new(&r.exe);
    cmd.args(&r.args[1..]).arg(FLAG);
    if browser && !r.args.iter().any(|a| a == "--restore-last-session") {
        cmd.arg("--restore-last-session");
    }
    // the daemon's own environment (it has the session's display and bus) with the program's own values on top
    // what the program prints goes to a log next to the pointer token, so a program that won't start can be diagnosed
    let log = crate::pointer::token_path().with_file_name("restart.log");
    let out = std::fs::OpenOptions::new().create(true).append(true).open(&log).map(std::process::Stdio::from).unwrap_or_else(|_| std::process::Stdio::null());
    let err = std::fs::OpenOptions::new().append(true).open(&log).map(std::process::Stdio::from).unwrap_or_else(|_| std::process::Stdio::null());
    cmd.envs(r.env).current_dir(&r.cwd).stdin(std::process::Stdio::null()).stdout(out).stderr(err).process_group(0);
    let _ = std::fs::OpenOptions::new().append(true).open(&log).map(|mut f| {
        use std::io::Write;
        let _ = writeln!(f, "--- restarting: {} {:?}", r.exe.display(), cmd.get_args().collect::<Vec<_>>());
    });
    cmd.spawn()?;
    Ok(format!("restarted {name} with {FLAG}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn flag_is_added_once() {
        let d = "[Desktop Entry]\nExec=/usr/bin/brave-browser-stable %U\n[Desktop Action x]\nExec=/usr/bin/brave-browser-stable\nExec=/usr/bin/other\n";
        let out = with_flag(d, |p| p.contains("brave")).unwrap();
        assert!(out.contains("Exec=/usr/bin/brave-browser-stable --force-renderer-accessibility %U\n"));
        assert!(out.contains("Exec=/usr/bin/brave-browser-stable --force-renderer-accessibility\n"));
        assert!(out.contains("Exec=/usr/bin/other\n"));
        assert!(with_flag(&out, |p| p.contains("brave")).is_none(), "already fixed");
        assert!(with_flag("Exec=firefox %u\n", |_| false).is_none());
    }

    #[test]
    fn splits_a_rewritten_command_line() {
        let one = b"/opt/google/chrome/chrome --user-data-dir=/tmp/my dir --no-first-run https://example.com";
        assert_eq!(split_cmdline(one), vec!["/opt/google/chrome/chrome", "--user-data-dir=/tmp/my dir", "--no-first-run", "https://example.com"]);
        assert_eq!(split_cmdline(b"/usr/bin/x\0--a\0b c\0"), vec!["/usr/bin/x", "--a", "b c"]);
    }

    #[test]
    fn finds_chromium_by_its_files_not_its_name() {
        let dir = std::env::temp_dir().join(format!("vimvibe-chromium-test-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let exe = dir.join("totally-unrelated-name");
        std::fs::write(&exe, "").unwrap();
        assert!(!is_chromium_exe(&exe));
        std::fs::write(dir.join("icudtl.dat"), "").unwrap();
        std::fs::write(dir.join("resources.pak"), "").unwrap();
        assert!(is_chromium_exe(&exe));
        std::fs::remove_dir_all(&dir).unwrap();
    }
}
