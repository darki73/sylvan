//! Stylus extractor.
//!
//! Stylus has no tree-sitter grammar in the language pack, so this is a
//! pure-regex extractor. It mirrors `extract_stylus_extras` in the
//! Python `stylesheet_extractor` module: function-style declarations
//! (`name(args)` on their own line) come out as `function` symbols and
//! bare `name = value` lines come out as `constant` symbols, with a
//! small keyword blocklist so CSS keywords like `block`, `flex`, and
//! `auto` do not get mistaken for Stylus variables.

use std::collections::HashSet;
use std::sync::OnceLock;

use fancy_regex::Regex;
use once_cell::sync::Lazy;
use sylvan_core::{
    ExtractionContext, ExtractionError, Import, LanguageExtractor, Symbol, make_symbol_id,
};

use crate::enrichment::{content_hash, extract_keywords, heuristic_summary};

static FUNC_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?m)^([\w-]+)\(([^)]*)\)\s*$").expect("stylus func regex compiles")
});

static VAR_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?m)^([\w-]+)\s*=\s*(.+)$").expect("stylus var regex compiles")
});

static STYLUS_IMPORT_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r#"(?m)^\s*@(?:import|require)\s+["']([^"']+)["']\s*$"#)
        .expect("stylus @import regex compiles")
});

fn keywords() -> &'static HashSet<&'static str> {
    static SET: OnceLock<HashSet<&'static str>> = OnceLock::new();
    SET.get_or_init(|| {
        [
            "if", "else", "for", "in", "return", "unless", "true", "false", "null", "not", "and",
            "or", "is", "isnt", "inherit", "initial", "unset", "none", "auto", "normal", "block",
            "inline", "flex", "grid", "absolute", "relative", "fixed", "sticky", "hidden",
            "visible", "solid", "dashed", "dotted", "transparent",
        ]
        .into_iter()
        .collect()
    })
}

fn line_number(source: &str, byte_pos: usize) -> u32 {
    let up_to = &source[..byte_pos.min(source.len())];
    (up_to.bytes().filter(|b| *b == b'\n').count() + 1) as u32
}

/// Built-in Stylus extractor.
pub struct StylusExtractor;

impl StylusExtractor {
    /// Construct a fresh instance. Stateless; there is no grammar to
    /// lazily load.
    pub fn new() -> Self {
        Self
    }
}

impl Default for StylusExtractor {
    fn default() -> Self {
        Self::new()
    }
}

fn make_constant(
    name: &str,
    sig: &str,
    ctx: &ExtractionContext<'_>,
    start: usize,
    end: usize,
) -> Symbol {
    let body = &ctx.source_bytes[start..end];
    Symbol {
        symbol_id: make_symbol_id(ctx.filename, name, "constant"),
        name: name.to_string(),
        qualified_name: name.to_string(),
        kind: "constant".to_string(),
        language: "stylus".to_string(),
        signature: Some(sig.to_string()),
        docstring: None,
        summary: Some(heuristic_summary(None, Some(sig), name)),
        decorators: Vec::new(),
        keywords: extract_keywords(name, None, &[]),
        parent_symbol_id: None,
        line_start: Some(line_number(ctx.source, start)),
        line_end: Some(line_number(ctx.source, end)),
        byte_offset: start as u32,
        byte_length: (end - start) as u32,
        content_hash: Some(content_hash(body)),
        cyclomatic: 0,
        max_nesting: 0,
        param_count: 0,
    }
}

fn make_function(
    name: &str,
    sig: &str,
    ctx: &ExtractionContext<'_>,
    start: usize,
    end: usize,
) -> Symbol {
    let body = &ctx.source_bytes[start..end];
    Symbol {
        symbol_id: make_symbol_id(ctx.filename, name, "function"),
        name: name.to_string(),
        qualified_name: name.to_string(),
        kind: "function".to_string(),
        language: "stylus".to_string(),
        signature: Some(sig.to_string()),
        docstring: None,
        summary: Some(heuristic_summary(None, Some(sig), name)),
        decorators: Vec::new(),
        keywords: extract_keywords(name, None, &[]),
        parent_symbol_id: None,
        line_start: Some(line_number(ctx.source, start)),
        line_end: Some(line_number(ctx.source, start)),
        byte_offset: start as u32,
        byte_length: (end - start) as u32,
        content_hash: Some(content_hash(body)),
        cyclomatic: 0,
        max_nesting: 0,
        param_count: 0,
    }
}

impl LanguageExtractor for StylusExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["stylus"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        let mut symbols: Vec<Symbol> = Vec::new();
        let mut seen: HashSet<String> = HashSet::new();
        let kws = keywords();

        for m in FUNC_RE.captures_iter(ctx.source).flatten() {
            let Some(name_m) = m.get(1) else { continue };
            let Some(params_m) = m.get(2) else { continue };
            let name = name_m.as_str();
            if kws.contains(name) || name.starts_with(['-', '.', '#', '@']) || seen.contains(name) {
                continue;
            }
            seen.insert(name.to_string());
            let sig = format!("{}({})", name, params_m.as_str());
            let whole = m.get(0).unwrap();
            symbols.push(make_function(name, &sig, ctx, whole.start(), whole.end()));
        }

        for m in VAR_RE.captures_iter(ctx.source).flatten() {
            let Some(name_m) = m.get(1) else { continue };
            let Some(value_m) = m.get(2) else { continue };
            let name = name_m.as_str();
            if kws.contains(name) || name.starts_with(['-', '.', '#', '@']) || seen.contains(name) {
                continue;
            }
            if name.contains('(') || name.contains('{') {
                continue;
            }
            let value = value_m.as_str().trim();
            seen.insert(name.to_string());
            let sig = format!("{} = {}", name, value);
            let whole = m.get(0).unwrap();
            symbols.push(make_constant(name, &sig, ctx, whole.start(), whole.end()));
        }

        Ok(symbols)
    }

    fn supports_imports(&self) -> bool {
        true
    }

    fn extract_imports(
        &self,
        ctx: &ExtractionContext<'_>,
    ) -> Result<Vec<Import>, ExtractionError> {
        let mut out: Vec<Import> = Vec::new();
        for m in STYLUS_IMPORT_RE.captures_iter(ctx.source).flatten() {
            let Some(spec) = m.get(1) else { continue };
            out.push(Import {
                specifier: spec.as_str().to_string(),
                names: Vec::new(),
            });
        }
        Ok(out)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        StylusExtractor::new()
            .extract(&ExtractionContext::new(source, "style.styl", "stylus"))
            .expect("stylus extraction")
    }

    fn imports(source: &str) -> Vec<Import> {
        StylusExtractor::new()
            .extract_imports(&ExtractionContext::new(source, "style.styl", "stylus"))
            .expect("stylus imports")
    }

    #[test]
    fn empty_file_yields_no_imports() {
        assert!(imports("").is_empty());
    }

    #[test]
    fn basic_import_has_no_names() {
        let imps = imports("@import \"a\"\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "a");
        assert!(imps[0].names.is_empty());
    }

    #[test]
    fn require_directive_captures_specifier() {
        let imps = imports("@require \"a\"\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "a");
        assert!(imps[0].names.is_empty());
    }

    #[test]
    fn multiple_imports_preserve_order() {
        let imps = imports("@import \"a\"\n@require \"b\"\n");
        assert_eq!(imps.len(), 2);
        assert_eq!(imps[0].specifier, "a");
        assert_eq!(imps[1].specifier, "b");
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_function_declaration() {
        let syms = extract("add(a, b)\n  a + b\n");
        assert!(syms.iter().any(|s| s.name == "add" && s.kind == "function"));
    }

    #[test]
    fn extracts_variable_assignment() {
        let syms = extract("primary = #f00\n");
        assert!(syms
            .iter()
            .any(|s| s.name == "primary" && s.kind == "constant"));
    }

    #[test]
    fn skips_css_keywords() {
        let syms = extract("auto = 1\nnone = 2\nblock = 3\n");
        assert!(syms.is_empty());
    }

    #[test]
    fn skips_sigil_prefixed_names() {
        let syms = extract(".foo = 1\n@bar = 2\n-baz = 3\n");
        assert!(syms.is_empty());
    }

    #[test]
    fn advertises_stylus_language() {
        assert_eq!(StylusExtractor::new().languages(), &["stylus"]);
    }
}
