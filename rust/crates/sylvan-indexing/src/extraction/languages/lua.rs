//! Lua extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the Lua grammar. Emits
//! `function_declaration` nodes as functions; preceding `--` comments
//! become the docstring.
//!
//! Mirrors the `"lua"` entry in the Python `_tree_sitter_only.py`
//! spec table.

use std::sync::OnceLock;

use sylvan_core::{ExtractionContext, ExtractionError, LanguageExtractor, Symbol};

use crate::extraction::spec::{
    ConstantStrategy, DecoratorStrategy, DocstringStrategy, LanguageSpec, SpecExtractor,
};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[("function_declaration", "function")],
    name_fields: &[("function_declaration", "name")],
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

/// Built-in Lua extractor.
pub struct LuaExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl LuaExtractor {
    /// Construct a fresh instance. Cheap; the tree-sitter language
    /// handle is lazily materialised on first extraction.
    pub fn new() -> Self {
        Self {
            inner: OnceLock::new(),
        }
    }

    fn delegate(&self) -> &SpecExtractor {
        self.inner.get_or_init(|| {
            SpecExtractor::new(&["lua"], crate::grammars::get_language("lua").expect("lua grammar"), &SPEC)
        })
    }
}

impl Default for LuaExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for LuaExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["lua"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        self.delegate().extract(ctx)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        LuaExtractor::new()
            .extract(&ExtractionContext::new(source, "main.lua", "lua"))
            .expect("lua extraction")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_function_declaration() {
        let syms = extract("function greet()\n  print('hi')\nend\n");
        assert_eq!(syms.len(), 1);
        assert_eq!(syms[0].name, "greet");
        assert_eq!(syms[0].kind, "function");
        assert_eq!(syms[0].language, "lua");
    }

    #[test]
    fn advertises_lua_language() {
        let ex = LuaExtractor::new();
        assert_eq!(ex.languages(), &["lua"]);
    }
}
