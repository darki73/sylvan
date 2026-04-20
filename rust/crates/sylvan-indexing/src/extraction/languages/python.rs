//! Python extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the Python grammar. Covers
//! the bits Python's [`LanguageSpec`] declares in the legacy plugin:
//! function / class symbols, signature stitching, next-sibling-string
//! docstrings, `@decorator` collection with byte-range expansion, and
//! module-level `ALL_CAPS = ...` constants. Method reclassification
//! happens automatically via `method_promotion`.
//!
//! Import extraction walks the parsed tree for `import_statement`
//! and `import_from_statement` nodes, producing one [`Import`] per
//! `from`-clause and one per bare `import` specifier (matching the
//! legacy regex behaviour where `import a, b` splits into two
//! records).
//!
//! Features left for later migration stages: complexity scoring,
//! content hashing, Jedi-based cross-file resolution.

use std::sync::OnceLock;

use sylvan_core::{
    ExtractionContext, ExtractionError, Import, LanguageExtractor, ResolverContext, Symbol,
};
use tree_sitter::Node;

use crate::extraction::spec::{
    ConstantStrategy, DecoratorStrategy, DocstringStrategy, LanguageSpec, SpecExtractor,
};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[
        ("function_definition", "function"),
        ("class_definition", "class"),
    ],
    name_fields: &[
        ("function_definition", "name"),
        ("class_definition", "name"),
    ],
    name_resolutions: &[],
    param_fields: &[("function_definition", "parameters")],
    return_type_fields: &[("function_definition", "return_type")],
    container_node_types: &["class_definition"],
    docstring_strategy: DocstringStrategy::NextSiblingString,
    decorator_strategy: DecoratorStrategy::Wrapper {
        wrapper: "decorated_definition",
        child: "decorator",
    },
    constant_strategy: ConstantStrategy::PythonAssignment,
    parameter_kinds: &[
        "identifier",
        "typed_parameter",
        "default_parameter",
        "typed_default_parameter",
        "list_splat_pattern",
        "dictionary_splat_pattern",
        "keyword_separator",
        "positional_separator",
        "tuple_pattern",
        "parameter",
    ],
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
            SpecExtractor::new(&["python"], crate::grammars::get_language("python").expect("python grammar"), &SPEC)
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

    fn supports_resolution(&self) -> bool {
        true
    }

    fn generate_candidates(
        &self,
        specifier: &str,
        source_path: &str,
        _context: &ResolverContext,
    ) -> Vec<String> {
        if specifier.starts_with('.') {
            return relative_candidates(specifier, source_path);
        }

        let mut out = Vec::new();
        if specifier.contains('.') {
            let path_base = specifier.replace('.', "/");
            for prefix in ["", "src/", "lib/"] {
                out.push(format!("{prefix}{path_base}.py"));
                out.push(format!("{prefix}{path_base}/__init__.py"));
            }
        } else {
            for prefix in ["", "src/", "lib/"] {
                out.push(format!("{prefix}{specifier}/__init__.py"));
                out.push(format!("{prefix}{specifier}.py"));
            }
        }
        dedupe(out)
    }
}

fn relative_candidates(specifier: &str, source_path: &str) -> Vec<String> {
    let dots = specifier.chars().take_while(|c| *c == '.').count();
    let remainder = &specifier[dots..];

    let source_dir = parent_dir(source_path);
    let mut base = source_dir.to_string();
    for _ in 1..dots {
        base = parent_dir(&base).to_string();
    }

    let path_base = if remainder.is_empty() {
        base
    } else {
        join_posix(&base, &remainder.replace('.', "/"))
    };
    let path_base = normalize(&path_base);

    vec![format!("{path_base}.py"), format!("{path_base}/__init__.py")]
}

fn parent_dir(path: &str) -> &str {
    match path.rfind('/') {
        Some(idx) => &path[..idx],
        None => "",
    }
}

fn join_posix(left: &str, right: &str) -> String {
    if left.is_empty() {
        right.to_string()
    } else {
        format!("{left}/{right}")
    }
}

fn normalize(path: &str) -> String {
    let mut parts: Vec<&str> = Vec::new();
    for segment in path.split('/') {
        match segment {
            "" | "." => {}
            ".." => {
                parts.pop();
            }
            other => parts.push(other),
        }
    }
    if parts.is_empty() {
        ".".to_string()
    } else {
        parts.join("/")
    }
}

fn dedupe(items: Vec<String>) -> Vec<String> {
    let mut seen = std::collections::HashSet::new();
    let mut out = Vec::with_capacity(items.len());
    for item in items {
        if seen.insert(item.clone()) {
            out.push(item);
        }
    }
    out
}

fn walk_imports(node: Node<'_>, source: &[u8], out: &mut Vec<Import>) {
    match node.kind() {
        "import_statement" => collect_plain_imports(node, source, out),
        "import_from_statement" => collect_from_import(node, source, out),
        _ => {
            let mut cursor = node.walk();
            for child in node.children(&mut cursor) {
                walk_imports(child, source, out);
            }
        }
    }
}

fn collect_plain_imports(node: Node<'_>, source: &[u8], out: &mut Vec<Import>) {
    let mut cursor = node.walk();
    for child in node.children_by_field_name("name", &mut cursor) {
        if let Some(spec) = module_text(child, source) {
            out.push(Import {
                specifier: spec,
                names: Vec::new(),
            });
        }
    }
}

fn collect_from_import(node: Node<'_>, source: &[u8], out: &mut Vec<Import>) {
    let Some(module) = node.child_by_field_name("module_name") else {
        return;
    };
    let Some(specifier) = node_text(module, source) else {
        return;
    };

    let mut names = Vec::new();
    let mut cursor = node.walk();
    for child in node.children_by_field_name("name", &mut cursor) {
        if let Some(name) = module_text(child, source) {
            names.push(name);
        }
    }
    if names.is_empty() {
        let mut c = node.walk();
        for child in node.children(&mut c) {
            if child.kind() == "wildcard_import" {
                names.push("*".into());
            }
        }
    }

    out.push(Import { specifier, names });
}

fn module_text(node: Node<'_>, source: &[u8]) -> Option<String> {
    if node.kind() == "aliased_import" {
        let name_node = node.child_by_field_name("name")?;
        return node_text(name_node, source);
    }
    node_text(node, source)
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
        PythonExtractor::new()
            .extract(&ExtractionContext::new(source, "mod.py", "python"))
            .expect("python extraction")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    fn candidates(specifier: &str, source: &str) -> Vec<String> {
        let ctx = ResolverContext::default();
        PythonExtractor::new().generate_candidates(specifier, source, &ctx)
    }

    #[test]
    fn top_level_module_generates_prefixed_candidates() {
        let c = candidates("os", "pkg/mod.py");
        assert!(c.contains(&"os/__init__.py".into()));
        assert!(c.contains(&"os.py".into()));
        assert!(c.contains(&"src/os/__init__.py".into()));
        assert!(c.contains(&"lib/os.py".into()));
    }

    #[test]
    fn dotted_module_expands_path_segments() {
        let c = candidates("sylvan.search.embeddings", "pkg/mod.py");
        assert!(c.contains(&"sylvan/search/embeddings.py".into()));
        assert!(c.contains(&"sylvan/search/embeddings/__init__.py".into()));
        assert!(c.contains(&"src/sylvan/search/embeddings.py".into()));
    }

    #[test]
    fn single_dot_relative_resolves_against_source_dir() {
        let c = candidates(".utils", "pkg/sub/mod.py");
        assert_eq!(
            c,
            vec!["pkg/sub/utils.py", "pkg/sub/utils/__init__.py"]
        );
    }

    #[test]
    fn double_dot_relative_walks_up_one_package() {
        let c = candidates("..config", "pkg/sub/mod.py");
        assert_eq!(
            c,
            vec!["pkg/config.py", "pkg/config/__init__.py"]
        );
    }

    #[test]
    fn bare_dot_relative_points_to_package_itself() {
        let c = candidates(".", "pkg/sub/mod.py");
        assert_eq!(
            c,
            vec!["pkg/sub.py", "pkg/sub/__init__.py"]
        );
    }

    fn imports(src: &str) -> Vec<Import> {
        PythonExtractor::new()
            .extract_imports(&ExtractionContext::new(src, "mod.py", "python"))
            .expect("python imports")
    }

    #[test]
    fn plain_import_yields_specifier_only() {
        let imps = imports("import os\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "os");
        assert!(imps[0].names.is_empty());
    }

    #[test]
    fn multi_plain_import_splits_into_records() {
        let imps = imports("import os, sys\n");
        let specs: Vec<&str> = imps.iter().map(|i| i.specifier.as_str()).collect();
        assert_eq!(specs, vec!["os", "sys"]);
    }

    #[test]
    fn aliased_import_keeps_pre_as_name() {
        let imps = imports("import numpy as np\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "numpy");
    }

    #[test]
    fn from_import_records_names() {
        let imps = imports("from os.path import join, dirname\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "os.path");
        assert_eq!(imps[0].names, vec!["join", "dirname"]);
    }

    #[test]
    fn relative_from_import_preserves_dots() {
        let imps = imports("from .utils import helper\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, ".utils");
        assert_eq!(imps[0].names, vec!["helper"]);
    }

    #[test]
    fn wildcard_import_records_star() {
        let imps = imports("from os import *\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "os");
        assert_eq!(imps[0].names, vec!["*"]);
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
        assert!(sig.contains("(a: int, b: int)"));
        assert!(sig.contains("-> int"));
        assert_eq!(syms[0].param_count, 2);
    }

    #[test]
    fn decorator_expands_byte_range_and_is_captured() {
        let src = "@staticmethod\n@classmethod\ndef noop():\n    pass\n";
        let syms = extract(src);
        assert_eq!(syms.len(), 1);
        let sym = &syms[0];
        assert_eq!(sym.decorators, vec!["@staticmethod", "@classmethod"]);
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
        assert_eq!(cls.decorators, vec!["@register"]);
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
