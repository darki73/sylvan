//! Haskell extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the Haskell grammar. Symbols
//! come from `function` and `signature` nodes; preceding `-- ...`
//! comments become the docstring.
//!
//! Mirrors the `"haskell"` entry in the Python `_tree_sitter_only.py`
//! spec table.

use std::sync::OnceLock;

use sylvan_core::{ExtractionContext, ExtractionError, LanguageExtractor, Symbol};

use crate::extraction::spec::{
    ConstantStrategy, DecoratorStrategy, DocstringStrategy, LanguageSpec, SpecExtractor,
};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[("function", "function"), ("signature", "type")],
    name_fields: &[("function", "name"), ("signature", "name")],
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

/// Built-in Haskell extractor.
pub struct HaskellExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl HaskellExtractor {
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
                &["haskell"],
                crate::grammars::get_language("haskell").expect("haskell grammar"),
                &SPEC,
            )
        })
    }
}

impl Default for HaskellExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for HaskellExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["haskell"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        self.delegate().extract(ctx)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        HaskellExtractor::new()
            .extract(&ExtractionContext::new(source, "Main.hs", "haskell"))
            .expect("haskell extraction")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_function_definition() {
        let syms = extract("greet x = x\n");
        assert!(!syms.is_empty());
        assert!(syms.iter().any(|s| s.name == "greet" && s.language == "haskell"));
    }

    #[test]
    fn advertises_haskell_language() {
        let ex = HaskellExtractor::new();
        assert_eq!(ex.languages(), &["haskell"]);
    }
}
