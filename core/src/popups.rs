//! Open menus. Qt leaves popup menus out of the accessibility tree (an app lists only its normal windows), so a menu
//! that is open right now can only be found from the event Qt sends when it appears:
//! `object:state-changed:showing` on a "popup menu" object (measured on Dolphin: 16 items, size equal to the popup
//! KWin reports). This keeps the set of currently showing menus up to date; the daemon pairs them with KWin's popup
//! surfaces (same app, same size) to learn where they are on screen. Nested submenus are just more entries.
//!
//! Side effect, by design of the toolkits: once any client registers for accessibility events, Qt apps start handing
//! key presses to the accessibility registry (as they do whenever a screen reader runs). That is also what lets
//! keygrab.rs read keys over a popup; while no keystroke listener is registered, the registry passes every key on.

use atspi::connection::AccessibilityConnection;
use atspi::{ObjectRefOwned, Role};
use futures_util::StreamExt;
use std::sync::Arc;
use tokio::sync::Mutex;

#[derive(Default)]
pub struct Menus {
    open: Mutex<Vec<ObjectRefOwned>>,
}

impl Menus {
    /// Menus currently shown (as last reported by their apps).
    pub async fn showing(&self) -> Vec<ObjectRefOwned> {
        self.open.lock().await.clone()
    }
}

/// Roles that count as an open menu.
fn is_menu(role: Role) -> bool {
    matches!(role, Role::PopupMenu | Role::Menu)
}

/// Register for "showing" changes and track menus in the background. Idle cost: one D-Bus signal per state change
/// of "showing" in accessible apps (menus, tooltips, pages being shown), nothing else.
pub async fn track(conn: &AccessibilityConnection) -> anyhow::Result<Arc<Menus>> {
    conn.register_event::<atspi::events::object::StateChangedEvent>().await?;
    let menus = Arc::new(Menus::default());
    let (m2, zc) = (menus.clone(), conn.connection().clone());
    tokio::spawn(async move {
        // Read every D-Bus message on the accessibility connection and keep only AT-SPI `StateChanged` signals;
        // of those only the "showing" state matters: showing=1 may be a new menu, showing=0 means one went away.
        let mut stream = zbus::MessageStream::from(&zc);
        while let Some(Ok(msg)) = stream.next().await {
            let h = msg.header();
            if h.message_type() != zbus::message::Type::Signal
                || h.interface().map(|i| i.as_str()) != Some("org.a11y.atspi.Event.Object")
                || h.member().map(|m| m.as_str()) != Some("StateChanged")
            {
                continue;
            }
            // The signal body comes in two shapes depending on the AT-SPI version; accept either one.
            let body = msg.body();
            let Ok((kind, detail1)) = body
                .deserialize::<(String, i32, i32, zbus::zvariant::OwnedValue, std::collections::HashMap<String, zbus::zvariant::OwnedValue>)>()
                .map(|(k, d, ..)| (k, d))
                .or_else(|_| body.deserialize::<(String, i32, i32, zbus::zvariant::OwnedValue, (String, zbus::zvariant::OwnedObjectPath))>().map(|(k, d, ..)| (k, d)))
            else {
                continue;
            };
            if kind != "showing" {
                continue;
            }
            let (Some(sender), Some(path)) = (h.sender(), h.path()) else { continue };
            let obj = atspi::ObjectRef::new_owned(sender.to_owned(), path.to_owned());
            if detail1 == 0 {
                m2.open.lock().await.retain(|o| o != &obj);
                continue;
            }
            // Never await a D-Bus call inside this loop: replies arrive on the same connection, behind the signals
            // this loop must keep draining (every app now emits state changes), so it would deadlock.
            let (m3, zc3) = (m2.clone(), zc.clone());
            tokio::spawn(async move {
                if role_of(&zc3, &obj).await.is_some_and(is_menu) {
                    let mut open = m3.open.lock().await;
                    if !open.contains(&obj) {
                        open.push(obj);
                    }
                    if std::env::var_os("VIMVIBE_DEBUG").is_some() {
                        eprintln!("menu shown ({} open)", open.len());
                    }
                }
            });
        }
    });
    Ok(menus)
}

/// Role of an object, asked live (None if the object is already gone).
async fn role_of(conn: &zbus::Connection, obj: &ObjectRefOwned) -> Option<Role> {
    let p = atspi::proxy::accessible::AccessibleProxy::builder(conn)
        .destination(obj.name()?.clone())
        .ok()?
        .path(obj.path().clone())
        .ok()?
        .cache_properties(zbus::proxy::CacheProperties::No)
        .build()
        .await
        .ok()?;
    p.get_role().await.ok()
}
