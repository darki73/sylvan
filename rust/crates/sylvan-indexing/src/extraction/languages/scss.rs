//! SCSS extractor.
//!
//! Combines three passes:
//!
//! 1. The shared [`SpecExtractor`] with the SCSS grammar, which picks
//!    up `@mixin`, `@function`, `@keyframes`, `@include`, and
//!    `rule_set` selectors as top-level symbols.
//! 2. A regex pass for SCSS variables (`$name: value;`). Tree-sitter
//!    SCSS parks these inside generic `declaration` nodes that carry no
//!    labeled name, so a tiny regex is cheaper than a bespoke AST
//!    walk and matches the Python behaviour exactly.
//! 3. A nested-selector expansion walk: for any `rule_set` whose child
//!    `rule_set`s reference `&`, we emit an extra `class` symbol with
//!    the `&` resolved to the parent selector. Mirrors how BEM-style
//!    SCSS `.btn { &--primary {...} }` is normally searched.
//!
//! Names emitted by pass 2 have the leading `$` stripped so
//! cross-file lookups use the bare identifier.

use std::collections::HashSet;
use std::sync::OnceLock;

use fancy_regex::Regex;
use once_cell::sync::Lazy;
use sylvan_core::{
    ExtractionContext, ExtractionError, Import, LanguageExtractor, Symbol, make_symbol_id,
};
use tree_sitter::Node;

use crate::enrichment::{content_hash, extract_keywords, heuristic_summary};
use crate::extraction::spec::{
    ConstantStrategy, DecoratorStrategy, DocstringStrategy, LanguageSpec, NameResolution,
    SpecExtractor,
};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[
        ("mixin_statement", "function"),
        ("function_statement", "function"),
        ("keyframes_statement", "function"),
        ("rule_set", "type"),
        ("include_statement", "constant"),
    ],
    name_fields: &[
        ("mixin_statement", "name"),
        ("function_statement", "name"),
    ],
    name_resolutions: &[
        ("keyframes_statement", NameResolution::ChildKind("keyframes_name")),
        ("rule_set", NameResolution::ChildKind("selectors")),
        ("include_statement", NameResolution::ChildKind("identifier")),
    ],
    param_fields: &[
        ("mixin_statement", "parameters"),
        ("function_statement", "parameters"),
    ],
    return_type_fields: &[],
    container_node_types: &[],
    docstring_strategy: DocstringStrategy::PrecedingComment,
    decorator_strategy: DecoratorStrategy::None,
    constant_strategy: ConstantStrategy::None,
    parameter_kinds: &[],
    method_promotion: &[],
};

static SCSS_VAR_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r"(?m)^\s*(\$[\w-]+)\s*:\s*(.+?)\s*(?:!default\s*)?;")
        .expect("scss var regex compiles")
});

static SCSS_USE_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r#"(?m)^\s*@use\s+["']([^"']+)["']\s*(?:as\s+([\w*]+))?\s*;"#)
        .expect("scss @use regex compiles")
});

static SCSS_FORWARD_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r#"(?m)^\s*@forward\s+["']([^"']+)["']\s*(?:(?:hide|show)\s+[^;]+)?\s*;"#)
        .expect("scss @forward regex compiles")
});

static SCSS_IMPORT_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r#"(?m)^\s*@import\s+["']([^"']+)["']\s*;"#)
        .expect("scss @import regex compiles")
});

/// Built-in SCSS extractor.
pub struct ScssExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl ScssExtractor {
    /// Construct a fresh instance. Cheap; the tree-sitter language
    /// handle is lazily materialised on first extraction.
    pub fn new() -> Self {
        Self {
            inner: OnceLock::new(),
        }
    }

    fn delegate(&self) -> &SpecExtractor {
        self.inner.get_or_init(|| {
            SpecExtractor::new(
                &["scss"],
                crate::grammars::get_language("scss").expect("scss grammar"),
                &SPEC,
            )
        })
    }
}

impl Default for ScssExtractor {
    fn default() -> Self {
        Self::new()
    }
}

fn line_number(source: &str, byte_pos: usize) -> u32 {
    let up_to = &source[..byte_pos.min(source.len())];
    (up_to.bytes().filter(|b| *b == b'\n').count() + 1) as u32
}

fn selector_text<'a>(rule_set: Node<'_>, source_bytes: &'a [u8]) -> Option<&'a str> {
    let sel = rule_set
        .child_by_field_name("selectors")
        .or_else(|| find_child_by_kind(rule_set, "selectors"))?;
    std::str::from_utf8(&source_bytes[sel.start_byte()..sel.end_byte()])
        .ok()
        .map(str::trim)
}

fn find_child_by_kind<'a>(node: Node<'a>, kind: &str) -> Option<Node<'a>> {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == kind {
            return Some(child);
        }
    }
    None
}

fn block_of(rule_set: Node<'_>) -> Option<Node<'_>> {
    rule_set
        .child_by_field_name("block")
        .or_else(|| find_child_by_kind(rule_set, "block"))
}

fn make_class_symbol(
    expanded: &str,
    node: Node<'_>,
    source_bytes: &[u8],
    filename: &str,
) -> Symbol {
    let start = node.start_byte();
    let end = node.end_byte();
    let body = &source_bytes[start..end];
    Symbol {
        symbol_id: make_symbol_id(filename, expanded, "class"),
        name: expanded.to_string(),
        qualified_name: expanded.to_string(),
        kind: "class".to_string(),
        language: "scss".to_string(),
        signature: Some(expanded.to_string()),
        docstring: None,
        summary: Some(heuristic_summary(None, Some(expanded), expanded)),
        decorators: Vec::new(),
        keywords: extract_keywords(expanded, None, &[]),
        parent_symbol_id: None,
        line_start: Some((node.start_position().row + 1) as u32),
        line_end: Some((node.end_position().row + 1) as u32),
        byte_offset: start as u32,
        byte_length: (end - start) as u32,
        content_hash: Some(content_hash(body)),
        cyclomatic: 0,
        max_nesting: 0,
        param_count: 0,
    }
}

fn expand_nested(
    node: Node<'_>,
    source_bytes: &[u8],
    parent_selector: Option<&str>,
    filename: &str,
    existing: &mut HashSet<String>,
    out: &mut Vec<Symbol>,
) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "rule_set" {
            let sel = selector_text(child, source_bytes).unwrap_or("");
            if sel.contains('&') {
                if let Some(parent) = parent_selector {
                    let expanded = sel.replace('&', parent);
                    if !existing.contains(&expanded) {
                        existing.insert(expanded.clone());
                        out.push(make_class_symbol(&expanded, child, source_bytes, filename));
                    }
                    if let Some(block) = block_of(child) {
                        expand_nested(block, source_bytes, Some(&expanded), filename, existing, out);
                    }
                }
            } else if let Some(block) = block_of(child) {
                expand_nested(block, source_bytes, Some(sel), filename, existing, out);
            }
        } else {
            expand_nested(child, source_bytes, parent_selector, filename, existing, out);
        }
    }
}

impl LanguageExtractor for ScssExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["scss"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        let spec = self.delegate();
        let mut symbols = spec.extract(ctx)?;
        let mut existing: HashSet<String> = symbols.iter().map(|s| s.name.clone()).collect();

        // Pass 2: regex-extract $variables.
        for m in SCSS_VAR_RE.captures_iter(ctx.source).flatten() {
            let Some(raw) = m.get(1) else { continue };
            let Some(value) = m.get(2) else { continue };
            let Some(whole) = m.get(0) else { continue };
            let name = raw.as_str().trim_start_matches('$').to_string();
            if existing.contains(&name) {
                continue;
            }
            existing.insert(name.clone());
            let sig = format!("{}: {}", raw.as_str(), value.as_str());
            let start = whole.start();
            let end = whole.end();
            let body = &ctx.source_bytes[start..end];
            symbols.push(Symbol {
                symbol_id: make_symbol_id(ctx.filename, &name, "constant"),
                name: name.clone(),
                qualified_name: name.clone(),
                kind: "constant".to_string(),
                language: "scss".to_string(),
                signature: Some(sig.clone()),
                docstring: None,
                summary: Some(heuristic_summary(None, Some(&sig), &name)),
                decorators: Vec::new(),
                keywords: extract_keywords(&name, None, &[]),
                parent_symbol_id: None,
                line_start: Some(line_number(ctx.source, start)),
                line_end: Some(line_number(ctx.source, end)),
                byte_offset: start as u32,
                byte_length: (end - start) as u32,
                content_hash: Some(content_hash(body)),
                cyclomatic: 0,
                max_nesting: 0,
                param_count: 0,
            });
        }

        // Pass 3: ampersand expansion. Re-parse because SpecExtractor
        // consumed its tree; the extra parse is cheap relative to the
        // first pass and keeps the spec API simple.
        let tree = spec.parse(ctx)?;
        expand_nested(
            tree.root_node(),
            ctx.source_bytes,
            None,
            ctx.filename,
            &mut existing,
            &mut symbols,
        );

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

        for m in SCSS_USE_RE.captures_iter(ctx.source).flatten() {
            let Some(spec) = m.get(1) else { continue };
            let mut names: Vec<String> = Vec::new();
            if let Some(alias) = m.get(2) {
                let alias_str = alias.as_str();
                if alias_str != "*" {
                    names.push(alias_str.to_string());
                }
            }
            out.push(Import {
                specifier: spec.as_str().to_string(),
                names,
            });
        }

        for m in SCSS_FORWARD_RE.captures_iter(ctx.source).flatten() {
            let Some(spec) = m.get(1) else { continue };
            out.push(Import {
                specifier: spec.as_str().to_string(),
                names: Vec::new(),
            });
        }

        for m in SCSS_IMPORT_RE.captures_iter(ctx.source).flatten() {
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
        ScssExtractor::new()
            .extract(&ExtractionContext::new(source, "styles.scss", "scss"))
            .expect("scss extraction")
    }

    fn imports(source: &str) -> Vec<Import> {
        ScssExtractor::new()
            .extract_imports(&ExtractionContext::new(source, "styles.scss", "scss"))
            .expect("scss imports")
    }

    #[test]
    fn empty_file_yields_no_imports() {
        assert!(imports("").is_empty());
    }

    #[test]
    fn basic_use_has_no_names() {
        let imps = imports("@use \"a\";\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "a");
        assert!(imps[0].names.is_empty());
    }

    #[test]
    fn use_with_alias_records_alias_name() {
        let imps = imports("@use \"a\" as b;\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "a");
        assert_eq!(imps[0].names, vec!["b".to_string()]);
    }

    #[test]
    fn use_with_star_alias_keeps_names_empty() {
        let imps = imports("@use \"a\" as *;\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "a");
        assert!(imps[0].names.is_empty());
    }

    #[test]
    fn multi_directive_file_preserves_use_forward_import_order() {
        let src = "@use \"a\" as b;\n@forward \"c\";\n@import \"d\";\n";
        let imps = imports(src);
        assert_eq!(imps.len(), 3);
        assert_eq!(imps[0].specifier, "a");
        assert_eq!(imps[0].names, vec!["b".to_string()]);
        assert_eq!(imps[1].specifier, "c");
        assert!(imps[1].names.is_empty());
        assert_eq!(imps[2].specifier, "d");
        assert!(imps[2].names.is_empty());
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_mixin_and_function() {
        let src = "@mixin button($color) { color: $color; }\n@function double($x) { @return $x * 2; }\n";
        let syms = extract(src);
        assert!(syms
            .iter()
            .any(|s| s.name == "button" && s.kind == "function"));
        assert!(syms
            .iter()
            .any(|s| s.name == "double" && s.kind == "function"));
    }

    #[test]
    fn extracts_keyframes() {
        let syms = extract("@keyframes fade { from { opacity: 0; } }\n");
        assert!(syms
            .iter()
            .any(|s| s.name == "fade" && s.kind == "function"));
    }

    #[test]
    fn extracts_rule_set_selectors_as_name() {
        let syms = extract(".card { padding: 10px; }\n");
        let card = syms.iter().find(|s| s.kind == "type").expect("rule_set");
        assert!(card.name.contains(".card"));
    }

    #[test]
    fn extracts_include_statement() {
        let syms = extract(".wrap { @include button(red); }\n");
        assert!(syms
            .iter()
            .any(|s| s.name == "button" && s.kind == "constant"));
    }

    #[test]
    fn extracts_variable_with_dollar_stripped() {
        let syms = extract("$primary: blue;\n");
        assert!(syms.iter().any(|s| s.name == "primary" && s.kind == "constant"));
    }

    #[test]
    fn expands_ampersand_child() {
        let syms = extract(".parent {\n  &__child { color: red; }\n}\n");
        assert!(syms
            .iter()
            .any(|s| s.name == ".parent__child" && s.kind == "class"));
    }

    #[test]
    fn expands_deeply_nested_ampersand() {
        let src = ".card {\n  &__header {\n    &--active { color: green; }\n  }\n}\n";
        let syms = extract(src);
        assert!(syms.iter().any(|s| s.name == ".card__header"));
        assert!(syms.iter().any(|s| s.name == ".card__header--active"));
    }

    #[test]
    fn advertises_scss_language() {
        assert_eq!(ScssExtractor::new().languages(), &["scss"]);
    }
}
