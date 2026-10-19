//! Pointer-click fallback for elements with no semantic activation path (GTK4 check boxes: no action, no focus).
//!
//! Wayland gives clients no way to inject input or read the pointer, so this uses the sanctioned route:
//! the XDG **RemoteDesktop portal**. The compositor shows a consent dialog; the user approves once and the portal
//! hands back a restore token, so later sessions start silently. We never touch the dialog ourselves, and the token
//! is only ever created through `pointer-setup` (the daemon never opens the dialog on its own).
//!
//! Keyboard: the same permission can also cover a keyboard device (asked for by `pointer-setup` since arrow keys
//! were added). Which devices the user granted is stored next to the token, and later sessions request exactly those,
//! so a grant made before keyboard support never turns into a surprise dialog.
//!
//! The portal's absolute motion needs a ScreenCast stream (a second dialog), so we use **relative** motion with a
//! closed loop: read the real cursor position from KWin (`workspace.cursorPos`), send the difference, read again,
//! until within a pixel. That is robust to pointer acceleration/scaling because every step is measured.

use crate::kwin;
use ashpd::desktop::remote_desktop::{
    DeviceType, KeyState, NotifyKeyboardKeysymOptions, NotifyPointerAxisOptions, NotifyPointerButtonOptions, NotifyPointerMotionOptions,
    RemoteDesktop, SelectDevicesOptions, StartOptions,
};
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
/// Where the granted device list ("pointer" or "pointer,keyboard") is kept, next to the token.
fn devices_path() -> PathBuf {
    token_path().with_file_name("granted-devices")
}

/// Whether the user's grant includes the keyboard (arrow keys).
pub fn keyboard_granted() -> bool {
    read_token().is_some() && std::fs::read_to_string(devices_path()).is_ok_and(|s| s.contains("keyboard"))
}

/// Whether `pointer-setup` was ever completed (a saved restore token exists), i.e. clicks need no new dialog.
pub fn is_set_up() -> bool {
    read_token().is_some()
}

pub struct Pointer {
    rd: RemoteDesktop,
    session: Session<RemoteDesktop>,
    /// The keyboard device was granted too (arrow keys).
    keyboard: bool,
}

impl Pointer {
    /// Open a RemoteDesktop session for the pointer. With `interactive` the portal may show its consent dialog
    /// (only `pointer-setup` passes it); without it a missing token is an error, so nothing pops up unexpectedly.
    pub async fn connect(interactive: bool) -> anyhow::Result<Self> {
        let token = read_token();
        anyhow::ensure!(interactive || token.is_some(), "pointer control is not set up; run `vimvibe-core pointer-setup` once");
        // setup asks for pointer + keyboard; afterwards exactly what was granted is requested again (no new dialog)
        let want = if interactive || keyboard_granted() { DeviceType::Pointer | DeviceType::Keyboard } else { BitFlags::from(DeviceType::Pointer) };
        let rd = RemoteDesktop::new().await?;
        let session = rd.create_session(CreateSessionOptions::default()).await?;
        rd.select_devices(
            &session,
            SelectDevicesOptions::default()
                .set_devices(want)
                .set_persist_mode(PersistMode::ExplicitlyRevoked)
                .set_restore_token(if interactive { None } else { token.as_deref() }),
        )
        .await?
        .response()?;
        let started = rd.start(&session, None, StartOptions::default()).await?.response()?;
        let devices = started.devices();
        anyhow::ensure!(devices.contains(DeviceType::Pointer), "the portal did not grant pointer control");
        if let Some(t) = started.restore_token() {
            write_token(t)?;
        }
        let keyboard = devices.contains(DeviceType::Keyboard);
        if interactive {
            std::fs::write(devices_path(), if keyboard { "pointer,keyboard" } else { "pointer" })?;
        }
        Ok(Pointer { rd, session, keyboard })
    }

    /// Whether this session can type (the user granted the keyboard).
    pub fn has_keyboard(&self) -> bool {
        self.keyboard
    }

    /// Press or release a key by X keysym (e.g. 0xff54 = Down) in the focused window.
    pub async fn key(&self, keysym: i32, pressed: bool) -> anyhow::Result<()> {
        anyhow::ensure!(self.keyboard, "keyboard control was not granted; run `vimvibe-core pointer-setup` again and allow the keyboard");
        let state = if pressed { KeyState::Pressed } else { KeyState::Released };
        self.rd.notify_keyboard_keysym(&self.session, keysym, state, NotifyKeyboardKeysymOptions::default()).await?;
        Ok(())
    }

    /// Tap a key (press, release).
    pub async fn tap(&self, keysym: i32) -> anyhow::Result<()> {
        self.key(keysym, true).await?;
        self.key(keysym, false).await
    }

    /// Move the pointer by (dx, dy) through the portal.
    pub async fn motion(&self, dx: f64, dy: f64) -> anyhow::Result<()> {
        self.rd.notify_pointer_motion(&self.session, dx, dy, NotifyPointerMotionOptions::default()).await?;
        Ok(())
    }

    /// Press or release a pointer button through the portal.
    async fn button(&self, b: Button, state: KeyState) -> anyhow::Result<()> {
        self.rd.notify_pointer_button(&self.session, b.code(), state, NotifyPointerButtonOptions::default()).await?;
        Ok(())
    }

    /// Hold the left button down (`down`) or let it go: the keyboard mouse's text selection (press, move the pointer
    /// with H J K L, release).
    pub async fn hold(&self, down: bool) -> anyhow::Result<()> {
        self.button(Button::Left, if down { KeyState::Pressed } else { KeyState::Released }).await
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

    /// Press and release `button` `count` times where the pointer is.
    pub async fn press(&self, button: Button, count: u32) -> anyhow::Result<()> {
        for i in 0..count {
            if i > 0 {
                tokio::time::sleep(Duration::from_millis(60)).await;
            }
            self.button(button, KeyState::Pressed).await?;
            tokio::time::sleep(Duration::from_millis(20)).await;
            self.button(button, KeyState::Released).await?;
        }
        Ok(())
    }

    /// Click at a screen position, then put the pointer back where the user had it (unless `restore` is false).
    pub async fn click_at(&self, x: f64, y: f64, button: Button, count: u32, restore: bool) -> anyhow::Result<()> {
        let origin = kwin::cursor_pos(Duration::from_millis(500)).await;
        self.move_to(x, y).await?;
        self.press(button, count).await?;
        if let (true, Some((ox, oy))) = (restore, origin) {
            tokio::time::sleep(Duration::from_millis(40)).await; // let the click land before the pointer leaves
            let _ = self.move_to(ox, oy).await;
        }
        Ok(())
    }

    /// Smooth scroll event: `dx` > 0 scrolls right, `dy` > 0 down, in units of 1/10 wheel notch (measured through
    /// Qt: 1 unit = angleDelta 12, fractions work). `finish` ends a gesture. KWin delivers the portal's vertical axis
    /// the other way round from its horizontal one, so `dy` is negated here (measured: +dy arrived as "up").
    /// Earlier "unreliable" smooth scrolling was this sign.
    pub async fn axis(&self, dx: f64, dy: f64, finish: bool) -> anyhow::Result<()> {
        self.rd.notify_pointer_axis(&self.session, dx, -dy, NotifyPointerAxisOptions::default().set_finish(finish)).await?;
        Ok(())
    }

    /// End the portal session.
    pub async fn close(self) {
        let _ = self.session.close().await;
    }
}
