//! Swift extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the Swift grammar. The
//! `tree-sitter-swift` grammar represents `class`, `struct`, and `enum`
//! declarations as a single `class_declaration` node; only the body
//! kind (`class_body` vs `enum_class_body`) distinguishes them. We emit
//! all three as kind `class` rather than listing node types the grammar
//! never produces. Symbol names come from a labeled `name` field on
//! every declaration; preceding `//` comments become the docstring.
//!
//! Import extraction mirrors the legacy Python regex
//! `^\s*import\s+(\w+)`: each matching line yields an `Import` whose
//! specifier is the framework name (e.g. `Foundation`). Swift imports
//! name frameworks, not file paths, so no resolution is provided.

use std::sync::OnceLock;

use fancy_regex::Regex;
use once_cell::sync::Lazy;
use sylvan_core::{ExtractionContext, ExtractionError, Import, LanguageExtractor, Symbol};

static IMPORT_RE: Lazy<Regex> =
    Lazy::new(|| Regex::new(r"(?m)^\s*import\s+(\w+)").expect("swift import regex"));

use crate::extraction::spec::{
    ConstantStrategy, DecoratorStrategy, DocstringStrategy, LanguageSpec, SpecExtractor,
};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[
        ("function_declaration", "function"),
        ("protocol_function_declaration", "function"),
        ("class_declaration", "class"),
        ("protocol_declaration", "type"),
    ],
    name_fields: &[
        ("function_declaration", "name"),
        ("protocol_function_declaration", "name"),
        ("class_declaration", "name"),
        ("protocol_declaration", "name"),
    ],
    name_resolutions: &[],
    param_fields: &[("function_declaration", "parameters")],
    return_type_fields: &[("function_declaration", "return_type")],
    container_node_types: &[
        "class_body",
        "enum_class_body",
        "protocol_body",
    ],
    docstring_strategy: DocstringStrategy::PrecedingComment,
    decorator_strategy: DecoratorStrategy::None,
    constant_strategy: ConstantStrategy::None,
    parameter_kinds: &[],
    method_promotion: &[],
};

/// Built-in Swift extractor.
pub struct SwiftExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl SwiftExtractor {
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
                &["swift"],
                crate::grammars::get_language("swift").expect("swift grammar"),
                &SPEC,
            )
        })
    }
}

impl Default for SwiftExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for SwiftExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["swift"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        self.delegate().extract(ctx)
    }

    fn supports_imports(&self) -> bool {
        true
    }

    fn extract_imports(
        &self,
        ctx: &ExtractionContext<'_>,
    ) -> Result<Vec<Import>, ExtractionError> {
        let mut out = Vec::new();
        for caps in IMPORT_RE.captures_iter(ctx.source).flatten() {
            if let Some(m) = caps.get(1) {
                out.push(Import {
                    specifier: m.as_str().to_string(),
                    names: Vec::new(),
                });
            }
        }
        Ok(out)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        SwiftExtractor::new()
            .extract(&ExtractionContext::new(source, "App.swift", "swift"))
            .expect("swift extraction")
    }

    fn imports(src: &str) -> Vec<Import> {
        SwiftExtractor::new()
            .extract_imports(&ExtractionContext::new(src, "App.swift", "swift"))
            .expect("swift imports")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_function_declaration() {
        let syms = extract("func greet(name: String) -> String {\n  return name\n}\n");
        assert!(syms
            .iter()
            .any(|s| s.name == "greet" && s.kind == "function"));
    }

    #[test]
    fn extracts_class_struct_and_enum_as_class() {
        let syms = extract("class Greeter {}\nstruct Point {}\nenum Color { case red }\n");
        assert!(syms.iter().any(|s| s.name == "Greeter" && s.kind == "class"));
        assert!(syms.iter().any(|s| s.name == "Point" && s.kind == "class"));
        assert!(syms.iter().any(|s| s.name == "Color" && s.kind == "class"));
    }

    #[test]
    fn extracts_protocol() {
        let syms = extract("protocol Printable {\n  func describe() -> String\n}\n");
        assert!(syms.iter().any(|s| s.name == "Printable" && s.kind == "type"));
        assert!(syms.iter().any(|s| s.name == "describe" && s.kind == "function"));
    }

    #[test]
    fn advertises_swift_language() {
        let ex = SwiftExtractor::new();
        assert_eq!(ex.languages(), &["swift"]);
    }

    #[test]
    fn empty_file_yields_no_imports() {
        assert!(imports("").is_empty());
    }

    #[test]
    fn single_import_records_framework_name() {
        let imps = imports("import Foundation\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "Foundation");
        assert!(imps[0].names.is_empty());
    }

    #[test]
    fn multiple_import_lines_produce_multiple_records() {
        let src = "import Foundation\nimport UIKit\n  import Combine\n";
        let imps = imports(src);
        assert_eq!(imps.len(), 3);
        assert_eq!(imps[0].specifier, "Foundation");
        assert_eq!(imps[1].specifier, "UIKit");
        assert_eq!(imps[2].specifier, "Combine");
    }

    #[test]
    fn non_matching_lines_are_ignored() {
        let src = "// import NotAFramework\nlet x = 1\nimport Foundation\nfunc f() {}\n";
        let imps = imports(src);
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "Foundation");
    }
}
