//! Post-extraction symbol enrichment.
//!
//! Ports `sylvan.indexing.source_code.symbol_enrichment` to Rust:
//! heuristic summaries, keyword extraction, content hashing, overload
//! disambiguation. The extraction pipeline calls these inline on every
//! symbol so Python callers never have to do the per-symbol work.

use std::collections::{HashMap, HashSet};
use std::sync::OnceLock;

use fancy_regex::Regex;
use sha2::{Digest, Sha256};
use sylvan_core::Symbol;

/// Hex-encoded SHA-256 of the symbol's source bytes.
pub fn content_hash(source_bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(source_bytes);
    let digest = hasher.finalize();
    let mut out = String::with_capacity(digest.len() * 2);
    for byte in digest.iter() {
        out.push_str(&format!("{byte:02x}"));
    }
    out
}

/// One-line summary from docstring, signature, or name (in that order).
///
/// Preserves the Python heuristic: first sentence of the first line if
/// there is a period within the first 120 characters, else the first
/// 120 characters of the first line; then the signature trimmed to
/// 120, then the raw name.
pub fn heuristic_summary(docstring: Option<&str>, signature: Option<&str>, name: &str) -> String {
    if let Some(doc) = docstring {
        let first_line = doc.lines().next().unwrap_or("").trim();
        if !first_line.is_empty() {
            if let Some(dot) = first_line.find('.')
                && dot > 0
                && dot < 120
            {
                return first_line[..=dot].to_string();
            }
            return truncate_chars(first_line, 120);
        }
    }
    if let Some(sig) = signature
        && !sig.is_empty()
    {
        return truncate_chars(sig, 120);
    }
    name.to_string()
}

fn truncate_chars(s: &str, max_chars: usize) -> String {
    s.chars().take(max_chars).collect()
}

fn camel_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])").unwrap())
}

fn split_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"[_\-./]").unwrap())
}

fn docword_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"\b[a-z]{3,}\b").unwrap())
}

fn decorator_head_re() -> &'static Regex {
    static RE: OnceLock<Regex> = OnceLock::new();
    RE.get_or_init(|| Regex::new(r"@?(\w+)").unwrap())
}

/// Split a camelCase or snake_case identifier into lowercase tokens
/// (each at least two characters long).
pub fn split_identifier(name: &str) -> Vec<String> {
    let normalised = camel_re().replace_all(name, "_").to_string();
    let mut out = Vec::new();
    for part in split_re().split(&normalised) {
        let part = match part {
            Ok(p) => p,
            Err(_) => continue,
        };
        if part.chars().count() >= 2 {
            out.push(part.to_lowercase());
        }
    }
    out
}

/// Sorted, deduplicated keyword list from the symbol's name, docstring,
/// and decorators. Mirrors the Python contract exactly.
pub fn extract_keywords(name: &str, docstring: Option<&str>, decorators: &[String]) -> Vec<String> {
    let mut set: HashSet<String> = HashSet::new();
    for tok in split_identifier(name) {
        set.insert(tok);
    }
    if let Some(doc) = docstring {
        let first_line = doc.lines().next().unwrap_or("").to_lowercase();
        for mat in docword_re().find_iter(&first_line).flatten() {
            set.insert(mat.as_str().to_string());
        }
    }
    for dec in decorators {
        if let Ok(Some(captures)) = decorator_head_re().captures(dec)
            && let Some(g1) = captures.get(1)
        {
            set.insert(g1.as_str().to_lowercase());
        }
    }
    let mut out: Vec<String> = set.into_iter().collect();
    out.sort();
    out
}

/// Append `~N` suffixes to duplicate `symbol_id` strings in place.
///
/// Later occurrences of the same id become `id~1`, `id~2`, ... — keeps
/// the first one untouched so stable cross-run references keep working
/// as long as nothing is reordered upstream.
pub fn disambiguate_overloads(symbols: &mut [Symbol]) {
    let mut seen: HashMap<String, u32> = HashMap::new();
    for sym in symbols.iter_mut() {
        let entry = seen.entry(sym.symbol_id.clone()).or_insert(0);
        if *entry > 0 {
            sym.symbol_id = format!("{}~{}", sym.symbol_id, entry);
        }
        *entry += 1;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hash_matches_python_sha256_hex() {
        assert_eq!(
            content_hash(b"hello"),
            "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
        );
    }

    #[test]
    fn summary_prefers_first_sentence_of_docstring() {
        let out = heuristic_summary(Some("Say hi. And more."), None, "greet");
        assert_eq!(out, "Say hi.");
    }

    #[test]
    fn summary_falls_back_to_signature_then_name() {
        assert_eq!(heuristic_summary(None, Some("(a, b)"), "add"), "(a, b)");
        assert_eq!(heuristic_summary(None, None, "add"), "add");
    }

    #[test]
    fn summary_truncates_long_docstring_to_120_chars() {
        let long = "a".repeat(200);
        assert_eq!(heuristic_summary(Some(&long), None, "x").len(), 120);
    }

    #[test]
    fn split_identifier_handles_camel_and_snake() {
        assert_eq!(split_identifier("MyHTTPClient"), vec!["my", "http", "client"]);
        assert_eq!(split_identifier("parse_file_v2"), vec!["parse", "file", "v2"]);
    }

    #[test]
    fn split_identifier_drops_single_char_fragments() {
        assert_eq!(split_identifier("aBcD"), vec!["bc"]);
        assert_eq!(split_identifier("a_b_c"), Vec::<String>::new());
    }

    #[test]
    fn keywords_merge_name_doc_decorators() {
        let kws = extract_keywords(
            "parse_file",
            Some("Parses the given file with care."),
            &["@staticmethod".to_string()],
        );
        assert!(kws.contains(&"parse".to_string()));
        assert!(kws.contains(&"file".to_string()));
        assert!(kws.contains(&"given".to_string()));
        assert!(kws.contains(&"staticmethod".to_string()));
        let mut sorted = kws.clone();
        sorted.sort();
        assert_eq!(kws, sorted, "keywords must be sorted");
    }

    #[test]
    fn keywords_ignore_short_doc_words() {
        let kws = extract_keywords("x", Some("a of to"), &[]);
        assert!(kws.iter().all(|k| k.len() >= 2));
    }

    #[test]
    fn disambiguate_appends_tilde_suffix_to_later_duplicates() {
        let mut symbols = vec![
            Symbol {
                symbol_id: "a".into(),
                ..Symbol::default()
            },
            Symbol {
                symbol_id: "a".into(),
                ..Symbol::default()
            },
            Symbol {
                symbol_id: "b".into(),
                ..Symbol::default()
            },
            Symbol {
                symbol_id: "a".into(),
                ..Symbol::default()
            },
        ];
        disambiguate_overloads(&mut symbols);
        assert_eq!(symbols[0].symbol_id, "a");
        assert_eq!(symbols[1].symbol_id, "a~1");
        assert_eq!(symbols[2].symbol_id, "b");
        assert_eq!(symbols[3].symbol_id, "a~2");
    }
}
