//! Julia extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the Julia grammar.
//! - `function_definition`: name is nested under `signature >
//!   call_expression > identifier[0]`.
//! - `struct_definition`: name is under `type_head > identifier[0]`.
//! - `module_definition`: name is a labeled `name` field.
//!
//! The short form (`greet(x) = expr`) parses as an `assignment` node
//! rather than a dedicated function-definition node, so it is not
//! extracted here; the surrounding context disambiguates assignment
//! from definition and belongs in a richer analysis pass.

use std::sync::OnceLock;

use sylvan_core::{ExtractionContext, ExtractionError, LanguageExtractor, Symbol};

use crate::extraction::spec::{
    ConstantStrategy, DecoratorStrategy, DocstringStrategy, LanguageSpec, NameLeaf,
    NameResolution, SpecExtractor,
};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[
        ("function_definition", "function"),
        ("struct_definition", "type"),
        ("module_definition", "type"),
    ],
    name_fields: &[("module_definition", "name")],
    name_resolutions: &[
        (
            "function_definition",
            NameResolution::Descend {
                path: &["signature", "call_expression"],
                leaf: NameLeaf::Identifier,
            },
        ),
        (
            "struct_definition",
            NameResolution::Descend {
                path: &["type_head"],
                leaf: NameLeaf::Identifier,
            },
        ),
    ],
    param_fields: &[],
    return_type_fields: &[],
    container_node_types: &[],
    docstring_strategy: DocstringStrategy::PrecedingComment,
    decorator_strategy: DecoratorStrategy::None,
    constant_strategy: ConstantStrategy::None,
    parameter_kinds: &[],
    method_promotion: &[],
};

/// Built-in Julia extractor.
pub struct JuliaExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl JuliaExtractor {
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
                &["julia"],
                crate::grammars::get_language("julia").expect("julia grammar"),
                &SPEC,
            )
        })
    }
}

impl Default for JuliaExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for JuliaExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["julia"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        self.delegate().extract(ctx)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        JuliaExtractor::new()
            .extract(&ExtractionContext::new(source, "script.jl", "julia"))
            .expect("julia extraction")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_function_definition() {
        let syms = extract("function greet()\n  println(\"hi\")\nend\n");
        assert!(syms
            .iter()
            .any(|s| s.name == "greet" && s.kind == "function"));
    }

    #[test]
    fn extracts_struct_definition() {
        let syms = extract("struct Point\n  x::Int\n  y::Int\nend\n");
        assert!(syms.iter().any(|s| s.name == "Point" && s.kind == "type"));
    }

    #[test]
    fn extracts_module_definition() {
        let syms = extract("module Foo\nend\n");
        assert!(syms.iter().any(|s| s.name == "Foo" && s.kind == "type"));
    }

    #[test]
    fn advertises_julia_language() {
        let ex = JuliaExtractor::new();
        assert_eq!(ex.languages(), &["julia"]);
    }
}
