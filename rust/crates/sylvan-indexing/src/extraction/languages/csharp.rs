//! C# extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the C# grammar. Mirrors the
//! Python plugin in `sylvan.indexing.languages.csharp`: class, interface,
//! struct, enum, and method declarations, signature stitching, preceding
//! `///` / `//` / `/* */` docstrings, `[Attribute]` byte-range expansion,
//! and `field_declaration` / `property_declaration` treated as
//! constant-like top-level patterns.
//!
//! Import extraction, PSR-style candidate generation, and complexity
//! scoring live outside this walker and are not ported here.

use std::sync::OnceLock;

use sylvan_core::{ExtractionContext, ExtractionError, LanguageExtractor, Symbol};

use crate::extraction::spec::{
    ConstantStrategy, DecoratorStrategy, DocstringStrategy, LanguageSpec, ModifierLocation,
    SpecExtractor,
};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[
        ("method_declaration", "method"),
        ("class_declaration", "class"),
        ("interface_declaration", "type"),
        ("struct_declaration", "class"),
        ("enum_declaration", "type"),
    ],
    name_fields: &[
        ("method_declaration", "name"),
        ("class_declaration", "name"),
        ("interface_declaration", "name"),
        ("struct_declaration", "name"),
        ("enum_declaration", "name"),
    ],
    param_fields: &[("method_declaration", "parameters")],
    return_type_fields: &[("method_declaration", "type")],
    container_node_types: &[
        "class_declaration",
        "interface_declaration",
        "struct_declaration",
        "enum_declaration",
    ],
    docstring_strategy: DocstringStrategy::PrecedingComment,
    decorator_strategy: DecoratorStrategy::PrecedingSiblings {
        kinds: &["attribute_list"],
    },
    constant_strategy: ConstantStrategy::ModifiedField {
        field_kinds: &["field_declaration"],
        modifiers: ModifierLocation::DirectByText { kind: "modifier" },
        required_modifiers: &["const"],
        declarator_kind: "variable_declarator",
        name_field: "name",
        uppercase_only: false,
    },
    parameter_kinds: &["parameter"],
    method_promotion: &[],
};

/// Built-in C# extractor.
pub struct CSharpExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl CSharpExtractor {
    /// Construct a fresh instance.
    pub fn new() -> Self {
        Self {
            inner: OnceLock::new(),
        }
    }

    fn delegate(&self) -> &SpecExtractor {
        self.inner.get_or_init(|| {
            SpecExtractor::new(&["csharp"], tree_sitter_c_sharp::LANGUAGE.into(), &SPEC)
        })
    }
}

impl Default for CSharpExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for CSharpExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["csharp"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        self.delegate().extract(ctx)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        CSharpExtractor::new()
            .extract(&ExtractionContext::new(source, "mod.cs", "csharp"))
            .expect("csharp extraction")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_class_with_method() {
        let syms = extract("class Dog { public void Bark() {} }");
        let cls = syms.iter().find(|s| s.kind == "class").expect("class");
        let method = syms.iter().find(|s| s.kind == "method").expect("method");
        assert_eq!(cls.name, "Dog");
        assert_eq!(method.name, "Bark");
        assert_eq!(method.qualified_name, "Dog.Bark");
        assert_eq!(method.parent_symbol_id.as_deref(), Some(cls.symbol_id.as_str()));
    }

    #[test]
    fn extracts_interface() {
        let syms = extract("interface IFoo { void Do(); }");
        let iface = syms.iter().find(|s| s.kind == "type").expect("interface");
        assert_eq!(iface.name, "IFoo");
    }

    #[test]
    fn preceding_doc_comment_becomes_docstring() {
        let src = "/// doc\nclass X {}\n";
        let syms = extract(src);
        let cls = syms.iter().find(|s| s.kind == "class").expect("class");
        assert!(
            cls.docstring.as_deref().unwrap_or("").contains("doc"),
            "expected docstring to contain 'doc', got {:?}",
            cls.docstring
        );
    }

    #[test]
    fn advertises_csharp_language() {
        assert_eq!(CSharpExtractor::new().languages(), &["csharp"]);
    }

    #[test]
    fn const_field_emits_constant_under_class() {
        let src = "class C { public const int Max = 10; }";
        let syms = extract(src);
        let cls = syms.iter().find(|s| s.kind == "class").expect("class");
        let c = syms
            .iter()
            .find(|s| s.kind == "constant" && s.name == "Max")
            .expect("constant");
        assert_eq!(c.qualified_name, "C.Max");
        assert_eq!(c.parent_symbol_id.as_deref(), Some(cls.symbol_id.as_str()));
    }

    #[test]
    fn non_const_field_is_not_a_constant() {
        let src = "class C { public int Mutable = 0; }";
        let syms = extract(src);
        assert!(syms.iter().all(|s| s.kind != "constant"));
    }
}
