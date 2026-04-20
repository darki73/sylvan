//! Fortran extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the Fortran grammar. Each
//! symbol-producing node exposes its name through a mandatory header
//! child: `module > module_statement > name`,
//! `program > program_statement > name`,
//! `function > function_statement[name]`,
//! `subroutine > subroutine_statement[name]`. Preceding `! ...`
//! comments become the docstring.

use std::sync::OnceLock;

use sylvan_core::{ExtractionContext, ExtractionError, LanguageExtractor, Symbol};

use crate::extraction::spec::{
    ConstantStrategy, DecoratorStrategy, DocstringStrategy, LanguageSpec, NameLeaf,
    NameResolution, SpecExtractor,
};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[
        ("function", "function"),
        ("subroutine", "function"),
        ("module", "type"),
        ("program", "type"),
    ],
    name_fields: &[],
    name_resolutions: &[
        (
            "module",
            NameResolution::Descend {
                path: &["module_statement"],
                leaf: NameLeaf::ChildKind("name"),
            },
        ),
        (
            "program",
            NameResolution::Descend {
                path: &["program_statement"],
                leaf: NameLeaf::ChildKind("name"),
            },
        ),
        (
            "function",
            NameResolution::Descend {
                path: &["function_statement"],
                leaf: NameLeaf::Field("name"),
            },
        ),
        (
            "subroutine",
            NameResolution::Descend {
                path: &["subroutine_statement"],
                leaf: NameLeaf::Field("name"),
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

/// Built-in Fortran extractor.
pub struct FortranExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl FortranExtractor {
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
                &["fortran"],
                crate::grammars::get_language("fortran").expect("fortran grammar"),
                &SPEC,
            )
        })
    }
}

impl Default for FortranExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for FortranExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["fortran"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        self.delegate().extract(ctx)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        FortranExtractor::new()
            .extract(&ExtractionContext::new(source, "mod.f90", "fortran"))
            .expect("fortran extraction")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_module_definition() {
        let syms = extract("module greeter\nend module greeter\n");
        assert!(syms
            .iter()
            .any(|s| s.name == "greeter" && s.kind == "type"));
    }

    #[test]
    fn extracts_program_definition() {
        let syms = extract("program hello\nend program\n");
        assert!(syms.iter().any(|s| s.name == "hello" && s.kind == "type"));
    }

    #[test]
    fn extracts_function_and_subroutine() {
        let syms = extract(
            "function f(x)\n  integer :: x\n  f = x\nend function\n\
             subroutine s(x)\nend subroutine\n",
        );
        assert!(syms.iter().any(|s| s.name == "f" && s.kind == "function"));
        assert!(syms.iter().any(|s| s.name == "s" && s.kind == "function"));
    }

    #[test]
    fn advertises_fortran_language() {
        let ex = FortranExtractor::new();
        assert_eq!(ex.languages(), &["fortran"]);
    }
}
