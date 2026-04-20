//! Bash extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the Bash grammar. Bash has
//! one symbol-producing node type (`function_definition`) and no
//! containers; preceding `# ...` comments become the docstring.
//!
//! Mirrors the `"bash"` entry in the Python `_tree_sitter_only.py`
//! spec table.

use std::sync::OnceLock;

use sylvan_core::{ExtractionContext, ExtractionError, LanguageExtractor, Symbol};

use crate::extraction::spec::{
    ConstantStrategy, DecoratorStrategy, DocstringStrategy, LanguageSpec, SpecExtractor,
};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[("function_definition", "function")],
    name_fields: &[("function_definition", "name")],
    param_fields: &[],
    return_type_fields: &[],
    container_node_types: &[],
    docstring_strategy: DocstringStrategy::PrecedingComment,
    decorator_strategy: DecoratorStrategy::None,
    constant_strategy: ConstantStrategy::None,
    parameter_kinds: &[],
    method_promotion: &[],
};

/// Built-in Bash extractor.
pub struct BashExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl BashExtractor {
    /// Construct a fresh instance. Cheap; the tree-sitter language
    /// handle is lazily materialised on first extraction.
    pub fn new() -> Self {
        Self {
            inner: OnceLock::new(),
        }
    }

    fn delegate(&self) -> &SpecExtractor {
        self.inner.get_or_init(|| {
            SpecExtractor::new(&["bash"], tree_sitter_bash::LANGUAGE.into(), &SPEC)
        })
    }
}

impl Default for BashExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for BashExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["bash"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        self.delegate().extract(ctx)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        BashExtractor::new()
            .extract(&ExtractionContext::new(source, "script.sh", "bash"))
            .expect("bash extraction")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_function_definition() {
        let syms = extract("greet() {\n  echo hi\n}\n");
        assert_eq!(syms.len(), 1);
        assert_eq!(syms[0].name, "greet");
        assert_eq!(syms[0].kind, "function");
        assert_eq!(syms[0].language, "bash");
        assert_eq!(syms[0].qualified_name, "greet");
    }

    #[test]
    fn extracts_function_keyword_form() {
        let syms = extract("function farewell {\n  echo bye\n}\n");
        assert_eq!(syms.len(), 1);
        assert_eq!(syms[0].name, "farewell");
    }

    #[test]
    fn preceding_comment_becomes_docstring() {
        let source = "# greets the user\n# second line\ngreet() {\n  echo hi\n}\n";
        let syms = extract(source);
        assert_eq!(syms.len(), 1);
        let doc = syms[0].docstring.as_deref().expect("docstring");
        assert!(doc.contains("greets the user"));
        assert!(doc.contains("second line"));
    }

    #[test]
    fn multiple_functions_produce_multiple_symbols() {
        let syms = extract("a() { :; }\nb() { :; }\nc() { :; }\n");
        let names: Vec<&str> = syms.iter().map(|s| s.name.as_str()).collect();
        assert_eq!(names, vec!["a", "b", "c"]);
    }

    #[test]
    fn byte_range_and_line_numbers_are_1_based() {
        let source = "\ngreet() {\n  echo hi\n}\n";
        let syms = extract(source);
        assert_eq!(syms.len(), 1);
        assert_eq!(syms[0].line_start, Some(2));
        assert!(syms[0].byte_length > 0);
    }

    #[test]
    fn advertises_bash_language() {
        let ex = BashExtractor::new();
        assert_eq!(ex.languages(), &["bash"]);
    }

    #[test]
    fn symbol_id_matches_make_symbol_id_shape() {
        let syms = extract("greet() { :; }\n");
        assert_eq!(syms[0].symbol_id, "script.sh::greet#function");
    }
}
