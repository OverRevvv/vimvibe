//! KDE Plasma 6 / KWin bridge: which window is focused, its PID and its screen geometry.
//!
//! AT-SPI frames do not carry reliable screen positions on Wayland and several apps flag a frame `Active`
//! even when they are not focused (08 R9, 10 §1). KWin knows the truth, but only exposes it through scripting,
//! so a tiny KWin script reports back over D-Bus to a service we own (`org.vimvibe.Bridge`). `print()` output
//! of KWin scripts is not reachable (prior art parses journalctl; this avoids that).

use serde::Deserialize;
use std::path::PathBuf;
use std::time::Duration;
use tokio::sync::mpsc;
use zbus::Connection;

/// Each session owns its own name so a one-shot query never steals reports meant for a running watcher.
const BRIDGE_NAME: &str = "@BRIDGE@";

/// The window KWin considers active.
#[derive(Debug, Clone, Deserialize, serde::Serialize, PartialEq)]
pub struct FocusInfo {
    pub pid: u32,
    #[serde(rename = "class")]
    pub class: String,
    pub caption: String,
    /// `clientGeometry` (content area without the server-side decoration): the origin AT-SPI window extents are relative to.
    pub x: i32,
    pub y: i32,
    pub w: i32,
    pub h: i32,
    /// KWin internal id (for window operations), frame geometry (client area + server-side decoration), and what the
    /// window allows: X closeable, A maximizable, I minimizable, D has a server-side decoration.
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub fx: i32,
    #[serde(default)]
    pub fy: i32,
    #[serde(default)]
    pub fw: i32,
    #[serde(default)]
    pub fh: i32,
    #[serde(default)]
    pub ops: String,
}

struct Bridge {
    tx: mpsc::UnboundedSender<FocusInfo>,
    wtx: mpsc::UnboundedSender<String>,
}

#[zbus::interface(name = "org.vimvibe.Bridge")]
impl Bridge {
    /// Called by the focus scripts (`callDBus`) with the active window as JSON.
    fn report(&self, json: String) {
        if let Ok(f) = serde_json::from_str::<FocusInfo>(&json) {
            let _ = self.tx.send(f);
        }
    }

    /// Called by KWin scripts (via the `Data` bridge method) for answers that are not a focus report: the window
    /// list, surfaces, the cursor position. Generic one-shot payload channel (window list, cursor position).
    fn data(&self, json: String) {
        let _ = self.wtx.send(json);
    }
}

const ONE_SHOT: &str = r#"
const w = workspace.activeWindow;
if (w) {
  const g = w.clientGeometry;
  callDBus("@BRIDGE@", "/", "org.vimvibe.Bridge", "Report",
    JSON.stringify({pid: w.pid, class: w.resourceClass, caption: w.caption, x: Math.round(g.x), y: Math.round(g.y), w: Math.round(g.width), h: Math.round(g.height),
      id: w.internalId.toString(), fx: Math.round(w.frameGeometry.x), fy: Math.round(w.frameGeometry.y), fw: Math.round(w.frameGeometry.width), fh: Math.round(w.frameGeometry.height),
      ops: (w.closeable ? "X" : "") + (w.maximizable ? "A" : "") + (w.minimizable ? "I" : "") + (w.noBorder ? "" : "D")}));
}
"#;

/// Persistent variant: reports on every activation and on geometry changes of the active window.
const WATCH: &str = r#"
function report(w) {
  if (!w || w !== workspace.activeWindow) return;
  const g = w.clientGeometry;
  callDBus("@BRIDGE@", "/", "org.vimvibe.Bridge", "Report",
    JSON.stringify({pid: w.pid, class: w.resourceClass, caption: w.caption, x: Math.round(g.x), y: Math.round(g.y), w: Math.round(g.width), h: Math.round(g.height),
      id: w.internalId.toString(), fx: Math.round(w.frameGeometry.x), fy: Math.round(w.frameGeometry.y), fw: Math.round(w.frameGeometry.width), fh: Math.round(w.frameGeometry.height),
      ops: (w.closeable ? "X" : "") + (w.maximizable ? "A" : "") + (w.minimizable ? "I" : "") + (w.noBorder ? "" : "D")}));
}
function hook(w) {
  if (!w) return;
  if (!w.vimvibeHooked) {
    w.vimvibeHooked = true;
    w.clientGeometryChanged.connect(function () { report(w); });
    w.captionChanged.connect(function () { report(w); });
  }
  report(w);
}
workspace.windowActivated.connect(hook);
hook(workspace.activeWindow);
"#;

/// Every normal window KWin manages (no captions: they can contain private page titles).
const LIST: &str = r#"
const out = [];
for (const w of workspace.windowList()) {
  if (!w.normalWindow || w.skipTaskbar) continue; // system helpers (video bridge, panels) are not apps to control
  const g = w.clientGeometry;
  out.push({pid: w.pid, class: w.resourceClass, caption_is_ui: w.caption == "vimvibe-palette",
            x: Math.round(g.x), y: Math.round(g.y), w: Math.round(g.width), h: Math.round(g.height), active: w === workspace.activeWindow});
}
callDBus("@BRIDGE@", "/", "org.vimvibe.Bridge", "Data", JSON.stringify(out));
"#;

/// The real pointer position in logical screen pixels (Wayland gives clients no way to read it otherwise).
const CURSOR: &str = r#"
callDBus("@BRIDGE@", "/", "org.vimvibe.Bridge", "Data", JSON.stringify({x: workspace.cursorPos.x, y: workspace.cursorPos.y})); // floats are fine here: parsed as f64
"#;

#[derive(Debug, Clone, Deserialize, serde::Serialize)]
pub struct WindowRef {
    pub pid: u32,
    pub class: String,
    #[serde(default)]
    pub caption_is_ui: bool,
    /// clientGeometry: the origin AT-SPI window-relative extents are relative to.
    #[serde(default)]
    pub x: i32,
    #[serde(default)]
    pub y: i32,
    #[serde(default)]
    pub w: i32,
    #[serde(default)]
    pub h: i32,
    #[serde(default)]
    pub active: bool,
}

/// Whether we run on KDE Plasma (KWin scripting, kglobalaccel available).
pub fn on_kde() -> bool {
    std::env::var("XDG_CURRENT_DESKTOP").is_ok_and(|d| d.to_uppercase().contains("KDE"))
}

/// A loaded KWin script plus the service that receives its reports. Dropping it without `stop` leaves the script
/// loaded in KWin until the next `stop`/session end, so callers should `stop().await`.
pub struct Session {
    conn: Connection,
    plugin: String,
    script_file: PathBuf,
    pub rx: mpsc::UnboundedReceiver<FocusInfo>,
    wrx: mpsc::UnboundedReceiver<String>,
}

impl Session {
    /// Own a unique bridge name, write the script with that name filled in, load and run it in KWin.
    async fn start(source: &str) -> anyhow::Result<Self> {
        Self::start_named(source, None).await
    }

    /// Like `start`, with a fixed KWin plugin name instead of a per-process one: a script that outlives the daemon
    /// (a crash) can then be unloaded by the next daemon (see `unload_leftover_keys`).
    async fn start_named(source: &str, fixed_plugin: Option<&str>) -> anyhow::Result<Self> {
        let (tx, rx) = mpsc::unbounded_channel();
        let (wtx, wrx) = mpsc::unbounded_channel();
        // unique per session: a long-lived watcher and one-shot queries (cursor, window list) coexist in the daemon
        static SEQ: std::sync::atomic::AtomicU32 = std::sync::atomic::AtomicU32::new(0);
        let bridge = format!("org.vimvibe.Bridge.p{}s{}", std::process::id(), SEQ.fetch_add(1, std::sync::atomic::Ordering::Relaxed));
        let source = source.replace(BRIDGE_NAME, &bridge);
        let conn = zbus::connection::Builder::session()?.name(bridge.as_str())?.serve_at("/", Bridge { tx, wtx })?.build().await?;
        let dir = std::env::var_os("XDG_RUNTIME_DIR").map(PathBuf::from).unwrap_or_else(std::env::temp_dir);
        let plugin = fixed_plugin.map_or_else(|| bridge.replace("org.vimvibe.Bridge.p", "vimvibe-"), str::to_string);
        let script_file = dir.join(format!("{plugin}.js"));
        std::fs::write(&script_file, &source)?;
        let id: i32 = conn
            .call_method(Some("org.kde.KWin"), "/Scripting", Some("org.kde.kwin.Scripting"), "loadScript", &(script_file.to_string_lossy().as_ref(), plugin.as_str()))
            .await?
            .body()
            .deserialize()?;
        let session = Session { conn, plugin, script_file, rx, wrx };
        let path = format!("/Scripting/Script{id}");
        session.conn.call_method(Some("org.kde.KWin"), path.as_str(), Some("org.kde.kwin.Script"), "run", &()).await?;
        Ok(session)
    }

    /// The next string a script sent through the `Data` bridge method (None when the session is gone).
    pub async fn next_data(&mut self) -> Option<String> {
        self.wrx.recv().await
    }

    /// KWin plugin name of the loaded script (for unloading it).
    pub fn plugin_name(&self) -> &str {
        &self.plugin
    }

    /// File the script was written to (removed on shutdown).
    pub fn script_path(&self) -> PathBuf {
        self.script_file.clone()
    }

    /// Unload the script from KWin and delete its file.
    pub async fn stop(self) {
        let _ = self.conn.call_method(Some("org.kde.KWin"), "/Scripting", Some("org.kde.kwin.Scripting"), "unloadScript", &(self.plugin.as_str(),)).await;
        let _ = std::fs::remove_file(&self.script_file);
    }
}

/// One-shot: ask KWin which window is active. None when KWin scripting is unavailable, nothing is active, or it times out.
pub async fn active_window(timeout: Duration) -> Option<FocusInfo> {
    let mut s = Session::start(ONE_SHOT).await.ok()?;
    let got = tokio::time::timeout(timeout, s.rx.recv()).await.ok().flatten();
    s.stop().await;
    got
}

/// KWin plugin name of the key-taking script (fixed, so a leftover one can be found and unloaded).
const KEYS_PLUGIN: &str = "vimvibe-keymode";

/// Take these keys system-wide (KWin global shortcuts, which win over every app on Wayland) until the returned session
/// is stopped. `keys` are (id, key sequence) pairs, e.g. ("j", "J"), ("shift-j", "Shift+J"), ("esc", "Esc"); each press
/// is delivered as its id through `Session::next_data`. The key is consumed: the focused app does not see it.
pub async fn grab_keys(keys: &[(&str, &str)]) -> anyhow::Result<Session> {
    let list = serde_json::to_string(keys)?;
    let source = format!(
        r#"
const keys = {list};
// one closure per key, so each shortcut reports its own id
function reg(id, seq) {{
  registerShortcut("vimvibe-key-" + id, "vimvibe key mode: " + id, seq, function () {{
    callDBus("@BRIDGE@", "/", "org.vimvibe.Bridge", "Data", id);
  }});
}}
for (const k of keys) reg(k[0], k[1]);
"#
    );
    unload_leftover_keys().await;
    Session::start_named(&source, Some(KEYS_PLUGIN)).await
}

/// Unload a key-taking script a crashed daemon left in KWin (it would keep eating those keys). Called before every
/// grab and at daemon start.
pub async fn unload_leftover_keys() {
    if let Ok(conn) = Connection::session().await {
        let _ = conn.call_method(Some("org.kde.KWin"), "/Scripting", Some("org.kde.kwin.Scripting"), "unloadScript", &(KEYS_PLUGIN,)).await;
    }
}

/// Persistent listener for the daemon: the returned session's `rx` yields a `FocusInfo` on every focus or geometry change.
pub async fn watch() -> anyhow::Result<Session> {
    Session::start(WATCH).await
}

/// All normal windows with their PID and class; None when KWin scripting is unavailable or it times out.
pub async fn list_windows(timeout: Duration) -> Option<Vec<WindowRef>> {
    let mut s = match Session::start(LIST).await {
        Ok(s) => s,
        Err(e) => {
            if std::env::var_os("VIMVIBE_DEBUG").is_some() {
                eprintln!("kwin list_windows: session start failed: {e}");
            }
            return None;
        }
    };
    let got = tokio::time::timeout(timeout, s.wrx.recv()).await.ok().flatten();
    s.stop().await;
    match serde_json::from_str(&got?) {
        Ok(v) => Some(v),
        Err(e) => {
            if std::env::var_os("VIMVIBE_DEBUG").is_some() {
                eprintln!("kwin list_windows: bad payload: {e}");
            }
            None
        }
    }
}

/// Current pointer position (logical px) from KWin, or None when scripting is unavailable.
pub async fn cursor_pos(timeout: Duration) -> Option<(f64, f64)> {
    let mut s = Session::start(CURSOR).await.ok()?;
    let got = tokio::time::timeout(timeout, s.wrx.recv()).await.ok().flatten();
    s.stop().await;
    let v: serde_json::Value = serde_json::from_str(&got?).ok()?;
    Some((v["x"].as_f64()?, v["y"].as_f64()?))
}

/// Every normal window with its KWin id and caption, for window switching. Captions can be private (page titles),
/// so they are only kept in memory for the open palette and never logged.
const WINDOWS: &str = r#"
const out = [];
for (const w of workspace.windowList()) {
  if (!w.normalWindow || w.skipTaskbar) continue;
  out.push({id: w.internalId.toString(), pid: w.pid, class: w.resourceClass, caption: w.caption,
            minimized: w.minimized, active: w === workspace.activeWindow});
}
callDBus("@BRIDGE@", "/", "org.vimvibe.Bridge", "Data", JSON.stringify(out));
"#;

const ACTIVATE: &str = r#"
let found = false;
for (const w of workspace.windowList()) {
  if (w.internalId.toString() == "@ID@") {
    if (w.minimized) w.minimized = false;
    workspace.activeWindow = w;
    found = true;
  }
}
callDBus("@BRIDGE@", "/", "org.vimvibe.Bridge", "Data", JSON.stringify({found: found}));
"#;

#[derive(Debug, Clone, Deserialize)]
pub struct WindowEntry {
    pub id: String,
    pub pid: u32,
    pub class: String,
    pub caption: String,
    #[serde(default)]
    pub minimized: bool,
    #[serde(default)]
    pub active: bool,
}

/// Run a script once and return the first payload it sends to `Data` (None on timeout).
async fn one_shot_data(source: &str, timeout: Duration) -> Option<String> {
    let mut s = Session::start(source).await.ok()?;
    let got = tokio::time::timeout(timeout, s.wrx.recv()).await.ok().flatten();
    s.stop().await;
    got
}

/// All normal windows (with captions) for window switching; None when KWin scripting is unavailable.
pub async fn windows(timeout: Duration) -> Option<Vec<WindowEntry>> {
    serde_json::from_str(&one_shot_data(WINDOWS, timeout).await?).ok()
}

/// Raise and focus a window by its KWin internal id (un-minimising it).
pub async fn activate_window(id: &str, timeout: Duration) -> anyhow::Result<()> {
    // ids are UUIDs like {0b1c...}; refuse anything else so nothing can be injected into the script
    anyhow::ensure!(!id.is_empty() && id.chars().all(|c| c.is_ascii_hexdigit() || "{}-".contains(c)), "bad window id");
    let got = one_shot_data(&ACTIVATE.replace("@ID@", id), timeout).await.ok_or_else(|| anyhow::anyhow!("KWin did not answer"))?;
    let v: serde_json::Value = serde_json::from_str(&got)?;
    anyhow::ensure!(v["found"].as_bool() == Some(true), "that window is gone");
    Ok(())
}

const WINDOW_OP: &str = r#"
let found = false;
for (const w of workspace.windowList()) {
  if (w.internalId.toString() != "@ID@") continue;
  found = true;
  switch ("@OP@") {
    case "close": w.closeWindow(); break;
    case "minimize": w.minimized = true; break;
    case "maximize": workspace.activeWindow = w; workspace.slotWindowMaximize(); break;
    case "alldesktops": w.onAllDesktops = !w.onAllDesktops; break;
    case "above": w.keepAbove = !w.keepAbove; break;
    case "below": w.keepBelow = !w.keepBelow; break;
    case "menu": workspace.activeWindow = w; workspace.slotWindowOperations(); break;
  }
}
callDBus("@BRIDGE@", "/", "org.vimvibe.Bridge", "Data", JSON.stringify({found: found}));
"#;

/// Run a title-bar operation on a window: close, minimize, maximize (toggle), alldesktops, above, below, menu.
pub async fn window_op(id: &str, op: &str, timeout: Duration) -> anyhow::Result<()> {
    anyhow::ensure!(!id.is_empty() && id.chars().all(|c| c.is_ascii_hexdigit() || "{}-".contains(c)), "bad window id");
    anyhow::ensure!(["close", "minimize", "maximize", "alldesktops", "above", "below", "menu"].contains(&op), "unknown window operation");
    let got = one_shot_data(&WINDOW_OP.replace("@ID@", id).replace("@OP@", op), timeout).await.ok_or_else(|| anyhow::anyhow!("KWin did not answer"))?;
    let v: serde_json::Value = serde_json::from_str(&got)?;
    anyhow::ensure!(v["found"].as_bool() == Some(true), "that window is gone");
    Ok(())
}

/// Non-normal surfaces that hold clickable things: panels/docks (the taskbar) and open popups (menus, dropdowns,
/// Plasma popups). No captions.
const SURFACES: &str = r#"
const out = [];
for (const w of workspace.windowList()) {
  let kind = "";
  if (w.dock) kind = "dock";
  else if (w.popupWindow || w.dropdownMenu || w.popupMenu || w.comboBox) kind = "popup";
  else if (w.normalWindow || w.dialog) kind = "window";
  else continue;
  const g = w.frameGeometry;
  out.push({kind: kind, pid: w.pid, class: w.resourceClass, x: Math.round(g.x), y: Math.round(g.y), w: Math.round(g.width), h: Math.round(g.height),
            active: w === workspace.activeWindow, hidden: !!w.hidden || !!w.minimized, layer: w.layer, stack: w.stackingOrder});
}
callDBus("@BRIDGE@", "/", "org.vimvibe.Bridge", "Data", JSON.stringify(out));
"#;

#[derive(Debug, Clone, Deserialize, serde::Serialize)]
pub struct Surface {
    /// "dock" (panel), "popup" (menu, dropdown, Plasma popup) or "window"
    pub kind: String,
    pub pid: u32,
    pub class: String,
    pub x: i32,
    pub y: i32,
    pub w: i32,
    pub h: i32,
    #[serde(default)]
    pub active: bool,
    /// Not on screen right now (an auto-hidden panel, a minimised window).
    #[serde(default)]
    pub hidden: bool,
    /// KWin stacking layer and position within the stack (higher = closer to the user).
    #[serde(default)]
    pub layer: i32,
    #[serde(default)]
    pub stack: i32,
}

impl Surface {
    /// Whether two surfaces overlap on screen.
    fn intersects(&self, o: &Surface) -> bool {
        self.x < o.x + o.w && o.x < self.x + self.w && self.y < o.y + o.h && o.y < self.y + self.h
    }

    /// A panel the user can actually see: not auto-hidden, and not covered by a window stacked above it (panels set
    /// to "windows can cover" sit below normal windows).
    pub fn visible_among(&self, all: &[Surface]) -> bool {
        !self.hidden
            && !all.iter().any(|o| o.kind == "window" && !o.hidden && o.intersects(self) && (o.layer, o.stack) > (self.layer, self.stack))
    }
}

/// Panels, popups and windows as KWin sees them right now; None when KWin scripting is unavailable.
pub async fn surfaces(timeout: Duration) -> Option<Vec<Surface>> {
    serde_json::from_str(&one_shot_data(SURFACES, timeout).await?).ok()
}
