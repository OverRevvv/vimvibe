//! Keys without keyboard focus, through the accessibility registry's keystroke listener (the mechanism screen readers
//! use): Qt and GTK 3 apps hand every key press to the registry and wait for the reply; a listener that answers
//! "consumed" keeps the key from reaching the app. Registered only while needed, only on this session's bus.
//!
//! Two modes:
//! - **Popup**: the overlay is shown over a popup that must keep the keyboard (Plasma's launcher, open menus); every
//!   plain key is taken and forwarded to the overlay.
//! - **Arrows**: the overlay is hidden and the app has the keyboard again; only the physical H J K L / I keys, Space
//!   and Esc are taken (matched by key position like Shortcat, so Dvorak/Colemak work), so the daemon can turn them
//!   into arrow keys; everything else — including the arrow keys we send — reaches the app.

use serde::Serialize;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicU8, Ordering};
use tokio::sync::mpsc::UnboundedSender;
use zbus::zvariant::ObjectPath;

pub const PATH: &str = "/org/vimvibe/KeyListener";
const DEC_DEST: &str = "org.a11y.atspi.Registry";
const DEC_PATH: &str = "/org/a11y/atspi/registry/deviceeventcontroller";
const DEC_IFACE: &str = "org.a11y.atspi.DeviceEventController";
/// key pressed + key released
const TYPES: u32 = (1 << 0) | (1 << 1);
/// Registry listeners match on the exact modifier state, so cover plain keys with any of Shift, Caps Lock, Num Lock.
/// Ctrl/Alt/Super combinations are not taken in popup mode: they keep working in the popup and system-wide.
/// Safety: if vimvibe dies while registered, the registry's calls to the vanished listener fail and count as "not
/// consumed" (measured), so keys reach the apps again; the dead entry itself stays until the session ends.
const MASKS: [u32; 8] = [0, 1, 2, 3, 16, 17, 18, 19];
/// Arrow mode also listens with Ctrl and Alt held (Space+Ctrl+J = Ctrl+Down), so those masks are added.
const ARROW_EXTRA: [u32; 3] = [4, 8, 12];

pub const MODE_OFF: u8 = 0;
pub const MODE_POPUP: u8 = 1;
pub const MODE_ARROWS: u8 = 2;

/// X keycodes (evdev + 8) of the keys arrow mode takes: physical positions, independent of the layout.
pub const KC_ESC: u32 = 9;
pub const KC_I: u32 = 31;
pub const KC_H: u32 = 43;
pub const KC_J: u32 = 44;
pub const KC_K: u32 = 45;
pub const KC_L: u32 = 46;
pub const KC_SPACE: u32 = 65;

#[derive(Debug, Clone, Serialize)]
pub struct Key {
    /// Key name as the toolkit reports it: "a", "A", "Return", "Escape", "BackSpace", "Down", "space", ...
    pub name: String,
    /// The key produces text (letters, digits, punctuation).
    pub text: bool,
    /// Pressed (true) or released.
    pub pressed: bool,
    /// X keycode (physical key).
    #[serde(skip)]
    pub code: u32,
}

/// Shared between the listener object and the daemon.
#[derive(Default)]
pub struct State {
    /// MODE_OFF / MODE_POPUP / MODE_ARROWS
    pub mode: AtomicU8,
    /// Set by every event the registry delivers (arrow mode's check that the app forwards keys at all).
    pub seen: AtomicBool,
}

pub struct Listener {
    pub tx: UnboundedSender<Key>,
    pub state: Arc<State>,
}

#[zbus::interface(name = "org.a11y.atspi.DeviceEventListener")]
impl Listener {
    /// (type, id, hw_code, modifiers, timestamp, event_string, is_text) -> consumed. The registry calls listeners
    /// with `(uiuuisb)` (seen on the bus), while toolkits hand events *to* the registry as `(uinnisb)`.
    fn notify_event(&self, ev: (u32, i32, u32, u32, i32, String, bool)) -> bool {
        let (kind, _id, code, _mods, _ts, name, text) = ev;
        self.state.seen.store(true, Ordering::SeqCst);
        let pressed = kind == 0;
        match self.state.mode.load(Ordering::SeqCst) {
            MODE_POPUP => {
                if pressed {
                    let _ = self.tx.send(Key { name, text, pressed, code });
                }
                true // the popup must not see any plain key
            }
            MODE_ARROWS => {
                if matches!(code, KC_ESC | KC_I | KC_H | KC_J | KC_K | KC_L | KC_SPACE) {
                    let _ = self.tx.send(Key { name, text, pressed, code });
                    true
                } else {
                    false // everything else (Shift, the arrow keys we send, other letters) goes to the app
                }
            }
            _ => false,
        }
    }
}

/// Serve the listener object on the accessibility bus (once, at daemon start).
pub async fn serve(conn: &zbus::Connection, tx: UnboundedSender<Key>, state: Arc<State>) -> zbus::Result<bool> {
    conn.object_server().at(PATH, Listener { tx, state }).await
}

/// Modifier masks to register for a mode.
fn masks(mode: u8) -> Vec<u32> {
    let mut m = MASKS.to_vec();
    if mode == MODE_ARROWS {
        m.extend(MASKS.iter().flat_map(|b| ARROW_EXTRA.iter().map(move |x| b | x)));
    }
    m
}

/// Start taking keys in `mode` (see the module docs) through the registry.
pub async fn grab(conn: &zbus::Connection, state: &State, mode: u8) -> anyhow::Result<()> {
    let path = ObjectPath::try_from(PATH)?;
    let keys: Vec<(i32, i32, String, i32)> = vec![]; // empty = every key
    state.mode.store(mode, Ordering::SeqCst);
    for mask in masks(mode) {
        // The reply is `false` on Wayland even though the listener is stored and called: it reports whether an X11
        // key grab could be set up, which does not exist here. Only a D-Bus error means it failed.
        conn.call_method(Some(DEC_DEST), DEC_PATH, Some(DEC_IFACE), "RegisterKeystrokeListener", &(&path, &keys, mask, TYPES, (true, true, false)))
            .await?;
    }
    Ok(())
}

/// Stop taking keys; every key reaches the apps again.
pub async fn release(conn: &zbus::Connection, state: &State) {
    state.mode.store(MODE_OFF, Ordering::SeqCst);
    let Ok(path) = ObjectPath::try_from(PATH) else { return };
    let keys: Vec<(i32, i32, String, i32)> = vec![];
    for mask in masks(MODE_ARROWS) {
        let _ = conn.call_method(Some(DEC_DEST), DEC_PATH, Some(DEC_IFACE), "DeregisterKeystrokeListener", &(&path, &keys, mask, TYPES)).await;
    }
}
