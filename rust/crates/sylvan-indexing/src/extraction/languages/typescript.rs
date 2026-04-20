//! TypeScript and TSX extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the two grammars exposed by
//! `tree-sitter-typescript`. A single [`LanguageSpec`] drives both, so
//! `.ts` and `.tsx` share symbol-node coverage and only differ in the
//! underlying parser.
//!
//! The spec mirrors the Python JavaScript plugin: function / class /
//! method symbols with preceding-comment docstrings, class containers
//! for method scoping, no decorator wrapper, no constant extraction.

use std::sync::OnceLock;

use sylvan_core::{ExtractionContext, ExtractionError, LanguageExtractor, Symbol};

use crate::extraction::spec::{DocstringStrategy, LanguageSpec, SpecExtractor};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[
        ("function_declaration", "function"),
        ("class_declaration", "class"),
        ("method_definition", "method"),
        ("interface_declaration", "type"),
        ("type_alias_declaration", "type"),
        ("enum_declaration", "type"),
    ],
    name_fields: &[
        ("function_declaration", "name"),
        ("class_declaration", "name"),
        ("method_definition", "name"),
        ("interface_declaration", "name"),
        ("type_alias_declaration", "name"),
        ("enum_declaration", "name"),
    ],
    param_fields: &[
        ("function_declaration", "parameters"),
        ("method_definition", "parameters"),
    ],
    return_type_fields: &[
        ("function_declaration", "return_type"),
        ("method_definition", "return_type"),
    ],
    container_node_types: &["class_declaration", "class"],
    docstring_strategy: DocstringStrategy::PrecedingComment,
    decorator_node_type: None,
    constant_patterns: &[],
    method_promotion: &[],
};

/// Built-in TypeScript / TSX extractor.
pub struct TypeScriptExtractor {
    ts_extractor: OnceLock<SpecExtractor>,
    tsx_extractor: OnceLock<SpecExtractor>,
}

impl TypeScriptExtractor {
    /// Construct a fresh instance.
    pub fn new() -> Self {
        Self {
            ts_extractor: OnceLock::new(),
            tsx_extractor: OnceLock::new(),
        }
    }

    fn ts_delegate(&self) -> &SpecExtractor {
        self.ts_extractor.get_or_init(|| {
            SpecExtractor::new(
                &["typescript"],
                tree_sitter_typescript::LANGUAGE_TYPESCRIPT.into(),
                &SPEC,
            )
        })
    }

    fn tsx_delegate(&self) -> &SpecExtractor {
        self.tsx_extractor.get_or_init(|| {
            SpecExtractor::new(
                &["tsx"],
                tree_sitter_typescript::LANGUAGE_TSX.into(),
                &SPEC,
            )
        })
    }
}

impl Default for TypeScriptExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for TypeScriptExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["typescript", "tsx"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        match ctx.language {
            "typescript" => self.ts_delegate().extract(ctx),
            "tsx" => self.tsx_delegate().extract(ctx),
            _ => Ok(Vec::new()),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract_ts(source: &str) -> Vec<Symbol> {
        TypeScriptExtractor::new()
            .extract(&ExtractionContext::new(source, "mod.ts", "typescript"))
            .expect("typescript extraction")
    }

    fn extract_tsx(source: &str, filename: &str) -> Vec<Symbol> {
        TypeScriptExtractor::new()
            .extract(&ExtractionContext::new(source, filename, "tsx"))
            .expect("tsx extraction")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract_ts("").is_empty());
    }

    #[test]
    fn extracts_typed_function_with_signature() {
        let src = "function add(a: number, b: number): number { return a+b; }\n";
        let syms = extract_ts(src);
        assert_eq!(syms.len(), 1);
        let sym = &syms[0];
        assert_eq!(sym.name, "add");
        assert_eq!(sym.kind, "function");
        assert_eq!(sym.language, "typescript");
        let sig = sym.signature.as_deref().expect("signature");
        assert!(sig.contains("(a: number, b: number)"));
        assert!(sig.contains("number"));
    }

    #[test]
    fn class_with_method_is_extracted() {
        let src = "class Dog { bark() {} }\n";
        let syms = extract_ts(src);
        let cls = syms.iter().find(|s| s.kind == "class").expect("class");
        let method = syms.iter().find(|s| s.kind == "method").expect("method");
        assert_eq!(cls.name, "Dog");
        assert_eq!(method.name, "bark");
        assert_eq!(method.qualified_name, "Dog.bark");
        assert_eq!(
            method.parent_symbol_id.as_deref(),
            Some(cls.symbol_id.as_str())
        );
    }

    #[test]
    fn tsx_grammar_parses_jsx_without_emitting_arrow_const() {
        let syms = extract_tsx("const X = () => <div/>;\n", "mod.tsx");
        assert!(syms.is_empty());
    }

    #[test]
    fn advertises_typescript_and_tsx_languages() {
        assert_eq!(
            TypeScriptExtractor::new().languages(),
            &["typescript", "tsx"]
        );
    }
}
