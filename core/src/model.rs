use atspi::connection::AccessibilityConnection;
use atspi::proxy::{action::ActionProxy, component::ComponentProxy};
use atspi::{CoordType, ObjectRefOwned};
use serde::Serialize;

/// One actionable UI element found in a window's accessibility tree.
#[derive(Debug, Clone, Default, Serialize)]
pub struct Element {
    pub app: String,
    pub window: String,
    pub role: String,
    pub name: String,
    pub description: String,
    /// Action names; only filled when enumeration is asked for them (`--with-actions`).
    pub actions: Vec<String>,
    /// Window-relative extents (x, y, w, h). Screen position = window client origin + this.
    pub rect: (i32, i32, i32, i32),
    pub enabled: bool,
    #[serde(skip)]
    pub object: Option<ObjectRefOwned>,
}

impl Element {
    /// Re-resolve the element and activate it, trying in order: its default AT-SPI action; selecting it through its
    /// parent's Selection interface (tabs, list rows: GTK4 tabs have no action); focusing it. Actions are looked up
    /// live so listing stays cheap. When none works the error says so (needs a pointer-click fallback).
    ///
    /// `pointer_ok` says a pointer click is available (pointer set up, not disabled). Then semantic paths that only
    /// *look* like activation are skipped in favour of a real click: list/tree items whose only action is
    /// toggle/select (Dolphin's Places: "Toggle" changes the selection but does not open the place), selecting through
    /// the parent, and focusing a non-text element. The caller turns the `NeedsPointer` error into a click.
    pub async fn activate(&self, conn: &AccessibilityConnection, pointer_ok: bool) -> anyhow::Result<String> {
        anyhow::ensure!(self.enabled, "'{}' is disabled", self.name);
        let item = matches!(self.role.as_str(), "ListItem" | "TreeItem" | "TableCell" | "TableRow" | "Icon");
        let needs_pointer = || -> anyhow::Error { NeedsPointer { role: self.role.clone(), rect: self.rect }.into() };
        let obj = self.object.as_ref().ok_or_else(|| anyhow::anyhow!("element has no object reference"))?;
        let bus = obj.name().ok_or_else(|| anyhow::anyhow!("null bus name"))?.clone();
        let path = obj.path().clone();
        let action = ActionProxy::builder(conn.connection()).destination(bus.clone())?.path(path.clone())?.build().await?;
        let actions = action.get_actions().await.unwrap_or_default();
        if let Some(i) = pick_action(&actions.iter().map(|a| a.name.as_str()).collect::<Vec<_>>()) {
            let selection_only = matches!(actions[i].name.to_lowercase().as_str(), "toggle" | "select" | "check" | "");
            if item && selection_only && pointer_ok {
                return Err(needs_pointer());
            }
            let ok = action.do_action(i as i32).await?;
            anyhow::ensure!(ok, "do_action({i}) returned false");
            let name = &actions[i].name;
            return Ok(format!("did action '{}'", if name.is_empty() { "(default)" } else { name }));
        }
        if item && pointer_ok {
            return Err(needs_pointer());
        }
        if matches!(self.role.as_str(), "PageTab" | "ListItem" | "TreeItem" | "TableCell") {
            if let Some(msg) = self.select_via_parent(conn).await {
                return Ok(msg);
            }
        }
        let text_input = matches!(self.role.as_str(), "Entry" | "PasswordText" | "Text" | "DocumentText" | "SpinButton" | "Terminal");
        if pointer_ok && !text_input {
            return Err(needs_pointer()); // focusing a button does not press it
        }
        let comp = ComponentProxy::builder(conn.connection()).destination(bus)?.path(path)?.build().await?;
        match comp.grab_focus().await {
            Ok(true) => Ok("focused (no action exposed)".into()),
            _ => Err(needs_pointer()),
        }
    }

    /// Give the element keyboard focus (Shortcat's "tap Control twice": focus without clicking).
    pub async fn focus(&self, conn: &AccessibilityConnection) -> anyhow::Result<String> {
        let obj = self.object.as_ref().ok_or_else(|| anyhow::anyhow!("element has no object reference"))?;
        let bus = obj.name().ok_or_else(|| anyhow::anyhow!("null bus name"))?.clone();
        let comp = ComponentProxy::builder(conn.connection()).destination(bus)?.path(obj.path().clone())?.build().await?;
        anyhow::ensure!(comp.grab_focus().await?, "the app refused to focus '{}'", self.name);
        Ok("focused".into())
    }

    /// Select this element through its parent's Selection interface (tabs and list rows that have no action).
    async fn select_via_parent(&self, conn: &AccessibilityConnection) -> Option<String> {
        let obj = self.object.as_ref()?;
        let me = crate::enumerate::proxy(conn, obj).await.ok()?;
        let index = me.get_index_in_parent().await.ok()?;
        let parent = me.parent().await.ok()?;
        let bus = parent.name()?.clone();
        let sel = atspi::proxy::selection::SelectionProxy::builder(conn.connection()).destination(bus).ok()?.path(parent.path().clone()).ok()?.build().await.ok()?;
        sel.select_child(index).await.ok()?.then(|| "selected through parent".to_string())
    }
}

/// No semantic activation worked (no action, no selection, focus unsupported): only a pointer click can.
/// Callers that can click (daemon, `act`) downcast to this; everyone else just shows the message.
#[derive(Debug)]
pub struct NeedsPointer {
    pub role: String,
    /// Window-relative extents; add the window's screen origin to click.
    #[allow(dead_code)] // kept for callers that want to report where a click would land
    pub rect: (i32, i32, i32, i32),
}

impl std::fmt::Display for NeedsPointer {
    /// Human-readable reason, shown when no pointer fallback is available.
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "no semantic way to activate this {} (no action, no selection, focus unsupported); needs a pointer click", self.role)
    }
}

impl std::error::Error for NeedsPointer {}

/// Which of an element's actions is the "default click". Toolkits order them arbitrarily (GTK4 list rows only offer
/// `listitem.scroll-to`, which scrolls but does not activate), so: known activating names first, then any action that
/// is not a scroll/menu helper, else none (the caller falls back to selection or focus). Empty names (Electron) count as default.
pub fn pick_action(names: &[&str]) -> Option<usize> {
    const PREFERRED: &[&str] = &["click", "press", "activate", "toggle", "check", "select", "open", "jump", "default", ""];
    for want in PREFERRED {
        if let Some(i) = names.iter().position(|n| n.eq_ignore_ascii_case(want)) {
            return Some(i);
        }
    }
    names.iter().position(|n| {
        let n = n.to_lowercase();
        !(n.contains("scroll") || n.contains("menu") || n.contains("context"))
    })
}

/// Window-relative extents through a Component proxy.
pub async fn extents(comp: &ComponentProxy<'_>) -> Option<(i32, i32, i32, i32)> {
    comp.get_extents(CoordType::Window).await.ok()
}

#[cfg(test)]
mod tests {
    use super::pick_action;

    // The activation ladder picks click/press/toggle over other actions.
    #[test]
    fn prefers_activating_actions() {
        assert_eq!(pick_action(&["click"]), Some(0));
        assert_eq!(pick_action(&["ShowMenu", "Press"]), Some(1));
        assert_eq!(pick_action(&["toggle"]), Some(0));
        assert_eq!(pick_action(&[""]), Some(0)); // Electron reports an unnamed default action
    }

    // Scroll and menu helper actions are never chosen as the click action.
    #[test]
    fn never_picks_scroll_or_menu_helpers() {
        assert_eq!(pick_action(&["listitem.scroll-to"]), None);
        assert_eq!(pick_action(&["ShowMenu"]), None);
        assert_eq!(pick_action(&["listitem.scroll-to", "custom"]), Some(1));
    }
}
