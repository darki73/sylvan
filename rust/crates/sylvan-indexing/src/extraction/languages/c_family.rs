//! C and C++ extractor.
//!
//! One file, two grammars. Mirrors `sylvan.indexing.languages.c_family`:
//! C gets function/struct/enum/typedef symbols, C++ layers on classes,
//! namespaces, and template declarations with proper containers for
//! nested symbols. Names live inside declarators rather than a direct
//! `name` field for functions and typedefs, so extraction relies on
//! [`SpecExtractor`]'s child-scan fallback.
//!
//! Features left for later stages (not this spec walker): `#include`
//! extraction, include-path resolution, system-header filtering.

use std::sync::OnceLock;

use sylvan_core::{ExtractionContext, ExtractionError, LanguageExtractor, Symbol};

use crate::extraction::spec::{
    ConstantStrategy, DecoratorStrategy, DocstringStrategy, LanguageSpec, SpecExtractor,
};

const C_PARAMETER_KINDS: &[&str] = &["parameter_declaration", "variadic_parameter"];

static C_SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[
        ("function_definition", "function"),
        ("struct_specifier", "class"),
        ("enum_specifier", "type"),
        ("type_definition", "type"),
    ],
    name_fields: &[
        ("struct_specifier", "name"),
        ("enum_specifier", "name"),
    ],
    param_fields: &[("function_definition", "declarator")],
    return_type_fields: &[("function_definition", "type")],
    container_node_types: &[],
    docstring_strategy: DocstringStrategy::PrecedingComment,
    decorator_strategy: DecoratorStrategy::None,
    constant_strategy: ConstantStrategy::None,
    parameter_kinds: C_PARAMETER_KINDS,
    method_promotion: &[],
};

static CPP_SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[
        ("function_definition", "function"),
        ("class_specifier", "class"),
        ("struct_specifier", "type"),
        ("enum_specifier", "type"),
        ("namespace_definition", "type"),
        ("template_declaration", "template"),
    ],
    name_fields: &[
        ("class_specifier", "name"),
        ("struct_specifier", "name"),
        ("enum_specifier", "name"),
        ("namespace_definition", "name"),
    ],
    param_fields: &[("function_definition", "declarator")],
    return_type_fields: &[("function_definition", "type")],
    container_node_types: &[
        "class_specifier",
        "struct_specifier",
        "namespace_definition",
    ],
    docstring_strategy: DocstringStrategy::PrecedingComment,
    decorator_strategy: DecoratorStrategy::None,
    constant_strategy: ConstantStrategy::None,
    parameter_kinds: C_PARAMETER_KINDS,
    method_promotion: &[],
};

/// Built-in C and C++ extractor.
pub struct CFamilyExtractor {
    c: OnceLock<SpecExtractor>,
    cpp: OnceLock<SpecExtractor>,
}

impl CFamilyExtractor {
    /// Construct a fresh instance.
    pub fn new() -> Self {
        Self {
            c: OnceLock::new(),
            cpp: OnceLock::new(),
        }
    }

    fn c_delegate(&self) -> &SpecExtractor {
        self.c.get_or_init(|| {
            SpecExtractor::new(&["c"], tree_sitter_c::LANGUAGE.into(), &C_SPEC)
        })
    }

    fn cpp_delegate(&self) -> &SpecExtractor {
        self.cpp.get_or_init(|| {
            SpecExtractor::new(&["cpp"], tree_sitter_cpp::LANGUAGE.into(), &CPP_SPEC)
        })
    }
}

impl Default for CFamilyExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for CFamilyExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["c", "cpp"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        match ctx.language {
            "c" => self.c_delegate().extract(ctx),
            "cpp" => self.cpp_delegate().extract(ctx),
            other => Err(ExtractionError::MissingDependency(format!(
                "c_family extractor received unsupported language: {other}"
            ))),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract_c(source: &str) -> Vec<Symbol> {
        CFamilyExtractor::new()
            .extract(&ExtractionContext::new(source, "mod.c", "c"))
            .expect("c extraction")
    }

    fn extract_cpp(source: &str) -> Vec<Symbol> {
        CFamilyExtractor::new()
            .extract(&ExtractionContext::new(source, "mod.cpp", "cpp"))
            .expect("cpp extraction")
    }

    #[test]
    fn empty_c_file_yields_no_symbols() {
        assert!(extract_c("").is_empty());
    }

    #[test]
    fn empty_cpp_file_yields_no_symbols() {
        assert!(extract_cpp("").is_empty());
    }

    #[test]
    fn extracts_c_function() {
        let syms = extract_c("int add(int a, int b) { return a+b; }\n");
        let func = syms
            .iter()
            .find(|s| s.kind == "function")
            .expect("function symbol");
        assert_eq!(func.name, "add");
        assert_eq!(func.language, "c");
        let sig = func.signature.as_deref().expect("signature");
        assert!(sig.contains("add"));
        assert!(sig.contains("int a"));
        assert!(sig.contains("int b"));
    }

    #[test]
    fn extracts_c_struct() {
        let syms = extract_c("struct Point { int x; };\n");
        let s = syms
            .iter()
            .find(|s| s.kind == "class" && s.name == "Point")
            .expect("struct Point");
        assert_eq!(s.language, "c");
    }

    #[test]
    fn extracts_cpp_class() {
        let syms = extract_cpp("class Dog { public: void bark(); };\n");
        let cls = syms
            .iter()
            .find(|s| s.kind == "class" && s.name == "Dog")
            .expect("class Dog");
        assert_eq!(cls.language, "cpp");
    }

    #[test]
    fn c_function_picks_up_preceding_block_comment() {
        let src = "/* doc */\nint x() { return 0; }\n";
        let syms = extract_c(src);
        let func = syms
            .iter()
            .find(|s| s.kind == "function")
            .expect("function symbol");
        let doc = func.docstring.as_deref().unwrap_or("");
        assert!(doc.contains("doc"), "expected docstring to contain 'doc', got {doc:?}");
    }

    #[test]
    fn advertises_c_and_cpp_languages() {
        assert_eq!(CFamilyExtractor::new().languages(), &["c", "cpp"]);
    }
}
