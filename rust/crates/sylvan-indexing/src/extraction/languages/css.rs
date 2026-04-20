//! CSS extractor.
//!
//! Walks the tree-sitter CSS AST and emits a symbol for each rule set,
//! media query, keyframes block, and import statement. Port of the
//! `"css"` entry in `sylvan.indexing.languages._tree_sitter_only`.
//!
//! Improvements over the Python LanguageSpec walk:
//!
//! - `import_statement` has no entry in the spec's `name_fields`, so
//!   the Python extractor's generic `extract_name` returns `None` and
//!   the import is silently dropped. Here we fall back to the raw node
//!   text (trimmed, `@import` stripped) so `@import "foo.css"` actually
//!   surfaces as a symbol.
//! - Preceding-comment docstring walks through tree-sitter siblings
//!   directly instead of round-tripping bytes, and handles the CSS-only
//!   `/* ... */` form inline (no language-dispatch table).

use sylvan_core::{ExtractionContext, ExtractionError, LanguageExtractor, Symbol, make_symbol_id};
use tree_sitter::{Node, Parser};

/// Built-in CSS extractor. Stateless; cheap to construct.
pub struct CssExtractor;

impl CssExtractor {
    /// Construct a fresh instance.
    pub fn new() -> Self {
        Self
    }
}

impl Default for CssExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for CssExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["css"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        if u32::try_from(ctx.source_bytes.len()).is_err() {
            return Err(ExtractionError::MissingDependency(format!(
                "css source exceeds u32::MAX bytes: {}",
                ctx.source_bytes.len()
            )));
        }

        let mut parser = Parser::new();
        parser
            .set_language(&tree_sitter_css::LANGUAGE.into())
            .map_err(|e| ExtractionError::GrammarLoad {
                language: "css".into(),
                message: e.to_string(),
            })?;

        let Some(tree) = parser.parse(ctx.source_bytes, None) else {
            return Ok(Vec::new());
        };

        let mut out = Vec::new();
        let root = tree.root_node();
        let mut cursor = root.walk();
        for child in root.children(&mut cursor) {
            if let Some(symbol) = extract_symbol(child, ctx) {
                out.push(symbol);
            }
        }
        Ok(out)
    }
}

fn extract_symbol(node: Node<'_>, ctx: &ExtractionContext<'_>) -> Option<Symbol> {
    let kind = match node.kind() {
        "rule_set" | "media_statement" => "type",
        "keyframes_statement" => "function",
        "import_statement" => "constant",
        _ => return None,
    };

    let name = symbol_name(node, ctx.source_bytes)?;
    if name.is_empty() {
        return None;
    }

    let start = node.start_byte();
    let end = node.end_byte();
    let byte_offset = u32::try_from(start).ok()?;
    let byte_length = u32::try_from(end.saturating_sub(start)).ok()?;

    let line_start = (node.start_position().row as u32) + 1;
    let line_end = (node.end_position().row as u32) + 1;

    let docstring = preceding_comment_docstring(node, ctx.source_bytes);

    Some(Symbol {
        symbol_id: make_symbol_id(ctx.filename, &name, kind),
        name: name.clone(),
        qualified_name: name,
        kind: kind.to_string(),
        language: "css".to_string(),
        line_start: Some(line_start),
        line_end: Some(line_end),
        byte_offset,
        byte_length,
        docstring,
        ..Symbol::default()
    })
}

fn symbol_name(node: Node<'_>, source: &[u8]) -> Option<String> {
    // tree-sitter-css exposes structural children (`selectors`,
    // `keyframes_name`, `binary_query`, `string_value`, ...) rather
    // than the named `selectors`/`name`/`condition` fields the Python
    // LanguageSpec advertises. We look up by child kind instead.
    match node.kind() {
        "rule_set" => first_child_text(node, source, &["selectors"]),
        "keyframes_statement" => first_child_text(node, source, &["keyframes_name"]),
        "media_statement" => first_child_text(
            node,
            source,
            &[
                "binary_query",
                "keyword_query",
                "feature_query",
                "parenthesized_query",
                "unary_query",
            ],
        )
        .or_else(|| media_query_text(node, source)),
        "import_statement" => import_target(node, source),
        _ => None,
    }
}

fn first_child_text(node: Node<'_>, source: &[u8], kinds: &[&str]) -> Option<String> {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if kinds.contains(&child.kind())
            && let Some(text) = slice_text(child, source)
        {
            let trimmed = text.trim();
            if !trimmed.is_empty() {
                return Some(trimmed.to_string());
            }
        }
    }
    None
}

fn media_query_text(node: Node<'_>, source: &[u8]) -> Option<String> {
    let mut cursor = node.walk();
    let mut parts: Vec<String> = Vec::new();
    for child in node.children(&mut cursor) {
        let kind = child.kind();
        // Skip the opening `@media` token, the trailing block, and
        // punctuation. Everything else is part of the query.
        if kind == "block" || kind == "@media" || kind == "{" || kind == "}" || kind == ";" {
            continue;
        }
        if let Some(text) = slice_text(child, source) {
            let t = text.trim();
            if !t.is_empty() {
                parts.push(t.to_string());
            }
        }
    }
    let joined = parts.join(" ").trim().to_string();
    if joined.is_empty() { None } else { Some(joined) }
}

fn import_target(node: Node<'_>, source: &[u8]) -> Option<String> {
    // `@import "foo.css";` → string_value child.
    // `@import url("bar.css");` → call_expression child.
    // Fall back to the raw node text with `@import` and `;` stripped so
    // unusual forms still surface (Python drops these silently).
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "string_value" => {
                if let Some(inner) = inner_string(child, source) {
                    return Some(inner);
                }
                if let Some(text) = slice_text(child, source) {
                    let s = text.trim().trim_matches(|c| c == '"' || c == '\'');
                    if !s.is_empty() {
                        return Some(s.to_string());
                    }
                }
            }
            "call_expression" => {
                if let Some(s) = call_expression_target(child, source) {
                    return Some(s);
                }
            }
            _ => {}
        }
    }
    let raw = slice_text(node, source)?;
    let stripped = raw
        .trim()
        .trim_start_matches("@import")
        .trim()
        .trim_end_matches(';')
        .trim()
        .trim_matches(|c| c == '"' || c == '\'');
    if stripped.is_empty() {
        None
    } else {
        Some(stripped.to_string())
    }
}

fn inner_string(node: Node<'_>, source: &[u8]) -> Option<String> {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "string_content"
            && let Some(text) = slice_text(child, source)
        {
            return Some(text.to_string());
        }
    }
    None
}

fn call_expression_target(node: Node<'_>, source: &[u8]) -> Option<String> {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "arguments" {
            let mut inner_cursor = child.walk();
            for arg in child.children(&mut inner_cursor) {
                if arg.kind() == "string_value"
                    && let Some(s) = inner_string(arg, source)
                {
                    return Some(s);
                }
                if arg.kind() == "plain_value"
                    && let Some(text) = slice_text(arg, source)
                {
                    return Some(text.trim().to_string());
                }
            }
        }
    }
    None
}

fn slice_text<'a>(node: Node<'_>, source: &'a [u8]) -> Option<&'a str> {
    std::str::from_utf8(source.get(node.start_byte()..node.end_byte())?).ok()
}

fn preceding_comment_docstring(node: Node<'_>, source: &[u8]) -> Option<String> {
    let mut parts: Vec<String> = Vec::new();
    let mut current = node.prev_named_sibling();
    while let Some(sibling) = current {
        if sibling.kind() != "comment" {
            break;
        }
        if let Some(text) = slice_text(sibling, source) {
            parts.push(text.to_string());
        }
        current = sibling.prev_named_sibling();
    }
    if parts.is_empty() {
        return None;
    }
    parts.reverse();
    Some(clean_css_comment_block(&parts.join("\n")))
}

fn clean_css_comment_block(text: &str) -> String {
    let mut lines: Vec<String> = Vec::new();
    for raw in text.split('\n') {
        let mut s = raw.trim();
        for prefix in ["/**", "/*", "*/", "*"] {
            if s.starts_with(prefix) {
                s = &s[prefix.len()..];
                break;
            }
        }
        let mut cleaned = s.to_string();
        if cleaned.ends_with("*/") {
            cleaned.truncate(cleaned.len() - 2);
        }
        lines.push(cleaned.trim().to_string());
    }
    lines.join("\n").trim().to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(src: &str, filename: &str) -> Vec<Symbol> {
        let ctx = ExtractionContext::new(src, filename, "css");
        CssExtractor::new().extract(&ctx).expect("extract ok")
    }

    #[test]
    fn empty_file_produces_no_symbols() {
        assert!(extract("", "a.css").is_empty());
    }

    #[test]
    fn whitespace_only_produces_no_symbols() {
        assert!(extract("   \n\n  \t  ", "a.css").is_empty());
    }

    #[test]
    fn simple_rule_set_is_a_type() {
        let syms = extract(".foo { color: red; }", "a.css");
        assert_eq!(syms.len(), 1);
        assert_eq!(syms[0].kind, "type");
        assert_eq!(syms[0].name, ".foo");
        assert_eq!(syms[0].language, "css");
        assert_eq!(syms[0].qualified_name, ".foo");
    }

    #[test]
    fn multiple_rule_sets_produce_one_symbol_each() {
        let src = ".a { color: red; }\n.b { color: blue; }\n.c { color: green; }";
        let syms = extract(src, "a.css");
        assert_eq!(syms.len(), 3);
        let names: Vec<&str> = syms.iter().map(|s| s.name.as_str()).collect();
        assert_eq!(names, vec![".a", ".b", ".c"]);
    }

    #[test]
    fn multi_selector_rule_set_preserves_commas() {
        let syms = extract("h1, h2, h3 { font-weight: bold; }", "a.css");
        assert_eq!(syms.len(), 1);
        assert_eq!(syms[0].name, "h1, h2, h3");
        assert_eq!(syms[0].kind, "type");
    }

    #[test]
    fn media_statement_is_a_type() {
        let syms = extract(
            "@media screen and (max-width: 600px) { .a { color: red; } }",
            "a.css",
        );
        let media: Vec<&Symbol> = syms
            .iter()
            .filter(|s| s.kind == "type" && s.name.contains("screen"))
            .collect();
        assert_eq!(media.len(), 1);
    }

    #[test]
    fn keyframes_statement_is_a_function() {
        let syms = extract(
            "@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }",
            "a.css",
        );
        let kf = syms.iter().find(|s| s.kind == "function").unwrap();
        assert_eq!(kf.name, "fadeIn");
    }

    #[test]
    fn import_statement_is_a_constant() {
        let syms = extract("@import \"foo.css\";", "a.css");
        let imp = syms.iter().find(|s| s.kind == "constant").unwrap();
        assert!(
            imp.name.contains("foo.css"),
            "expected import name to contain foo.css, got {:?}",
            imp.name
        );
    }

    #[test]
    fn import_statement_with_url_is_a_constant() {
        let syms = extract("@import url(\"bar.css\");", "a.css");
        assert_eq!(syms.iter().filter(|s| s.kind == "constant").count(), 1);
    }

    #[test]
    fn preceding_comment_becomes_docstring() {
        let src = "/* doc */\n.foo { color: red; }";
        let syms = extract(src, "a.css");
        assert_eq!(syms.len(), 1);
        assert_eq!(syms[0].docstring.as_deref(), Some("doc"));
    }

    #[test]
    fn multiline_preceding_comment_preserves_content() {
        let src = "/*\n * first line\n * second line\n */\n.foo { color: red; }";
        let syms = extract(src, "a.css");
        let doc = syms[0].docstring.as_deref().unwrap();
        assert!(doc.contains("first line"), "got {doc:?}");
        assert!(doc.contains("second line"), "got {doc:?}");
    }

    #[test]
    fn missing_docstring_stays_none() {
        let syms = extract(".foo { color: red; }", "a.css");
        assert!(syms[0].docstring.is_none());
    }

    #[test]
    fn multiple_preceding_comments_are_merged() {
        let src = "/* one */\n/* two */\n.foo { color: red; }";
        let syms = extract(src, "a.css");
        let doc = syms[0].docstring.as_deref().unwrap();
        assert!(doc.contains("one"));
        assert!(doc.contains("two"));
    }

    #[test]
    fn byte_offsets_and_lines_are_one_based() {
        let src = "\n\n.foo { color: red; }";
        let syms = extract(src, "a.css");
        assert_eq!(syms.len(), 1);
        assert_eq!(syms[0].line_start, Some(3));
        assert_eq!(syms[0].line_end, Some(3));
        assert_eq!(syms[0].byte_offset, 2);
        assert_eq!(syms[0].byte_length, ".foo { color: red; }".len() as u32);
    }

    #[test]
    fn symbol_id_encodes_kind_and_path() {
        let syms = extract(".foo { color: red; }", "styles/main.css");
        assert_eq!(syms[0].symbol_id, "styles/main.css::.foo#type");
    }

    #[test]
    fn malformed_css_best_effort_parse() {
        // Tree-sitter is error-tolerant; the good rule should still
        // extract. No panic, no error.
        let src = ".broken { color: ;;; }\n.ok { color: red; }";
        let syms = extract(src, "a.css");
        assert!(syms.iter().any(|s| s.name == ".ok"));
    }

    #[test]
    fn rule_set_followed_by_import_yields_both() {
        let src = "@import \"base.css\";\n.foo { color: red; }";
        let syms = extract(src, "a.css");
        assert_eq!(syms.len(), 2);
        assert_eq!(
            syms.iter().filter(|s| s.kind == "constant").count(),
            1,
            "import"
        );
        assert_eq!(
            syms.iter().filter(|s| s.kind == "type").count(),
            1,
            "rule_set"
        );
    }

    #[test]
    fn extractor_advertises_css_only() {
        assert_eq!(CssExtractor::new().languages(), &["css"]);
    }
}
