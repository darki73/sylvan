//! Elixir extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the Elixir grammar. Emits
//! functions via the `call` node type (e.g. `def foo`), reading the
//! name from the `target` field; preceding `#` comments become the
//! docstring.
//!
//! Mirrors the `"elixir"` entry in the Python `_tree_sitter_only.py`
//! spec table.

use std::sync::OnceLock;

use sylvan_core::{ExtractionContext, ExtractionError, LanguageExtractor, Symbol};

use crate::extraction::spec::{
    ConstantStrategy, DecoratorStrategy, DocstringStrategy, LanguageSpec, SpecExtractor,
};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[("call", "function")],
    name_fields: &[("call", "target")],
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

/// Built-in Elixir extractor.
pub struct ElixirExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl ElixirExtractor {
    /// Construct a fresh instance. Cheap; the tree-sitter language
    /// handle is lazily materialised on first extraction.
    pub fn new() -> Self {
        Self {
            inner: OnceLock::new(),
        }
    }

    fn delegate(&self) -> &SpecExtractor {
        self.inner.get_or_init(|| {
            SpecExtractor::new(&["elixir"], crate::grammars::get_language("elixir").expect("elixir grammar"), &SPEC)
        })
    }
}

impl Default for ElixirExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for ElixirExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["elixir"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        self.delegate().extract(ctx)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        ElixirExtractor::new()
            .extract(&ExtractionContext::new(source, "main.ex", "elixir"))
            .expect("elixir extraction")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_call_as_function() {
        let syms = extract("defmodule Greeter do\n  def hi, do: :ok\nend\n");
        assert!(!syms.is_empty());
        assert!(syms.iter().any(|s| s.kind == "function"));
        assert!(syms.iter().all(|s| s.language == "elixir"));
    }

    #[test]
    fn advertises_elixir_language() {
        let ex = ElixirExtractor::new();
        assert_eq!(ex.languages(), &["elixir"]);
    }
}
