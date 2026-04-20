//! Java extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the Java grammar. Mirrors
//! the spec declared in the legacy Python plugin: class, interface,
//! enum, method, and constructor declarations. Docstrings come from
//! preceding `//` or `/** ... */` comments. Java annotations
//! (`@Override`, `@Deprecated`) are not wrappers around their target
//! method in the tree-sitter grammar, so `decorator_node_type` stays
//! `None`; annotation capture falls through to the legacy Python path
//! until the walker grows a sibling-based decorator rule.
//!
//! Features left for later migration stages: import extraction,
//! candidate path resolution against `src/main/java/`, complexity
//! tuning, and `field_declaration` constant emission (the current
//! walker's constant path is hard-coded around Python's
//! `expression_statement`/`assignment` shape).

use std::sync::OnceLock;

use sylvan_core::{ExtractionContext, ExtractionError, LanguageExtractor, Symbol};

use crate::extraction::spec::{DocstringStrategy, LanguageSpec, SpecExtractor};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[
        ("method_declaration", "method"),
        ("class_declaration", "class"),
        ("interface_declaration", "type"),
        ("enum_declaration", "type"),
        ("constructor_declaration", "method"),
    ],
    name_fields: &[
        ("method_declaration", "name"),
        ("class_declaration", "name"),
        ("interface_declaration", "name"),
        ("enum_declaration", "name"),
        ("constructor_declaration", "name"),
    ],
    param_fields: &[
        ("method_declaration", "parameters"),
        ("constructor_declaration", "parameters"),
    ],
    return_type_fields: &[("method_declaration", "type")],
    container_node_types: &[
        "class_declaration",
        "interface_declaration",
        "enum_declaration",
    ],
    docstring_strategy: DocstringStrategy::PrecedingComment,
    decorator_node_type: None,
    constant_patterns: &["field_declaration"],
    method_promotion: &[],
};

/// Built-in Java extractor.
pub struct JavaExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl JavaExtractor {
    /// Construct a fresh instance.
    pub fn new() -> Self {
        Self {
            inner: OnceLock::new(),
        }
    }

    fn delegate(&self) -> &SpecExtractor {
        self.inner.get_or_init(|| {
            SpecExtractor::new(&["java"], tree_sitter_java::LANGUAGE.into(), &SPEC)
        })
    }
}

impl Default for JavaExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for JavaExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["java"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        self.delegate().extract(ctx)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        JavaExtractor::new()
            .extract(&ExtractionContext::new(source, "Mod.java", "java"))
            .expect("java extraction")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn class_with_method_nests_method_under_class() {
        let syms = extract("class Foo { void bar() {} }");
        assert_eq!(syms.len(), 2);
        let cls = syms.iter().find(|s| s.kind == "class").expect("class");
        let method = syms.iter().find(|s| s.kind == "method").expect("method");
        assert_eq!(cls.name, "Foo");
        assert_eq!(method.name, "bar");
        assert_eq!(method.qualified_name, "Foo.bar");
        assert_eq!(method.parent_symbol_id.as_deref(), Some(cls.symbol_id.as_str()));
    }

    #[test]
    fn constructor_is_emitted_as_method() {
        let syms = extract("public class Foo { public Foo() {} }");
        let cls = syms.iter().find(|s| s.kind == "class").expect("class");
        assert_eq!(cls.name, "Foo");
        let ctor = syms
            .iter()
            .find(|s| s.kind == "method" && s.name == "Foo")
            .expect("constructor");
        assert_eq!(ctor.qualified_name, "Foo.Foo");
        assert_eq!(ctor.parent_symbol_id.as_deref(), Some(cls.symbol_id.as_str()));
    }

    #[test]
    fn interface_declaration_becomes_type_symbol() {
        let syms = extract("interface I { void doIt(); }");
        let iface = syms.iter().find(|s| s.kind == "type").expect("interface");
        assert_eq!(iface.name, "I");
    }

    #[test]
    fn preceding_block_comment_becomes_docstring() {
        let src = "/** doc */\nclass X {}\n";
        let syms = extract(src);
        let cls = syms.iter().find(|s| s.kind == "class").expect("class");
        let doc = cls.docstring.as_deref().expect("docstring");
        assert!(doc.contains("doc"), "docstring was {doc:?}");
    }

    #[test]
    fn signature_includes_params() {
        let src = "class G { public void greet(String name) {} }";
        let syms = extract(src);
        let method = syms.iter().find(|s| s.kind == "method").expect("method");
        let sig = method.signature.as_deref().expect("signature");
        assert!(
            sig.contains("greet(String name)"),
            "signature was {sig:?}"
        );
    }

    #[test]
    fn advertises_java_language() {
        assert_eq!(JavaExtractor::new().languages(), &["java"]);
    }
}
