//! Go extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the Go grammar. Mirrors the
//! spec declared in the legacy Python plugin: top-level functions,
//! receiver methods, and type declarations. Docstrings come from
//! preceding `//` comments. Go has no decorators and no class-method
//! distinction, so `decorator_strategy`, `constant_strategy`, and
//! `method_promotion` all stay at their `None` / empty defaults.
//!
//! Import extraction walks the parsed tree for `import_declaration`
//! nodes and pulls each `import_spec`'s `path` field, unquoting the
//! interpreted string literal so the specifier matches the Python
//! plugin's output. Aliased forms (`alias "path"`) and `_`/`.` side
//! imports collapse to a bare specifier since names carry no value
//! for Go imports.
//!
//! Features left for later migration stages: candidate path resolution
//! against stdlib and complexity tuning.

use std::sync::OnceLock;

use sylvan_core::{ExtractionContext, ExtractionError, Import, LanguageExtractor, Symbol};
use tree_sitter::Node;

use crate::extraction::spec::{
    ConstantStrategy, DecoratorStrategy, DocstringStrategy, LanguageSpec, SpecExtractor,
};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[
        ("function_declaration", "function"),
        ("method_declaration", "method"),
        ("type_spec", "type"),
    ],
    name_fields: &[
        ("function_declaration", "name"),
        ("method_declaration", "name"),
        ("type_spec", "name"),
    ],
    param_fields: &[
        ("function_declaration", "parameters"),
        ("method_declaration", "parameters"),
    ],
    return_type_fields: &[
        ("function_declaration", "result"),
        ("method_declaration", "result"),
    ],
    container_node_types: &[],
    docstring_strategy: DocstringStrategy::PrecedingComment,
    decorator_strategy: DecoratorStrategy::None,
    constant_strategy: ConstantStrategy::WrappedSpecs {
        wrapper_kinds: &["const_declaration", "var_declaration"],
        spec_kinds: &["const_spec", "var_spec"],
        name_field: "name",
        uppercase_only: true,
    },
    parameter_kinds: &["parameter_declaration", "variadic_parameter_declaration"],
    method_promotion: &[],
};

/// Built-in Go extractor.
pub struct GoExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl GoExtractor {
    /// Construct a fresh instance.
    pub fn new() -> Self {
        Self {
            inner: OnceLock::new(),
        }
    }

    fn delegate(&self) -> &SpecExtractor {
        self.inner.get_or_init(|| {
            SpecExtractor::new(&["go"], tree_sitter_go::LANGUAGE.into(), &SPEC)
        })
    }
}

impl Default for GoExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for GoExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["go"]
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
        let tree = self.delegate().parse(ctx)?;
        let mut out = Vec::new();
        walk_imports(tree.root_node(), ctx.source_bytes, &mut out);
        Ok(out)
    }
}

fn walk_imports(node: Node<'_>, source: &[u8], out: &mut Vec<Import>) {
    if node.kind() == "import_declaration" {
        collect_import_declaration(node, source, out);
        return;
    }
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        walk_imports(child, source, out);
    }
}

fn collect_import_declaration(node: Node<'_>, source: &[u8], out: &mut Vec<Import>) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "import_spec" => collect_import_spec(child, source, out),
            "import_spec_list" => {
                let mut c = child.walk();
                for spec in child.children(&mut c) {
                    if spec.kind() == "import_spec" {
                        collect_import_spec(spec, source, out);
                    }
                }
            }
            _ => {}
        }
    }
}

fn collect_import_spec(node: Node<'_>, source: &[u8], out: &mut Vec<Import>) {
    let Some(path_node) = node.child_by_field_name("path") else {
        return;
    };
    let Some(raw) = node_text(path_node, source) else {
        return;
    };
    let specifier = unquote(&raw);
    if specifier.is_empty() {
        return;
    }
    out.push(Import {
        specifier,
        names: Vec::new(),
    });
}

fn unquote(raw: &str) -> String {
    let trimmed = raw.trim();
    if trimmed.len() >= 2 {
        let first = trimmed.chars().next().unwrap();
        let last = trimmed.chars().last().unwrap();
        if (first == '"' && last == '"') || (first == '`' && last == '`') {
            return trimmed[1..trimmed.len() - 1].to_string();
        }
    }
    trimmed.to_string()
}

fn node_text(node: Node<'_>, source: &[u8]) -> Option<String> {
    std::str::from_utf8(&source[node.byte_range()])
        .ok()
        .map(|s| s.to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        GoExtractor::new()
            .extract(&ExtractionContext::new(source, "main.go", "go"))
            .expect("go extraction")
    }

    fn imports(src: &str) -> Vec<Import> {
        GoExtractor::new()
            .extract_imports(&ExtractionContext::new(src, "main.go", "go"))
            .expect("go imports")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_top_level_function() {
        let syms = extract("package main\n\nfunc Foo() {}\n");
        assert_eq!(syms.len(), 1);
        assert_eq!(syms[0].name, "Foo");
        assert_eq!(syms[0].kind, "function");
        assert_eq!(syms[0].qualified_name, "Foo");
        assert_eq!(syms[0].language, "go");
    }

    #[test]
    fn extracts_receiver_method() {
        let src = "package main\n\ntype Receiver struct{}\n\nfunc (r *Receiver) Method() {}\n";
        let syms = extract(src);
        let method = syms.iter().find(|s| s.kind == "method").expect("method");
        assert_eq!(method.name, "Method");
        assert_eq!(method.kind, "method");
    }

    #[test]
    fn extracts_type_declaration() {
        let src = "package main\n\ntype User struct {\n    Name string\n}\n";
        let syms = extract(src);
        let ty = syms.iter().find(|s| s.kind == "type").expect("type");
        assert_eq!(ty.name, "User");
        assert_eq!(ty.qualified_name, "User");
    }

    #[test]
    fn preceding_line_comment_becomes_docstring() {
        let src = "package main\n\n// doc comment\nfunc Foo() {}\n";
        let syms = extract(src);
        assert_eq!(syms.len(), 1);
        assert_eq!(syms[0].docstring.as_deref(), Some("doc comment"));
    }

    #[test]
    fn signature_spans_up_to_body() {
        let src = "package main\n\nfunc Add(a int, b int) int { return a + b }\n";
        let syms = extract(src);
        let sig = syms[0].signature.as_deref().expect("signature");
        assert!(sig.contains("Add(a int, b int)"), "signature was {sig:?}");
        assert!(sig.contains("int"), "signature was {sig:?}");
        assert_eq!(syms[0].name, "Add");
    }

    #[test]
    fn advertises_go_language() {
        assert_eq!(GoExtractor::new().languages(), &["go"]);
    }

    #[test]
    fn uppercase_const_declaration_emits_constant() {
        let src = "package main\n\nconst MAX = 5\n";
        let syms = extract(src);
        let c = syms.iter().find(|s| s.kind == "constant").expect("constant");
        assert_eq!(c.name, "MAX");
    }

    #[test]
    fn grouped_const_block_emits_each_uppercase_spec() {
        let src = "package main\n\nconst (\n    FOO = 1\n    bar = 2\n    BAZ = 3\n)\n";
        let syms = extract(src);
        let names: Vec<&str> = syms
            .iter()
            .filter(|s| s.kind == "constant")
            .map(|s| s.name.as_str())
            .collect();
        assert_eq!(names, vec!["FOO", "BAZ"]);
    }

    #[test]
    fn single_line_import_yields_specifier() {
        let imps = imports("package main\n\nimport \"fmt\"\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "fmt");
        assert!(imps[0].names.is_empty());
    }

    #[test]
    fn grouped_import_block_splits_each_path() {
        let src = "package main\n\nimport (\n    \"fmt\"\n    \"os\"\n    \"net/http\"\n)\n";
        let imps = imports(src);
        let specs: Vec<&str> = imps.iter().map(|i| i.specifier.as_str()).collect();
        assert_eq!(specs, vec!["fmt", "os", "net/http"]);
    }

    #[test]
    fn aliased_import_uses_path_as_specifier() {
        let src = "package main\n\nimport f \"fmt\"\n";
        let imps = imports(src);
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "fmt");
    }

    #[test]
    fn blank_and_dot_side_imports_collapse_to_path() {
        let src = "package main\n\nimport (\n    _ \"database/sql\"\n    . \"math\"\n)\n";
        let imps = imports(src);
        let specs: Vec<&str> = imps.iter().map(|i| i.specifier.as_str()).collect();
        assert_eq!(specs, vec!["database/sql", "math"]);
    }
}
