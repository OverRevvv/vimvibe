mod apps;
mod config;
mod decor;
mod daemon;
mod doctor;
mod enumerate;
mod hints;
mod keygrab;
mod kwin;
pub(crate) mod matcher;
mod model;
mod pointer;
mod popups;
mod scroller;

use atspi::connection::{AccessibilityConnection, read_session_accessibility, set_session_accessibility};
use clap::{Parser, Subcommand};
use enumerate::{Opts, enumerate, list_apps, target_window};
use std::time::{Duration, Instant};

/// vimvibe core prototype: keyboard-driven "click anything by typing its name" over AT-SPI.
#[derive(Parser)]
#[command(version)]
struct Cli {
    #[command(subcommand)]
    cmd: Cmd,
    /// Target the app whose accessible name contains this text instead of the focused window.
    #[arg(long, global = true)]
    app: Option<String>,
    #[arg(long, global = true)]
    json: bool,
    /// Include hidden / zero-size elements (debugging).
    #[arg(long, global = true)]
    include_hidden: bool,
    #[arg(long, global = true, default_value_t = 3000)]
    timeout_ms: u64,
    /// Enable session accessibility (org.a11y.Status.IsEnabled=true) before running.
    #[arg(long, global = true)]
    enable_a11y: bool,
    /// How to find elements: auto (cache, then tree walk), cache, collection (experimental), or walk.
    #[arg(long, global = true, value_enum, default_value_t = Strategy::Auto)]
    strategy: Strategy,
    /// Testing: click with the pointer even when a semantic action exists.
    #[arg(long, global = true)]
    force_pointer: bool,
    /// Never fall back to a pointer click when no semantic activation works.
    #[arg(long, global = true)]
    no_pointer: bool,
    /// Also fetch action names per element (slower; activation does not need it).
    #[arg(long, global = true)]
    with_actions: bool,
}

#[derive(Clone, Copy, PartialEq, clap::ValueEnum)]
pub(crate) enum Strategy {
    Auto,
    Cache,
    Collection,
    Walk,
}

#[derive(Subcommand)]
enum Cmd {
    /// Show whether session accessibility is enabled.
    Status,
    /// List applications on the accessibility bus.
    Apps,
    /// List actionable elements of the target window.
    List,
    /// Fuzzy-search the target window's elements.
    Search {
        query: Vec<String>,
        #[arg(short, long, default_value_t = 15)]
        limit: usize,
    },
    /// One-time: ask the desktop (RemoteDesktop portal) for permission to click, scroll and send arrow keys for you. Shows a consent dialog;
    /// nothing else in vimvibe ever opens it. The approval is remembered through a restore token.
    PointerSetup,
    /// Print the real pointer position (logical px) as KWin reports it.
    Cursor,
    /// List panels, open popups and windows as KWin sees them (kind, class, pid, geometry; no titles).
    Surfaces,
    /// Press keys in the focused window through the portal, e.g. `key j j space` (testing; needs keyboard permission).
    /// Each argument is an X keysym name (a letter, digit, `space`, `Down`, ...) or a hex keysym like `0xff54`;
    /// `+name` only presses, `-name` only releases.
    Key { keys: Vec<String> },
    /// Testing: send smooth scroll events where the pointer is: `scroll-px 0 60 --steps 30` sends 30 events of 2 units
    /// (1 unit = 1/10 wheel notch), 8 ms apart, then a finish event. Negative values need `--`: `scroll-px -- 0 -60`.
    ScrollPx {
        dx: f64,
        dy: f64,
        #[arg(long, default_value_t = 30)]
        steps: u32,
    },
    /// Click at screen coordinates through the portal (needs `pointer-setup` first).
    Click {
        x: f64,
        y: f64,
        #[arg(long)]
        right: bool,
        #[arg(long)]
        double: bool,
        /// Leave the pointer on the target instead of putting it back.
        #[arg(long)]
        no_restore: bool,
    },
    /// Check the setup (accessibility, apps, shortcut, daemon). Read-only unless a --fix flag is given.
    Doctor {
        /// Turn session accessibility (AT-SPI) on.
        #[arg(long)]
        fix: bool,
        /// Write ~/.config/environment.d/50-vimvibe-accessibility.conf (toolkit accessibility variables; applies at next login).
        #[arg(long)]
        fix_env: bool,
    },
    /// Run the resident daemon: warm focus tracking, global shortcut, D-Bus API for UIs.
    Daemon {
        /// Do not register the global shortcut (use the Trigger D-Bus method).
        #[arg(long)]
        no_hotkey: bool,
    },
    /// Show what KWin says is focused and which AT-SPI window it maps to.
    Focus,
    /// Print KWin focus/geometry events for N seconds (default 15).
    Watch {
        #[arg(default_value_t = 15)]
        seconds: u64,
    },
    /// Enumerate once, then answer JSON-lines requests on stdin: {"q":"text"} or {"act":N} (N indexes the last result list).
    Serve,
    /// Activate the best (or --index N) match with its AT-SPI action.
    Act {
        query: Vec<String>,
        #[arg(long, default_value_t = 0)]
        index: usize,
        #[arg(long)]
        dry_run: bool,
    },
}

/// CLI entry point: parse the command, connect to the accessibility bus when needed, and run it.
#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let cli = Cli::parse();
    if cli.enable_a11y {
        set_session_accessibility(true).await?;
    }
    match cli.cmd {
        Cmd::Key { keys } => {
            let p = pointer::Pointer::connect(false).await?;
            for k in keys {
                let (press, release, name) = match k.chars().next() {
                    Some('+') if k.len() > 1 => (true, false, &k[1..]),
                    Some('-') if k.len() > 1 => (false, true, &k[1..]),
                    _ => (true, true, k.as_str()),
                };
                let sym = keysym(name).ok_or_else(|| anyhow::anyhow!("unknown key {name}"))?;
                if press {
                    p.key(sym, true).await?;
                }
                if release {
                    p.key(sym, false).await?;
                }
                tokio::time::sleep(Duration::from_millis(60)).await;
            }
            p.close().await;
            return Ok(());
        }
        Cmd::Surfaces => {
            let list = kwin::surfaces(Duration::from_millis(1000)).await.ok_or_else(|| anyhow::anyhow!("KWin scripting unavailable"))?;
            for s in list {
                println!("{:6} {:28} pid {:7} ({}, {}, {}x{}){}{}", s.kind, s.class, s.pid, s.x, s.y, s.w, s.h, if s.active { " active" } else { "" }, if s.hidden { " hidden" } else { "" });
            }
            return Ok(());
        }
        Cmd::Cursor => {
            match kwin::cursor_pos(Duration::from_millis(1000)).await {
                Some((x, y)) => println!("{x:.0} {y:.0}"),
                None => anyhow::bail!("cannot read the cursor position (KDE/KWin scripting required)"),
            }
            return Ok(());
        }
        Cmd::PointerSetup => {
            println!("A permission dialog from your desktop will appear: approve it to let vimvibe click, scroll and send");
            println!("arrow keys for you (tick the keyboard as well as the pointer for arrow keys).");
            let p = pointer::Pointer::connect(true).await?;
            println!("granted: pointer{}; token saved to {}", if p.has_keyboard() { " and keyboard" } else { " only (no arrow keys)" }, pointer::token_path().display());
            p.close().await;
            return Ok(());
        }
        Cmd::ScrollPx { dx, dy, steps } => {
            let p = pointer::Pointer::connect(false).await?;
            for _ in 0..steps {
                p.axis(dx / steps as f64, dy / steps as f64, false).await?;
                tokio::time::sleep(Duration::from_millis(8)).await;
            }
            p.axis(0.0, 0.0, true).await?;
            tokio::time::sleep(Duration::from_millis(100)).await;
            p.close().await;
            return Ok(());
        }
        Cmd::Click { x, y, right, double, no_restore } => {
            let p = pointer::Pointer::connect(false).await?;
            let button = if right { pointer::Button::Right } else { pointer::Button::Left };
            p.click_at(x, y, button, if double { 2 } else { 1 }, !no_restore).await?;
            println!("clicked at ({x:.0}, {y:.0})");
            p.close().await;
            return Ok(());
        }
        _ => {}
    }
    if let Cmd::Doctor { fix, fix_env } = cli.cmd {
        std::process::exit(doctor::run(fix, fix_env, cli.json).await?);
    }
    if let Cmd::Status = cli.cmd {
        println!("session accessibility enabled: {}", read_session_accessibility().await?);
        return Ok(());
    }
    let conn = AccessibilityConnection::new().await?;
    if let Cmd::Daemon { no_hotkey } = cli.cmd {
        return daemon::run(conn, cli.timeout_ms, !no_hotkey).await;
    }
    if let Cmd::Apps = cli.cmd {
        for (name, n) in list_apps(&conn).await? {
            println!("{name}\t({n} top-level children)");
        }
        return Ok(());
    }
    if let Cmd::Watch { seconds } = cli.cmd {
        let mut s = kwin::watch().await?;
        let end = tokio::time::Instant::now() + Duration::from_secs(seconds);
        while let Ok(Some(f)) = tokio::time::timeout_at(end, s.rx.recv()).await {
            println!("{}\tpid {}\t{}\t({}, {}, {}x{})", f.class, f.pid, trunc(&f.caption, 50), f.x, f.y, f.w, f.h);
        }
        s.stop().await;
        return Ok(());
    }
    let t_focus = Instant::now();
    let focus = if cli.app.is_none() && kwin::on_kde() { kwin::active_window(Duration::from_millis(500)).await } else { None };
    let focus_ms = t_focus.elapsed();
    let mut win = target_window(&conn, cli.app.as_deref(), focus.as_ref()).await?.ok_or_else(|| {
        anyhow::anyhow!("no target window found (is accessibility enabled and the app restarted? try --enable-a11y / --app NAME)")
    })?;
    enumerate::fill_geometry(&conn, &mut win).await;
    if let Cmd::Focus = cli.cmd {
        println!("kwin focus ({focus_ms:.0?}): {focus:?}");
        println!("matched AT-SPI window: {} / '{}' geometry {:?}", win.app, win.title, win.geometry);
        return Ok(());
    }
    let opts = Opts { include_hidden: cli.include_hidden, timeout: Duration::from_millis(cli.timeout_ms), max_nodes: 50_000, with_actions: cli.with_actions };
    let t = Instant::now();
    let (found, via) = find_elements(&conn, &win, &opts, cli.strategy).await;
    let (els, truncated) = found;
    eprintln!("[{} / '{}'] {} elements in {:.0?} via {via}{}", win.app, win.title, els.len(), t.elapsed(), if truncated { " (TRUNCATED by budget)" } else { "" });

    let (query, limit, act, index, dry) = match &cli.cmd {
        Cmd::List => (String::new(), usize::MAX, false, 0, false),
        Cmd::Search { query, limit } => (query.join(" "), *limit, false, 0, false),
        Cmd::Act { query, index, dry_run } => (query.join(" "), index + 1, true, *index, *dry_run),
        Cmd::Serve => (String::new(), 0, false, 0, false),
        Cmd::Focus | Cmd::Watch { .. } | Cmd::Daemon { .. } | Cmd::Doctor { .. } | Cmd::PointerSetup | Cmd::Cursor | Cmd::Click { .. } => unreachable!(),
        _ => unreachable!(),
    };
    if let Cmd::Serve = cli.cmd {
        return serve(&conn, &win, &els, truncated).await;
    }
    let hits = matcher::search(&els, &query, limit);
    if cli.json {
        let v: Vec<_> = hits.iter().map(|h| serde_json::json!({"score": h.score, "element": h.el})).collect();
        println!("{}", serde_json::to_string_pretty(&v)?);
    } else if !act {
        for (i, h) in hits.iter().enumerate() {
            let e = h.el;
            println!("{i:>3}  {:>5}  {:<12} {:<40} {:<14} {:?}{}", h.score, e.role, trunc(&e.name, 40), e.actions.first().map(String::as_str).unwrap_or("-"), e.rect, if e.enabled { "" } else { " (disabled)" });
        }
    }
    if act {
        let h = hits.get(index).ok_or_else(|| anyhow::anyhow!("no match at index {index} for '{query}'"))?;
        println!("target: {} '{}' {:?}", h.el.role, h.el.name, h.el.rect);
        if dry {
            println!("dry run, not activating");
        } else {
            let outcome = if cli.force_pointer { Err(model::NeedsPointer { role: h.el.role.clone(), rect: h.el.rect }.into()) } else { h.el.activate(&conn, !cli.no_pointer && pointer::is_set_up()).await };
            match outcome {
                Ok(msg) => println!("{msg}"),
                Err(e) if e.downcast_ref::<model::NeedsPointer>().is_some() && !cli.no_pointer => {
                    let (ox, oy) = win.geometry.map(|(x, y, _, _)| (x, y)).ok_or_else(|| anyhow::anyhow!("{e}, but the window's screen position is unknown (KWin geometry needed)"))?;
                    let (cx, cy) = ((h.el.rect.0 + h.el.rect.2 / 2 + ox) as f64, (h.el.rect.1 + h.el.rect.3 / 2 + oy) as f64);
                    let p = pointer::Pointer::connect(false).await.map_err(|pe| anyhow::anyhow!("{e}; {pe}"))?;
                    p.click_at(cx, cy, pointer::Button::Left, 1, true).await?;
                    p.close().await;
                    println!("clicked at ({cx:.0}, {cy:.0}) through the portal");
                }
                Err(e) => return Err(e),
            }
        }
    }
    Ok(())
}

/// Run the chosen strategy; `auto` tries the app cache, then the tree walk, falling through on failure or empty results.
pub(crate) async fn find_elements(conn: &AccessibilityConnection, win: &enumerate::Window, opts: &Opts, st: Strategy) -> ((Vec<model::Element>, bool), &'static str) {
    if matches!(st, Strategy::Auto | Strategy::Cache) {
        match enumerate::enumerate_cache(conn, win, opts).await {
            Some(v) if !v.is_empty() || st == Strategy::Cache => return ((v, false), "cache"),
            _ => {}
        }
    }
    if st == Strategy::Collection {
        // opt-in only: measured slower than the walk and it also returns closed-menu items
        if let Some(v) = enumerate::enumerate_collection(conn, win, opts).await {
            return ((v, false), "collection");
        }
    }
    (enumerate(conn, win, opts).await, "walk")
}

/// `serve` command: answer JSON-lines search/activate requests on stdin over one enumeration.
async fn serve(conn: &AccessibilityConnection, win: &enumerate::Window, els: &[model::Element], truncated: bool) -> anyhow::Result<()> {
    use tokio::io::{AsyncBufReadExt, BufReader};
    let say = |v: serde_json::Value| println!("{v}");
    say(serde_json::json!({"ready": true, "app": win.app, "window": win.title, "count": els.len(), "truncated": truncated, "origin": win.geometry}));
    let mut last: Vec<&model::Element> = Vec::new();
    let mut lines = BufReader::new(tokio::io::stdin()).lines();
    while let Some(line) = lines.next_line().await? {
        let Ok(req) = serde_json::from_str::<serde_json::Value>(&line) else {
            say(serde_json::json!({"error": "invalid json"}));
            continue;
        };
        if let Some(q) = req.get("q").and_then(|v| v.as_str()) {
            let hits = matcher::search(els, q, 30);
            last = hits.iter().map(|h| h.el).collect();
            // screen position = KWin clientGeometry origin + window-relative extents (null when KWin geometry is unknown)
            let screen = |e: &model::Element| win.geometry.map(|(ox, oy, _, _)| (e.rect.0 + ox, e.rect.1 + oy, e.rect.2, e.rect.3));
            let v: Vec<_> = hits.iter().map(|h| serde_json::json!({"score": h.score, "element": h.el, "screen": screen(h.el)})).collect();
            say(serde_json::json!({"hits": v}));
        } else if let Some(i) = req.get("act").and_then(|v| v.as_u64()) {
            match last.get(i as usize) {
                None => say(serde_json::json!({"act": false, "error": "no such result"})),
                Some(e) => match e.activate(conn, false).await { // serve has no pointer path
                    Ok(msg) => say(serde_json::json!({"act": true, "message": msg})),
                    Err(err) => say(serde_json::json!({"act": false, "error": err.to_string()})),
                },
            }
        } else if req.get("quit").is_some() {
            break;
        }
    }
    Ok(())
}

/// X keysym for a key name used by the `key` command: one letter/digit, a few named keys, or `0x…` hex.
fn keysym(name: &str) -> Option<i32> {
    if let Some(hex) = name.strip_prefix("0x") {
        return i32::from_str_radix(hex, 16).ok();
    }
    let mut chars = name.chars();
    if let (Some(c), None) = (chars.next(), chars.clone().next()) {
        if c.is_ascii_alphanumeric() {
            return Some(c.to_ascii_lowercase() as i32); // Latin-1 keysyms equal the character code
        }
    }
    Some(match name {
        "space" => 0x20,
        "Return" => 0xff0d,
        "Escape" => 0xff1b,
        "Tab" => 0xff09,
        "Left" => 0xff51,
        "Up" => 0xff52,
        "Right" => 0xff53,
        "Down" => 0xff54,
        "Shift_L" => 0xffe1,
        "Control_L" => 0xffe3,
        _ => return None,
    })
}

/// Shorten `s` to `n` characters for table output.
fn trunc(s: &str, n: usize) -> String {
    if s.chars().count() <= n { s.replace('\n', " ") } else { s.chars().take(n - 1).collect::<String>().replace('\n', " ") + "…" }
}
