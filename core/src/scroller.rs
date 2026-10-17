//! The smooth-scroll engine: every scroll request adds to a distance still to travel, and a critically damped spring
//! (no overshoot, no sudden start) moves the content through it. Many small requests (a held key repeating) merge into
//! one continuous glide instead of a series of separate jumps, which is what makes it feel like a mouse wheel on a
//! smooth-scrolling browser rather than like key presses.
//!
//! Distances are in **units**: 1 unit = 1/10 of a mouse-wheel notch (what the portal's smooth axis calls one pixel;
//! measured: a notch is 10 units, i.e. 120 in Qt's angleDelta). A scroll step of "1 notch" is therefore 10 units.
//! The daemon calls [`Scroller::step`] about every 8 ms and sends what it returns as smooth axis events.

use std::sync::Mutex;
use tokio::sync::Notify;

/// Events are quantised to the smallest amount an app can tell apart (Qt: angleDelta in 1/12 unit).
const QUANTUM: f64 = 1.0 / 12.0;
/// Spring settling: after `settle_ms` the remaining distance is about 1 %.
const SETTLE_K: f64 = 6.6;

#[derive(Default)]
struct State {
    /// Distance still to travel (units), per axis: x right, y down.
    rx: f64,
    ry: f64,
    /// Current speed (units/s).
    vx: f64,
    vy: f64,
    /// Not yet sent because it is below one quantum.
    ox: f64,
    oy: f64,
    /// Time the glide takes to settle, ms (≤ 1 means jump).
    settle_ms: f64,
    busy: bool,
    emitted: bool,
}

#[derive(Default)]
pub struct Scroller {
    st: Mutex<State>,
    /// Wakes the scroll task when work arrives.
    pub wake: Notify,
}

/// What one tick produced.
pub struct Tick {
    pub dx: f64,
    pub dy: f64,
    /// The glide is over (send the gesture-finish event if anything was sent).
    pub done: bool,
    pub emitted: bool,
}

/// Advance one axis by `dt` seconds: returns the distance moved. Sub-stepped so a short settle time stays stable.
fn spring(r: &mut f64, v: &mut f64, w: f64, dt: f64) -> f64 {
    let n = ((w * dt / 0.2).ceil() as usize).max(1);
    let h = dt / n as f64;
    let mut moved = 0.0;
    for _ in 0..n {
        *v += (w * w * *r - 2.0 * w * *v) * h;
        let mut m = *v * h;
        if m.abs() > r.abs() && m.signum() == r.signum() {
            m = *r; // never past the target
            *v = 0.0;
        }
        *r -= m;
        moved += m;
    }
    moved
}

/// Round to whole quanta, keeping the remainder in `rest`.
fn quantise(rest: &mut f64, add: f64) -> f64 {
    *rest += add;
    let q = (*rest / QUANTUM).round() * QUANTUM;
    *rest -= q;
    q
}

impl Scroller {
    /// Add `dx`/`dy` units to the distance to travel, to be covered in about `settle_ms` (≤ 1: at once).
    pub fn add(&self, dx: f64, dy: f64, settle_ms: f64) {
        let mut s = self.st.lock().unwrap();
        s.rx += dx;
        s.ry += dy;
        s.settle_ms = settle_ms;
        s.busy = true;
        drop(s);
        self.wake.notify_one();
    }

    /// Whether a glide is still running.
    pub fn busy(&self) -> bool {
        self.st.lock().unwrap().busy
    }

    /// Abandon whatever is left (the portal session broke).
    pub fn clear(&self) {
        *self.st.lock().unwrap() = State::default();
    }

    /// Advance by `dt` seconds.
    pub fn step(&self, dt: f64) -> Tick {
        let mut s = self.st.lock().unwrap();
        if !s.busy {
            return Tick { dx: 0.0, dy: 0.0, done: true, emitted: false };
        }
        let (mut mx, mut my);
        if s.settle_ms <= 1.0 {
            (mx, my) = (s.rx, s.ry);
            (s.rx, s.ry, s.vx, s.vy) = (0.0, 0.0, 0.0, 0.0);
        } else {
            let w = SETTLE_K / (s.settle_ms / 1000.0);
            let st = &mut *s;
            mx = spring(&mut st.rx, &mut st.vx, w, dt);
            my = spring(&mut st.ry, &mut st.vy, w, dt);
        }
        let done = s.rx.abs() < 0.02 && s.ry.abs() < 0.02 && s.vx.abs() < 0.5 && s.vy.abs() < 0.5;
        if done {
            mx += s.rx;
            my += s.ry;
            (s.rx, s.ry, s.vx, s.vy) = (0.0, 0.0, 0.0, 0.0);
        }
        let (dx, dy) = (quantise(&mut s.ox, mx), quantise(&mut s.oy, my));
        s.emitted |= dx != 0.0 || dy != 0.0;
        let emitted = s.emitted;
        if done {
            s.busy = false;
            s.emitted = false;
            (s.ox, s.oy) = (0.0, 0.0);
        }
        Tick { dx, dy, done, emitted }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // Step the scroller in 8 ms ticks for `ms` milliseconds; returns the total distance and the tick count.
    fn run(s: &Scroller, ms: usize) -> (f64, f64, usize) {
        let (mut sx, mut sy, mut n) = (0.0, 0.0, 0);
        for _ in 0..ms / 8 {
            let t = s.step(0.008);
            sx += t.dx;
            sy += t.dy;
            n += (t.dx != 0.0 || t.dy != 0.0) as usize;
            if t.done {
                break;
            }
        }
        (sx, sy, n)
    }

    // A glide delivers exactly the requested distance, in steady steps.
    #[test]
    fn covers_the_whole_distance_smoothly() {
        let s = Scroller::default();
        s.add(0.0, 10.0, 220.0);
        let (x, y, n) = run(&s, 2000);
        assert!(x == 0.0 && (y - 10.0).abs() < 0.05, "{x} {y}");
        assert!(n > 15, "should arrive as many small events, got {n}");
        assert!(!s.busy());
    }

    // The glide never goes past the target and eases in.
    #[test]
    fn never_overshoots_and_starts_gently() {
        let s = Scroller::default();
        s.add(0.0, 100.0, 300.0);
        let first = s.step(0.008).dy;
        assert!(first < 5.0, "starts gently (under 5 % in the first tick): {first}");
        let mut total = first;
        for _ in 0..400 {
            let t = s.step(0.008);
            total += t.dy;
            assert!(total <= 100.05, "overshoot {total}");
            if t.done {
                break;
            }
        }
        assert!((total - 100.0).abs() < 0.05);
    }

    // Repeated key presses (a held key) add up to one glide with the exact total; a reversal then scrolls back the new distance.
    #[test]
    fn repeats_merge_into_one_glide_and_reversal_works() {
        let s = Scroller::default();
        let mut total = 0.0;
        for i in 0..20 {
            s.add(0.0, 10.0, 220.0); // a key held down, repeating every ~33 ms
            for _ in 0..4 {
                total += s.step(0.008).dy;
            }
            let _ = i;
        }
        while s.busy() {
            total += s.step(0.008).dy;
        }
        assert!((total - 200.0).abs() < 0.1, "{total}");
        s.add(0.0, -30.0, 220.0);
        let (_, y, _) = run(&s, 3000);
        assert!((y + 30.0).abs() < 0.05, "{y}");
    }

    // A jump to an edge is large and immediate; an idle scroller produces nothing.
    #[test]
    fn jump_and_idle() {
        let s = Scroller::default();
        let t = s.step(0.008);
        assert!(t.done && !t.emitted && t.dx == 0.0);
        s.add(5.0, -2.0, 0.0);
        let t = s.step(0.008);
        assert!(t.done && (t.dx - 5.0).abs() < 0.05 && (t.dy + 2.0).abs() < 0.05);
    }

    // A short glide lands exactly on its target distance.
    #[test]
    fn short_settle_is_stable() {
        let s = Scroller::default();
        s.add(0.0, 10.0, 20.0);
        let (_, y, _) = run(&s, 1000);
        assert!((y - 10.0).abs() < 0.05, "{y}");
    }
}
