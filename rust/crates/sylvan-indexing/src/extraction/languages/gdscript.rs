//! GDScript extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the GDScript grammar.
//! GDScript has two symbol-producing node types (`function_definition`
//! and `class_definition`); `class_definition` also acts as a
//! container. Preceding `# ...` comments become the docstring.
//!
//! Mirrors the `"gdscript"` entry in the Python `_tree_sitter_only.py`
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
    ],
    name_fields: &[
        ("function_definition", "name"),
        ("class_definition", "name"),
    ],
    name_resolutions: &[],
    param_fields: &[],
    return_type_fields: &[],
    container_node_types: &["class_definition"],
    docstring_strategy: DocstringStrategy::PrecedingComment,
    decorator_strategy: DecoratorStrategy::None,
    constant_strategy: ConstantStrategy::None,
    parameter_kinds: &[],
    method_promotion: &[],
};

/// Built-in GDScript extractor.
pub struct GdscriptExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl GdscriptExtractor {
    /// Construct a fresh instance. Cheap; the tree-sitter language
    /// handle is lazily materialised on first extraction.
    pub fn new() -> Self {
        Self {
            inner: OnceLock::new(),
        }
    }

    fn delegate(&self) -> &SpecExtractor {
        self.inner.get_or_init(|| {
            SpecExtractor::new(&["gdscript"], crate::grammars::get_language("gdscript").expect("gdscript grammar"), &SPEC)
        })
    }
}

impl Default for GdscriptExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for GdscriptExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["gdscript"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        self.delegate().extract(ctx)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        GdscriptExtractor::new()
            .extract(&ExtractionContext::new(source, "script.gd", "gdscript"))
            .expect("gdscript extraction")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_function_definition() {
        let syms = extract("func greet():\n\tprint(\"hi\")\n");
        assert!(syms.iter().any(|s| s.name == "greet" && s.kind == "function"));
        assert_eq!(syms[0].language, "gdscript");
    }

    #[test]
    fn advertises_gdscript_language() {
        let ex = GdscriptExtractor::new();
        assert_eq!(ex.languages(), &["gdscript"]);
    }
}
