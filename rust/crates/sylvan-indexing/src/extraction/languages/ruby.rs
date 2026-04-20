//! Ruby extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the Ruby grammar. Mirrors the
//! Ruby [`LanguageSpec`] declared in the legacy plugin: method /
//! singleton_method / class / module symbols, signature stitching,
//! preceding `#` comment docstrings, and ALL_CAPS `assignment`
//! constants. Ruby has no decorator syntax and no method promotion
//! since the grammar already names the node `method`.
//!
//! Import extraction walks the parsed tree for top-level `call` nodes
//! whose method is `require` or `require_relative` with a single
//! string-literal argument, matching the legacy plugin's regex
//! coverage. Quotes are stripped so the specifier matches the Python
//! plugin's output exactly.
//!
//! Features left for later migration stages (not this spec walker):
//! complexity scoring, content hashing, cross-file resolution.

use std::sync::OnceLock;

use sylvan_core::{ExtractionContext, ExtractionError, Import, LanguageExtractor, Symbol};
use tree_sitter::Node;

use crate::extraction::spec::{
    ConstantStrategy, DecoratorStrategy, DocstringStrategy, LanguageSpec, SpecExtractor,
};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[
        ("method", "method"),
        ("singleton_method", "method"),
        ("class", "class"),
        ("module", "module"),
    ],
    name_fields: &[
        ("method", "name"),
        ("singleton_method", "name"),
        ("class", "name"),
        ("module", "name"),
    ],
    param_fields: &[
        ("method", "parameters"),
        ("singleton_method", "parameters"),
    ],
    return_type_fields: &[],
    container_node_types: &["class", "module"],
    docstring_strategy: DocstringStrategy::PrecedingComment,
    decorator_strategy: DecoratorStrategy::None,
    constant_strategy: ConstantStrategy::None,
    parameter_kinds: &[
        "identifier",
        "optional_parameter",
        "keyword_parameter",
        "hash_splat_parameter",
        "splat_parameter",
        "block_parameter",
    ],
    method_promotion: &[],
};

const REQUIRE_METHODS: &[&str] = &["require", "require_relative"];

/// Built-in Ruby extractor.
pub struct RubyExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl RubyExtractor {
    /// Construct a fresh instance.
    pub fn new() -> Self {
        Self {
            inner: OnceLock::new(),
        }
    }

    fn delegate(&self) -> &SpecExtractor {
        self.inner.get_or_init(|| {
            SpecExtractor::new(&["ruby"], tree_sitter_ruby::LANGUAGE.into(), &SPEC)
        })
    }
}

impl Default for RubyExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for RubyExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["ruby"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        self.delegate().extract(ctx)
    }

    fn supports_imports(&self) -> bool {
        true
    }

    fn extract_imports(
        &self,
        ctx: &ExtractionContext<'_>,
    ) -> Result<Vec<Import>, ExtractionError> {
        let tree = self.delegate().parse(ctx)?;
        let mut out = Vec::new();
        walk_imports(tree.root_node(), ctx.source_bytes, &mut out);
        Ok(out)
    }
}

fn walk_imports(node: Node<'_>, source: &[u8], out: &mut Vec<Import>) {
    if node.kind() == "call" {
        if collect_call(node, source, out) {
            return;
        }
    }
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        walk_imports(child, source, out);
    }
}

fn collect_call(node: Node<'_>, source: &[u8], out: &mut Vec<Import>) -> bool {
    if node.child_by_field_name("receiver").is_some() {
        return false;
    }
    let Some(method) = node.child_by_field_name("method") else {
        return false;
    };
    if method.kind() != "identifier" {
        return false;
    }
    let Some(method_name) = node_text(method, source) else {
        return false;
    };
    if !REQUIRE_METHODS.contains(&method_name.as_str()) {
        return false;
    }

    let Some(args) = node.child_by_field_name("arguments") else {
        return false;
    };
    let mut cursor = args.walk();
    let specifier = args
        .children(&mut cursor)
        .find_map(|child| string_literal_content(child, source));
    let Some(specifier) = specifier else {
        return false;
    };
    out.push(Import {
        specifier,
        names: Vec::new(),
    });
    true
}

fn string_literal_content(node: Node<'_>, source: &[u8]) -> Option<String> {
    if node.kind() != "string" {
        return None;
    }
    let mut cursor = node.walk();
    let mut buf = String::new();
    let mut has_content = false;
    for child in node.children(&mut cursor) {
        if child.kind() == "string_content" {
            if let Some(text) = node_text(child, source) {
                buf.push_str(&text);
                has_content = true;
            }
        }
    }
    if has_content {
        return Some(buf);
    }
    node_text(node, source).map(|raw| strip_quotes(&raw))
}

fn strip_quotes(raw: &str) -> String {
    let trimmed = raw.trim();
    let bytes = trimmed.as_bytes();
    if bytes.len() >= 2 {
        let first = bytes[0];
        let last = bytes[bytes.len() - 1];
        if (first == b'"' && last == b'"') || (first == b'\'' && last == b'\'') {
            return trimmed[1..trimmed.len() - 1].to_string();
        }
    }
    trimmed.to_string()
}

fn node_text(node: Node<'_>, source: &[u8]) -> Option<String> {
    std::str::from_utf8(&source[node.byte_range()])
        .ok()
        .map(|s| s.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        RubyExtractor::new()
            .extract(&ExtractionContext::new(source, "mod.rb", "ruby"))
            .expect("ruby extraction")
    }

    fn imports(src: &str) -> Vec<Import> {
        RubyExtractor::new()
            .extract_imports(&ExtractionContext::new(src, "mod.rb", "ruby"))
            .expect("ruby imports")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_top_level_method() {
        let syms = extract("def greet\nend\n");
        assert_eq!(syms.len(), 1);
        assert_eq!(syms[0].name, "greet");
        assert_eq!(syms[0].kind, "method");
        assert_eq!(syms[0].qualified_name, "greet");
        assert_eq!(syms[0].language, "ruby");
    }

    #[test]
    fn extracts_class_with_nested_method() {
        let syms = extract("class Dog\n  def bark\n  end\nend\n");
        assert_eq!(syms.len(), 2);
        let cls = syms.iter().find(|s| s.kind == "class").expect("class");
        let method = syms.iter().find(|s| s.kind == "method").expect("method");
        assert_eq!(cls.name, "Dog");
        assert_eq!(method.name, "bark");
        assert_eq!(method.qualified_name, "Dog.bark");
        assert_eq!(
            method.parent_symbol_id.as_deref(),
            Some(cls.symbol_id.as_str())
        );
    }

    #[test]
    fn extracts_module_symbol() {
        let syms = extract("module M\nend\n");
        assert_eq!(syms.len(), 1);
        assert_eq!(syms[0].name, "M");
        assert_eq!(syms[0].kind, "module");
    }

    #[test]
    fn preceding_hash_comment_becomes_docstring() {
        let src = "# greet comment\ndef x\nend\n";
        let syms = extract(src);
        assert_eq!(syms.len(), 1);
        let doc = syms[0].docstring.as_deref().expect("docstring");
        assert!(doc.contains("comment"), "docstring was: {doc:?}");
    }

    #[test]
    fn advertises_ruby_language() {
        assert_eq!(RubyExtractor::new().languages(), &["ruby"]);
    }

    #[test]
    fn require_call_records_specifier() {
        let imps = imports("require 'json'\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "json");
        assert!(imps[0].names.is_empty());
    }

    #[test]
    fn require_relative_records_specifier() {
        let imps = imports("require_relative './helper'\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "./helper");
    }

    #[test]
    fn double_quoted_require_records_specifier() {
        let imps = imports("require \"net/http\"\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "net/http");
    }

    #[test]
    fn multiple_requires_emit_one_record_each() {
        let src = "require 'a'\nrequire 'b'\nrequire_relative 'c'\n";
        let imps = imports(src);
        let specs: Vec<&str> = imps.iter().map(|i| i.specifier.as_str()).collect();
        assert_eq!(specs, vec!["a", "b", "c"]);
    }

    #[test]
    fn load_and_autoload_are_ignored_matching_python_plugin() {
        let imps = imports("load 'x'\nautoload :Foo, 'foo'\n");
        assert!(imps.is_empty(), "expected no imports, got {imps:?}");
    }

    #[test]
    fn require_with_receiver_is_ignored() {
        let imps = imports("Kernel.require 'nope'\n");
        assert!(imps.is_empty(), "expected no imports, got {imps:?}");
    }

    #[test]
    fn non_literal_argument_is_skipped() {
        let imps = imports("require some_var\n");
        assert!(imps.is_empty());
    }
}
