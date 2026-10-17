//! Resident daemon: keeps the AT-SPI connection and the KWin focus watcher warm, owns the global shortcut,
//! and snapshots the focused window the moment the shortcut fires, before any UI can take focus.
//!
//! D-Bus API (session bus, name `org.vimvibe.Daemon`, path `/org/vimvibe/Daemon`) — UIs are thin clients:
//!   Trigger() -> json     snapshot the focused window; emits `Opened`. Toggles: when a snapshot is open it closes it.
//!   Search(q) -> json     ranked hits over the snapshot: [{id, hint, score, element, screen}]; a query equal to an
//!                         element's letter hint puts that element first
//!   Elements() -> json    every element with its id, letter hint and screen rectangle (for drawing labels)
//!   Activate(i) -> json   activate hit `i` of the last Search, then close the snapshot
//!   ActivateId(id) -> json  activate element `id` (from Elements/Search), then close the snapshot
//!   ActivateWith(id, action) -> json  same with action click | right | double | middle | hover | focus
//!   Refresh() -> json     re-read the same window (emits Opened again)
//!   ScrollStart(id), Scroll(dx, dy), ScrollEdge(dir), ScrollEnd()   scroll the element `id` (or the window): smooth glide in tenths of a wheel notch; ScrollEdge jumps to the top (-1) / bottom (1)
//!   ArrowStart(dx, dy), ArrowEnd(reopen)            arrow-key mode (Space + H/J/K/L sends arrows to the app)
//! Apps listed under [apps] exclude in ~/.config/vimvibe/config.toml are never read: Trigger emits Refused instead
//! (also emitted, with only `error`, when the focused window cannot be read).
//!   Close()               drop the snapshot; emits `Closed`
//!   Quit()                shut down (same as the Meta+Shift+Q shortcut); emits `Quitting` first
//!   Status() -> json      accessibility/KWin/shortcut state and the last timings
//! Signals: Opened(json), Closed(), Refused(json), Quitting(), Key(json) (typed over a popup, see keygrab.rs),
//! OpenSettings() (Ctrl+Shift+, pressed).
//!
//! Nothing runs while idle: no polling, the only wake-ups are D-Bus messages (hotkey, KWin focus reports, UI calls).

use crate::enumerate::{Opts, target_window};
use crate::kwin::{self, FocusInfo};
use crate::model::Element;
use crate::{Strategy, config, find_elements, hints, matcher};
use atspi::connection::AccessibilityConnection;
use futures_util::StreamExt;
use serde_json::{Value, json};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::Mutex;
use zbus::object_server::SignalEmitter;

/// D-Bus name of the daemon: `org.vimvibe.Daemon`, or `org.vimvibe.Daemon<Profile>` (e.g. `...DaemonDev`) for a
/// development profile so two daemons can run at once.
pub(crate) fn name() -> String {
    let p = config::profile();
    let mut cs = p.chars();
    match cs.next() {
        Some(c) => format!("org.vimvibe.Daemon{}{}", c.to_ascii_uppercase(), cs.as_str()),
        None => "org.vimvibe.Daemon".into(),
    }
}
pub(crate) const PATH: &str = "/org/vimvibe/Daemon";
/// Window title of the palette UI (see palette/vimvibe_palette.py); never a target.
const UI_CAPTION: &str = "vimvibe-palette";
/// KDE shortcut component (the group shown in System Settings → Shortcuts): `vimvibe`, `vimvibe-dev`, ...
pub(crate) fn component() -> String {
    config::dir_name()
}
const ACTION: &str = "toggle";
const QUIT_ACTION: &str = "quit";
const SETTINGS_ACTION: &str = "settings";
const CTRL: i32 = 0x0400_0000;
const SHIFT: i32 = 0x0200_0000;
const ALT: i32 = 0x0800_0000;
const META: i32 = 0x1000_0000;
/// Default keys per action (toggle, quit, settings). The installed vimvibe uses Meta+Shift+Space / Meta+Shift+Q /
/// Ctrl+Shift+,; a development profile uses Alt where the installed one uses Shift, so both can be registered at once.
fn default_keys() -> ([i32; 1], [i32; 1], Vec<i32>) {
    if config::profile().is_empty() {
        ([META | SHIFT | 0x20], [META | SHIFT | 0x51], vec![CTRL | SHIFT | 0x2c, CTRL | SHIFT | 0x3c])
    } else {
        ([META | ALT | 0x20], [META | ALT | 0x51], vec![CTRL | ALT | 0x2c])
    }
}
/// Apps whose windows are popups that close the moment another window takes the keyboard (Plasma's launcher, tray and
/// calendar popups, KRunner). vimvibe's overlay must take the keyboard, so their elements would vanish before use.
const CLOSES_ON_FOCUS_LOSS: &[&str] = &["plasmashell", "org.kde.plasmashell", "krunner", "org.kde.krunner"];
/// Qt::META | Qt::SHIFT | Qt::Key_Space. kglobalaccel keeps a user's own rebinding from System Settings over this default.
pub(crate) fn default_key() -> i32 {
    default_keys().0[0]
}

struct Snapshot {
    els: Vec<Element>,
    /// Letter hint per element (same index as `els`), see hints.rs.
    hints: Vec<String>,
    /// Element indexes of the last Search, in rank order (what `Activate(i)` refers to).
    last: Vec<usize>,
    geometry: Option<(i32, i32, i32, i32)>,
    /// Results that are not AT-SPI elements, by element index: other windows, title-bar buttons, applications.
    extra: std::collections::HashMap<usize, Extra>,
    /// Elements of open menus: listed first when nothing is typed (the menu is what the user is looking at).
    in_menu: std::collections::HashSet<usize>,
}

/// What activating a non-AT-SPI result does.
#[derive(Clone)]
enum Extra {
    /// Raise another window (KWin internal id).
    Window(String),
    /// A title-bar operation on the target window: (KWin id, op).
    TitleBar(String, &'static str),
    /// Launch an application (.desktop file).
    App(std::path::PathBuf),
}

impl Snapshot {
    /// Screen rectangle of an element (window origin + window-relative extents), None for results with no place on screen.
    fn screen(&self, e: &Element) -> Option<(i32, i32, i32, i32)> {
        if e.rect.2 <= 0 || e.rect.3 <= 0 {
            return None; // window results and zero-size elements have no place on screen
        }
        self.geometry.map(|(ox, oy, _, _)| (e.rect.0 + ox, e.rect.1 + oy, e.rect.2, e.rect.3))
    }
}

struct Shared {
    a11y: AccessibilityConnection,
    focus: Mutex<Option<FocusInfo>>,
    snap: Mutex<Option<Snapshot>>,
    stats: Mutex<Value>,
    /// Opened lazily, and only when `pointer-setup` was done before: the daemon never triggers the consent dialog.
    pointer: Mutex<Option<crate::pointer::Pointer>>,
    timeout: Duration,
    kwin_watching: std::sync::atomic::AtomicBool,
    hotkey: std::sync::atomic::AtomicBool,
    /// Wakes the main loop to shut down (Quit method or the quit shortcut).
    quit: tokio::sync::Notify,
    /// The keystroke listener is registered (an overlay is open over a popup that must keep the keyboard).
    grabbed: std::sync::atomic::AtomicBool,
    /// Bumped on every open (reported to UIs as `generation`).
    generation: std::sync::atomic::AtomicU64,
    /// Wakes the key task when a grab starts, so its safety timeout runs only while keys are taken.
    grab_started: tokio::sync::Notify,
    /// Menus that are open right now (Qt keeps them out of the tree; see popups.rs).
    menus: Option<Arc<crate::popups::Menus>>,
    /// Keystroke listener state (mode, "seen" flag), shared with the listener object (keygrab.rs).
    keys: Arc<crate::keygrab::State>,
    /// While scrolling: where the pointer was before we parked it over the scroll target (restored at the end).
    scroll_origin: Mutex<Option<(f64, f64)>>,
    /// The smooth-scroll engine (scroller.rs); `scroll_task` sends what it produces.
    scroller: crate::scroller::Scroller,
}

struct Daemon(Arc<Shared>);

#[zbus::interface(name = "org.vimvibe.Daemon")]
impl Daemon {
    /// D-Bus `Trigger()`: open the overlay for the focused window, or close it when it is open.
    async fn trigger(&self, #[zbus(signal_emitter)] em: SignalEmitter<'_>) -> String {
        trigger(&self.0, &em).await.to_string()
    }

    /// D-Bus `Search(q)`: rank the snapshot's elements for `query` and remember the order for `Activate(i)`.
    async fn search(&self, query: String) -> String {
        let mut guard = self.0.snap.lock().await;
        let Some(s) = guard.as_mut() else { return json!({"error": "no open snapshot; call Trigger first"}).to_string() };
        let mut ids: Vec<(usize, i64)> = matcher::search(&s.els, &query, usize::MAX)
            .iter()
            .filter_map(|h| s.els.iter().position(|e| std::ptr::eq(e, h.el)).map(|i| (i, h.score)))
            .collect();
        // Other windows and applications are for when you type: with an empty query the list is the window's own
        // elements (unless there are none, e.g. opened over the start menu). When typing they rank a little below an
        // equally good element of the window you are in. Title-bar buttons go after the window's content.
        let has_content = s.els.iter().enumerate().any(|(i, _)| !s.extra.contains_key(&i));
        let elsewhere = |i: usize| matches!(s.extra.get(&i), Some(Extra::Window(_) | Extra::App(_)));
        if query.trim().is_empty() {
            if has_content {
                ids.retain(|&(i, _)| !elsewhere(i));
            }
            ids.sort_by_key(|&(i, _)| (!s.in_menu.contains(&i), s.extra.contains_key(&i), matches!(s.extra.get(&i), Some(Extra::App(_)))));
        } else {
            for (i, score) in ids.iter_mut() {
                if elsewhere(*i) && has_content {
                    *score -= 60;
                }
            }
            ids.sort_by(|a, b| b.1.cmp(&a.1));
        }
        ids.truncate(30);
        // typing an element's hint puts that element first (Shortcat: "select an element by typing its hint")
        if let Some(i) = hints::as_hint(&query).and_then(|q| s.hints.iter().position(|h| *h == q)) {
            ids.retain(|&(j, _)| j != i);
            ids.insert(0, (i, i64::MAX));
            ids.truncate(30);
        }
        let out: Vec<Value> = ids
            .iter()
            .map(|&(i, score)| json!({"id": i, "hint": s.hints[i], "score": score, "element": s.els[i], "screen": s.screen(&s.els[i])}))
            .collect();
        s.last = ids.iter().map(|&(i, _)| i).collect();
        json!({"hits": out}).to_string()
    }

    /// Every element of the snapshot with its hint and screen rectangle (for drawing the labels).
    async fn elements(&self) -> String {
        let guard = self.0.snap.lock().await;
        let Some(s) = guard.as_ref() else { return json!({"error": "no open snapshot; call Trigger first"}).to_string() };
        let out: Vec<Value> = s
            .els
            .iter()
            .enumerate()
            .map(|(i, e)| json!({"id": i, "hint": s.hints[i], "name": e.name, "role": e.role, "enabled": e.enabled, "screen": s.screen(e)}))
            .collect();
        json!({"elements": out}).to_string()
    }

    /// Activate hit `index` of the last Search.
    async fn activate(&self, index: i32, #[zbus(signal_emitter)] em: SignalEmitter<'_>) -> String {
        let id = {
            let guard = self.0.snap.lock().await;
            guard.as_ref().and_then(|s| usize::try_from(index).ok().and_then(|i| s.last.get(i).copied()))
        };
        match id {
            Some(id) => activate_id(&self.0, id, Act::Click, &em).await,
            None => json!({"ok": false, "error": "no such result (call Search first)"}),
        }
        .to_string()
    }

    /// Activate an element by its id from `Elements()` / a hit's `id` (e.g. a clicked label).
    async fn activate_id(&self, id: i32, #[zbus(signal_emitter)] em: SignalEmitter<'_>) -> String {
        match usize::try_from(id) {
            Ok(id) => activate_id(&self.0, id, Act::Click, &em).await,
            Err(_) => json!({"ok": false, "error": "negative id"}),
        }
        .to_string()
    }

    /// Like ActivateId with a chosen action: click, right, double, middle, hover, focus.
    async fn activate_with(&self, id: i32, action: String, #[zbus(signal_emitter)] em: SignalEmitter<'_>) -> String {
        match (usize::try_from(id), Act::parse(&action)) {
            (Ok(id), Some(act)) => activate_id(&self.0, id, act, &em).await,
            (Err(_), _) => json!({"ok": false, "error": "negative id"}),
            (_, None) => json!({"ok": false, "error": format!("unknown action '{action}' (click, right, double, middle, hover, focus)")}),
        }
        .to_string()
    }

    /// Start scrolling: park the pointer over element `id` (or the middle of the window when `id` < 0), remembering
    /// where it was. Apps scroll whatever is under the pointer, so this picks *what* scrolls. Needs `pointer-setup`.
    async fn scroll_start(&self, id: i32) -> String {
        let (target, geometry) = {
            let guard = self.0.snap.lock().await;
            let Some(s) = guard.as_ref() else { return json!({"ok": false, "error": "no open snapshot"}).to_string() };
            let el = usize::try_from(id).ok().and_then(|i| s.els.get(i)).filter(|e| e.rect.2 > 0 && e.rect.3 > 0);
            (el.map(|e| e.rect), s.geometry)
        };
        let Some((ox, oy, ww, wh)) = geometry.filter(|g| g.2 > 0) else { return json!({"ok": false, "error": "the window's position is unknown"}).to_string() };
        let (x, y) = match target {
            Some((ex, ey, ew, eh)) => ((ox + ex + ew / 2) as f64, (oy + ey + eh / 2) as f64),
            None => ((ox + ww / 2) as f64, (oy + wh / 2) as f64),
        };
        let mut guard = self.0.pointer.lock().await;
        if guard.is_none() {
            match crate::pointer::Pointer::connect(false).await {
                Ok(p) => *guard = Some(p),
                Err(e) => return json!({"ok": false, "error": format!("scrolling needs pointer permission: {e}")}).to_string(),
            }
        }
        let mut origin = self.0.scroll_origin.lock().await;
        if origin.is_none() {
            *origin = kwin::cursor_pos(Duration::from_millis(500)).await;
        }
        match guard.as_ref().expect("connected").move_to(x, y).await {
            Ok(_) => json!({"ok": true, "at": [x, y]}).to_string(),
            Err(e) => {
                *guard = None;
                json!({"ok": false, "error": e.to_string()}).to_string()
            }
        }
    }

    /// Scroll where `ScrollStart` parked the pointer: `dy` > 0 down, `dx` > 0 right, in tenths of a wheel notch. The
    /// distance is added to a smooth glide that carries on after this returns (repeats merge into one continuous
    /// motion). Natural scrolling, swapped left/right and the glide's length come from the settings.
    async fn scroll(&self, dx: i32, dy: i32) -> String {
        if self.0.pointer.lock().await.is_none() {
            return json!({"ok": false, "error": "call ScrollStart first"}).to_string();
        }
        queue_scroll(&self.0, dx as f64, dy as f64);
        json!({"ok": true}).to_string()
    }

    /// Scroll to the top (`dir` < 0) or the bottom (`dir` > 0) of what is under the pointer: a long, fast glide of
    /// `edge_notches` that the app stops at the end of its content. Same pointer rules as `Scroll`.
    async fn scroll_edge(&self, dir: i32) -> String {
        if self.0.pointer.lock().await.is_none() {
            return json!({"ok": false, "error": "call ScrollStart first"}).to_string();
        }
        let c = config::load().scroll;
        let notches = c.edge_notches.clamp(10.0, 5000.0);
        self.0.scroller.add(0.0, dir.signum() as f64 * notches * 10.0, c.edge_ms.clamp(150, 3000) as f64);
        json!({"ok": true}).to_string()
    }

    /// Stop scrolling: put the pointer back where it was before `ScrollStart` (once the glide has finished).
    async fn scroll_end(&self) {
        wait_scroll_idle(&self.0).await;
        let origin = self.0.scroll_origin.lock().await.take();
        if let (Some((x, y)), Some(p)) = (origin, self.0.pointer.lock().await.as_ref()) {
            let _ = p.move_to(x, y).await;
        }
    }

    /// Start arrow mode (Space + H/J/K/L): close the overlay so the app has the keyboard again, take the physical
    /// H J K L / I, Space and Esc keys through the keystroke listener, check the app really hands its keys over (a
    /// harmless Shift tap must arrive), then send the first arrow (dx, dy). Needs the keyboard permission; without it
    /// the answer says `"fallback": "scroll"` and nothing changes.
    async fn arrow_start(&self, dx: i32, dy: i32, #[zbus(signal_emitter)] em: SignalEmitter<'_>) -> String {
        use std::sync::atomic::Ordering::SeqCst;
        let sh = &self.0;
        if sh.snap.lock().await.is_none() {
            return json!({"ok": false, "error": "no open snapshot"}).to_string();
        }
        if let Err(e) = keyboard_session(sh).await {
            return json!({"ok": false, "fallback": "scroll", "error": e.to_string()}).to_string();
        }
        let target = sh.focus.lock().await.clone();
        let app = target.as_ref().map(|f| f.class.clone()).unwrap_or_default();
        close(sh, &em).await;
        // The keys we send go to whichever window has the keyboard: wait until KWin reports the app active again
        // (the overlay hides first), so neither the check below nor the arrows land in vimvibe's own window.
        let mut back = false;
        for _ in 0..25 {
            if let Some(f) = kwin::active_window(Duration::from_millis(200)).await {
                if f.caption != UI_CAPTION && target.as_ref().is_none_or(|t| t.pid == f.pid) {
                    back = true;
                    break;
                }
            }
            tokio::time::sleep(Duration::from_millis(30)).await;
        }
        if !back {
            open(sh, &em).await;
            return json!({"ok": false, "error": "the app did not get the keyboard back"}).to_string();
        }
        if let Err(e) = crate::keygrab::grab(sh.a11y.connection(), &sh.keys, crate::keygrab::MODE_ARROWS).await {
            crate::keygrab::release(sh.a11y.connection(), &sh.keys).await;
            open(sh, &em).await;
            return json!({"ok": false, "error": format!("could not read keys: {e}")}).to_string();
        }
        sh.grabbed.store(true, SeqCst);
        sh.grab_started.notify_one();
        // Only apps that hand their keys to the accessibility registry (Qt, GTK 3) let us tell the user's H/J/K/L
        // apart from typing. Check with a Shift tap: if the listener never sees it, J would be typed into the app.
        sh.keys.seen.store(false, SeqCst);
        send_arrow(sh, XK_SHIFT_L).await;
        let mut ok = false;
        for _ in 0..20 {
            if sh.keys.seen.load(SeqCst) {
                ok = true;
                break;
            }
            tokio::time::sleep(Duration::from_millis(20)).await;
        }
        if !ok {
            end_arrows(sh, &em, true).await;
            return json!({"ok": false, "error": format!("{app} doesn't share its key presses with accessibility, so vimvibe can't send arrow keys there (works in KDE/Qt and GTK 3 apps such as Firefox). Space+Ctrl+H/J/K/L scrolls instead.")}).to_string();
        }
        if let Some(ks) = arrow_keysym(dx, dy) {
            send_arrow(sh, ks).await;
        }
        json!({"ok": true}).to_string()
    }

    /// Leave arrow mode (the UI saw Space released itself); `reopen` brings the overlay back.
    async fn arrow_end(&self, reopen: bool, #[zbus(signal_emitter)] em: SignalEmitter<'_>) {
        if self.0.keys.mode.load(std::sync::atomic::Ordering::SeqCst) == crate::keygrab::MODE_ARROWS {
            end_arrows(&self.0, &em, reopen).await;
        }
    }

    /// Re-read the same window (Shortcat's Cmd+R): drops the snapshot without `Closed`, then emits `Opened` again.
    async fn refresh(&self, #[zbus(signal_emitter)] em: SignalEmitter<'_>) -> String {
        wait_scroll_idle(&self.0).await; // labels must match where a running glide ends
        self.0.snap.lock().await.take();
        open(&self.0, &em).await.to_string()
    }

    /// D-Bus `Close()`: drop the snapshot (and any key grab) and tell UIs.
    async fn close(&self, #[zbus(signal_emitter)] em: SignalEmitter<'_>) {
        close(&self.0, &em).await;
    }

    /// D-Bus `Status()`: accessibility, KWin, shortcut and pointer state plus the last open's timings, as JSON.
    async fn status(&self) -> String {
        use std::sync::atomic::Ordering::Relaxed;
        let a11y = atspi::connection::read_session_accessibility().await.ok();
        json!({
            "accessibility_enabled": a11y,
            "kwin_watching": self.0.kwin_watching.load(Relaxed),
            "hotkey_registered": self.0.hotkey.load(Relaxed),
            "focus": *self.0.focus.lock().await,
            "snapshot_open": self.0.snap.lock().await.is_some(),
            "pointer": if self.0.pointer.lock().await.is_some() { "ready" } else if crate::pointer::is_set_up() { "set up (connects on first use)" } else { "not set up (run: vimvibe-core pointer-setup)" },
            "keyboard": crate::pointer::keyboard_granted(),
            "last": *self.0.stats.lock().await,
        })
        .to_string()
    }

    /// Shut vimvibe down (daemon and overlay), like the Meta+Shift+Q shortcut.
    async fn quit(&self) {
        self.0.quit.notify_one();
    }

    /// A key typed while a passive overlay is open: `{"name": "a", "text": true}` (Esc is handled by the daemon).
    #[zbus(signal)]
    async fn key(emitter: &SignalEmitter<'_>, payload: &str) -> zbus::Result<()>;

    /// The settings shortcut (Ctrl+Shift+,) was pressed: the UI opens its Settings window.
    #[zbus(signal)]
    async fn open_settings(emitter: &SignalEmitter<'_>) -> zbus::Result<()>;

    /// Emitted right before the daemon exits; UIs should exit too.
    #[zbus(signal)]
    async fn quitting(emitter: &SignalEmitter<'_>) -> zbus::Result<()>;

    /// Signal: a snapshot is ready; payload = app, counts, timings, window origin, passive flag.
    #[zbus(signal)]
    async fn opened(emitter: &SignalEmitter<'_>, payload: &str) -> zbus::Result<()>;

    /// Signal: the snapshot was dropped; UIs hide.
    #[zbus(signal)]
    async fn closed(emitter: &SignalEmitter<'_>) -> zbus::Result<()>;

    /// Trigger could not open: `{"excluded": rule, "error": ...}` for an excluded app, otherwise `{"error": ...}`.
    #[zbus(signal)]
    async fn refused(emitter: &SignalEmitter<'_>, payload: &str) -> zbus::Result<()>;
}

/// What to do with an element. `Click` runs the semantic activation ladder (pointer click only as a fallback); the
/// others are pointer actions at the element's centre and need `pointer-setup`.
#[derive(Clone, Copy, PartialEq, Debug)]
enum Act {
    Click,
    Right,
    Double,
    Middle,
    Hover,
    Focus,
}

impl Act {
    /// Action name from the D-Bus API (`click`, `right`, ...) to `Act`.
    fn parse(s: &str) -> Option<Act> {
        Some(match s {
            "" | "click" => Act::Click,
            "right" => Act::Right,
            "double" => Act::Double,
            "middle" => Act::Middle,
            "hover" => Act::Hover,
            "focus" => Act::Focus,
            _ => return None,
        })
    }
}

/// Do `act` on snapshot element `id`: close the overlay first, then window/title-bar/app results via KWin or the
/// launcher, elements via the semantic ladder with the pointer as fallback. Returns the JSON result for the UI.
async fn activate_id(sh: &Shared, id: usize, act: Act, em: &SignalEmitter<'_>) -> Value {
    let (el, geometry, extra) = {
        let guard = sh.snap.lock().await;
        match guard.as_ref() {
            Some(s) => (s.els.get(id).cloned(), s.geometry, s.extra.get(&id).cloned()),
            None => (None, None, None),
        }
    };
    let Some(el) = el else { return json!({"ok": false, "error": "no such element (call Trigger first)"}) };
    // close first: the UI hides, the target window regains focus, then the action lands
    close(sh, em).await;
    let t = Instant::now();
    let res = if let Some(x) = extra {
        match x {
            Extra::Window(wid) => kwin::activate_window(&wid, Duration::from_millis(500)).await.map(|_| json!({"ok": true, "message": "raised window", "via": "kwin"})),
            Extra::TitleBar(wid, op) => kwin::window_op(&wid, op, Duration::from_millis(500)).await.map(|_| json!({"ok": true, "message": format!("window {op}"), "via": "kwin"})),
            Extra::App(path) => crate::apps::launch(&path).map(|_| json!({"ok": true, "message": "launched", "via": "desktop"})),
        }
    } else {
        match act {
            Act::Click => match el.activate(&sh.a11y, crate::pointer::is_set_up()).await {
                Ok(msg) => Ok(json!({"ok": true, "message": msg, "via": "semantic"})),
                Err(e) if e.downcast_ref::<crate::model::NeedsPointer>().is_some() => match pointer_action(sh, &el, geometry, Act::Click).await {
                    Ok(msg) => Ok(json!({"ok": true, "message": msg, "via": "pointer"})),
                    Err(pe) => Err(anyhow::anyhow!("{e}; {pe}")),
                },
                Err(e) => Err(e),
            },
            Act::Focus => match el.focus(&sh.a11y).await {
                Ok(m) => Ok(json!({"ok": true, "message": m, "via": "semantic"})),
                // GTK4 does not implement grab_focus; clicking a text field focuses it without side effects
                Err(e) if matches!(el.role.as_str(), "Entry" | "PasswordText" | "Text" | "DocumentText" | "SpinButton" | "Terminal") => {
                    match pointer_action(sh, &el, geometry, Act::Click).await {
                        Ok(m) => Ok(json!({"ok": true, "message": m, "via": "pointer"})),
                        Err(pe) => Err(anyhow::anyhow!("{e}; {pe}")),
                    }
                }
                Err(e) => Err(e),
            },
            other => match el.enabled {
                false => Err(anyhow::anyhow!("'{}' is disabled", el.name)),
                true => pointer_action(sh, &el, geometry, other).await.map(|m| json!({"ok": true, "message": m, "via": "pointer"})),
            },
        }
    };
    match res {
        Ok(mut v) => {
            v["name"] = json!(el.name);
            v["role"] = json!(el.role);
            v["ms"] = json!(ms(t.elapsed()));
            v
        }
        Err(e) => json!({"ok": false, "error": e.to_string(), "name": el.name}),
    }
}

/// Pointer rung: click (or hover) at the element's centre through the RemoteDesktop portal.
async fn pointer_action(sh: &Shared, el: &Element, geometry: Option<(i32, i32, i32, i32)>, act: Act) -> anyhow::Result<String> {
    use crate::pointer::Button;
    let (ox, oy) = geometry.map(|(x, y, _, _)| (x, y)).ok_or_else(|| anyhow::anyhow!("the window's screen position is unknown"))?;
    let mut guard = sh.pointer.lock().await;
    if guard.is_none() {
        *guard = Some(crate::pointer::Pointer::connect(false).await?); // errors when pointer-setup was never run; never prompts
    }
    let (cx, cy) = ((el.rect.0 + el.rect.2 / 2 + ox) as f64, (el.rect.1 + el.rect.3 / 2 + oy) as f64);
    let p = guard.as_ref().expect("just connected");
    let r = match act {
        Act::Hover => p.move_to(cx, cy).await.map(|_| format!("moved the pointer to ({cx:.0}, {cy:.0})")),
        _ => {
            let (button, count, what) = match act {
                Act::Right => (Button::Right, 1, "right-clicked"),
                Act::Double => (Button::Left, 2, "double-clicked"),
                Act::Middle => (Button::Middle, 1, "middle-clicked"),
                _ => (Button::Left, 1, "clicked"),
            };
            // a right click opens a menu where the pointer is, so it must stay there; plain clicks restore it
            let restore = matches!(act, Act::Click | Act::Double | Act::Middle);
            p.click_at(cx, cy, button, count, restore).await.map(|_| format!("{what} at ({cx:.0}, {cy:.0}) through the portal"))
        }
    };
    if r.is_err() {
        *guard = None; // drop a possibly dead session so the next attempt reconnects
    }
    r
}

/// Release the keyboard grab if any, drop the snapshot and emit `Closed` (no-op when nothing is open).
/// X keysyms of the arrow keys.
const XK_LEFT: i32 = 0xff51;
const XK_UP: i32 = 0xff52;
const XK_RIGHT: i32 = 0xff53;
const XK_DOWN: i32 = 0xff54;
const XK_SHIFT_L: i32 = 0xffe1;

/// Arrow keysym for a direction (dx, dy).
fn arrow_keysym(dx: i32, dy: i32) -> Option<i32> {
    Some(match (dx.signum(), dy.signum()) {
        (-1, 0) => XK_LEFT,
        (1, 0) => XK_RIGHT,
        (0, -1) => XK_UP,
        (0, 1) => XK_DOWN,
        _ => return None,
    })
}

/// Direction of a physical key in arrow mode for the configured layout ("hjkl" or "ijkl").
fn arrow_for(code: u32, layout: &str) -> Option<(i32, i32)> {
    use crate::keygrab::{KC_H, KC_I, KC_J, KC_K, KC_L};
    Some(match (layout, code) {
        ("ijkl", KC_I) => (0, -1),
        ("ijkl", KC_J) => (-1, 0),
        ("ijkl", KC_K) => (0, 1),
        ("ijkl", KC_L) => (1, 0),
        (_, KC_H) if layout != "ijkl" => (-1, 0),
        (_, KC_J) => (0, 1),
        (_, KC_K) => (0, -1),
        (_, KC_L) => (1, 0),
        _ => return None,
    })
}

/// A pointer+keyboard portal session, (re)connected when the grant includes the keyboard but the cached session
/// doesn't. Errors when the keyboard was never granted.
async fn keyboard_session(sh: &Shared) -> anyhow::Result<()> {
    let mut guard = sh.pointer.lock().await;
    if guard.as_ref().is_some_and(|p| p.has_keyboard()) {
        return Ok(());
    }
    anyhow::ensure!(crate::pointer::keyboard_granted(), "arrow keys need keyboard permission: run `vimvibe-core pointer-setup` and allow the keyboard");
    *guard = Some(crate::pointer::Pointer::connect(false).await?);
    anyhow::ensure!(guard.as_ref().is_some_and(|p| p.has_keyboard()), "the desktop did not grant the keyboard");
    Ok(())
}

/// Send one arrow key (tap) to the focused window.
async fn send_arrow(sh: &Shared, keysym: i32) {
    if let Some(p) = sh.pointer.lock().await.as_ref() {
        if let Err(e) = p.tap(keysym).await {
            eprintln!("arrow key failed: {e}");
        }
    }
}

/// A key the listener took in arrow mode: H/J/K/L (or I/J/K/L) send arrows, Space release ends the mode and brings
/// the overlay back, Esc ends it without the overlay.
async fn arrow_key(sh: &Shared, em: &SignalEmitter<'_>, k: &crate::keygrab::Key) {
    use crate::keygrab::{KC_ESC, KC_SPACE};
    match (k.code, k.pressed) {
        (KC_ESC, true) => end_arrows(sh, em, false).await,
        (KC_SPACE, false) => end_arrows(sh, em, true).await,
        (crate::keygrab::KC_D, true) => arrow_mode_scroll(sh, 1).await,
        (crate::keygrab::KC_U, true) => arrow_mode_scroll(sh, -1).await,
        (code, true) => {
            let layout = config::load().scroll.keys;
            if let Some((dx, dy)) = arrow_for(code, &layout) {
                if let Some(ks) = arrow_keysym(dx, dy) {
                    send_arrow(sh, ks).await;
                }
            }
        }
        _ => {}
    }
}

/// Queue a scroll of (dx, dy) tenths of a wheel notch with the user's scroll settings applied: swapped left/right,
/// natural direction, the glide's length (see config.rs). Clamped so a runaway caller can't flood the desktop.
fn queue_scroll(sh: &Shared, dx: f64, dy: f64) {
    let c = config::load().scroll;
    let (mut dx, mut dy) = (dx.clamp(-2000.0, 2000.0), dy.clamp(-2000.0, 2000.0));
    if c.invert_horizontal {
        dx = -dx;
    }
    if c.natural {
        (dx, dy) = (-dx, -dy);
    }
    sh.scroller.add(dx, dy, if c.smooth { c.smooth_ms.clamp(20, 1000) as f64 } else { 0.0 });
}

/// Wait (at most 3 s) for the running glide to finish, so the pointer is not moved away from under it.
async fn wait_scroll_idle(sh: &Shared) {
    for _ in 0..300 {
        if !sh.scroller.busy() {
            return;
        }
        tokio::time::sleep(Duration::from_millis(10)).await;
    }
}

/// Sends the scroll engine's output as smooth axis events about every 8 ms while a glide runs.
async fn scroll_task(sh: Arc<Shared>) {
    loop {
        sh.scroller.wake.notified().await;
        let mut tick = tokio::time::interval(Duration::from_millis(8));
        tick.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
        let mut last = std::time::Instant::now();
        loop {
            tick.tick().await;
            let now = std::time::Instant::now();
            let dt = now.duration_since(last).as_secs_f64().min(0.05);
            last = now;
            let t = sh.scroller.step(dt);
            let guard = sh.pointer.lock().await;
            let Some(p) = guard.as_ref() else {
                sh.scroller.clear();
                break;
            };
            let sent = if t.dx != 0.0 || t.dy != 0.0 { p.axis(t.dx, t.dy, false).await } else { Ok(()) };
            let fin = if t.done && t.emitted { p.axis(0.0, 0.0, true).await } else { Ok(()) };
            if let Err(e) = sent.and(fin) {
                eprintln!("scroll failed: {e}");
                sh.scroller.clear();
                break;
            }
            if t.done {
                break;
            }
        }
    }
}

/// Space + D / U while arrow mode is on: scroll the middle of the focused window (the overlay is hidden, so the wheel
/// reaches the app directly). The pointer is parked once and put back when the mode ends.
async fn arrow_mode_scroll(sh: &Shared, dir: i32) {
    let step = (config::load().scroll.distance.clamp(0.1, 20.0) * 10.0).round();
    let Some(f) = sh.focus.lock().await.clone() else { return };
    {
        let guard = sh.pointer.lock().await;
        let Some(p) = guard.as_ref() else { return };
        let mut origin = sh.scroll_origin.lock().await;
        if origin.is_none() {
            *origin = kwin::cursor_pos(Duration::from_millis(500)).await;
            let _ = p.move_to((f.x + f.w / 2) as f64, (f.y + f.h / 2) as f64).await;
        }
    }
    queue_scroll(sh, 0.0, dir as f64 * step);
}

/// Leave arrow mode: give every key back to the app, and reopen the overlay on the (changed) window if asked.
async fn end_arrows(sh: &Shared, em: &SignalEmitter<'_>, reopen: bool) {
    if sh.grabbed.swap(false, std::sync::atomic::Ordering::SeqCst) {
        crate::keygrab::release(sh.a11y.connection(), &sh.keys).await;
    }
    wait_scroll_idle(sh).await;
    if let Some((x, y)) = sh.scroll_origin.lock().await.take() {
        if let Some(p) = sh.pointer.lock().await.as_ref() {
            let _ = p.move_to(x, y).await; // pointer back after Space + D/U scrolling in arrow mode
        }
    }
    if reopen {
        open(sh, em).await;
    }
}

async fn close(sh: &Shared, em: &SignalEmitter<'_>) {
    if sh.grabbed.swap(false, std::sync::atomic::Ordering::SeqCst) {
        crate::keygrab::release(sh.a11y.connection(), &sh.keys).await;
    }
    if sh.snap.lock().await.take().is_some() {
        let _ = Daemon::closed(em).await;
    }
}

/// Shortcut / `Trigger()` behaviour: toggle the overlay.
async fn trigger(sh: &Shared, em: &SignalEmitter<'_>) -> Value {
    if sh.snap.lock().await.is_some() {
        close(sh, em).await;
        return json!({"toggled": "closed"});
    }
    open(sh, em).await
}

/// Snapshot the focused window (plus, optionally, the list of other windows) and emit `Opened`.
async fn open(sh: &Shared, em: &SignalEmitter<'_>) -> Value {
    let t0 = Instant::now();
    let cfg = config::load(); // re-read every time: edits apply without a restart
    let cached = sh.focus.lock().await.clone();
    let focus = match cached {
        Some(f) => Some(f),
        None if kwin::on_kde() => kwin::active_window(Duration::from_millis(300)).await, // watcher not running or silent so far
        None => None,
    };
    let t_focus = t0.elapsed();
    let result: anyhow::Result<Value> = async {
        // Plasma's launcher/tray/calendar popups and KRunner close when the overlay takes the keyboard, so their own
        // elements can't be used. Opening over them gives the launcher experience instead: installed apps and open
        // windows, searched by name.
        let popup_mode = focus.as_ref().is_some_and(|f| CLOSES_ON_FOCUS_LOSS.contains(&f.class.to_lowercase().as_str()));
        // excluded apps are refused before their accessibility tree is read at all
        if let Some(f) = focus.as_ref().filter(|_| !popup_mode) {
            if let Some(rule) = cfg.apps.excluded("", Some(&f.class), Some(f.pid)) {
                return Ok(json!({"excluded": rule, "error": format!("{} is excluded in {}", f.class, config::path().display())}));
            }
        }
        let want_windows = cfg.search.windows && kwin::on_kde();
        let want_apps = cfg.search.apps;
        let (mut els, truncated, via, win_app, win_title, geometry, t_win) = if popup_mode {
            // the popup's own elements when it exposes them (Plasma's launcher does), else just apps and windows
            let opts = Opts { include_hidden: false, timeout: sh.timeout, max_nodes: 50_000, with_actions: false };
            match target_window(&sh.a11y, None, focus.as_ref()).await.ok().flatten().filter(|w| w.geometry.is_some()) {
                Some(win) => {
                    let t_win = t0.elapsed();
                    let ((els, truncated), via) = find_elements(&sh.a11y, &win, &opts, Strategy::Auto).await;
                    (els, truncated, via, win.app, win.title, win.geometry, t_win)
                }
                None => (vec![], false, "launcher", "Applications".to_string(), String::new(), None, t0.elapsed()),
            }
        } else {
            if atspi::connection::read_session_accessibility().await.ok() == Some(false) {
                anyhow::bail!("Desktop accessibility is off, so no app shows its buttons. Run `vimvibe doctor --fix`, then restart the apps you want to use.");
            }
            let win = target_window(&sh.a11y, None, focus.as_ref())
                .await?
                .ok_or_else(|| match &focus {
                    Some(f) => anyhow::anyhow!("{} is not visible to accessibility: restart it (accessibility must be on before an app starts; Chrome/Electron also need --force-renderer-accessibility). Run `vimvibe doctor`.", f.class),
                    None => anyhow::anyhow!("no target window found (is accessibility enabled, and was the app started after enabling it?)"),
                })?;
            if let Some(rule) = cfg.apps.excluded(&win.app, None, None) {
                return Ok(json!({"excluded": rule, "error": format!("{} is excluded in {}", win.app, config::path().display())}));
            }
            let t_win = t0.elapsed();
            let opts = Opts { include_hidden: false, timeout: sh.timeout, max_nodes: 50_000, with_actions: false };
            let ((els, truncated), via) = find_elements(&sh.a11y, &win, &opts, Strategy::Auto).await;
            (els, truncated, via, win.app, win.title, win.geometry, t_win)
        };
        // Open menus and the desktop's panels live in surfaces of their own. KWin knows where those are; their
        // AT-SPI objects give the elements (window-relative). Pair them by app and size, then move their elements
        // into the target window's coordinates so one origin serves the whole snapshot.
        let base = geometry.map(|(x, y, _, _)| (x, y)).unwrap_or((0, 0));
        let geometry = geometry.or(Some((0, 0, 0, 0))); // launcher fallback: screen coordinates
        let surfaces = if kwin::on_kde() { kwin::surfaces(Duration::from_millis(300)).await.unwrap_or_default() } else { vec![] };
        let focus_pid = focus.as_ref().map(|f| f.pid);
        let mut menu_popups: Vec<&kwin::Surface> = surfaces.iter().filter(|x| x.kind == "popup" && Some(x.pid) == focus_pid).collect();
        let any_menu_open = !menu_popups.is_empty();
        let mut in_menu = std::collections::HashSet::new();
        let opts = Opts { include_hidden: false, timeout: sh.timeout, max_nodes: 50_000, with_actions: false };
        let shift = |mut v: Vec<Element>, x: i32, y: i32| {
            for e in v.iter_mut().filter(|e| e.rect.2 > 0 && e.rect.3 > 0) {
                e.rect.0 += x - base.0;
                e.rect.1 += y - base.1;
            }
            v
        };
        if any_menu_open {
            if let Some(menus) = &sh.menus {
                for m in menus.showing().await {
                    let (Some(pid), Some((w, h))) = (crate::enumerate::app_pid(&sh.a11y, &m).await, crate::enumerate::window_size(&sh.a11y, &m).await) else { continue };
                    let Some(pos) = menu_popups.iter().position(|p| p.pid == pid && (p.w - w).abs() <= 2 && (p.h - h).abs() <= 2) else { continue };
                    let p = menu_popups.remove(pos);
                    let mw = crate::enumerate::Window { app: win_app.clone(), title: String::new(), root: m, geometry: Some((p.x, p.y, p.w, p.h)) };
                    let mels = crate::enumerate::menu_items(&sh.a11y, &mw, (p.w, p.h)).await;
                    for e in shift(mels, p.x, p.y) {
                        in_menu.insert(els.len());
                        els.push(e);
                    }
                }
            }
        }
        if cfg.search.panel && !surfaces.is_empty() {
            // only panels on screen now: an auto-hidden or covered panel's buttons can't be clicked
            let docks: Vec<&kwin::Surface> = surfaces.iter().filter(|x| x.kind == "dock" && x.visible_among(&surfaces)).collect();
            if !docks.is_empty() {
                for (pw, (w, h)) in crate::enumerate::app_windows(&sh.a11y, "plasmashell").await {
                    if let Some(d) = docks.iter().find(|d| (d.w - w).abs() <= 2 && (d.h - h).abs() <= 2) {
                        let pw = crate::enumerate::Window { geometry: Some((d.x, d.y, d.w, d.h)), ..pw };
                        let ((pels, _), _) = find_elements(&sh.a11y, &pw, &opts, Strategy::Auto).await;
                        els.extend(shift(pels, d.x, d.y));
                    }
                }
            }
        }
        // An open menu closes when the overlay takes the keyboard, like Plasma's popups: use the passive overlay.
        let popup_mode = popup_mode || any_menu_open;
        let n_elements = els.len();
        let mut extra = std::collections::HashMap::new();
        // the target window's title-bar buttons (KWin draws them, so they are not in the app's tree)
        if let (Some(f), Some(_)) = (&focus, geometry) {
            for b in crate::decor::buttons(f) {
                extra.insert(els.len(), Extra::TitleBar(f.id.clone(), b.op));
                els.push(Element { app: win_app.clone(), window: win_title.clone(), role: "Button".into(), name: b.name.into(), rect: b.rect, enabled: true, ..Default::default() });
            }
        }
        let mut hints = hints::assign(&els);
        let wins = if want_windows { kwin::windows(Duration::from_millis(300)).await.unwrap_or_default() } else { vec![] };
        // other windows become "Window" results (no on-screen label); the target window and excluded apps are left out
        let mut n_windows = 0;
        for w in wins {
            if (w.active && !popup_mode) || w.caption == UI_CAPTION || cfg.apps.excluded("", Some(&w.class), Some(w.pid)).is_some() {
                continue;
            }
            let app = w.class.rsplit('.').next().unwrap_or(&w.class).to_string();
            let mut name = if w.caption.is_empty() { app.clone() } else { format!("{app} — {}", w.caption) };
            if w.minimized {
                name.push_str(" (minimized)");
            }
            extra.insert(els.len(), Extra::Window(w.id));
            els.push(Element { app, window: w.caption, role: "Window".into(), name, enabled: true, ..Default::default() });
            hints.push(String::new());
            n_windows += 1;
        }
        let mut n_apps = 0;
        if want_apps {
            for a in crate::apps::list() {
                extra.insert(els.len(), Extra::App(a.path));
                els.push(Element { app: a.id, role: "Application".into(), name: a.name, description: a.extra, enabled: true, ..Default::default() });
                hints.push(String::new());
                n_apps += 1;
            }
        }
        let meta = json!({
            "app": win_app, "window": win_title, "count": n_elements, "windows": n_windows, "apps": n_apps, "truncated": truncated, "via": via,
            "origin": geometry, "launcher": popup_mode && n_elements == 0,
            // passive: the overlay must not take the keyboard (the popup would close); keys arrive as Key signals
            "passive": popup_mode,
            "ms": {"focus": ms(t_focus), "window": ms(t_win), "total": ms(t0.elapsed())},
        });
        *sh.snap.lock().await = Some(Snapshot { hints, els, last: vec![], geometry, extra, in_menu });
        let generation = sh.generation.fetch_add(1, std::sync::atomic::Ordering::SeqCst) + 1;
        if popup_mode {
            match crate::keygrab::grab(sh.a11y.connection(), &sh.keys, crate::keygrab::MODE_POPUP).await {
                Ok(()) => {
                    sh.grabbed.store(true, std::sync::atomic::Ordering::SeqCst);
                    sh.grab_started.notify_one();
                }
                Err(e) => {
                    crate::keygrab::release(sh.a11y.connection(), &sh.keys).await;
                    *sh.snap.lock().await = None;
                    anyhow::bail!("could not read keys over this popup: {e}");
                }
            }
        }
        let mut meta = meta;
        meta["generation"] = json!(generation);
        Ok(meta)
    }
    .await;
    let out = result.unwrap_or_else(|e| json!({"error": e.to_string()}));
    *sh.stats.lock().await = out.clone();
    if out.get("error").is_none() {
        let _ = Daemon::opened(em, &out.to_string()).await;
    } else {
        let _ = Daemon::refused(em, &out.to_string()).await; // excluded app, or nothing readable: the UI tells the user why
    }
    out
}

/// Duration in milliseconds, one decimal (for the timings UIs show).
fn ms(d: Duration) -> f64 {
    (d.as_secs_f64() * 1000.0 * 10.0).round() / 10.0
}

/// Register vimvibe's global shortcuts with KDE's kglobalaccel (toggle, quit) and return the component object path to
/// listen on. kglobalaccel keeps a key the user changed in System Settings over these defaults.
async fn register_hotkeys(conn: &zbus::Connection) -> anyhow::Result<zbus::zvariant::OwnedObjectPath> {
    let call = |member: &'static str| (Some("org.kde.kglobalaccel"), "/kglobalaccel", Some("org.kde.KGlobalAccel"), member);
    let (toggle, quit, settings) = default_keys();
    let comp = component();
    let shortcuts: [(&str, &str, Vec<i32>); 3] = [
        (ACTION, "Toggle palette", toggle.to_vec()),
        (QUIT_ACTION, "Quit vimvibe", quit.to_vec()),
        (SETTINGS_ACTION, "Open vimvibe settings", settings),
    ];
    for (action, label, keys) in shortcuts {
        let id = vec![comp.as_str(), action, "vimvibe", label];
        let (d, p, i, m) = call("doRegister");
        conn.call_method(d, p, i, m, &(id.clone(),)).await?;
        let (d, p, i, m) = call("setShortcut");
        conn.call_method(d, p, i, m, &(id, keys, 2u32)).await?; // 2 = SetPresent
    }
    let (d, p, i, m) = call("getComponent");
    let path: zbus::zvariant::OwnedObjectPath = conn.call_method(d, p, i, m, &(comp.as_str(),)).await?.body().deserialize()?;
    Ok(path)
}

/// Run the daemon until SIGTERM, Ctrl+C or the quit shortcut: turn accessibility on, start menu tracking, the key
/// listener, the KWin focus watcher and the global shortcuts, serve the D-Bus API, and clean all of it up on exit.
pub async fn run(a11y: AccessibilityConnection, timeout_ms: u64, enable_hotkey: bool) -> anyhow::Result<()> {
    use std::sync::atomic::Ordering::Relaxed;
    let menus = match crate::popups::track(&a11y).await {
        Ok(m) => Some(m),
        Err(e) => {
            eprintln!("menu tracking unavailable ({e}); open menus will close when vimvibe opens");
            None
        }
    };
    // Without session accessibility no app exposes its elements; turning it on is what the user installed vimvibe for
    // (Shortcat asks for the macOS Accessibility permission for the same reason). Apps started before this stay
    // invisible until restarted; Trigger explains that per app.
    if config::load().accessibility.enable_on_start && atspi::connection::read_session_accessibility().await.ok() == Some(false) {
        match atspi::connection::set_session_accessibility(true).await {
            Ok(()) => eprintln!("turned desktop accessibility on; apps that were already running must be restarted to be visible"),
            Err(e) => eprintln!("could not turn desktop accessibility on ({e}); run `vimvibe doctor --fix`"),
        }
    }
    let sh = Arc::new(Shared {
        a11y,
        focus: Mutex::new(None),
        snap: Mutex::new(None),
        stats: Mutex::new(Value::Null),
        pointer: Mutex::new(None),
        timeout: Duration::from_millis(timeout_ms),
        kwin_watching: Default::default(),
        hotkey: Default::default(),
        quit: Default::default(),
        grabbed: Default::default(),
        generation: Default::default(),
        grab_started: Default::default(),
        menus,
        scroll_origin: Mutex::new(None),
        scroller: Default::default(),
        keys: Default::default(),
    });
    let conn = zbus::connection::Builder::session()?
        .name(name())
        .map_err(|e| anyhow::anyhow!("cannot own {}: {e}", name()))?
        .serve_at(PATH, Daemon(sh.clone()))?
        .build()
        .await
        .map_err(|e| anyhow::anyhow!("could not start (is another vimvibe daemon already running?): {e}"))?;
    let em = SignalEmitter::new(&conn, PATH)?;

    tokio::spawn(scroll_task(sh.clone()));

    // keys typed over a popup (see keygrab.rs): Esc closes here, so the keyboard is released even without a UI
    {
        let (ktx, mut krx) = tokio::sync::mpsc::unbounded_channel();
        if let Err(e) = crate::keygrab::serve(sh.a11y.connection(), ktx, sh.keys.clone()).await {
            eprintln!("keystroke listener unavailable ({e}); popups will be closed by the overlay");
        }
        let (sh2, em2) = (sh.clone(), em.clone());
        tokio::spawn(async move {
            const IDLE: Duration = Duration::from_secs(60); // never hold the keyboard longer than this without a key
            loop {
                let k = if sh2.grabbed.load(Relaxed) {
                    match tokio::time::timeout(IDLE, krx.recv()).await {
                        Ok(Some(k)) => k,
                        Ok(None) => break,
                        Err(_) => {
                            eprintln!("no key for {}s over a popup: closing and releasing the keyboard", IDLE.as_secs());
                            close(&sh2, &em2).await;
                            continue;
                        }
                    }
                } else {
                    tokio::select! {
                        k = krx.recv() => match k { Some(k) => k, None => break },
                        _ = sh2.grab_started.notified() => continue,
                    }
                };
                if !sh2.grabbed.load(Relaxed) {
                    continue;
                }
                if sh2.keys.mode.load(Relaxed) == crate::keygrab::MODE_ARROWS {
                    arrow_key(&sh2, &em2, &k).await;
                } else if !k.pressed {
                    // popup mode forwards presses only
                } else if k.name == "Escape" {
                    close(&sh2, &em2).await;
                } else {
                    let _ = Daemon::key(&em2, &serde_json::to_string(&k).unwrap_or_default()).await;
                }
            }
        });
    }

    let mut kwin_cleanup: Option<(String, std::path::PathBuf)> = None;
    // Warm focus cache from KWin; a trigger then needs no KWin round trip.
    if kwin::on_kde() {
        match kwin::watch().await {
            Ok(session) => {
                sh.kwin_watching.store(true, Relaxed);
                kwin_cleanup = Some((session.plugin_name().to_string(), session.script_path()));
                if let Some(f) = kwin::active_window(Duration::from_millis(500)).await {
                    *sh.focus.lock().await = Some(f); // the watcher only reports changes, so seed it
                }
                let sh2 = sh.clone();
                tokio::spawn(async move {
                    let mut session = session; // capture the whole session: its D-Bus connection owns the bridge name KWin reports to
                    while let Some(f) = session.rx.recv().await {
                        if std::env::var_os("VIMVIBE_DEBUG").is_some() {
                            eprintln!("focus report: {} pid {}", f.class, f.pid);
                        }
                        if f.caption == UI_CAPTION {
                            continue; // keep the last real target; otherwise a quick re-trigger would snapshot the palette itself
                        }
                        *sh2.focus.lock().await = Some(f);
                    }
                });
            }
            Err(e) => eprintln!("kwin watcher unavailable ({e}); focus will be queried per trigger"),
        }
    }

    // Global shortcut (KDE). On other desktops bind any key to: gdbus call --session --dest org.vimvibe.Daemon
    //   --object-path /org/vimvibe/Daemon --method org.vimvibe.Daemon.Trigger
    if enable_hotkey && kwin::on_kde() {
        match register_hotkeys(&conn).await {
            Ok(path) => {
                let proxy = zbus::Proxy::new(&conn, "org.kde.kglobalaccel", path, "org.kde.kglobalaccel.Component").await?;
                let mut pressed = proxy.receive_signal("globalShortcutPressed").await?;
                sh.hotkey.store(true, Relaxed);
                let (sh2, em2) = (sh.clone(), em.clone());
                tokio::spawn(async move {
                    while let Some(msg) = pressed.next().await {
                        // (component, action, timestamp)
                        let action = msg.body().deserialize::<(String, String, i64)>().map(|(_, a, _)| a).unwrap_or_default();
                        if action == QUIT_ACTION {
                            sh2.quit.notify_one();
                        } else if action == SETTINGS_ACTION {
                            close(&sh2, &em2).await;
                            let _ = Daemon::open_settings(&em2).await;
                        } else {
                            trigger(&sh2, &em2).await;
                        }
                    }
                });
            }
            Err(e) => eprintln!("global shortcut not registered ({e}); use the Trigger D-Bus method"),
        }
    }
    eprintln!("vimvibe daemon ready on {} (kwin watcher: {}, hotkey: {})", name(), sh.kwin_watching.load(Relaxed), sh.hotkey.load(Relaxed));

    let mut term = tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())?;
    tokio::select! {
        _ = tokio::signal::ctrl_c() => {}
        _ = term.recv() => {}
        _ = sh.quit.notified() => eprintln!("quit requested"),
    }
    close(&sh, &em).await; // releases the keystroke listener if an overlay is open over a popup
    let _ = Daemon::quitting(&em).await; // the overlay exits on this
    if sh.hotkey.load(Relaxed) {
        for action in [ACTION, QUIT_ACTION, SETTINGS_ACTION] {
            let _ = conn.call_method(Some("org.kde.kglobalaccel"), "/kglobalaccel", Some("org.kde.KGlobalAccel"), "unregister", &(component().as_str(), action)).await;
        }
    }
    if let Some((plugin, file)) = kwin_cleanup {
        let _ = conn.call_method(Some("org.kde.KWin"), "/Scripting", Some("org.kde.kwin.Scripting"), "unloadScript", &(plugin.as_str(),)).await;
        let _ = std::fs::remove_file(file);
    }
    eprintln!("vimvibe daemon stopped");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::keygrab::{KC_H, KC_I, KC_J, KC_K, KC_L};

    #[test]
    fn arrow_layouts() {
        assert_eq!(arrow_for(KC_H, "hjkl"), Some((-1, 0)));
        assert_eq!(arrow_for(KC_J, "hjkl"), Some((0, 1)));
        assert_eq!(arrow_for(KC_K, "hjkl"), Some((0, -1)));
        assert_eq!(arrow_for(KC_L, "hjkl"), Some((1, 0)));
        assert_eq!(arrow_for(KC_I, "hjkl"), None);
        assert_eq!(arrow_for(KC_I, "ijkl"), Some((0, -1)));
        assert_eq!(arrow_for(KC_J, "ijkl"), Some((-1, 0)));
        assert_eq!(arrow_for(KC_K, "ijkl"), Some((0, 1)));
        assert_eq!(arrow_for(KC_H, "ijkl"), None);
        assert_eq!(arrow_keysym(0, 1), Some(XK_DOWN));
        assert_eq!(arrow_keysym(-1, 0), Some(XK_LEFT));
    }
}
