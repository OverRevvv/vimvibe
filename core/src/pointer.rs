//! Pointer-click fallback for elements with no semantic activation path (GTK4 check boxes: no action, no focus).
//!
//! Wayland gives clients no way to inject input or read the pointer, so this uses the sanctioned route:
//! the XDG **RemoteDesktop portal**. The compositor shows a consent dialog; the user approves once and the portal
//! hands back a restore token, so later sessions start silently. We never touch the dialog ourselves, and the token
//! is only ever created through `pointer-setup` (the daemon never opens the dialog on its own).
//!
//! The portal's absolute motion needs a ScreenCast stream (a second dialog), so we use **relative** motion with a
//! closed loop: read the real cursor position from KWin (`workspace.cursorPos`), send the difference, read again,
//! until within a pixel. That is robust to pointer acceleration/scaling because every step is measured.

use crate::kwin;
use ashpd::desktop::remote_desktop::{DeviceType, KeyState, NotifyPointerButtonOptions, NotifyPointerMotionOptions, RemoteDesktop, SelectDevicesOptions, StartOptions};
use ashpd::desktop::{CreateSessionOptions, PersistMode, Session};
use ashpd::enumflags2::BitFlags;
use std::path::PathBuf;
use std::time::Duration;

const BTN_LEFT: i32 = 0x110;
const BTN_RIGHT: i32 = 0x111;
const BTN_MIDDLE: i32 = 0x112;

#[derive(Clone, Copy, PartialEq, Debug)]
pub enum Button {
    Left,
    Right,
    Middle,
}

impl Button {
    /// Linux input event code of the button.
    fn code(self) -> i32 {
        match self {
            Button::Left => BTN_LEFT,
            Button::Right => BTN_RIGHT,
            Button::Middle => BTN_MIDDLE,
        }
    }
}

/// Where the portal's restore token is kept: `$XDG_STATE_HOME/vimvibe/pointer-token`.
pub fn token_path() -> PathBuf {
    let base = std::env::var_os("XDG_STATE_HOME")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("HOME").map(|h| PathBuf::from(h).join(".local/state")))
        .unwrap_or_else(|| PathBuf::from(".local/state"));
    base.join("vimvibe").join("pointer-token")
}

/// The saved restore token, if pointer setup was done.
fn read_token() -> Option<String> {
    std::fs::read_to_string(token_path()).ok().map(|s| s.trim().to_string()).filter(|s| !s.is_empty())
}

/// Save a restore token, readable by the user only.
fn write_token(token: &str) -> anyhow::Result<()> {
    use std::os::unix::fs::PermissionsExt;
    let p = token_path();
    if let Some(dir) = p.parent() {
        std::fs::create_dir_all(dir)?;
    }
    std::fs::write(&p, token)?;
    std::fs::set_permissions(&p, std::fs::Permissions::from_mode(0o600))?; // it is a credential for pointer control
    Ok(())
}

/// Whether pointer clicks are available without asking (setup was done once).
pub fn is_set_up() -> bool {
    read_token().is_some()
}

pub struct Pointer {
    rd: RemoteDesktop,
    session: Session<RemoteDesktop>,
}

impl Pointer {
    /// Open a RemoteDesktop session for the pointer. With `interactive` the portal may show its consent dialog
    /// (only `pointer-setup` passes it); without it a missing token is an error, so nothing pops up unexpectedly.
    pub async fn connect(interactive: bool) -> anyhow::Result<Self> {
        let token = read_token();
        anyhow::ensure!(interactive || token.is_some(), "pointer control is not set up; run `vimvibe-core pointer-setup` once");
        let rd = RemoteDesktop::new().await?;
        let session = rd.create_session(CreateSessionOptions::default()).await?;
        rd.select_devices(
            &session,
            SelectDevicesOptions::default()
                .set_devices(BitFlags::from(DeviceType::Pointer))
                .set_persist_mode(PersistMode::ExplicitlyRevoked)
                .set_restore_token(token.as_deref()),
        )
        .await?
        .response()?;
        let started = rd.start(&session, None, StartOptions::default()).await?.response()?;
        anyhow::ensure!(started.devices().contains(DeviceType::Pointer), "the portal did not grant pointer control");
        if let Some(t) = started.restore_token() {
            write_token(t)?;
        }
        Ok(Pointer { rd, session })
    }

    /// Move the pointer by (dx, dy) through the portal.
    async fn motion(&self, dx: f64, dy: f64) -> anyhow::Result<()> {
        self.rd.notify_pointer_motion(&self.session, dx, dy, NotifyPointerMotionOptions::default()).await?;
        Ok(())
    }

    /// Press or release a pointer button through the portal.
    async fn button(&self, b: Button, state: KeyState) -> anyhow::Result<()> {
        self.rd.notify_pointer_button(&self.session, b.code(), state, NotifyPointerButtonOptions::default()).await?;
        Ok(())
    }

    /// Move the pointer to (x, y) in logical screen pixels. Returns where it ended up.
    pub async fn move_to(&self, x: f64, y: f64) -> anyhow::Result<(f64, f64)> {
        let mut last = kwin::cursor_pos(Duration::from_millis(500)).await.ok_or_else(|| anyhow::anyhow!("cannot read the cursor position from KWin"))?;
        for _ in 0..8 {
            let (dx, dy) = (x - last.0, y - last.1);
            if dx.abs() <= 1.0 && dy.abs() <= 1.0 {
                return Ok(last);
            }
            self.motion(dx, dy).await?;
            tokio::time::sleep(Duration::from_millis(12)).await;
            last = kwin::cursor_pos(Duration::from_millis(500)).await.ok_or_else(|| anyhow::anyhow!("cannot read the cursor position from KWin"))?;
        }
        anyhow::ensure!((x - last.0).abs() <= 3.0 && (y - last.1).abs() <= 3.0, "pointer did not converge on ({x:.0}, {y:.0}); stopped at ({:.0}, {:.0})", last.0, last.1);
        Ok(last)
    }

    /// Click at a screen position, then put the pointer back where the user had it (unless `restore` is false).
    pub async fn click_at(&self, x: f64, y: f64, button: Button, count: u32, restore: bool) -> anyhow::Result<()> {
        let origin = kwin::cursor_pos(Duration::from_millis(500)).await;
        self.move_to(x, y).await?;
        for i in 0..count {
            if i > 0 {
                tokio::time::sleep(Duration::from_millis(60)).await;
            }
            self.button(button, KeyState::Pressed).await?;
            tokio::time::sleep(Duration::from_millis(20)).await;
            self.button(button, KeyState::Released).await?;
        }
        if let (true, Some((ox, oy))) = (restore, origin) {
            tokio::time::sleep(Duration::from_millis(40)).await; // let the click land before the pointer leaves
            let _ = self.move_to(ox, oy).await;
        }
        Ok(())
    }

    /// End the portal session.
    pub async fn close(self) {
        let _ = self.session.close().await;
    }
}
