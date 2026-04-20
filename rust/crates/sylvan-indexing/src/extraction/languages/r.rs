//! R extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the R grammar. R has one
//! symbol-producing node type (`function_definition`) and no
//! containers; preceding `# ...` comments become the docstring.
//!
//! Mirrors the `"r"` entry in the Python `_tree_sitter_only.py`
//! spec table.

use std::sync::OnceLock;

use sylvan_core::{ExtractionContext, ExtractionError, LanguageExtractor, Symbol};

use crate::extraction::spec::{
    ConstantStrategy, DecoratorStrategy, DocstringStrategy, LanguageSpec, SpecExtractor,
};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[("function_definition", "function")],
    name_fields: &[("function_definition", "name")],
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

/// Built-in R extractor.
pub struct RExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl RExtractor {
    /// Construct a fresh instance. Cheap; the tree-sitter language
    /// handle is lazily materialised on first extraction.
    pub fn new() -> Self {
        Self {
            inner: OnceLock::new(),
        }
    }

    fn delegate(&self) -> &SpecExtractor {
        self.inner.get_or_init(|| {
            SpecExtractor::new(&["r"], crate::grammars::get_language("r").expect("r grammar"), &SPEC)
        })
    }
}

impl Default for RExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for RExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["r"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        self.delegate().extract(ctx)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        RExtractor::new()
            .extract(&ExtractionContext::new(source, "script.R", "r"))
            .expect("r extraction")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_function_definition() {
        let syms = extract("greet <- function() {\n  print(\"hi\")\n}\n");
        assert!(syms.iter().any(|s| s.kind == "function"));
        assert_eq!(syms[0].language, "r");
    }

    #[test]
    fn advertises_r_language() {
        let ex = RExtractor::new();
        assert_eq!(ex.languages(), &["r"]);
    }
}
