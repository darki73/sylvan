//! Perl extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the Perl grammar. Emits
//! `subroutine_declaration_statement` nodes as functions; preceding `#` comments
//! become the docstring.
//!
//! Mirrors the `"perl"` entry in the Python `_tree_sitter_only.py`
//! spec table.

use std::sync::OnceLock;

use sylvan_core::{ExtractionContext, ExtractionError, LanguageExtractor, Symbol};

use crate::extraction::spec::{
    ConstantStrategy, DecoratorStrategy, DocstringStrategy, LanguageSpec, SpecExtractor,
};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[("subroutine_declaration_statement", "function")],
    name_fields: &[("subroutine_declaration_statement", "name")],
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

/// Built-in Perl extractor.
pub struct PerlExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl PerlExtractor {
    /// Construct a fresh instance. Cheap; the tree-sitter language
    /// handle is lazily materialised on first extraction.
    pub fn new() -> Self {
        Self {
            inner: OnceLock::new(),
        }
    }

    fn delegate(&self) -> &SpecExtractor {
        self.inner.get_or_init(|| {
            SpecExtractor::new(&["perl"], crate::grammars::get_language("perl").expect("perl grammar"), &SPEC)
        })
    }
}

impl Default for PerlExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for PerlExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["perl"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        self.delegate().extract(ctx)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        PerlExtractor::new()
            .extract(&ExtractionContext::new(source, "main.pl", "perl"))
            .expect("perl extraction")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_subroutine_declaration_statement() {
        let syms = extract("sub greet {\n  print \"hi\\n\";\n}\n");
        assert_eq!(syms.len(), 1);
        assert_eq!(syms[0].name, "greet");
        assert_eq!(syms[0].kind, "function");
        assert_eq!(syms[0].language, "perl");
    }

    #[test]
    fn advertises_perl_language() {
        let ex = PerlExtractor::new();
        assert_eq!(ex.languages(), &["perl"]);
    }
}
