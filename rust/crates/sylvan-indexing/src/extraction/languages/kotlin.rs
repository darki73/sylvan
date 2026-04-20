//! Kotlin extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the Kotlin grammar. The
//! tree-sitter-kotlin grammar shipped in the language pack exposes a
//! flatter shape than most other C-family grammars: classes,
//! interfaces, and enums all surface as `class_declaration`, and the
//! declaration's name arrives as an unlabeled `type_identifier` child
//! rather than through a named field. Functions follow the same
//! pattern with `simple_identifier` as the name-bearing child.
//!
//! `object` declarations and trailing lambdas fall through the
//! grammar as `infix_expression` / `object_literal` rather than a
//! dedicated declaration node, so we do not emit them here — there
//! simply is no reliable top-level node to key on.

use std::sync::OnceLock;

use sylvan_core::{ExtractionContext, ExtractionError, LanguageExtractor, Symbol};

use crate::extraction::spec::{
    ConstantStrategy, DecoratorStrategy, DocstringStrategy, LanguageSpec, NameResolution,
    SpecExtractor,
};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[
        ("function_declaration", "function"),
        ("class_declaration", "class"),
    ],
    name_fields: &[],
    name_resolutions: &[
        ("function_declaration", NameResolution::ChildKind("simple_identifier")),
        ("class_declaration", NameResolution::ChildKind("type_identifier")),
    ],
    param_fields: &[("function_declaration", "function_value_parameters")],
    return_type_fields: &[],
    container_node_types: &["class_declaration"],
    docstring_strategy: DocstringStrategy::PrecedingComment,
    decorator_strategy: DecoratorStrategy::None,
    constant_strategy: ConstantStrategy::None,
    parameter_kinds: &[],
    method_promotion: &[],
};

/// Built-in Kotlin extractor.
pub struct KotlinExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl KotlinExtractor {
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
                &["kotlin"],
                crate::grammars::get_language("kotlin").expect("kotlin grammar"),
                &SPEC,
            )
        })
    }
}

impl Default for KotlinExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for KotlinExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["kotlin"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        self.delegate().extract(ctx)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        KotlinExtractor::new()
            .extract(&ExtractionContext::new(source, "App.kt", "kotlin"))
            .expect("kotlin extraction")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_class_and_method() {
        let src = "class Greeter {\n  fun greet(name: String): String { return name }\n}\n";
        let syms = extract(src);
        assert!(syms.iter().any(|s| s.name == "Greeter" && s.kind == "class"));
        assert!(syms.iter().any(|s| s.name == "greet"));
    }

    #[test]
    fn extracts_interface_as_class() {
        let syms = extract("interface Shape { fun area(): Double }\n");
        assert!(syms.iter().any(|s| s.name == "Shape" && s.kind == "class"));
    }

    #[test]
    fn advertises_kotlin_language() {
        assert_eq!(KotlinExtractor::new().languages(), &["kotlin"]);
    }
}
