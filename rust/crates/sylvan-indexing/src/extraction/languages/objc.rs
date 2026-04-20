//! Objective-C extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the Objective-C grammar.
//! Mirrors the `"objc"` entry in the Python `_tree_sitter_only.py`
//! spec table.

use std::sync::OnceLock;

use sylvan_core::{ExtractionContext, ExtractionError, LanguageExtractor, Symbol};

use crate::extraction::spec::{
    ConstantStrategy, DecoratorStrategy, DocstringStrategy, LanguageSpec, SpecExtractor,
};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[
        ("class_interface", "class"),
        ("class_implementation", "class"),
        ("method_declaration", "method"),
        ("function_definition", "function"),
    ],
    name_fields: &[
        ("class_interface", "name"),
        ("class_implementation", "name"),
        ("method_declaration", "selector"),
        ("function_definition", "declarator"),
    ],
    name_resolutions: &[],
    param_fields: &[],
    return_type_fields: &[],
    container_node_types: &["class_interface", "class_implementation"],
    docstring_strategy: DocstringStrategy::PrecedingComment,
    decorator_strategy: DecoratorStrategy::None,
    constant_strategy: ConstantStrategy::None,
    parameter_kinds: &[],
    method_promotion: &[],
};

/// Built-in Objective-C extractor.
pub struct ObjCExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl ObjCExtractor {
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
                &["objc"],
                crate::grammars::get_language("objc").expect("objc grammar"),
                &SPEC,
            )
        })
    }
}

impl Default for ObjCExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for ObjCExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["objc"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        self.delegate().extract(ctx)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        ObjCExtractor::new()
            .extract(&ExtractionContext::new(source, "Thing.m", "objc"))
            .expect("objc extraction")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_class_interface() {
        let syms = extract("@interface Thing : NSObject\n@end\n");
        assert!(syms.iter().any(|s| s.name == "Thing" && s.kind == "class"));
    }

    #[test]
    fn advertises_objc_language() {
        let ex = ObjCExtractor::new();
        assert_eq!(ex.languages(), &["objc"]);
    }
}
