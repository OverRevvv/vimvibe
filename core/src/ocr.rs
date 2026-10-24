//! OCR fallback: label what is on screen when an app exposes nothing to accessibility (Spotify, games, Electron
//! apps started without the flag, remote desktops...).
//!
//! The screen is captured with `spectacle`, `tesseract` reads it, and every phrase it finds becomes a clickable
//! element at that spot. Both are external programs, so vimvibe adds no build dependency and the layer simply
//! stays off when either is missing (`available()`), leaving the mouse grid as the last resort.

use crate::model::Element;
use std::time::Duration;

/// Default smallest OCR confidence (0-100) a word needs to be kept (`[ocr] min_confidence`); below this tesseract is
/// mostly reading icons and noise.
pub const MIN_CONF: f32 = 55.0;

/// One word tesseract found, in screenshot pixels.
#[derive(Debug, Clone, PartialEq)]
struct Word {
    /// Tesseract's (block, paragraph, line) numbers: words only merge into a phrase within the same line.
    line: (u32, u32, u32),
    text: String,
    x: i32,
    y: i32,
    w: i32,
    h: i32,
}

/// True when both helper programs can be started, so callers can skip the layer instead of failing at use.
pub fn available() -> bool {
    on_path("spectacle") && on_path("tesseract")
}

/// Whether `name` is an executable in one of the `PATH` directories.
fn on_path(name: &str) -> bool {
    std::env::var_os("PATH").is_some_and(|p| std::env::split_paths(&p).any(|d| d.join(name).is_file()))
}

/// Parse tesseract's TSV output into words. Only word rows (level 5) with at least `min_conf` confidence and some
/// text are kept; malformed lines are skipped rather than failing the whole read.
fn parse_tsv(tsv: &str, min_conf: f32) -> Vec<Word> {
    tsv.lines()
        .filter_map(|l| {
            let c: Vec<&str> = l.splitn(12, '\t').collect();
            if c.len() < 12 || c[0] != "5" {
                return None;
            }
            let text = c[11].trim();
            let conf: f32 = c[10].parse().ok()?;
            if text.is_empty() || conf < min_conf || !text.chars().any(|ch| ch.is_alphanumeric()) {
                return None;
            }
            Some(Word {
                line: (c[2].parse().ok()?, c[3].parse().ok()?, c[4].parse().ok()?),
                text: text.to_string(),
                x: c[6].parse().ok()?,
                y: c[7].parse().ok()?,
                w: c[8].parse().ok()?,
                h: c[9].parse().ok()?,
            })
        })
        .collect()
}

/// Join neighbouring words of one line into phrases ("Liked Songs" is one target, not two): a word joins the previous
/// one when the gap between them is smaller than the text height, which is wider than a space but narrower than the
/// gap between separate buttons.
fn merge_phrases(words: Vec<Word>) -> Vec<Word> {
    let mut out: Vec<Word> = Vec::new();
    for w in words {
        match out.last_mut() {
            Some(p) if p.line == w.line && w.x - (p.x + p.w) < p.h.max(w.h) => {
                let bottom = (p.y + p.h).max(w.y + w.h);
                p.y = p.y.min(w.y);
                p.h = bottom - p.y;
                p.w = w.x + w.w - p.x;
                p.text.push(' ');
                p.text.push_str(&w.text);
            }
            _ => out.push(w),
        }
    }
    out
}

/// Turn phrases into elements positioned relative to the window `win` (x, y, w, h in screen coordinates). `scale` is
/// screenshot pixels per screen coordinate (2.0 on a 200% display). Phrases outside the window are dropped.
fn to_elements(phrases: Vec<Word>, win: (i32, i32, i32, i32), scale: f64, app: &str, title: &str) -> Vec<Element> {
    let s = |v: i32| (v as f64 / scale).round() as i32;
    phrases
        .into_iter()
        .filter_map(|p| {
            let (x, y, w, h) = (s(p.x), s(p.y), s(p.w).max(1), s(p.h).max(1));
            let (cx, cy) = (x + w / 2, y + h / 2);
            if cx < win.0 || cy < win.1 || cx >= win.0 + win.2 || cy >= win.1 + win.3 {
                return None;
            }
            Some(Element {
                app: app.to_string(),
                window: title.to_string(),
                role: "Label".into(),
                name: p.text,
                rect: (x - win.0, y - win.1, w, h),
                enabled: true,
                ..Default::default()
            })
        })
        .collect()
}

/// Width in pixels of a PNG, read from its header (so no image library is needed).
fn png_width(bytes: &[u8]) -> Option<u32> {
    (bytes.len() > 24 && &bytes[1..4] == b"PNG").then(|| u32::from_be_bytes([bytes[16], bytes[17], bytes[18], bytes[19]]))
}

/// A fresh path for a screenshot in the user's runtime directory (private to the user, in memory on most systems).
pub fn shot_path(tag: &str) -> std::path::PathBuf {
    let dir = std::env::var_os("XDG_RUNTIME_DIR").map(std::path::PathBuf::from).unwrap_or_else(std::env::temp_dir);
    dir.join(format!("vimvibe-{tag}-{}.png", std::process::id()))
}

/// Take a screenshot of the whole screen into `png` with spectacle (no window, no notification).
pub async fn screenshot(png: &std::path::Path) -> anyhow::Result<()> {
    let shot = tokio::process::Command::new("spectacle").args(["-b", "-f", "-n", "-o"]).arg(png).output().await?;
    anyhow::ensure!(shot.status.success(), "spectacle failed");
    Ok(())
}

/// Read the words of a screenshot with tesseract. Returns the words (in screenshot pixels) and the display scale
/// (screenshot pixels per screen coordinate, from `screen_w`, the logical width of the screenshot's area).
async fn recognize(png: &std::path::Path, screen_w: Option<i32>, opts: &crate::config::Ocr) -> anyhow::Result<(Vec<Word>, f64)> {
    let scale = match (screen_w, png_width(&std::fs::read(png)?)) {
        (Some(sw), Some(pw)) if sw > 0 => pw as f64 / sw as f64,
        _ => 1.0,
    };
    let out = tokio::process::Command::new("tesseract").arg(png).args(["stdout", "-l", &opts.lang, "--psm", "11", "tsv"]).output().await?;
    anyhow::ensure!(out.status.success(), "tesseract failed");
    Ok((parse_tsv(&String::from_utf8_lossy(&out.stdout), opts.min_confidence), scale))
}

/// Run `work` with the OCR time limit, then delete the screenshot whatever happened: it can show private content and
/// must never be left behind.
async fn limited<T>(png: &std::path::Path, opts: &crate::config::Ocr, work: impl std::future::Future<Output = anyhow::Result<T>>) -> anyhow::Result<T> {
    let limit = Duration::from_millis(opts.timeout_ms.max(500));
    let res = tokio::time::timeout(limit, work).await.map_err(|_| anyhow::anyhow!("OCR took longer than {limit:?}"));
    let _ = std::fs::remove_file(png);
    res?
}

/// Capture the screen, read it and return one element per phrase inside `win`. `screen_w` is the logical width of
/// the screenshot's area, used to work out the display scale; `opts` gives the language, confidence and time limit.
/// Errors when a helper fails or takes longer than the limit.
pub async fn read_window(win: (i32, i32, i32, i32), screen_w: Option<i32>, app: &str, title: &str, opts: &crate::config::Ocr) -> anyhow::Result<Vec<Element>> {
    let png = shot_path("ocr");
    limited(&png, opts, async {
        screenshot(&png).await?;
        let (words, scale) = recognize(&png, screen_w, opts).await?;
        Ok(to_elements(merge_phrases(words), win, scale, app, title))
    })
    .await
}

/// Text mode: read the words of a screenshot already taken into `png` (see `screenshot`) and return them as JSON in
/// screen coordinates, one entry per word with its tesseract line ("block.paragraph.line"), so the overlay can
/// rebuild the text exactly where it is on screen. The screenshot is deleted afterwards.
pub async fn read_words(png: &std::path::Path, screen_w: Option<i32>, opts: &crate::config::Ocr) -> anyhow::Result<serde_json::Value> {
    limited(png, opts, async {
        let (words, scale) = recognize(png, screen_w, opts).await?;
        Ok(words_json(&words, scale))
    })
    .await
}

/// Words as JSON for the overlay: pixels divided by the display scale, the line as "block.paragraph.line".
fn words_json(words: &[Word], scale: f64) -> serde_json::Value {
    let s = |v: i32| (v as f64 / scale).round() as i32;
    serde_json::Value::Array(
        words
            .iter()
            .map(|w| serde_json::json!({"text": w.text, "x": s(w.x), "y": s(w.y), "w": s(w.w).max(1), "h": s(w.h).max(1),
                                        "line": format!("{}.{}.{}", w.line.0, w.line.1, w.line.2)}))
            .collect(),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A TSV row in tesseract's column order for a word.
    fn row(line: u32, conf: &str, x: i32, text: &str) -> String {
        format!("5\t1\t1\t1\t{line}\t1\t{x}\t10\t40\t12\t{conf}\t{text}")
    }

    #[test]
    fn parse_keeps_confident_words_only() {
        let tsv = format!("level\tpage\n{}\n{}\n{}\n1\t1\t0\t0\t0\t0\t0\t0\t9\t9\t-1\t", row(1, "90", 5, "Home"), row(1, "20", 60, "xx"), row(1, "95", 70, "--"));
        let w = parse_tsv(&tsv, MIN_CONF);
        assert_eq!(w.len(), 1);
        assert_eq!(w[0].text, "Home");
    }

    #[test]
    fn close_words_merge_far_words_do_not() {
        let tsv = [row(1, "90", 10, "Liked"), row(1, "90", 55, "Songs"), row(1, "90", 300, "Search")].join("\n");
        let p = merge_phrases(parse_tsv(&tsv, MIN_CONF));
        assert_eq!(p.iter().map(|w| w.text.as_str()).collect::<Vec<_>>(), ["Liked Songs", "Search"]);
        assert_eq!(p[0].w, 85); // 10 .. 95
    }

    #[test]
    fn elements_are_window_relative_and_clipped() {
        let tsv = [row(1, "90", 110, "In"), row(1, "90", 900, "Out")].join("\n");
        let els = to_elements(merge_phrases(parse_tsv(&tsv, MIN_CONF)), (100, 0, 200, 100), 1.0, "app", "t");
        assert_eq!(els.len(), 1);
        assert_eq!(els[0].rect.0, 10);
        assert_eq!(els[0].name, "In");
    }

    #[test]
    fn words_json_keeps_lines_and_scales() {
        let tsv = [row(3, "90", 200, "Hi"), row(4, "90", 40, "there")].join("\n");
        let v = words_json(&parse_tsv(&tsv, MIN_CONF), 2.0);
        assert_eq!(v[0]["x"], 100);
        assert_eq!(v[0]["line"], "1.1.3");
        assert_eq!(v[1]["text"], "there");
    }

    #[test]
    fn scale_divides_pixels() {
        let tsv = row(1, "90", 200, "Hi");
        let els = to_elements(parse_tsv(&tsv, MIN_CONF), (0, 0, 500, 500), 2.0, "a", "t");
        assert_eq!(els[0].rect.0, 100);
    }
}
