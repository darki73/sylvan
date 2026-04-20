//! Go extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the Go grammar. Mirrors the
//! spec declared in the legacy Python plugin: top-level functions,
//! receiver methods, and type declarations. Docstrings come from
//! preceding `//` comments. Go has no decorators and no class-method
//! distinction, so `decorator_node_type` and `method_promotion` are
//! unused.
//!
//! Features left for later migration stages: import extraction,
//! candidate path resolution against stdlib, and complexity tuning.

use std::sync::OnceLock;

use sylvan_core::{ExtractionContext, ExtractionError, LanguageExtractor, Symbol};

use crate::extraction::spec::{DocstringStrategy, LanguageSpec, SpecExtractor};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[
        ("function_declaration", "function"),
        ("method_declaration", "method"),
        ("type_spec", "type"),
    ],
    name_fields: &[
        ("function_declaration", "name"),
        ("method_declaration", "name"),
        ("type_spec", "name"),
    ],
    param_fields: &[
        ("function_declaration", "parameters"),
        ("method_declaration", "parameters"),
    ],
    return_type_fields: &[
        ("function_declaration", "result"),
        ("method_declaration", "result"),
    ],
    container_node_types: &[],
    docstring_strategy: DocstringStrategy::PrecedingComment,
    decorator_node_type: None,
    constant_patterns: &[],
    method_promotion: &[],
};

/// Built-in Go extractor.
pub struct GoExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl GoExtractor {
    /// Construct a fresh instance.
    pub fn new() -> Self {
        Self {
            inner: OnceLock::new(),
        }
    }

    fn delegate(&self) -> &SpecExtractor {
        self.inner.get_or_init(|| {
            SpecExtractor::new(&["go"], tree_sitter_go::LANGUAGE.into(), &SPEC)
        })
    }
}

impl Default for GoExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for GoExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["go"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        self.delegate().extract(ctx)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        GoExtractor::new()
            .extract(&ExtractionContext::new(source, "main.go", "go"))
            .expect("go extraction")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_top_level_function() {
        let syms = extract("package main\n\nfunc Foo() {}\n");
        assert_eq!(syms.len(), 1);
        assert_eq!(syms[0].name, "Foo");
        assert_eq!(syms[0].kind, "function");
        assert_eq!(syms[0].qualified_name, "Foo");
        assert_eq!(syms[0].language, "go");
    }

    #[test]
    fn extracts_receiver_method() {
        let src = "package main\n\ntype Receiver struct{}\n\nfunc (r *Receiver) Method() {}\n";
        let syms = extract(src);
        let method = syms.iter().find(|s| s.kind == "method").expect("method");
        assert_eq!(method.name, "Method");
        assert_eq!(method.kind, "method");
    }

    #[test]
    fn extracts_type_declaration() {
        let src = "package main\n\ntype User struct {\n    Name string\n}\n";
        let syms = extract(src);
        let ty = syms.iter().find(|s| s.kind == "type").expect("type");
        assert_eq!(ty.name, "User");
        assert_eq!(ty.qualified_name, "User");
    }

    #[test]
    fn preceding_line_comment_becomes_docstring() {
        let src = "package main\n\n// doc comment\nfunc Foo() {}\n";
        let syms = extract(src);
        assert_eq!(syms.len(), 1);
        assert_eq!(syms[0].docstring.as_deref(), Some("doc comment"));
    }

    #[test]
    fn signature_spans_up_to_body() {
        let src = "package main\n\nfunc Add(a int, b int) int { return a + b }\n";
        let syms = extract(src);
        let sig = syms[0].signature.as_deref().expect("signature");
        assert!(sig.contains("Add(a int, b int)"), "signature was {sig:?}");
        assert!(sig.contains("int"), "signature was {sig:?}");
        assert_eq!(syms[0].name, "Add");
    }

    #[test]
    fn advertises_go_language() {
        assert_eq!(GoExtractor::new().languages(), &["go"]);
    }
}
