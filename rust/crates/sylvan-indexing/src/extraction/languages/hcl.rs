//! HCL / Terraform extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the HCL grammar. Symbols come
//! from `block` nodes named by their `type` field; preceding `# ...`
//! comments become the docstring.
//!
//! Mirrors the `"hcl"` entry in the Python `_tree_sitter_only.py` spec
//! table.

use std::sync::OnceLock;

use sylvan_core::{ExtractionContext, ExtractionError, LanguageExtractor, Symbol};

use crate::extraction::spec::{
    ConstantStrategy, DecoratorStrategy, DocstringStrategy, LanguageSpec, SpecExtractor,
};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[("block", "type")],
    name_fields: &[("block", "type")],
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

/// Built-in HCL extractor.
pub struct HclExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl HclExtractor {
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
                &["hcl"],
                crate::grammars::get_language("hcl").expect("hcl grammar"),
                &SPEC,
            )
        })
    }
}

impl Default for HclExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for HclExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["hcl"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        self.delegate().extract(ctx)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        HclExtractor::new()
            .extract(&ExtractionContext::new(source, "main.tf", "hcl"))
            .expect("hcl extraction")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_block() {
        let syms = extract("resource \"aws_instance\" \"web\" {\n  ami = \"abc\"\n}\n");
        assert!(!syms.is_empty());
        assert_eq!(syms[0].language, "hcl");
    }

    #[test]
    fn advertises_hcl_language() {
        let ex = HclExtractor::new();
        assert_eq!(ex.languages(), &["hcl"]);
    }
}
