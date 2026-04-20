//! Ruby extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the Ruby grammar. Mirrors the
//! Ruby [`LanguageSpec`] declared in the legacy plugin: method /
//! singleton_method / class / module symbols, signature stitching,
//! preceding `#` comment docstrings, and ALL_CAPS `assignment`
//! constants. Ruby has no decorator syntax and no method promotion
//! since the grammar already names the node `method`.
//!
//! Features left for later migration stages (not this spec walker):
//! complexity scoring, content hashing, `require` / `require_relative`
//! extraction and resolution.

use std::sync::OnceLock;

use sylvan_core::{ExtractionContext, ExtractionError, LanguageExtractor, Symbol};

use crate::extraction::spec::{
    ConstantStrategy, DecoratorStrategy, DocstringStrategy, LanguageSpec, SpecExtractor,
};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[
        ("method", "method"),
        ("singleton_method", "method"),
        ("class", "class"),
        ("module", "module"),
    ],
    name_fields: &[
        ("method", "name"),
        ("singleton_method", "name"),
        ("class", "name"),
        ("module", "name"),
    ],
    param_fields: &[
        ("method", "parameters"),
        ("singleton_method", "parameters"),
    ],
    return_type_fields: &[],
    container_node_types: &["class", "module"],
    docstring_strategy: DocstringStrategy::PrecedingComment,
    decorator_strategy: DecoratorStrategy::None,
    constant_strategy: ConstantStrategy::None,
    parameter_kinds: &[
        "identifier",
        "optional_parameter",
        "keyword_parameter",
        "hash_splat_parameter",
        "splat_parameter",
        "block_parameter",
    ],
    method_promotion: &[],
};

/// Built-in Ruby extractor.
pub struct RubyExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl RubyExtractor {
    /// Construct a fresh instance.
    pub fn new() -> Self {
        Self {
            inner: OnceLock::new(),
        }
    }

    fn delegate(&self) -> &SpecExtractor {
        self.inner.get_or_init(|| {
            SpecExtractor::new(&["ruby"], tree_sitter_ruby::LANGUAGE.into(), &SPEC)
        })
    }
}

impl Default for RubyExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for RubyExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["ruby"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        self.delegate().extract(ctx)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        RubyExtractor::new()
            .extract(&ExtractionContext::new(source, "mod.rb", "ruby"))
            .expect("ruby extraction")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_top_level_method() {
        let syms = extract("def greet\nend\n");
        assert_eq!(syms.len(), 1);
        assert_eq!(syms[0].name, "greet");
        assert_eq!(syms[0].kind, "method");
        assert_eq!(syms[0].qualified_name, "greet");
        assert_eq!(syms[0].language, "ruby");
    }

    #[test]
    fn extracts_class_with_nested_method() {
        let syms = extract("class Dog\n  def bark\n  end\nend\n");
        assert_eq!(syms.len(), 2);
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
    fn extracts_module_symbol() {
        let syms = extract("module M\nend\n");
        assert_eq!(syms.len(), 1);
        assert_eq!(syms[0].name, "M");
        assert_eq!(syms[0].kind, "module");
    }

    #[test]
    fn preceding_hash_comment_becomes_docstring() {
        let src = "# greet comment\ndef x\nend\n";
        let syms = extract(src);
        assert_eq!(syms.len(), 1);
        let doc = syms[0].docstring.as_deref().expect("docstring");
        assert!(doc.contains("comment"), "docstring was: {doc:?}");
    }

    #[test]
    fn advertises_ruby_language() {
        assert_eq!(RubyExtractor::new().languages(), &["ruby"]);
    }
}
