//! Dart extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the Dart grammar. Emits
//! function and method signatures, classes, mixins, enums, and
//! extensions; preceding `//` comments become the docstring.
//!
//! Mirrors the `"dart"` entry in the Python `_tree_sitter_only.py`
//! spec table.

use std::sync::OnceLock;

use sylvan_core::{ExtractionContext, ExtractionError, LanguageExtractor, Symbol};

use crate::extraction::spec::{
    ConstantStrategy, DecoratorStrategy, DocstringStrategy, LanguageSpec, SpecExtractor,
};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[
        ("function_signature", "function"),
        ("method_signature", "method"),
        ("class_definition", "class"),
        ("mixin_declaration", "type"),
        ("enum_declaration", "type"),
        ("extension_declaration", "type"),
    ],
    name_fields: &[
        ("function_signature", "name"),
        ("method_signature", "name"),
        ("class_definition", "name"),
        ("mixin_declaration", "name"),
        ("enum_declaration", "name"),
        ("extension_declaration", "name"),
    ],
    name_resolutions: &[],
    param_fields: &[],
    return_type_fields: &[],
    container_node_types: &["class_definition", "mixin_declaration"],
    docstring_strategy: DocstringStrategy::PrecedingComment,
    decorator_strategy: DecoratorStrategy::None,
    constant_strategy: ConstantStrategy::None,
    parameter_kinds: &[],
    method_promotion: &[],
};

/// Built-in Dart extractor.
pub struct DartExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl DartExtractor {
    /// Construct a fresh instance. Cheap; the tree-sitter language
    /// handle is lazily materialised on first extraction.
    pub fn new() -> Self {
        Self {
            inner: OnceLock::new(),
        }
    }

    fn delegate(&self) -> &SpecExtractor {
        self.inner.get_or_init(|| {
            SpecExtractor::new(&["dart"], crate::grammars::get_language("dart").expect("dart grammar"), &SPEC)
        })
    }
}

impl Default for DartExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for DartExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["dart"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        self.delegate().extract(ctx)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        DartExtractor::new()
            .extract(&ExtractionContext::new(source, "main.dart", "dart"))
            .expect("dart extraction")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_class_definition() {
        let syms = extract("class Greeter {}\n");
        let class = syms.iter().find(|s| s.name == "Greeter").expect("class");
        assert_eq!(class.kind, "class");
        assert_eq!(class.language, "dart");
    }

    #[test]
    fn advertises_dart_language() {
        let ex = DartExtractor::new();
        assert_eq!(ex.languages(), &["dart"]);
    }
}
