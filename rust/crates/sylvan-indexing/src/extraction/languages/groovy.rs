//! Groovy extractor.
//!
//! The `tree-sitter-groovy` grammar is a token-stream grammar: classes,
//! methods, and control flow all parse as nested `command` / `unit` /
//! `block` nodes with the `class` / `def` keywords appearing as plain
//! `identifier` leaves. There is no structural `class_definition` /
//! `method_declaration` / `function_definition` node, which means
//! name-based symbol extraction cannot be expressed via
//! [`LanguageSpec`]. We register the extractor so the pipeline still
//! recognises `.groovy` / `.gradle` files as Groovy, but the symbol
//! pass yields nothing until a text-pattern strategy is added.

use std::sync::OnceLock;

use sylvan_core::{ExtractionContext, ExtractionError, LanguageExtractor, Symbol};

use crate::extraction::spec::{
    ConstantStrategy, DecoratorStrategy, DocstringStrategy, LanguageSpec, SpecExtractor,
};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[],
    name_fields: &[],
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

/// Built-in Groovy extractor. Parses the source but emits no symbols
/// because of a grammar limitation; see the module-level doc.
pub struct GroovyExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl GroovyExtractor {
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
                &["groovy"],
                crate::grammars::get_language("groovy").expect("groovy grammar"),
                &SPEC,
            )
        })
    }
}

impl Default for GroovyExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for GroovyExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["groovy"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        self.delegate().extract(ctx)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        GroovyExtractor::new()
            .extract(&ExtractionContext::new(source, "build.groovy", "groovy"))
            .expect("groovy extraction")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn parses_without_panicking() {
        // Grammar limitation: no structural class/method nodes, so no
        // symbols are emitted. This test guards against regressions
        // that would reintroduce a panic on real Groovy source.
        let _ = extract("class Greeter {\n  def hello() { println 'hi' }\n}\n");
    }

    #[test]
    fn advertises_groovy_language() {
        let ex = GroovyExtractor::new();
        assert_eq!(ex.languages(), &["groovy"]);
    }
}
