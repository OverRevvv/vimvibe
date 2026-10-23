use crate::model::{Element, extents};
use atspi::connection::AccessibilityConnection;
use atspi::proxy::accessible::AccessibleProxy;
use atspi::proxy::{action::ActionProxy, component::ComponentProxy};
use atspi::{ObjectRefOwned, Role, State};
use futures_util::future::join_all;
use std::time::{Duration, Instant};

pub struct Window {
    pub app: String,
    pub title: String,
    pub root: ObjectRefOwned,
    /// KWin clientGeometry (x, y, w, h) when known: screen position = origin + window-relative extents.
    pub geometry: Option<(i32, i32, i32, i32)>,
}

pub struct Opts {
    pub include_hidden: bool,
    pub timeout: Duration,
    pub max_nodes: usize,
    /// Also fetch each element's action names (one extra call per element; not needed to activate).
    pub with_actions: bool,
}

const ACTIONABLE: &[&str] = &[
    "Button", "ToggleButton", "CheckBox", "RadioButton", "MenuItem", "CheckMenuItem", "RadioMenuItem",
    "Link", "PageTab", "ListItem", "TreeItem", "ComboBox", "Entry", "PasswordText", "SpinButton", "Slider",
    "TableCell", "PushButtonMenu", "Switch",
];

const INPUT_ROLES: &[&str] = &["Entry", "PasswordText", "ComboBox", "SpinButton", "Slider"];

/// An uncached Accessible proxy for an object (cached properties go stale as UIs change).
pub async fn proxy(conn: &AccessibilityConnection, r: &ObjectRefOwned) -> anyhow::Result<AccessibleProxy<'static>> {
    let bus = r.name().ok_or_else(|| anyhow::anyhow!("null bus name"))?.clone();
    let p = AccessibleProxy::builder(conn.connection())
        .destination(bus)?
        .path(r.path().clone())?
        .cache_properties(zbus::proxy::CacheProperties::No)
        .build()
        .await?;
    Ok(p)
}

/// Every app on the accessibility bus with its number of top-level windows (`apps` command).
pub async fn list_apps(conn: &AccessibilityConnection) -> anyhow::Result<Vec<(String, usize)>> {
    let root = conn.root_accessible_on_registry().await?;
    let mut out = vec![];
    for a in root.get_children().await? {
        if let Ok(p) = proxy(conn, &a).await {
            out.push((p.name().await.unwrap_or_default(), p.child_count().await.unwrap_or(0).max(0) as usize));
        }
    }
    Ok(out)
}

/// Process id behind an accessible object (asked from the bus daemon for the object's connection).
pub(crate) async fn app_pid(conn: &AccessibilityConnection, app: &ObjectRefOwned) -> Option<u32> {
    let name = app.name()?.clone();
    let dbus = zbus::fdo::DBusProxy::new(conn.connection()).await.ok()?;
    dbus.get_connection_unix_process_id(zbus::names::BusName::Unique(name.clone())).await.ok()
}

/// The window to act on.
/// With KWin's `focus` the AT-SPI app is matched by PID, which is authoritative (several apps flag a frame `Active`
/// when they are not focused: the on-screen keyboard, tray apps); within that app the Active frame, then the one whose
/// title equals KWin's caption, wins. Without it (or without a PID match) the old heuristic applies: Active frames
/// ranked showing + has children + non-empty title. `app_filter` restricts by app name and falls back to any frame.
pub async fn target_window(conn: &AccessibilityConnection, app_filter: Option<&str>, focus: Option<&crate::kwin::FocusInfo>) -> anyhow::Result<Option<Window>> {
    let root = conn.root_accessible_on_registry().await?;
    let filter = app_filter.map(|s| s.to_lowercase());
    let geometry = focus.map(|f| (f.x, f.y, f.w, f.h));
    let mut best: Option<(i32, Window)> = None;
    let mut fallback = None;
    let mut any_pid_match = false;
    // visit every app on the accessibility bus and score each of its windows; the best score is the target
    for a in root.get_children().await? {
        let Ok(app) = proxy(conn, &a).await else { continue };
        let app_name = app.name().await.unwrap_or_default();
        if let Some(f) = &filter {
            if !app_name.to_lowercase().contains(f) {
                continue;
            }
        }
        let pid_match = match focus {
            Some(f) if filter.is_none() => app_pid(conn, &a).await == Some(f.pid),
            _ => false,
        };
        any_pid_match |= pid_match;
        for w in app.get_children().await.unwrap_or_default() {
            let Ok(wp) = proxy(conn, &w).await else { continue };
            let Ok(state) = wp.get_state().await else { continue };
            let title = wp.name().await.unwrap_or_default();
            let win = Window { app: app_name.clone(), title: title.clone(), root: w.clone(), geometry: if pid_match { geometry } else { None } };
            let active = state.contains(State::Active);
            // A window whose title is exactly KWin's caption is a candidate even when its app's PID did not match and it is
            // not flagged Active: sandboxed apps (Flatpak) report the proxy's PID, and Qt WebEngine apps never set Active.
            let title_match = filter.is_none() && focus.is_some_and(|f| !f.caption.is_empty() && f.caption == title);
            if active || pid_match || title_match {
                // score: the PID KWin reported dominates (+16, +4 if the title matches the caption), then Active (+8),
                // visible (+2), has content (+4) and a title (+1)
                let mut score = 1;
                if pid_match {
                    score += 16;
                    if focus.is_some_and(|f| f.caption == title) {
                        score += 4;
                    }
                }
                if title_match && !pid_match {
                    score += 6;
                }
                if active {
                    score += 8;
                }
                if state.contains(State::Showing) {
                    score += 2;
                }
                if wp.child_count().await.unwrap_or(0) > 0 {
                    score += 4;
                }
                if !title.trim().is_empty() {
                    score += 1; // untitled frames are usually system surfaces (on-screen keyboard)
                }
                if std::env::var_os("VIMVIBE_DEBUG").is_some() {
                    eprintln!("candidate: {} / '{}' score {score} (pid match {pid_match}, active {active})", win.app, win.title);
                }
                if best.as_ref().is_none_or(|(s, _)| score > *s) {
                    best = Some((score, win));
                }
            } else if filter.is_some() && fallback.is_none() {
                fallback = Some(win);
            }
        }
    }
    // The compositor told us which window is focused, but no accessible app has its PID: that app is not on the
    // accessibility bus (started before accessibility was enabled, or no a11y support). Picking some other "active"
    // window (an on-screen keyboard, a tray app) would show the wrong elements, so only accept a candidate whose title
    // is exactly the focused window's caption (sandboxed apps can report a different PID).
    if let (Some(f), None, false) = (focus, &filter, any_pid_match) {
        // Such a window (Flatpak/Snap apps: the accessibility bus reports the sandbox proxy's PID, not the app's) was
        // matched by its title, so it is the window KWin reported and its geometry is the one that places the labels.
        // Without this the labels are drawn relative to the screen corner instead of the window.
        return Ok(best
            .map(|(_, mut w)| {
                w.geometry = geometry;
                w
            })
            .filter(|w| !f.caption.is_empty() && w.title == f.caption));
    }
    Ok(best.map(|(_, w)| w).or(fallback))
}

/// Fill `win.geometry` from KWin's window list when the window was chosen by app name (no focus info). Matches by PID and
/// prefers the active window; with several windows of one app and none active the first one wins (title matching would
/// need captions, which we avoid reading).
pub async fn fill_geometry(conn: &AccessibilityConnection, win: &mut Window) {
    if win.geometry.is_some() || !crate::kwin::on_kde() {
        return;
    }
    let Some(pid) = app_pid(conn, &win.root).await else { return };
    if std::env::var_os("VIMVIBE_DEBUG").is_some() {
        eprintln!("fill_geometry: app pid {pid}");
    }
    let Some(list) = crate::kwin::list_windows(Duration::from_millis(800)).await else { return };
    if std::env::var_os("VIMVIBE_DEBUG").is_some() {
        eprintln!("fill_geometry: kwin windows (pid,class): {:?}", list.iter().map(|w| (w.pid, w.class.as_str())).collect::<Vec<_>>());
    }
    let mut mine: Vec<_> = list.iter().filter(|w| w.pid == pid).collect();
    mine.sort_by_key(|w| !w.active);
    if let Some(w) = mine.first() {
        win.geometry = Some((w.x, w.y, w.w, w.h));
    }
}

struct Visit {
    element: Option<Element>,
    children: Vec<ObjectRefOwned>,
}

/// One node of the tree walk: whether to descend, and the element it yields if it is actionable and visible.
async fn visit(conn: &AccessibilityConnection, r: &ObjectRefOwned, win: &Window, is_root: bool, o: &Opts) -> Visit {
    let none = Visit { element: None, children: vec![] };
    let Ok(p) = proxy(conn, r).await else { return none };
    let Ok(state) = p.get_state().await else { return none };
    if !is_root && !o.include_hidden && !state.contains(State::Showing) {
        return none; // prune hidden subtrees (hidden panels, closed menus)
    }
    let children = match p.get_children().await {
        Ok(c) => c,
        Err(e) => {
            if std::env::var_os("VIMVIBE_DEBUG").is_some() {
                eprintln!("get_children failed on {}: {e}", r.path_as_str());
            }
            vec![]
        }
    };
    let role_s = role_of(conn, r, &p, &state).await;
    if !ACTIONABLE.contains(&role_s.as_str()) {
        return Visit { element: None, children };
    }
    let element = build_element(conn, r, win, o, &p, &state, role_s, &children).await;
    Visit { element, children }
}

/// Typed `get_role` fails for roles newer than the `atspi` crate knows (it stops at 129). GTK4's `Switch` is 130,
/// so fall back to the raw number instead of silently dropping the element.
async fn role_of(conn: &AccessibilityConnection, r: &ObjectRefOwned, p: &AccessibleProxy<'_>, state: &atspi::StateSet) -> String {
    if let Ok(role) = p.get_role().await {
        return role_name(role, state);
    }
    let raw = async {
        let bus = r.name()?.clone();
        let m = conn.connection().call_method(Some(bus), r.path().clone(), Some("org.a11y.atspi.Accessible"), "GetRole", &()).await.ok()?;
        m.body().deserialize::<u32>().ok()
    };
    match raw.await {
        Some(130) => "Switch".into(),
        _ => "Invalid".into(),
    }
}

/// Qt reports line edits as editable Text; everything else uses the AT-SPI role name.
fn role_name(role: Role, state: &atspi::StateSet) -> String {
    let s = format!("{role:?}");
    if s == "Text" && state.contains(State::Editable) { "Entry".into() } else { s }
}

/// Name and extents (and optionally actions) for one actionable node; shared by the tree walk and the Collection path.
async fn build_element(
    conn: &AccessibilityConnection,
    r: &ObjectRefOwned,
    win: &Window,
    o: &Opts,
    p: &AccessibleProxy<'_>,
    state: &atspi::StateSet,
    role_s: String,
    children: &[ObjectRefOwned],
) -> Option<Element> {
    let mut name = p.name().await.unwrap_or_default();
    let description = p.description().await.unwrap_or_default();
    if name.trim().is_empty() {
        name = description.clone();
    }
    if name.trim().is_empty() {
        name = content_name(conn, children, 2).await; // GTK4 list rows, menu items: the text lives in a child label
    }
    if name.trim().is_empty() {
        if INPUT_ROLES.contains(&role_s.as_str()) {
            name = format!("(unlabeled {})", role_s.to_lowercase()); // still reachable by role word, like Shortcat's "not labelled"
        } else {
            return None;
        }
    }
    let rect = element_rect(conn, r).await.unwrap_or_default();
    let actions = if o.with_actions { element_actions(conn, r).await } else { vec![] };
    if !o.include_hidden && (rect.2 <= 0 || rect.3 <= 0) {
        return None;
    }
    Some(Element {
        app: win.app.clone(),
        window: win.title.clone(),
        role: role_s,
        name: name.trim().to_string(),
        description,
        actions,
        rect,
        enabled: state.contains(State::Enabled) || state.contains(State::Sensitive),
        object: Some(r.clone()),
    })
}

/// ARIA-style "name from content": the first non-empty accessible names found in the subtree (bounded).
fn content_name<'a>(conn: &'a AccessibilityConnection, children: &'a [ObjectRefOwned], depth: u32) -> std::pin::Pin<Box<dyn std::future::Future<Output = String> + Send + 'a>> {
    Box::pin(async move {
        let mut parts: Vec<String> = vec![];
        for c in children.iter().take(8) {
            let Ok(p) = proxy(conn, c).await else { continue };
            let n = p.name().await.unwrap_or_default();
            if !n.trim().is_empty() {
                parts.push(n.trim().to_string());
            } else if depth > 1 {
                if let Ok(grand) = p.get_children().await {
                    let n = content_name(conn, &grand, depth - 1).await;
                    if !n.is_empty() {
                        parts.push(n);
                    }
                }
            }
            if parts.join(" ").chars().count() >= 80 {
                break;
            }
        }
        parts.join(" ")
    })
}

/// Window-relative extents of an object.
async fn element_rect(conn: &AccessibilityConnection, r: &ObjectRefOwned) -> Option<(i32, i32, i32, i32)> {
    let bus = r.name()?.clone();
    let c = ComponentProxy::builder(conn.connection()).destination(bus).ok()?.path(r.path().clone()).ok()?.build().await.ok()?;
    extents(&c).await
}

/// Action names of an object (only fetched with `--with-actions`).
async fn element_actions(conn: &AccessibilityConnection, r: &ObjectRefOwned) -> Vec<String> {
    let go = async {
        let bus = r.name()?.clone();
        let a = ActionProxy::builder(conn.connection()).destination(bus).ok()?.path(r.path().clone()).ok()?.build().await.ok()?;
        a.get_actions().await.ok().map(|v| v.into_iter().map(|x| x.name).collect::<Vec<_>>())
    };
    go.await.unwrap_or_default()
}

const ACTIONABLE_ROLES: &[Role] = &[
    Role::Button, Role::ToggleButton, Role::CheckBox, Role::RadioButton, Role::MenuItem, Role::CheckMenuItem,
    Role::RadioMenuItem, Role::Link, Role::PageTab, Role::ListItem, Role::TreeItem, Role::ComboBox, Role::Entry,
    Role::PasswordText, Role::SpinButton, Role::Slider, Role::TableCell, Role::PushButtonMenu,
];

/// AT-SPI bitmask encoding used by Collection rules: 4 x i32 words, bit (n % 32) of word (n / 32).
fn bitmask(values: impl IntoIterator<Item = u32>) -> Vec<i32> {
    let mut w = vec![0i32; 4];
    for v in values.into_iter().filter(|v| *v < 128) {
        // roles >= 128 (e.g. PushButtonMenu) cannot be expressed on the wire; the tree walk still finds them
        w[(v / 32) as usize] |= 1i32.wrapping_shl(v % 32);
    }
    w
}

/// One raw Collection.GetMatches call. The `atspi` crate's ObjectMatchRule sends roles as a plain list, but the wire
/// protocol (and libatspi, Qt, GTK) use bitmasks for states and roles, so the request is built by hand.
async fn get_matches(conn: &AccessibilityConnection, win: &Window, states: &[State], roles: &[Role]) -> Option<Vec<ObjectRefOwned>> {
    use std::collections::HashMap;
    let bus = win.root.name()?.clone();
    let rule = (
        bitmask(states.iter().map(|s| (*s as u64).trailing_zeros())),
        1i32, // states: match ALL
        HashMap::<String, String>::new(),
        1i32,
        bitmask(roles.iter().map(|r| *r as u32)),
        2i32, // roles: match ANY
        Vec::<String>::new(),
        1i32,
        false,
    );
    let msg = conn
        .connection()
        .call_method(Some(bus), win.root.path().clone(), Some("org.a11y.atspi.Collection"), "GetMatches", &(rule, 1u32, 0i32, true))
        .await
        .ok()?;
    msg.body().deserialize::<Vec<ObjectRefOwned>>().ok()
}

/// Fast path: ask the app to filter its own tree (AT-SPI Collection), one round trip instead of one per node.
/// Returns None when the window has no Collection interface or the call fails, so the caller can fall back to the walk.
pub async fn enumerate_collection(conn: &AccessibilityConnection, win: &Window, o: &Opts) -> Option<Vec<Element>> {
    let showing: &[State] = if o.include_hidden { &[] } else { &[State::Showing] };
    let editable = [showing, &[State::Editable]].concat();
    let (a, b) = futures_util::future::join(
        get_matches(conn, win, showing, ACTIONABLE_ROLES),
        get_matches(conn, win, &editable, &[Role::Text]), // Qt line edits are editable Text
    )
    .await;
    let mut refs = a?;
    refs.extend(b.unwrap_or_default());
    let start = Instant::now();
    if std::env::var_os("VIMVIBE_DEBUG").is_some() {
        eprintln!("collection: {} candidate refs (before per-element calls)", refs.len());
    }
    let built = join_all(refs.iter().map(|r| async move {
        if start.elapsed() > o.timeout {
            return None;
        }
        let p = proxy(conn, r).await.ok()?;
        let state = p.get_state().await.ok()?;
        let role_s = role_of(conn, r, &p, &state).await;
        build_element(conn, r, win, o, &p, &state, role_s, &[]).await
    }))
    .await;
    Some(finish(conn, win, o, built.into_iter().flatten().collect()).await)
}

/// Same as `content_name` but answered from the already-fetched cache (no calls).
fn cached_content_name(it: &atspi::CacheItem, children: &std::collections::HashMap<String, Vec<&atspi::CacheItem>>, depth: u32) -> String {
    let mut parts: Vec<String> = vec![];
    for c in children.get(it.object.path_as_str()).into_iter().flatten().take(8) {
        let n = c.short_name.trim();
        if !n.is_empty() {
            parts.push(n.to_string());
        } else if depth > 1 {
            let n = cached_content_name(c, children, depth - 1);
            if !n.is_empty() {
                parts.push(n);
            }
        }
    }
    parts.join(" ")
}

/// Cache path: one `Cache.GetItems` call returns every node's role, name and state for the whole app, so the tree is
/// filtered locally and only survivors need a call (their extents). Returns None when the app has no usable cache.
pub async fn enumerate_cache(conn: &AccessibilityConnection, win: &Window, o: &Opts) -> Option<Vec<Element>> {
    use atspi::proxy::cache::CacheProxy;
    use std::collections::HashMap;
    // 1. fetch the whole app tree in one call (the bus name of the window's app is the cache's destination)
    let bus = win.root.name()?.clone();
    let cache = CacheProxy::builder(conn.connection()).destination(bus).ok()?.build().await.ok()?;
    let items = cache.get_items().await.ok()?;
    // 2. index the flat item list by parent, children in their on-screen order, so the tree can be walked locally
    let mut children: HashMap<String, Vec<&atspi::CacheItem>> = HashMap::new();
    for it in &items {
        children.entry(it.parent.path_as_str().to_string()).or_default().push(it);
    }
    for v in children.values_mut() {
        v.sort_by_key(|i| i.index);
    }
    if let Some(needle) = std::env::var_os("VIMVIBE_DEBUG_NAME") {
        let needle = needle.to_string_lossy().to_lowercase();
        for it in items.iter().filter(|i| i.short_name.to_lowercase().contains(&needle)) {
            eprintln!("cache item {:?} role {:?} states showing={} parent={} children_in_cache={}", it.short_name, it.role, it.states.contains(State::Showing), it.parent.path_as_str(), children.get(it.object.path_as_str()).map_or(0, |v| v.len()));
        }
    }
    // 3. depth-first walk from the window root, keeping hidden-subtree pruning and collecting actionable candidates
    let mut stack: Vec<&atspi::CacheItem> = children.get(win.root.path_as_str()).into_iter().flatten().rev().copied().collect();
    let mut cands = vec![];
    // Chromium's cache can lag behind the live tree (new nodes missing, VS Code: 3 buttons). Every node records how many
    // children it has, so a visible node with fewer children in the cache than declared marks an incomplete subtree.
    let mut repair: Vec<&atspi::CacheItem> = vec![];
    let found = |it: &atspi::CacheItem| children.get(it.object.path_as_str()).map_or(0, |v| v.len());
    if let Some(root_item) = items.iter().find(|i| i.object.path_as_str() == win.root.path_as_str()) {
        if root_item.children as usize > found(root_item) {
            repair.push(root_item);
        }
    }
    while let Some(it) = stack.pop() {
        if !o.include_hidden && !it.states.contains(State::Showing) {
            continue; // prune hidden subtrees, as the walk does
        }
        if it.children as usize > found(it) {
            repair.push(it);
        }
        let role_s = role_name(it.role, &it.states);
        if ACTIONABLE.contains(&role_s.as_str()) {
            cands.push((it, role_s));
        }
        stack.extend(children.get(it.object.path_as_str()).into_iter().flatten().rev().copied());
    }
    if std::env::var_os("VIMVIBE_DEBUG").is_some() {
        eprintln!("cache: {} items in app, {} candidates", items.len(), cands.len());
    }
    // 4. turn candidates into Elements concurrently: pick a name (own name, description, then text of its children),
    //    read the on-screen rectangle (the only per-element call) and drop empty or zero-sized ones
    let children_ref = &children;
    let built = join_all(cands.into_iter().map(|(it, role_s)| async move {
        let mut name = it.short_name.clone(); // crate field naming: short_name = accessible name, name = description
        let description = it.name.clone();
        if name.trim().is_empty() {
            name = description.clone();
        }
        if name.trim().is_empty() {
            name = cached_content_name(it, children_ref, 2);
        }
        if name.trim().is_empty() {
            if INPUT_ROLES.contains(&role_s.as_str()) {
                name = format!("(unlabeled {})", role_s.to_lowercase());
            } else {
                return None;
            }
        }
        let rect = element_rect(conn, &it.object).await.unwrap_or_default();
        if !o.include_hidden && (rect.2 <= 0 || rect.3 <= 0) {
            return None;
        }
        let actions = if o.with_actions { element_actions(conn, &it.object).await } else { vec![] };
        Some(Element {
            app: win.app.clone(),
            window: win.title.clone(),
            role: role_s,
            name: name.trim().to_string(),
            description,
            actions,
            rect,
            enabled: it.states.contains(State::Enabled) || it.states.contains(State::Sensitive),
            object: Some(it.object.clone()),
        })
    }))
    .await;
    let mut els: Vec<Element> = built.into_iter().flatten().collect();
    // repair: read the live children of incomplete nodes and walk only the ones the cache does not know
    if !repair.is_empty() {
        let known: std::collections::HashSet<&str> = items.iter().map(|i| i.object.path_as_str()).collect();
        let live = join_all(repair.iter().map(|it| async move {
            let p = proxy(conn, &it.object).await.ok()?;
            p.get_children().await.ok()
        }))
        .await;
        let missing: Vec<ObjectRefOwned> = live.into_iter().flatten().flatten().filter(|r| !known.contains(r.path_as_str())).collect();
        if std::env::var_os("VIMVIBE_DEBUG").is_some() {
            eprintln!("cache repair: {} incomplete nodes, {} live children missing from the cache", repair.len(), missing.len());
        }
        if !missing.is_empty() {
            let (extra, _) = bfs(conn, win, o, missing, false).await;
            els.extend(extra);
        }
    }
    Some(finish(conn, win, o, els).await)
}

/// Breadth-first walk (levels fetched concurrently) with node and time budgets; returns partial results on budget exhaustion.
pub async fn enumerate(conn: &AccessibilityConnection, win: &Window, o: &Opts) -> (Vec<Element>, bool) {
    let (out, truncated) = bfs(conn, win, o, vec![win.root.clone()], true).await;
    (finish(conn, win, o, out).await, truncated)
}

/// The walk itself, from any starting nodes (`first_is_root` exempts the very first level from the Showing prune).
async fn bfs(conn: &AccessibilityConnection, win: &Window, o: &Opts, start: Vec<ObjectRefOwned>, first_is_root: bool) -> (Vec<Element>, bool) {
    let t = Instant::now();
    let mut level = start;
    let (mut out, mut seen, mut first, mut truncated) = (vec![], 0usize, first_is_root, false);
    while !level.is_empty() {
        if t.elapsed() > o.timeout || seen > o.max_nodes {
            truncated = true;
            break;
        }
        seen += level.len();
        let visits = join_all(level.iter().map(|r| visit(conn, r, win, first, o))).await;
        first = false;
        level = vec![];
        for v in visits {
            if let Some(e) = v.element {
                out.push(e);
            }
            level.extend(v.children);
        }
    }
    (out, truncated)
}

/// Clip to the window (virtualised lists report off-screen rows as Showing with huge offsets), sort, dedupe.
async fn finish(conn: &AccessibilityConnection, win: &Window, o: &Opts, mut out: Vec<Element>) -> Vec<Element> {
    if !o.include_hidden {
        if let Some((w, h)) = window_size(conn, &win.root).await {
            out.retain(|e| {
                let (cx, cy) = (e.rect.0 + e.rect.2 / 2, e.rect.1 + e.rect.3 / 2);
                cx >= 0 && cy >= 0 && cx < w && cy < h
            });
        }
    }
    // collapse exact duplicates (same role, name, rect)
    out.sort_by(|a, b| (a.rect.1, a.rect.0, &a.name).cmp(&(b.rect.1, b.rect.0, &b.name)));
    out.dedup_by(|a, b| a.role == b.role && a.name == b.name && a.rect == b.rect);
    collapse_twins(conn, out).await
}

/// Some toolkits expose one control as two nodes at the same place with the same name (GTK4 MenuButton = Button +
/// ToggleButton, DropDown = ComboBox + ToggleButton). Keep the twin that can actually be activated.
async fn collapse_twins(conn: &AccessibilityConnection, out: Vec<Element>) -> Vec<Element> {
    use std::collections::HashMap;
    let mut groups: HashMap<(String, (i32, i32, i32, i32)), Vec<usize>> = HashMap::new();
    for (i, e) in out.iter().enumerate() {
        groups.entry((e.name.clone(), e.rect)).or_default().push(i);
    }
    let mut drop = vec![false; out.len()];
    for idxs in groups.values().filter(|g| g.len() > 1) {
        let mut keep = idxs[0];
        for &i in idxs {
            let has = match &out[i].object {
                Some(o) => !element_actions(conn, o).await.is_empty(),
                None => false,
            };
            if has {
                keep = i;
                break;
            }
        }
        for &i in idxs {
            drop[i] = i != keep;
        }
    }
    out.into_iter().zip(drop).filter(|(_, d)| !d).map(|(e, _)| e).collect()
}

/// Size of a window or popup from its own extents (used to pair accessible windows with KWin surfaces).
pub(crate) async fn window_size(conn: &AccessibilityConnection, root: &ObjectRefOwned) -> Option<(i32, i32)> {
    let bus = root.name()?.clone();
    let c = ComponentProxy::builder(conn.connection()).destination(bus).ok()?.path(root.path().clone()).ok()?.build().await.ok()?;
    let (_, _, w, h) = extents(&c).await?;
    (w > 0 && h > 0).then_some((w, h))
}

/// Top-level windows of the accessible app(s) named `app` with their sizes (for pairing with KWin surfaces, e.g.
/// Plasma's panels, which are separate windows of plasmashell).
pub async fn app_windows(conn: &AccessibilityConnection, app: &str) -> Vec<(Window, (i32, i32))> {
    let mut out = vec![];
    let Ok(root) = conn.root_accessible_on_registry().await else { return out };
    for a in root.get_children().await.unwrap_or_default() {
        let Ok(ap) = proxy(conn, &a).await else { continue };
        if ap.name().await.unwrap_or_default() != app {
            continue;
        }
        for w in ap.get_children().await.unwrap_or_default() {
            let title = match proxy(conn, &w).await {
                Ok(wp) => wp.name().await.unwrap_or_default(),
                Err(_) => continue,
            };
            if let Some(size) = window_size(conn, &w).await {
                out.push((Window { app: app.to_string(), title, root: w, geometry: None }, size));
            }
        }
    }
    out
}

/// The entries of an open menu: its direct children only (closed submenus hang below their entry with stale
/// positions), with a real size inside the menu, separators and nameless entries left out. Qt menu items don't carry
/// the Showing state while the menu is open, so states are not used to filter.
pub async fn menu_items(conn: &AccessibilityConnection, menu: &Window, size: (i32, i32)) -> Vec<Element> {
    let mut out: Vec<(Element, bool)> = vec![];
    let Ok(mp) = proxy(conn, &menu.root).await else { return vec![] };
    let o = Opts { include_hidden: true, timeout: Duration::from_millis(1000), max_nodes: 500, with_actions: false };
    for c in mp.get_children().await.unwrap_or_default().into_iter().take(200) {
        let Ok(p) = proxy(conn, &c).await else { continue };
        let state = p.get_state().await.unwrap_or_default();
        let role_s = role_of(conn, &c, &p, &state).await;
        if role_s == "Separator" {
            continue;
        }
        let kids = p.get_children().await.unwrap_or_default();
        let Some(e) = build_element(conn, &c, menu, &o, &p, &state, role_s, &kids).await else { continue };
        if std::env::var_os("VIMVIBE_DEBUG").is_some() {
            eprintln!("menu item {:?} {:?} visible={} showing={} enabled={}", e.name, e.rect, state.contains(State::Visible), state.contains(State::Showing), e.enabled);
        }
        let (x, y, w, h) = e.rect;
        if w > 0 && h > 0 && x >= -2 && y >= -2 && x < size.0 && y < size.1 && !e.name.starts_with("(unlabeled ") {
            out.push((e, state.contains(State::Visible)));
        }
    }
    // Every entry of one Qt menu has the same width. Qt keeps one accessible per action, so an action that also sits
    // in another menu reports its geometry *there* (Dolphin's hamburger menu reuses the menu bar's actions: widths 240,
    // 286, 327 inside a 304-wide menu). Entries with the menu's own width keep their place; the others stay searchable
    // and activatable (activation uses the action, not the position) but get no on-screen label.
    let width_mode = |items: Vec<i32>| {
        let mut counts = std::collections::HashMap::new();
        for w in items {
            *counts.entry(w).or_insert(0) += 1;
        }
        counts.into_iter().max_by_key(|&(w, n)| (n, w)).map(|(w, _)| w)
    };
    let own = width_mode(out.iter().filter(|(_, v)| *v).map(|(e, _)| e.rect.2).collect()).or_else(|| width_mode(out.iter().map(|(e, _)| e.rect.2).collect()));
    let mut items: Vec<Element> = out
        .into_iter()
        .map(|(mut e, _)| {
            if own.is_some_and(|w| (e.rect.2 - w).abs() > 2) {
                e.rect = (0, 0, 0, 0);
            }
            e
        })
        .collect();
    // For those, ask the menu which entry is under points down its middle (Qt answers that from the menu itself,
    // so it is right even when the entry's own extents are not) and rebuild each entry's row from the hits.
    if items.iter().any(|e| e.rect.2 == 0) {
        if let Some(rows) = probe_rows(conn, &menu.root, size).await {
            for e in items.iter_mut().filter(|e| e.rect.2 == 0) {
                if let Some(r) = e.object.as_ref().and_then(|o| rows.get(o.path().as_str())) {
                    e.rect = *r;
                }
            }
        }
    }
    items
}

/// Entry rows of an open menu by hit-testing every few pixels down its middle: object path -> (x, y, w, h).
async fn probe_rows(conn: &AccessibilityConnection, menu: &ObjectRefOwned, size: (i32, i32)) -> Option<std::collections::HashMap<String, (i32, i32, i32, i32)>> {
    let bus = menu.name()?.clone();
    let c = ComponentProxy::builder(conn.connection()).destination(bus).ok()?.path(menu.path().clone()).ok()?.build().await.ok()?;
    let (w, h) = size;
    let step = 4;
    let mut rows: std::collections::HashMap<String, (i32, i32, i32, i32)> = std::collections::HashMap::new();
    let mut y = 1;
    while y < h {
        if let Ok(hit) = c.get_accessible_at_point(w / 2, y, atspi::CoordType::Window).await {
            let path = hit.path().as_str().to_string();
            if path != menu.path().as_str() && !path.ends_with("/null") {
                let r = rows.entry(path).or_insert((4, y, (w - 8).max(1), 1));
                r.3 = y - r.1 + 1;
            }
        }
        y += step;
    }
    Some(rows)
}
