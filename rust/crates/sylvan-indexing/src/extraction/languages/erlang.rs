//! Erlang extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the Erlang grammar. Symbols
//! come from `function_clause` nodes; preceding `% ...` comments become
//! the docstring.
//!
//! Mirrors the `"erlang"` entry in the Python `_tree_sitter_only.py`
//! spec table.

use std::sync::OnceLock;

use sylvan_core::{ExtractionContext, ExtractionError, LanguageExtractor, Symbol};

use crate::extraction::spec::{
    ConstantStrategy, DecoratorStrategy, DocstringStrategy, LanguageSpec, SpecExtractor,
};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[("function_clause", "function")],
    name_fields: &[("function_clause", "name")],
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

/// Built-in Erlang extractor.
pub struct ErlangExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl ErlangExtractor {
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
                &["erlang"],
                crate::grammars::get_language("erlang").expect("erlang grammar"),
                &SPEC,
            )
        })
    }
}

impl Default for ErlangExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for ErlangExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["erlang"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        self.delegate().extract(ctx)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        ErlangExtractor::new()
            .extract(&ExtractionContext::new(source, "mod.erl", "erlang"))
            .expect("erlang extraction")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_function_clause() {
        let syms = extract("-module(mod).\ngreet(X) -> X.\n");
        assert!(syms.iter().any(|s| s.name == "greet" && s.kind == "function"));
    }

    #[test]
    fn advertises_erlang_language() {
        let ex = ErlangExtractor::new();
        assert_eq!(ex.languages(), &["erlang"]);
    }
}
