//! JavaScript extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the JavaScript grammar.
//! Mirrors the spec declared by the legacy Python plugin: function
//! declarations, class declarations, and `method_definition` nodes
//! (which map directly to the `method` kind, so no promotion entry is
//! needed). Docstrings come from preceding `//` or `/** ... */` comment
//! siblings.
//!
//! Arrow functions, variable-declarator functions, and export wrappers
//! are intentionally not listed here. The Python spec does not include
//! them and this port stays byte-for-byte compatible with that surface.

use std::sync::OnceLock;

use sylvan_core::{ExtractionContext, ExtractionError, LanguageExtractor, Symbol};

use crate::extraction::spec::{DocstringStrategy, LanguageSpec, SpecExtractor};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[
        ("function_declaration", "function"),
        ("class_declaration", "class"),
        ("method_definition", "method"),
    ],
    name_fields: &[
        ("function_declaration", "name"),
        ("class_declaration", "name"),
        ("method_definition", "name"),
    ],
    param_fields: &[
        ("function_declaration", "parameters"),
        ("method_definition", "parameters"),
    ],
    return_type_fields: &[],
    container_node_types: &["class_declaration", "class"],
    docstring_strategy: DocstringStrategy::PrecedingComment,
    decorator_node_type: None,
    constant_patterns: &[],
    method_promotion: &[],
};

/// Built-in JavaScript extractor.
pub struct JavaScriptExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl JavaScriptExtractor {
    /// Construct a fresh instance.
    pub fn new() -> Self {
        Self {
            inner: OnceLock::new(),
        }
    }

    fn delegate(&self) -> &SpecExtractor {
        self.inner.get_or_init(|| {
            SpecExtractor::new(
                &["javascript"],
                tree_sitter_javascript::LANGUAGE.into(),
                &SPEC,
            )
        })
    }
}

impl Default for JavaScriptExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for JavaScriptExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["javascript"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        self.delegate().extract(ctx)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        JavaScriptExtractor::new()
            .extract(&ExtractionContext::new(source, "mod.js", "javascript"))
            .expect("javascript extraction")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_top_level_function_with_signature() {
        let syms = extract("function add(a, b) { return a + b; }\n");
        assert_eq!(syms.len(), 1);
        assert_eq!(syms[0].name, "add");
        assert_eq!(syms[0].kind, "function");
        assert_eq!(syms[0].language, "javascript");
        let sig = syms[0].signature.as_deref().expect("signature");
        assert!(sig.contains("(a, b)"), "signature was {sig:?}");
        assert_eq!(syms[0].param_count, 2);
    }

    #[test]
    fn class_with_method_is_promoted_via_method_definition_node() {
        let syms = extract("class Dog { bark() {} }\n");
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
    fn preceding_jsdoc_becomes_docstring() {
        let src = "/** say hi */\nfunction say() {}\n";
        let syms = extract(src);
        assert_eq!(syms.len(), 1);
        let doc = syms[0].docstring.as_deref().expect("docstring");
        assert!(doc.contains("say hi"), "docstring was {doc:?}");
    }

    #[test]
    fn arrow_and_variable_declarator_functions_are_not_extracted() {
        let syms = extract("const f = () => 1;\n");
        assert!(
            syms.is_empty(),
            "expected no symbols for variable-bound arrow, got {syms:?}"
        );
    }

    #[test]
    fn advertises_javascript_language() {
        assert_eq!(JavaScriptExtractor::new().languages(), &["javascript"]);
    }
}
