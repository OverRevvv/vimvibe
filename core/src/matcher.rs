use crate::model::Element;
use nucleo_matcher::pattern::{CaseMatching, Normalization, Pattern};
use nucleo_matcher::{Config, Matcher, Utf32Str};

pub struct Hit<'a> {
    pub score: i64,
    pub el: &'a Element,
}

/// Query words that name an element type, mapped to AT-SPI role names (Shortcat-style role words).
fn role_alias(word: &str) -> Option<&'static [&'static str]> {
    Some(match word {
        "button" | "btn" => &["Button", "ToggleButton", "PushButtonMenu"],
        "link" => &["Link"],
        "check" | "checkbox" => &["CheckBox", "CheckMenuItem"],
        "switch" => &["Switch", "ToggleButton"],
        "radio" => &["RadioButton", "RadioMenuItem"],
        "menu" => &["MenuItem", "CheckMenuItem", "RadioMenuItem"],
        "tab" => &["PageTab"],
        "field" | "entry" | "input" | "textfield" => &["Entry", "PasswordText"],
        "list" | "item" => &["ListItem", "TreeItem"],
        "combo" | "dropdown" => &["ComboBox"],
        "slider" => &["Slider"],
        "spin" | "spinner" => &["SpinButton"],
        _ => return None,
    })
}

const SYNONYMS: &[&[&str]] = &[
    &["delete", "remove", "clear", "destroy", "trash"],
    &["close", "quit", "exit"],
    &["ok", "confirm", "accept", "apply", "done"],
    &["cancel", "dismiss", "abort"],
    &["settings", "preferences", "options", "configure"],
    &["new", "create", "add"],
    &["open", "load"],
    &["save", "store"],
    &["find", "search"],
];

/// The query plus its synonym expansions ("remove" also searches "delete", ...); the first entry is the literal query.
fn variants(text: &str) -> Vec<String> {
    let mut v = vec![text.to_string()];
    if let Some(group) = SYNONYMS.iter().find(|g| g.contains(&text)) {
        v.extend(group.iter().filter(|s| **s != text).map(|s| s.to_string()));
    }
    v
}

/// Fuzzy score of `pat` against `hay`, None when it doesn't match.
fn score(matcher: &mut Matcher, buf: &mut Vec<char>, pat: &Pattern, hay: &str) -> Option<u32> {
    pat.score(Utf32Str::new(hay, buf), matcher)
}

/// Score every element (restricted to `roles` when given): fuzzy name match, description substring, bonuses for
/// exact/prefix and short names, a heavy penalty for disabled elements.
fn run<'a>(els: &'a [Element], roles: &[&str], text: &str) -> Vec<Hit<'a>> {
    let mut matcher = Matcher::new(Config::DEFAULT);
    let mut buf = Vec::new();
    let pats: Vec<Pattern> = variants(text).iter().map(|t| Pattern::parse(t, CaseMatching::Ignore, Normalization::Smart)).collect();
    let lower = text.to_lowercase();
    let mut hits = vec![];
    for el in els {
        if !roles.is_empty() && !roles.contains(&el.role.as_str()) {
            continue;
        }
        if text.is_empty() {
            hits.push(Hit { score: 0, el });
            continue;
        }
        let mut best: Option<i64> = None;
        for (i, p) in pats.iter().enumerate() {
            let penalty = if i == 0 { 0 } else { 15 }; // synonym matches rank slightly below literal ones
            if let Some(s) = score(&mut matcher, &mut buf, p, &el.name) {
                best = best.max(Some(s as i64 - penalty));
            } else if i == 0 && !lower.is_empty() && el.description.to_lowercase().contains(&lower) {
                best = best.max(Some(40)); // description is a weaker signal: substring only, fuzzy is too loose on long text
            }
        }
        let Some(mut s) = best else { continue };
        let name = el.name.to_lowercase();
        s -= name.chars().count() as i64; // shorter labels rank higher
        if name == lower {
            s += 200;
        } else if name.starts_with(&lower) {
            s += 50;
        }
        if !el.enabled {
            s -= 500;
        }
        hits.push(Hit { score: s, el });
    }
    hits
}

/// Search entry point: split role words (`btn`, `link`, ...) from text, score, and sort (empty query: reading order).
pub fn search<'a>(els: &'a [Element], query: &str, limit: usize) -> Vec<Hit<'a>> {
    let words: Vec<String> = query.split_whitespace().map(|w| w.to_lowercase()).collect();
    let mut roles: Vec<&str> = vec![];
    let mut rest: Vec<&str> = vec![];
    for w in &words {
        match role_alias(w) {
            Some(r) => roles.extend(r),
            None => rest.push(w),
        }
    }
    let text = rest.join(" ");
    let mut hits = run(els, &roles, &text);
    if hits.is_empty() && !roles.is_empty() {
        hits = run(els, &[], &words.join(" ")); // role word was part of the label, e.g. "Voice button"
    }
    if text.is_empty() {
        hits.sort_by_key(|h| (h.el.rect.1, h.el.rect.0));
    } else {
        hits.sort_by(|a, b| b.score.cmp(&a.score).then_with(|| (a.el.rect.1, a.el.rect.0).cmp(&(b.el.rect.1, b.el.rect.0))));
    }
    hits.truncate(limit);
    hits
}

#[cfg(test)]
mod tests {
    use super::*;

    fn el(role: &str, name: &str) -> Element {
        Element {
            app: "t".into(), window: "w".into(), role: role.into(), name: name.into(), description: String::new(),
            actions: vec!["Press".into()], rect: (0, 0, 10, 10), enabled: true, object: None,
        }
    }

    fn names(h: &[Hit]) -> Vec<String> {
        h.iter().map(|h| h.el.name.clone()).collect()
    }

    #[test]
    fn fuzzy_and_prefix() {
        let els = vec![el("Button", "Save As"), el("Button", "Save"), el("MenuItem", "Select all")];
        let h = search(&els, "sav", 10);
        assert_eq!(names(&h)[0], "Save"); // shorter + prefix wins
    }

    #[test]
    fn role_word_filters() {
        let els = vec![el("Link", "Patna"), el("Button", "Patna map")];
        let h = search(&els, "patna link", 10);
        assert_eq!(names(&h), vec!["Patna"]);
        let h = search(&els, "btn patna", 10);
        assert_eq!(names(&h), vec!["Patna map"]);
    }

    #[test]
    fn role_word_fallback_when_part_of_label() {
        let els = vec![el("Button", "Voice button")];
        assert_eq!(names(&search(&els, "voice button", 10)), vec!["Voice button"]);
    }

    #[test]
    fn synonyms() {
        let els = vec![el("Button", "Remove"), el("Button", "Rename")];
        let h = search(&els, "delete", 10);
        assert_eq!(names(&h), vec!["Remove"]);
    }

    #[test]
    fn description_needs_substring() {
        let mut a = el("Button", ")");
        a.description = "Close parenthesis".into();
        let mut b = el("Button", "X");
        b.description = "Clear everything".into();
        let els = vec![a, b];
        assert_eq!(names(&search(&els, "clear", 10)), vec!["X"]);
    }

    #[test]
    fn disabled_ranks_last() {
        let mut a = el("Button", "Copy");
        a.enabled = false;
        let els = vec![a, el("Button", "Copy path")];
        assert_eq!(names(&search(&els, "copy", 10))[0], "Copy path");
    }

    #[test]
    fn empty_query_orders_by_position() {
        let mut a = el("Button", "B");
        a.rect = (0, 50, 1, 1);
        let mut b = el("Button", "A");
        b.rect = (0, 10, 1, 1);
        assert_eq!(names(&search(&[a, b], "", 10)), vec!["A", "B"]);
    }
}
