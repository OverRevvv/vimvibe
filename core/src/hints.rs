//! Letter hints ("shortcuts") for every element, Shortcat-style: a short uppercase label derived from the element's
//! name where possible ("Pull requests" → PR, "Projects" → PR or PRO, "Changelog" → CH), unique within the snapshot.
//!
//! Hints are 2–3 characters. Single letters are not used: the hint is typed into the same field as the search, and a
//! single letter would hijack every one-letter query. Assignment runs in reading order (top to bottom, left to right) so
//! the elements near the top get the most natural labels, and it is deterministic, so the same window gets the same
//! labels on every trigger.

use crate::model::Element;
use std::collections::HashSet;

const ALPHA: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZ";

/// Upper-case ASCII alphanumeric words of a name. Non-ASCII letters are folded where trivial (é → E) and dropped otherwise.
fn words(name: &str) -> Vec<Vec<u8>> {
    let mut out = vec![];
    let mut cur = vec![];
    for ch in name.chars() {
        let c = fold(ch);
        match c {
            Some(c) if c.is_ascii_alphanumeric() => cur.push(c.to_ascii_uppercase() as u8),
            _ => {
                if !cur.is_empty() {
                    out.push(std::mem::take(&mut cur));
                }
            }
        }
    }
    if !cur.is_empty() {
        out.push(cur);
    }
    out
}

/// Fold common accented Latin letters to ASCII so names like "Éditer" still give letter hints.
fn fold(c: char) -> Option<char> {
    if c.is_ascii() {
        return Some(c);
    }
    Some(match c {
        'à' | 'á' | 'â' | 'ã' | 'ä' | 'å' | 'À' | 'Á' | 'Â' | 'Ã' | 'Ä' | 'Å' => 'a',
        'è' | 'é' | 'ê' | 'ë' | 'È' | 'É' | 'Ê' | 'Ë' => 'e',
        'ì' | 'í' | 'î' | 'ï' | 'Ì' | 'Í' | 'Î' | 'Ï' => 'i',
        'ò' | 'ó' | 'ô' | 'õ' | 'ö' | 'ø' | 'Ò' | 'Ó' | 'Ô' | 'Õ' | 'Ö' | 'Ø' => 'o',
        'ù' | 'ú' | 'û' | 'ü' | 'Ù' | 'Ú' | 'Û' | 'Ü' => 'u',
        'ç' | 'Ç' => 'c',
        'ñ' | 'Ñ' => 'n',
        'ß' => 's',
        _ => return None,
    })
}

/// Mnemonic candidates for a name, best first.
fn candidates(name: &str) -> Vec<String> {
    let ws = words(name);
    let mut c: Vec<Vec<u8>> = vec![];
    if let Some(w0) = ws.first() {
        if let Some(w1) = ws.get(1) {
            c.push(vec![w0[0], w1[0]]); // initials: Pull requests → PR
        }
        if w0.len() >= 2 {
            c.push(w0[..2].to_vec()); // prefix: Changelog → CH
        }
        if w0.len() >= 3 {
            c.push(w0[..3].to_vec()); // longer prefix: Projects → PRO
        }
        if let (Some(w1), Some(w2)) = (ws.get(1), ws.get(2)) {
            c.push(vec![w0[0], w1[0], w2[0]]); // three initials
        }
        for &b in w0.iter().skip(2) {
            c.push(vec![w0[0], b]); // first letter + a later letter of the first word: Changelog → CA, CN, CG…
        }
        for w in ws.iter().skip(2) {
            c.push(vec![w0[0], w[0]]); // first letter + a later word's initial
        }
        if let Some(w1) = ws.get(1) {
            if w1.len() >= 2 {
                c.push(vec![w0[0], w1[0], w1[1]]);
            }
            if w0.len() >= 2 {
                c.push(vec![w0[0], w0[1], w1[0]]);
            }
        }
        for &b in ALPHA {
            c.push(vec![w0[0], b]); // last resort that still starts with the name's first letter
        }
    }
    c.into_iter().filter(|v| v.len() >= 2).map(|v| String::from_utf8(v).unwrap_or_default()).collect()
}

/// One unique hint per element (same order as `els`).
pub fn assign(els: &[Element]) -> Vec<String> {
    let mut order: Vec<usize> = (0..els.len()).collect();
    // reading order; rows bucketed so elements on one visual line count as one row
    order.sort_by_key(|&i| (els[i].rect.1.div_euclid(12), els[i].rect.0));
    let mut used: HashSet<String> = HashSet::new();
    let mut out = vec![String::new(); els.len()];
    let mut unnamed = vec![];
    for &i in &order {
        // "(unlabeled button)" is a placeholder the enumerator gives nameless elements, not a name to take letters from
        let name = if els[i].name.starts_with("(unlabeled ") { "" } else { els[i].name.as_str() };
        let pick = candidates(name).into_iter().find(|h| !used.contains(h));
        match pick {
            Some(h) => {
                used.insert(h.clone());
                out[i] = h;
            }
            None => unnamed.push(i),
        }
    }
    // elements with no usable name (or every mnemonic taken): free two-letter combos, then three
    let mut free = ALPHA.iter().flat_map(|&a| ALPHA.iter().map(move |&b| format!("{}{}", a as char, b as char))).chain(
        ALPHA.iter().flat_map(|&a| ALPHA.iter().flat_map(move |&b| ALPHA.iter().map(move |&c| format!("{}{}{}", a as char, b as char, c as char)))),
    );
    for i in unnamed {
        if let Some(h) = free.by_ref().find(|h| !used.contains(h)) {
            used.insert(h.clone());
            out[i] = h;
        }
    }
    out
}

/// The typed query, if it is shaped like a hint (2–3 letters/digits, spaces ignored), upper-cased.
pub fn as_hint(query: &str) -> Option<String> {
    let q: String = query.chars().filter(|c| !c.is_whitespace()).collect();
    (2..=3).contains(&q.len()).then(|| q.to_ascii_uppercase()).filter(|q| q.bytes().all(|b| b.is_ascii_alphanumeric()))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn el(name: &str, x: i32, y: i32) -> Element {
        Element { name: name.into(), rect: (x, y, 10, 10), enabled: true, ..Default::default() }
    }

    #[test]
    fn mnemonics_and_uniqueness() {
        let els = vec![el("Pull requests", 0, 0), el("Projects", 50, 0), el("Changelog", 100, 0), el("", 0, 50), el("(unlabeled entry)", 10, 50), el("Projects 2", 0, 100)];
        let h = assign(&els);
        assert_eq!(h[0], "PR");
        assert_eq!(h[1], "PRO");
        assert_eq!(h[2], "CH");
        assert_eq!(h[5], "P2");
        assert_eq!((h[3].as_str(), h[4].as_str()), ("AA", "AB"), "nameless elements get free combos, not letters from the placeholder");
        let set: HashSet<_> = h.iter().collect();
        assert_eq!(set.len(), h.len(), "hints must be unique: {h:?}");
        assert!(h.iter().all(|s| (2..=3).contains(&s.len())));
    }

    #[test]
    fn many_elements_all_get_hints() {
        let els: Vec<Element> = (0..1500).map(|i| el(if i % 3 == 0 { "" } else { "Item" }, i % 40, i / 40)).collect();
        let h = assign(&els);
        assert!(h.iter().all(|s| !s.is_empty()));
        assert_eq!(h.iter().collect::<HashSet<_>>().len(), h.len());
    }

    #[test]
    fn hint_shaped_queries() {
        assert_eq!(as_hint("pr"), Some("PR".into()));
        assert_eq!(as_hint("p"), None);
        assert_eq!(as_hint("save"), None);
        assert_eq!(as_hint("p 2"), Some("P2".into()));
    }
}

#[cfg(test)]
mod bench {
    use super::*;
    #[test]
    fn assign_10k_is_fast() {
        let names = ["Pull requests", "Issues", "Code", "Actions", "", "Settings", "Item 12", "Changelog", "Explore all"];
        let els: Vec<Element> = (0..10_000)
            .map(|i| Element { name: format!("{} {}", names[i % names.len()], i / 7), rect: ((i % 50) as i32 * 20, (i / 50) as i32 * 12, 10, 10), ..Default::default() })
            .collect();
        let t = std::time::Instant::now();
        let h = assign(&els);
        eprintln!("assign 10k: {:?}", t.elapsed());
        assert_eq!(h.iter().collect::<HashSet<_>>().len(), h.len());
    }
}
