//! Scala extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the Scala grammar. Emits
//! functions, classes, objects, traits, and val definitions; preceding
//! `//` comments become the docstring.
//!
//! Mirrors the `"scala"` entry in the Python `_tree_sitter_only.py`
//! spec table.

use std::sync::OnceLock;

use sylvan_core::{ExtractionContext, ExtractionError, LanguageExtractor, Symbol};

use crate::extraction::spec::{
    ConstantStrategy, DecoratorStrategy, DocstringStrategy, LanguageSpec, SpecExtractor,
};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[
        ("function_definition", "function"),
        ("class_definition", "class"),
        ("object_definition", "class"),
        ("trait_definition", "type"),
        ("val_definition", "constant"),
    ],
    name_fields: &[
        ("function_definition", "name"),
        ("class_definition", "name"),
        ("object_definition", "name"),
        ("trait_definition", "name"),
        ("val_definition", "pattern"),
    ],
    name_resolutions: &[],
    param_fields: &[],
    return_type_fields: &[],
    container_node_types: &["class_definition", "object_definition", "trait_definition"],
    docstring_strategy: DocstringStrategy::PrecedingComment,
    decorator_strategy: DecoratorStrategy::None,
    constant_strategy: ConstantStrategy::None,
    parameter_kinds: &[],
    method_promotion: &[],
};

/// Built-in Scala extractor.
pub struct ScalaExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl ScalaExtractor {
    /// Construct a fresh instance. Cheap; the tree-sitter language
    /// handle is lazily materialised on first extraction.
    pub fn new() -> Self {
        Self {
            inner: OnceLock::new(),
        }
    }

    fn delegate(&self) -> &SpecExtractor {
        self.inner.get_or_init(|| {
            SpecExtractor::new(&["scala"], crate::grammars::get_language("scala").expect("scala grammar"), &SPEC)
        })
    }
}

impl Default for ScalaExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for ScalaExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["scala"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        self.delegate().extract(ctx)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        ScalaExtractor::new()
            .extract(&ExtractionContext::new(source, "main.scala", "scala"))
            .expect("scala extraction")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_class_definition() {
        let syms = extract("class Greeter {\n  def hi(): Unit = ()\n}\n");
        let class = syms.iter().find(|s| s.name == "Greeter").expect("class");
        assert_eq!(class.kind, "class");
        assert_eq!(class.language, "scala");
    }

    #[test]
    fn advertises_scala_language() {
        let ex = ScalaExtractor::new();
        assert_eq!(ex.languages(), &["scala"]);
    }
}
