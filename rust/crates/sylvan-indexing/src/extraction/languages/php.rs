//! PHP extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the PHP grammar. Mirrors
//! the legacy `sylvan.indexing.languages.php` spec: functions,
//! methods, classes, interfaces, traits, and enums, with preceding
//! comment docstrings. PHP source may be embedded in a file that also
//! contains non-PHP preamble (HTML), so we use `LANGUAGE_PHP` rather
//! than `LANGUAGE_PHP_ONLY`.
//!
//! Import extraction (PSR-4 resolution, group use) lives elsewhere.

use std::sync::OnceLock;

use sylvan_core::{ExtractionContext, ExtractionError, LanguageExtractor, Symbol};

use crate::extraction::spec::{DocstringStrategy, LanguageSpec, SpecExtractor};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[
        ("function_definition", "function"),
        ("method_declaration", "method"),
        ("class_declaration", "class"),
        ("interface_declaration", "type"),
        ("trait_declaration", "type"),
        ("enum_declaration", "type"),
    ],
    name_fields: &[
        ("function_definition", "name"),
        ("method_declaration", "name"),
        ("class_declaration", "name"),
        ("interface_declaration", "name"),
        ("trait_declaration", "name"),
        ("enum_declaration", "name"),
    ],
    param_fields: &[
        ("function_definition", "parameters"),
        ("method_declaration", "parameters"),
    ],
    return_type_fields: &[],
    container_node_types: &[
        "class_declaration",
        "interface_declaration",
        "trait_declaration",
    ],
    docstring_strategy: DocstringStrategy::PrecedingComment,
    decorator_node_type: None,
    constant_patterns: &["const_declaration", "property_declaration"],
    method_promotion: &[],
};

/// Built-in PHP extractor.
pub struct PhpExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl PhpExtractor {
    /// Construct a fresh instance.
    pub fn new() -> Self {
        Self {
            inner: OnceLock::new(),
        }
    }

    fn delegate(&self) -> &SpecExtractor {
        self.inner.get_or_init(|| {
            SpecExtractor::new(&["php"], tree_sitter_php::LANGUAGE_PHP.into(), &SPEC)
        })
    }
}

impl Default for PhpExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for PhpExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["php"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        self.delegate().extract(ctx)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        PhpExtractor::new()
            .extract(&ExtractionContext::new(source, "mod.php", "php"))
            .expect("php extraction")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_top_level_function() {
        let syms = extract("<?php function greet() {} ?>");
        let fun = syms
            .iter()
            .find(|s| s.kind == "function" && s.name == "greet")
            .expect("function greet");
        assert_eq!(fun.language, "php");
        let sig = fun.signature.as_deref().expect("signature");
        assert!(sig.contains("greet()"));
    }

    #[test]
    fn extracts_class_with_method() {
        let syms = extract("<?php class Dog { public function bark() {} } ?>");
        let cls = syms
            .iter()
            .find(|s| s.kind == "class" && s.name == "Dog")
            .expect("class Dog");
        let method = syms
            .iter()
            .find(|s| s.kind == "method" && s.name == "bark")
            .expect("method bark");
        assert_eq!(method.qualified_name, "Dog.bark");
        assert_eq!(
            method.parent_symbol_id.as_deref(),
            Some(cls.symbol_id.as_str())
        );
    }

    #[test]
    fn extracts_interface_declaration() {
        let syms = extract("<?php interface IFoo { public function x(); } ?>");
        let iface = syms
            .iter()
            .find(|s| s.name == "IFoo")
            .expect("interface IFoo");
        assert_eq!(iface.kind, "type");
    }

    #[test]
    fn docstring_is_preceding_comment() {
        let src = "<?php /** doc */ function x() {} ?>";
        let syms = extract(src);
        let fun = syms
            .iter()
            .find(|s| s.name == "x")
            .expect("function x");
        let doc = fun.docstring.as_deref().expect("docstring");
        assert!(doc.contains("doc"), "got: {doc:?}");
    }

    #[test]
    fn advertises_php_language() {
        assert_eq!(PhpExtractor::new().languages(), &["php"]);
    }
}
