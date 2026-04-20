//! Gleam extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the Gleam grammar. Symbols
//! come from `function`, `type_definition`, and `constant` nodes;
//! preceding `// ...` comments become the docstring.
//!
//! Mirrors the `"gleam"` entry in the Python `_tree_sitter_only.py`
//! spec table.

use std::sync::OnceLock;

use sylvan_core::{ExtractionContext, ExtractionError, LanguageExtractor, Symbol};

use crate::extraction::spec::{
    ConstantStrategy, DecoratorStrategy, DocstringStrategy, LanguageSpec, SpecExtractor,
};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[
        ("function", "function"),
        ("type_definition", "type"),
        ("constant", "constant"),
    ],
    name_fields: &[
        ("function", "name"),
        ("type_definition", "name"),
        ("constant", "name"),
    ],
    name_resolutions: &[],
    param_fields: &[],
    return_type_fields: &[],
    container_node_types: &[],
    docstring_strategy: DocstringStrategy::PrecedingComment,
    decorator_strategy: DecoratorStrategy::None,
    constant_strategy: ConstantStrategy::None,
    parameter_kinds: &[],
    method_promotion: &[],
};

/// Built-in Gleam extractor.
pub struct GleamExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl GleamExtractor {
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
                &["gleam"],
                crate::grammars::get_language("gleam").expect("gleam grammar"),
                &SPEC,
            )
        })
    }
}

impl Default for GleamExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for GleamExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["gleam"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        self.delegate().extract(ctx)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        GleamExtractor::new()
            .extract(&ExtractionContext::new(source, "main.gleam", "gleam"))
            .expect("gleam extraction")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_function() {
        let syms = extract("pub fn greet(name: String) -> String {\n  name\n}\n");
        assert!(syms.iter().any(|s| s.name == "greet" && s.kind == "function"));
    }

    #[test]
    fn advertises_gleam_language() {
        let ex = GleamExtractor::new();
        assert_eq!(ex.languages(), &["gleam"]);
    }
}
