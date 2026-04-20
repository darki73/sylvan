//! Nix extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the Nix grammar. Nix has
//! one symbol-producing node type (`binding`) and no containers;
//! preceding `# ...` comments become the docstring.
//!
//! Mirrors the `"nix"` entry in the Python `_tree_sitter_only.py`
//! spec table.

use std::sync::OnceLock;

use sylvan_core::{ExtractionContext, ExtractionError, LanguageExtractor, Symbol};

use crate::extraction::spec::{
    ConstantStrategy, DecoratorStrategy, DocstringStrategy, LanguageSpec, SpecExtractor,
};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[("binding", "function")],
    name_fields: &[("binding", "attrpath")],
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

/// Built-in Nix extractor.
pub struct NixExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl NixExtractor {
    /// Construct a fresh instance. Cheap; the tree-sitter language
    /// handle is lazily materialised on first extraction.
    pub fn new() -> Self {
        Self {
            inner: OnceLock::new(),
        }
    }

    fn delegate(&self) -> &SpecExtractor {
        self.inner.get_or_init(|| {
            SpecExtractor::new(&["nix"], crate::grammars::get_language("nix").expect("nix grammar"), &SPEC)
        })
    }
}

impl Default for NixExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for NixExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["nix"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        self.delegate().extract(ctx)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        NixExtractor::new()
            .extract(&ExtractionContext::new(source, "default.nix", "nix"))
            .expect("nix extraction")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_binding() {
        let syms = extract("{ greet = \"hi\"; }\n");
        assert_eq!(syms.len(), 1);
        assert_eq!(syms[0].kind, "function");
        assert_eq!(syms[0].language, "nix");
    }

    #[test]
    fn advertises_nix_language() {
        let ex = NixExtractor::new();
        assert_eq!(ex.languages(), &["nix"]);
    }
}
