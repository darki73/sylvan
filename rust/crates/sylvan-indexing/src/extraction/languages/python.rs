//! Python extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the Python grammar. Covers
//! the bits Python's [`LanguageSpec`] declares in the legacy plugin:
//! function / class symbols, signature stitching, next-sibling-string
//! docstrings, `@decorator` collection with byte-range expansion, and
//! module-level `ALL_CAPS = ...` constants. Method reclassification
//! happens automatically via `method_promotion`.
//!
//! Features left for later migration stages (not this spec walker):
//! complexity scoring, content hashing, import extraction, Jedi-based
//! cross-file resolution.

use std::sync::OnceLock;

use sylvan_core::{ExtractionContext, ExtractionError, LanguageExtractor, Symbol};

use crate::extraction::spec::{DocstringStrategy, LanguageSpec, SpecExtractor};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[
        ("function_definition", "function"),
        ("class_definition", "class"),
    ],
    name_fields: &[
        ("function_definition", "name"),
        ("class_definition", "name"),
    ],
    param_fields: &[("function_definition", "parameters")],
    return_type_fields: &[("function_definition", "return_type")],
    container_node_types: &["class_definition"],
    docstring_strategy: DocstringStrategy::NextSiblingString,
    decorator_node_type: Some("decorated_definition"),
    constant_patterns: &["expression_statement", "assignment"],
    method_promotion: &[("class", "method")],
};

/// Built-in Python extractor.
pub struct PythonExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl PythonExtractor {
    /// Construct a fresh instance.
    pub fn new() -> Self {
        Self {
            inner: OnceLock::new(),
        }
    }

    fn delegate(&self) -> &SpecExtractor {
        self.inner.get_or_init(|| {
            SpecExtractor::new(&["python"], tree_sitter_python::LANGUAGE.into(), &SPEC)
        })
    }
}

impl Default for PythonExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for PythonExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["python"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        self.delegate().extract(ctx)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        PythonExtractor::new()
            .extract(&ExtractionContext::new(source, "mod.py", "python"))
            .expect("python extraction")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_top_level_function() {
        let syms = extract("def greet():\n    pass\n");
        assert_eq!(syms.len(), 1);
        assert_eq!(syms[0].name, "greet");
        assert_eq!(syms[0].kind, "function");
        assert_eq!(syms[0].qualified_name, "greet");
        assert_eq!(syms[0].language, "python");
    }

    #[test]
    fn extracts_class_with_method_promotion() {
        let syms = extract("class Dog:\n    def bark(self):\n        pass\n");
        assert_eq!(syms.len(), 2);
        let cls = &syms[0];
        let method = &syms[1];
        assert_eq!(cls.kind, "class");
        assert_eq!(cls.name, "Dog");
        assert_eq!(method.kind, "method");
        assert_eq!(method.name, "bark");
        assert_eq!(method.qualified_name, "Dog.bark");
        assert_eq!(method.parent_symbol_id.as_deref(), Some(cls.symbol_id.as_str()));
    }

    #[test]
    fn docstring_is_next_sibling_string() {
        let src = "def greet():\n    \"\"\"Say hi.\"\"\"\n    pass\n";
        let syms = extract(src);
        assert_eq!(syms[0].docstring.as_deref(), Some("Say hi."));
    }

    #[test]
    fn signature_includes_params_and_return_type() {
        let src = "def add(a: int, b: int) -> int:\n    return a + b\n";
        let syms = extract(src);
        let sig = syms[0].signature.as_deref().expect("signature");
        assert!(sig.starts_with("(a: int, b: int)"));
        assert!(sig.ends_with("-> int"));
        assert_eq!(syms[0].param_count, 2);
    }

    #[test]
    fn decorator_expands_byte_range_and_is_captured() {
        let src = "@staticmethod\n@classmethod\ndef noop():\n    pass\n";
        let syms = extract(src);
        assert_eq!(syms.len(), 1);
        let sym = &syms[0];
        assert_eq!(sym.decorators, vec!["staticmethod", "classmethod"]);
        assert_eq!(sym.byte_offset, 0, "range should start at first decorator");
        assert_eq!(sym.line_start, Some(1));
    }

    #[test]
    fn module_constant_emitted_for_all_caps_assignment() {
        let src = "MAX_RETRIES = 5\nlower = 1\n";
        let syms = extract(src);
        let kinds: Vec<(&str, &str)> = syms
            .iter()
            .map(|s| (s.name.as_str(), s.kind.as_str()))
            .collect();
        assert!(kinds.contains(&("MAX_RETRIES", "constant")));
        assert!(!kinds.iter().any(|(n, _)| *n == "lower"));
    }

    #[test]
    fn constant_skipped_inside_class_body() {
        let src = "class C:\n    INSIDE = 1\n";
        let syms = extract(src);
        let names: Vec<&str> = syms.iter().map(|s| s.name.as_str()).collect();
        assert_eq!(names, vec!["C"], "class-body assignments are not module constants");
    }

    #[test]
    fn decorated_class_is_recorded_with_decorators() {
        let src = "@register\nclass Widget:\n    def use(self):\n        pass\n";
        let syms = extract(src);
        let cls = syms.iter().find(|s| s.kind == "class").expect("class");
        assert_eq!(cls.decorators, vec!["register"]);
        assert!(syms.iter().any(|s| s.kind == "method" && s.name == "use"));
    }

    #[test]
    fn advertises_python_language() {
        assert_eq!(PythonExtractor::new().languages(), &["python"]);
    }

    #[test]
    fn symbol_id_matches_make_symbol_id_shape() {
        let syms = extract("def greet():\n    pass\n");
        assert_eq!(syms[0].symbol_id, "mod.py::greet#function");
    }
}
