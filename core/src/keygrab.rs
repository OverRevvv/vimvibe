//! Keys without keyboard focus, for popups that close when anything else takes the keyboard (Plasma's launcher,
//! tray and calendar popups). The overlay is shown without focus, the popup keeps it, and we read the keys the user
//! types through the accessibility registry's keystroke listener (the mechanism screen readers use): Qt and GTK apps
//! hand every key press to the registry and wait for the reply; a listener that answers "consumed" keeps the key from
//! reaching the app. Registered only while such an overlay is open, and only on the accessibility bus of this session.

use serde::Serialize;
use tokio::sync::mpsc::UnboundedSender;
use zbus::zvariant::ObjectPath;

pub const PATH: &str = "/org/vimvibe/KeyListener";
const DEC_DEST: &str = "org.a11y.atspi.Registry";
const DEC_PATH: &str = "/org/a11y/atspi/registry/deviceeventcontroller";
const DEC_IFACE: &str = "org.a11y.atspi.DeviceEventController";
/// key pressed + key released
const TYPES: u32 = (1 << 0) | (1 << 1);
/// Registry listeners match on the exact modifier state, so cover plain keys with any of Shift, Caps Lock, Num Lock.
/// Ctrl/Alt/Super combinations are not taken: they keep working in the popup and system-wide.
/// Safety: if vimvibe dies while registered, the registry's calls to the vanished listener fail and count as "not
/// consumed" (measured), so keys reach the apps again; the dead entry itself stays until the session ends.
const MASKS: [u32; 8] = [0, 1, 2, 3, 16, 17, 18, 19];

#[derive(Debug, Clone, Serialize)]
pub struct Key {
    /// Key name as the toolkit reports it: "a", "A", "Return", "Escape", "BackSpace", "Down", "space", ...
    pub name: String,
    /// The key produces text (letters, digits, punctuation).
    pub text: bool,
}

pub struct Listener {
    pub tx: UnboundedSender<Key>,
}

#[zbus::interface(name = "org.a11y.atspi.DeviceEventListener")]
impl Listener {
    /// (type, id, hw_code, modifiers, timestamp, event_string, is_text) -> consumed. The registry calls listeners
    /// with `(uiuuisb)` (seen on the bus), while toolkits hand events *to* the registry as `(uinnisb)`.
    fn notify_event(&self, ev: (u32, i32, u32, u32, i32, String, bool)) -> bool {
        let (kind, _id, _hw, _mods, _ts, name, text) = ev;
        if kind == 0 {
            let _ = self.tx.send(Key { name, text });
        }
        true // consume press and release: the popup must not see them
    }
}

/// Serve the listener object on the accessibility bus (once, at daemon start).
pub async fn serve(conn: &zbus::Connection, tx: UnboundedSender<Key>) -> zbus::Result<bool> {
    conn.object_server().at(PATH, Listener { tx }).await
}

/// Start taking plain key presses (all modifier masks in `MASKS`) through the registry.
pub async fn grab(conn: &zbus::Connection) -> anyhow::Result<()> {
    let path = ObjectPath::try_from(PATH)?;
    let keys: Vec<(i32, i32, String, i32)> = vec![]; // empty = every key
    for mask in MASKS {
        // The reply is `false` on Wayland even though the listener is stored and called: it reports whether an X11
        // key grab could be set up, which does not exist here. Only a D-Bus error means it failed.
        conn.call_method(Some(DEC_DEST), DEC_PATH, Some(DEC_IFACE), "RegisterKeystrokeListener", &(&path, &keys, mask, TYPES, (true, true, false)))
            .await?;
    }
    Ok(())
}

/// Stop taking keys; every key reaches the apps again.
pub async fn release(conn: &zbus::Connection) {
    let Ok(path) = ObjectPath::try_from(PATH) else { return };
    let keys: Vec<(i32, i32, String, i32)> = vec![];
    for mask in MASKS {
        let _ = conn.call_method(Some(DEC_DEST), DEC_PATH, Some(DEC_IFACE), "DeregisterKeystrokeListener", &(&path, &keys, mask, TYPES)).await;
    }
}
