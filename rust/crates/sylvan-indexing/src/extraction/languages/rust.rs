//! Rust extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the Rust grammar. Mirrors
//! the Rust [`LanguageSpec`] in the legacy Python plugin: functions,
//! impl/struct/enum/trait/type items, preceding-comment docstrings,
//! and parameter/return-type fields for signature stitching. No
//! decorators, no method promotion, no module-level constant
//! emission (the spec lists const/static/let patterns but the walker
//! only acts on patterns that resolve through `try_emit_constant`'s
//! assignment shape, so they pass through as non-symbol nodes here).
//!
//! Features left for later migration stages: import extraction, use
//! resolution, self-receiver stripping, Rust-specific complexity.

use std::sync::OnceLock;

use sylvan_core::{ExtractionContext, ExtractionError, LanguageExtractor, Symbol};

use crate::extraction::spec::{
    ConstantStrategy, DecoratorStrategy, DocstringStrategy, LanguageSpec, SpecExtractor,
};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[
        ("function_item", "function"),
        ("impl_item", "class"),
        ("struct_item", "class"),
        ("enum_item", "type"),
        ("trait_item", "type"),
        ("type_item", "type"),
    ],
    name_fields: &[
        ("function_item", "name"),
        ("impl_item", "type"),
        ("struct_item", "name"),
        ("enum_item", "name"),
        ("trait_item", "name"),
        ("type_item", "name"),
    ],
    param_fields: &[("function_item", "parameters")],
    return_type_fields: &[("function_item", "return_type")],
    container_node_types: &["impl_item", "trait_item"],
    docstring_strategy: DocstringStrategy::PrecedingComment,
    decorator_strategy: DecoratorStrategy::PrecedingSiblings {
        kinds: &["attribute_item", "inner_attribute_item"],
    },
    constant_strategy: ConstantStrategy::DirectItems {
        item_kinds: &["const_item", "static_item"],
        name_field: "name",
        uppercase_only: false,
    },
    parameter_kinds: &["parameter", "self_parameter"],
    method_promotion: &[],
};

/// Built-in Rust extractor.
pub struct RustExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl RustExtractor {
    /// Construct a fresh instance.
    pub fn new() -> Self {
        Self {
            inner: OnceLock::new(),
        }
    }

    fn delegate(&self) -> &SpecExtractor {
        self.inner.get_or_init(|| {
            SpecExtractor::new(&["rust"], tree_sitter_rust::LANGUAGE.into(), &SPEC)
        })
    }
}

impl Default for RustExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for RustExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["rust"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        self.delegate().extract(ctx)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        RustExtractor::new()
            .extract(&ExtractionContext::new(source, "lib.rs", "rust"))
            .expect("rust extraction")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_top_level_function() {
        let syms = extract("fn greet() {}\n");
        assert_eq!(syms.len(), 1);
        assert_eq!(syms[0].name, "greet");
        assert_eq!(syms[0].kind, "function");
        assert_eq!(syms[0].qualified_name, "greet");
        assert_eq!(syms[0].language, "rust");
        let sig = syms[0].signature.as_deref().expect("signature");
        assert_eq!(sig, "fn greet()");
    }

    #[test]
    fn extracts_struct_symbol() {
        let syms = extract("struct Point { x: i32 }\n");
        let point = syms
            .iter()
            .find(|s| s.name == "Point")
            .expect("struct symbol");
        assert_eq!(point.kind, "class");
        assert_eq!(point.qualified_name, "Point");
    }

    #[test]
    fn impl_item_is_container_and_nests_methods() {
        let syms = extract("impl Foo { fn bar(&self) {} }\n");
        let parent = syms
            .iter()
            .find(|s| s.name == "Foo" && s.kind == "class")
            .expect("impl symbol");
        let bar = syms
            .iter()
            .find(|s| s.name == "bar")
            .expect("nested fn symbol");
        assert_eq!(bar.kind, "function");
        assert_eq!(bar.qualified_name, "Foo.bar");
        assert_eq!(
            bar.parent_symbol_id.as_deref(),
            Some(parent.symbol_id.as_str())
        );
    }

    #[test]
    fn preceding_triple_slash_comment_is_docstring() {
        let src = "/// doc\nfn x() {}\n";
        let syms = extract(src);
        let doc = syms[0].docstring.as_deref().expect("docstring");
        assert!(doc.contains("doc"), "expected doc fragment, got {doc:?}");
    }

    #[test]
    fn advertises_rust_language() {
        assert_eq!(RustExtractor::new().languages(), &["rust"]);
    }

    #[test]
    fn const_item_emits_constant() {
        let syms = extract("const MAX: u32 = 5;\n");
        let c = syms.iter().find(|s| s.kind == "constant").expect("constant");
        assert_eq!(c.name, "MAX");
    }

    #[test]
    fn static_item_emits_constant() {
        let syms = extract("static TABLE: &[u8] = &[];\n");
        let c = syms.iter().find(|s| s.kind == "constant").expect("constant");
        assert_eq!(c.name, "TABLE");
    }
}
