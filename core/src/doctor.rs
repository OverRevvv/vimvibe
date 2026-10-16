//! `vimvibe-core doctor`: first-run / troubleshooting check.
//!
//! Read-only unless asked: `--fix` turns session accessibility on, `--fix-env` writes the toolkit environment file.
//! Most "it finds nothing" reports are accessibility setup, not bugs (research/10: the per-toolkit table from
//! vimium-everywhere; research/08 R1: AT-SPI is off by default here and apps started earlier never appear).
//! Privacy: window titles are never read or printed, only application class and PID.

use crate::daemon;
use crate::kwin;
use atspi::connection::{AccessibilityConnection, read_session_accessibility, set_session_accessibility};
use serde::Serialize;
use std::collections::BTreeMap;
use std::path::PathBuf;
use std::time::Duration;

#[derive(Serialize, Clone, Copy, PartialEq, Debug)]
#[serde(rename_all = "lowercase")]
pub enum Status {
    Ok,
    Info,
    Warn,
    Fail,
}

#[derive(Serialize)]
pub struct Check {
    pub id: &'static str,
    pub status: Status,
    pub title: String,
    pub detail: Vec<String>,
    pub fix: Option<String>,
}

/// Build one check result.
fn check(id: &'static str, status: Status, title: impl Into<String>, detail: Vec<String>, fix: Option<&str>) -> Check {
    Check { id, status, title: title.into(), detail, fix: fix.map(str::to_string) }
}

#[derive(Clone, Copy, PartialEq, Debug, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum Toolkit {
    Chromium,
    Firefox,
    Java,
    Qt,
    Gtk,
    Unknown,
}

impl Toolkit {
    /// What to do when a window of this toolkit is missing from the accessibility bus (from the vimium-everywhere
    /// compatibility table, 10 §1; our own experiments confirmed the Chromium and "started before enabling" cases).
    fn hint(self) -> &'static str {
        match self {
            Toolkit::Chromium => "Chromium/Electron: restart it after accessibility is on; if still missing launch with ACCESSIBILITY_ENABLED=1 and --force-renderer-accessibility",
            Toolkit::Firefox => "Firefox: restart it; if still missing set GNOME_ACCESSIBILITY=1 for it",
            Toolkit::Java => "Java: needs the ATK bridge (Fedora: java-atk-wrapper, Debian/Ubuntu: libatk-wrapper-java) and a restart",
            Toolkit::Qt => "Qt: restart it; if still missing set QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1",
            Toolkit::Gtk => "GTK: restart it (it should work once accessibility was on at launch)",
            Toolkit::Unknown => "toolkit not recognised: restart it; games, Wine, Tk and other exotic toolkits may never expose accessibility",
        }
    }
}

/// Guess the toolkit from the libraries a process has mapped. Heuristic (labelled as such in the output).
fn detect_toolkit(pid: u32) -> Toolkit {
    let Ok(maps) = std::fs::read_to_string(format!("/proc/{pid}/maps")) else { return Toolkit::Unknown };
    let has = |needle: &str| maps.contains(needle);
    if has("icudtl.dat") || has("v8_context_snapshot") || has("libffmpeg.so") {
        Toolkit::Chromium
    } else if has("libxul.so") {
        Toolkit::Firefox
    } else if has("libjvm.so") {
        Toolkit::Java
    } else if has("libQt6Core") || has("libQt5Core") {
        Toolkit::Qt
    } else if has("libgtk-4") || has("libgtk-3") {
        Toolkit::Gtk
    } else {
        Toolkit::Unknown
    }
}

/// An app that is registered but whose window has (almost) no accessible nodes: Chromium/Electron without renderer
/// accessibility reports a 2-item cache. Uses the app cache when available, else the window's child count.
async fn tree_looks_empty(conn: &AccessibilityConnection, app: &atspi::ObjectRefOwned) -> bool {
    use atspi::proxy::cache::CacheProxy;
    if let Some(bus) = app.name() {
        if let Ok(b) = CacheProxy::builder(conn.connection()).destination(bus.clone()) {
            if let Ok(cache) = b.build().await {
                if let Ok(items) = cache.get_items().await {
                    return items.len() <= 5;
                }
            }
        }
    }
    let Ok(p) = crate::enumerate::proxy(conn, app).await else { return false };
    let mut total = 0;
    for w in p.get_children().await.unwrap_or_default() {
        if let Ok(wp) = crate::enumerate::proxy(conn, &w).await {
            total += wp.child_count().await.unwrap_or(0);
        }
    }
    total == 0
}

/// The environment.d file `--fix-env` writes so toolkits enable accessibility from login on.
fn env_file() -> PathBuf {
    let base = std::env::var_os("XDG_CONFIG_HOME")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".config")))
        .unwrap_or_else(|| PathBuf::from(".config"));
    base.join("environment.d").join("50-vimvibe-accessibility.conf")
}

const ENV_CONTENT: &str = "# written by `vimvibe-core doctor --fix-env`; applies from the next login\n\
QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1\nGNOME_ACCESSIBILITY=1\nACCESSIBILITY_ENABLED=1\n";

/// Run every check (applying `--fix`/`--fix-env` first when asked), print them, and return the exit code
/// (1 when anything failed).
pub async fn run(fix: bool, fix_env: bool, json: bool) -> anyhow::Result<i32> {
    let mut out: Vec<Check> = vec![];

    // 1. session
    let session = std::env::var("XDG_SESSION_TYPE").unwrap_or_default();
    let desktop = std::env::var("XDG_CURRENT_DESKTOP").unwrap_or_default();
    let kde = kwin::on_kde();
    out.push(if kde && session == "wayland" {
        check("session", Status::Ok, format!("KDE Plasma on Wayland ({desktop})"), vec![], None)
    } else if kde {
        check("session", Status::Warn, format!("KDE Plasma on {session} (X11 is secondary; Wayland is the primary target)"), vec![], None)
    } else {
        check(
            "session",
            Status::Warn,
            format!("{desktop} on {session}: the global shortcut and focus tracking are KDE-only"),
            vec!["Element search still works; the daemon cannot register a shortcut here".into()],
            Some("bind any key in your desktop to: gdbus call --session --dest org.vimvibe.Daemon --object-path /org/vimvibe/Daemon --method org.vimvibe.Daemon.Trigger"),
        )
    });

    // 2. accessibility switch
    let mut enabled = read_session_accessibility().await;
    if let Ok(false) = enabled {
        if fix {
            set_session_accessibility(true).await?;
            enabled = read_session_accessibility().await;
            out.push(check("a11y-fixed", Status::Info, "Turned session accessibility on (--fix)", vec!["Apps started before this must be restarted to appear".into()], None));
        }
    }
    let a11y_on = matches!(enabled, Ok(true));
    out.push(match &enabled {
        Ok(true) => check("a11y", Status::Ok, "Session accessibility (AT-SPI) is enabled", vec![], None),
        Ok(false) => check(
            "a11y",
            Status::Fail,
            "Session accessibility (AT-SPI) is OFF: no application will expose its buttons",
            vec!["This is the Linux counterpart of Shortcat's Accessibility permission".into()],
            Some("vimvibe-core doctor --fix   (then restart the apps you want to control)"),
        ),
        Err(e) => check("a11y", Status::Fail, "The AT-SPI accessibility bus is not reachable", vec![e.to_string()], Some("install and start at-spi2-core (it normally ships with the desktop)")),
    });

    // 3. which windows are visible to accessibility
    let wins = if kde { kwin::list_windows(Duration::from_millis(1000)).await } else { None };
    match &wins {
        None if kde => out.push(check("kwin", Status::Warn, "Could not list windows through KWin scripting", vec!["The daemon falls back to the active-frame heuristic".into()], None)),
        None => {}
        Some(_) => out.push(check("kwin", Status::Ok, "KWin scripting works (focus tracking and window geometry)", vec![], None)),
    }
    if let Some(wins) = wins.filter(|_| a11y_on) {
        // (pid, app name, ref) of everything on the accessibility bus
        let mut on_bus: Vec<(u32, String, atspi::ObjectRefOwned)> = vec![];
        let mut conn_opt = None;
        if let Ok(conn) = AccessibilityConnection::new().await {
            if let Ok(root) = conn.root_accessible_on_registry().await {
                for app in root.get_children().await.unwrap_or_default() {
                    let name = match crate::enumerate::proxy(&conn, &app).await {
                        Ok(p) => p.name().await.unwrap_or_default(),
                        Err(_) => String::new(),
                    };
                    let pid = crate::enumerate::app_pid(&conn, &app).await.unwrap_or(0);
                    on_bus.push((pid, name, app));
                }
            }
            conn_opt = Some(conn);
        }
        let mut by_pid: BTreeMap<u32, String> = BTreeMap::new();
        for w in wins.iter().filter(|w| !w.caption_is_ui) {
            by_pid.entry(w.pid).or_insert_with(|| w.class.clone());
        }
        // Sandboxed apps (Flatpak/Snap) report a PID from another namespace, so fall back to matching the app name
        // against the window class (`com.rtosta.zapzap` ~ `ZapZap`).
        let find = |pid: u32, class: &str| {
            let tail = class.rsplit('.').next().unwrap_or(class).to_lowercase();
            // name matching only for bus entries whose PID is not another listed window's (Flatpak PIDs match nothing)
            on_bus.iter().find(|(p, n, _)| *p == pid || !by_pid.contains_key(p) && { let n = n.to_lowercase(); !n.is_empty() && (n == tail || n == class.to_lowercase() || tail.contains(&n) || n.contains(&tail)) })
        };
        let (mut seen, mut missing, mut empty) = (0usize, vec![], vec![]);
        for (pid, class) in &by_pid {
            match find(*pid, class) {
                None => missing.push((*pid, class.clone())),
                Some((_, _, app)) => {
                    seen += 1;
                    if let Some(conn) = &conn_opt {
                        if tree_looks_empty(conn, app).await {
                            empty.push((*pid, class.clone()));
                        }
                    }
                }
            }
        }
        let describe = |(pid, class): &(u32, String)| {
            let tk = detect_toolkit(*pid);
            (tk, format!("{class} (pid {pid}, looks like {tk:?})"))
        };
        if missing.is_empty() && empty.is_empty() {
            out.push(check("apps", Status::Ok, format!("All {} open application windows are visible to accessibility", seen), vec![], None));
        }
        if !missing.is_empty() {
            let detail: Vec<String> = missing.iter().map(|m| { let (tk, d) = describe(m); format!("{d}: {}", tk.hint()) }).collect();
            out.push(check(
                "apps",
                Status::Warn,
                format!("{} of {} open applications are not visible to accessibility", missing.len(), by_pid.len()),
                detail,
                Some("restart those applications; toolkit hints above"),
            ));
        }
        if !empty.is_empty() {
            let detail: Vec<String> = empty
                .iter()
                .map(|m| {
                    let (tk, d) = describe(m);
                    let how = if tk == Toolkit::Chromium { "launch it with --force-renderer-accessibility (Chromium builds its accessibility tree lazily; seen once with VS Code: 2 nodes at first launch, 400+ with the flag)".to_string() } else { tk.hint().to_string() };
                    format!("{d}: {how}")
                })
                .collect();
            out.push(check(
                "apps-empty",
                Status::Warn,
                format!("{} application(s) are on the accessibility bus but expose an empty tree (nothing to click)", empty.len()),
                detail,
                None,
            ));
        }
    } else if !a11y_on {
        out.push(check("apps", Status::Info, "Application check skipped until accessibility is enabled", vec![], None));
    }

    // 4. shortcut
    if kde {
        let conn = zbus::Connection::session().await?;
        // daemon state first: KDE reports a shortcut as unavailable to everyone, including its owner
        let status: Option<serde_json::Value> = conn
            .call_method(Some(daemon::NAME), daemon::PATH, Some("org.vimvibe.Daemon"), "Status", &())
            .await
            .ok()
            .and_then(|m| m.body().deserialize::<String>().ok())
            .and_then(|s| serde_json::from_str(&s).ok());
        let avail: Option<bool> = conn
            .call_method(Some("org.kde.kglobalaccel"), "/kglobalaccel", Some("org.kde.KGlobalAccel"), "isGlobalShortcutAvailable", &(daemon::DEFAULT_KEY, daemon::COMPONENT))
            .await
            .ok()
            .and_then(|m| m.body().deserialize().ok());
        let ours = status.as_ref().is_some_and(|s| s["hotkey_registered"] == true);
        out.push(match avail {
            _ if ours => check("shortcut", Status::Ok, "Shortcut Meta+Shift+Space is registered by the running daemon", vec![], None),
            Some(true) => check("shortcut", Status::Ok, "Default shortcut Meta+Shift+Space is free (or already ours)", vec![], None),
            Some(false) => check(
                "shortcut",
                Status::Warn,
                "Meta+Shift+Space is already bound to another action",
                vec!["The daemon keeps whatever is configured; rebind in System Settings → Shortcuts".into()],
                None,
            ),
            None => check("shortcut", Status::Warn, "Could not query KDE's global shortcut service", vec![], None),
        });
        out.push(match status {
            None => check(
                "daemon",
                Status::Warn,
                "The vimvibe daemon is not running",
                vec![],
                Some("vimvibe-core daemon   (or install packaging/vimvibe-daemon.service as a systemd user unit)"),
            ),
            Some(s) => {
                let ok = s["hotkey_registered"] == true && s["kwin_watching"] == true;
                check(
                    "daemon",
                    if ok { Status::Ok } else { Status::Warn },
                    if ok { "Daemon running: shortcut registered, focus watcher active".to_string() } else { "Daemon running but degraded".to_string() },
                    vec![format!("hotkey_registered={} kwin_watching={}", s["hotkey_registered"], s["kwin_watching"])],
                    None,
                )
            }
        });
    }

    // pointer fallback
    out.push(if crate::pointer::is_set_up() {
        check("pointer", Status::Ok, "Pointer-click fallback approved (RemoteDesktop portal token present)", vec![format!("token: {}", crate::pointer::token_path().display())], None)
    } else {
        check(
            "pointer",
            Status::Info,
            "Pointer-click fallback not set up (only needed for controls with no semantic activation, e.g. GTK4 check boxes)",
            vec!["Setup shows one consent dialog from your desktop; vimvibe never opens it on its own".into()],
            Some("vimvibe-core pointer-setup"),
        )
    });

    // 6. persistent environment for toolkits that need a flag
    let ef = env_file();
    if fix_env {
        if let Some(dir) = ef.parent() {
            std::fs::create_dir_all(dir)?;
        }
        std::fs::write(&ef, ENV_CONTENT)?;
        out.push(check("env-fixed", Status::Info, format!("Wrote {}", ef.display()), vec!["Takes effect at your next login; sets QT_LINUX_ACCESSIBILITY_ALWAYS_ON, GNOME_ACCESSIBILITY, ACCESSIBILITY_ENABLED for all apps".into()], None));
    } else if ef.exists() {
        out.push(check("env", Status::Ok, "Toolkit accessibility environment file is present", vec![ef.display().to_string()], None));
    } else {
        out.push(check(
            "env",
            Status::Info,
            "No toolkit accessibility environment file (only needed when an app stays invisible after a restart)",
            vec![],
            Some("vimvibe-core doctor --fix-env"),
        ));
    }
    out.push(check("overlay", Status::Info, "Keyboard-grabbing overlay (layer-shell) not checked: keys typed before the palette appears reach the target app", vec![], None));

    let failed = out.iter().any(|c| c.status == Status::Fail);
    if json {
        println!("{}", serde_json::to_string_pretty(&out)?);
    } else {
        for c in &out {
            let mark = match c.status {
                Status::Ok => "[ ok ]",
                Status::Info => "[info]",
                Status::Warn => "[warn]",
                Status::Fail => "[FAIL]",
            };
            println!("{mark} {}", c.title);
            for d in &c.detail {
                println!("         {d}");
            }
            if let Some(f) = &c.fix {
                println!("         fix: {f}");
            }
        }
        println!("\n{}", if failed { "Setup incomplete: fix the [FAIL] items above." } else { "No blocking problems found." });
    }
    Ok(i32::from(failed))
}
