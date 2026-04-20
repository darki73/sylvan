//! LESS extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the LESS grammar, then
//! post-processes the emitted symbols to match the naming conventions
//! the rest of sylvan expects:
//!
//! - LESS variables come out of the grammar as `@name`; we strip the
//!   leading `@` so searches / refs use the bare identifier.
//! - Mixin definitions arrive as `.name` (or `#name`); we strip the
//!   leading selector sigil for the same reason.
//!
//! Rule sets keep their selector text verbatim (`.container` stays
//! `.container`) because that text IS the symbol name a reader would
//! write to find it.

use std::sync::OnceLock;

use fancy_regex::Regex;
use once_cell::sync::Lazy;
use sylvan_core::{
    ExtractionContext, ExtractionError, Import, LanguageExtractor, Symbol, make_symbol_id,
};

use crate::extraction::spec::{
    ConstantStrategy, DecoratorStrategy, DocstringStrategy, LanguageSpec, SpecExtractor,
};

static LESS_IMPORT_RE: Lazy<Regex> = Lazy::new(|| {
    Regex::new(r#"(?m)^\s*@import\s+(?:\([^)]*\)\s*)?["']([^"']+)["']\s*;"#)
        .expect("less @import regex compiles")
});

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[
        ("rule_set", "type"),
        ("mixin_def", "function"),
        ("variable_def", "constant"),
        ("keyframes_statement", "function"),
        ("import_statement", "constant"),
    ],
    name_fields: &[
        ("rule_set", "selectors"),
        ("mixin_def", "name"),
        ("variable_def", "name"),
        ("keyframes_statement", "name"),
        ("import_statement", "import"),
    ],
    name_resolutions: &[],
    param_fields: &[("mixin_def", "params")],
    return_type_fields: &[],
    container_node_types: &[],
    docstring_strategy: DocstringStrategy::PrecedingComment,
    decorator_strategy: DecoratorStrategy::None,
    constant_strategy: ConstantStrategy::None,
    parameter_kinds: &[],
    method_promotion: &[],
};

/// Built-in LESS extractor.
pub struct LessExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl LessExtractor {
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
                &["less"],
                crate::grammars::get_language("less").expect("less grammar"),
                &SPEC,
            )
        })
    }
}

impl Default for LessExtractor {
    fn default() -> Self {
        Self::new()
    }
}

fn rename(sym: &mut Symbol, filename: &str, new_name: String) {
    sym.name = new_name.clone();
    sym.qualified_name = new_name;
    sym.symbol_id = make_symbol_id(filename, &sym.qualified_name, &sym.kind);
}

impl LanguageExtractor for LessExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["less"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        let mut symbols = self.delegate().extract(ctx)?;
        for sym in &mut symbols {
            match sym.kind.as_str() {
                "constant" => {
                    if let Some(stripped) = sym.name.strip_prefix('@') {
                        rename(sym, ctx.filename, stripped.to_string());
                    }
                }
                "function" => {
                    let trimmed = sym
                        .name
                        .trim_start_matches(|c: char| c == '.' || c == '#')
                        .to_string();
                    if trimmed != sym.name {
                        rename(sym, ctx.filename, trimmed);
                    }
                }
                _ => {}
            }
        }
        Ok(symbols)
    }

    fn supports_imports(&self) -> bool {
        true
    }

    fn extract_imports(
        &self,
        ctx: &ExtractionContext<'_>,
    ) -> Result<Vec<Import>, ExtractionError> {
        let mut out: Vec<Import> = Vec::new();
        for m in LESS_IMPORT_RE.captures_iter(ctx.source).flatten() {
            let Some(spec) = m.get(1) else { continue };
            out.push(Import {
                specifier: spec.as_str().to_string(),
                names: Vec::new(),
            });
        }
        Ok(out)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        LessExtractor::new()
            .extract(&ExtractionContext::new(source, "styles.less", "less"))
            .expect("less extraction")
    }

    fn imports(source: &str) -> Vec<Import> {
        LessExtractor::new()
            .extract_imports(&ExtractionContext::new(source, "styles.less", "less"))
            .expect("less imports")
    }

    #[test]
    fn empty_file_yields_no_imports() {
        assert!(imports("").is_empty());
    }

    #[test]
    fn basic_import_has_no_names() {
        let imps = imports("@import \"a\";\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "a");
        assert!(imps[0].names.is_empty());
    }

    #[test]
    fn import_with_options_still_captures_specifier() {
        let imps = imports("@import (reference) \"a.less\";\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "a.less");
        assert!(imps[0].names.is_empty());
    }

    #[test]
    fn multiple_imports_preserve_order() {
        let imps = imports("@import \"a\";\n@import \"b\";\n");
        assert_eq!(imps.len(), 2);
        assert_eq!(imps[0].specifier, "a");
        assert_eq!(imps[1].specifier, "b");
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_rule_set() {
        let syms = extract(".card { padding: 10px; }\n");
        let rule = syms.iter().find(|s| s.kind == "type").expect("rule_set");
        assert!(rule.name.contains(".card"));
    }

    #[test]
    fn strips_selector_sigil_from_mixin_def() {
        let syms = extract(".border-radius(@radius) { border-radius: @radius; }\n");
        let mixin = syms
            .iter()
            .find(|s| s.kind == "function")
            .expect("mixin_def");
        assert_eq!(mixin.name, "border-radius");
    }

    #[test]
    fn strips_at_prefix_from_variable() {
        let syms = extract("@base: #f938ab;\n");
        assert!(syms.iter().any(|s| s.kind == "constant" && s.name == "base"));
    }

    #[test]
    fn extracts_keyframes() {
        let syms = extract("@keyframes fade { from { opacity: 0; } }\n");
        assert!(syms
            .iter()
            .any(|s| s.name == "fade" && s.kind == "function"));
    }

    #[test]
    fn advertises_less_language() {
        assert_eq!(LessExtractor::new().languages(), &["less"]);
    }
}
