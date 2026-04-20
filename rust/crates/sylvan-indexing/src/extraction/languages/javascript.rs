//! JavaScript extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the JavaScript grammar.
//! Mirrors the spec declared by the legacy Python plugin: function
//! declarations, class declarations, and `method_definition` nodes
//! (which map directly to the `method` kind, so no promotion entry is
//! needed). Docstrings come from preceding `//` or `/** ... */` comment
//! siblings.
//!
//! Arrow functions, variable-declarator functions, and export wrappers
//! are intentionally not listed here. The Python spec does not include
//! them and this port stays byte-for-byte compatible with that surface.
//!
//! Import extraction walks the parsed tree for `import_statement` and
//! `export_statement` nodes with a `source` field, plus `require(...)`
//! and dynamic `import(...)` call expressions. Each record carries the
//! specifier (quotes stripped) and the list of bound names. Default,
//! namespace (`* as X`), and named (`{ a, b as c }`) clauses all feed
//! into the names vector; aliases collapse to the pre-`as` identifier
//! to match the legacy plugin.
//!
//! Import resolution covers relative specifiers (`./utils`, `../lib/x`)
//! against the source file's directory and tsconfig path aliases
//! (`@/components/Foo`) against the resolver context. Bare module
//! specifiers (`react`) return no candidates, letting the orchestrator
//! route external modules to library index lookups.

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
        ("function_declaration", "function"),
        ("class_declaration", "class"),
        ("method_definition", "method"),
    ],
    name_fields: &[
        ("function_declaration", "name"),
        ("class_declaration", "name"),
        ("method_definition", "name"),
    ],
    param_fields: &[
        ("function_declaration", "parameters"),
        ("method_definition", "parameters"),
    ],
    return_type_fields: &[],
    container_node_types: &["class_declaration", "class"],
    docstring_strategy: DocstringStrategy::PrecedingComment,
    decorator_strategy: DecoratorStrategy::None,
    constant_strategy: ConstantStrategy::None,
    parameter_kinds: &[
        "identifier",
        "rest_pattern",
        "assignment_pattern",
        "object_pattern",
        "array_pattern",
    ],
    method_promotion: &[],
};

/// Built-in JavaScript extractor.
pub struct JavaScriptExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl JavaScriptExtractor {
    /// Construct a fresh instance.
    pub fn new() -> Self {
        Self {
            inner: OnceLock::new(),
        }
    }

    fn delegate(&self) -> &SpecExtractor {
        self.inner.get_or_init(|| {
            SpecExtractor::new(
                &["javascript"],
                tree_sitter_javascript::LANGUAGE.into(),
                &SPEC,
            )
        })
    }
}

impl Default for JavaScriptExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for JavaScriptExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["javascript"]
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
        let mut seen = Vec::new();
        walk_imports(tree.root_node(), ctx.source_bytes, &mut out, &mut seen);
        Ok(out)
    }

    fn supports_resolution(&self) -> bool {
        true
    }

    fn generate_candidates(
        &self,
        specifier: &str,
        source_path: &str,
        context: &ResolverContext,
    ) -> Vec<String> {
        generate_js_candidates(specifier, source_path, context)
    }
}

const JS_EXTENSIONS: &[&str] = &[".js", ".ts", ".tsx", ".jsx", ".mjs", ".vue", ".svelte"];

fn generate_js_candidates(
    specifier: &str,
    source_path: &str,
    context: &ResolverContext,
) -> Vec<String> {
    if !context.tsconfig_aliases.is_empty() && !specifier.starts_with('.') {
        if let Some(expanded) = expand_ts_alias(specifier, &context.tsconfig_aliases) {
            return extension_candidates(&expanded);
        }
    }

    if !specifier.starts_with('.') && !specifier.starts_with('/') {
        return Vec::new();
    }

    let source_dir = parent_dir(source_path);
    let joined = join_posix(source_dir, specifier);
    let resolved = normalize(&joined);

    extension_candidates(&resolved)
}

fn expand_ts_alias(
    specifier: &str,
    aliases: &std::collections::BTreeMap<String, Vec<String>>,
) -> Option<String> {
    let mut keys: Vec<&String> = aliases.keys().collect();
    keys.sort_by(|a, b| b.len().cmp(&a.len()));
    for alias in keys {
        let with_slash = format!("{alias}/");
        if specifier == alias.as_str() || specifier.starts_with(&with_slash) {
            let remainder = specifier[alias.len()..].trim_start_matches('/');
            if let Some(targets) = aliases.get(alias) {
                if let Some(target) = targets.first() {
                    if remainder.is_empty() {
                        return Some(target.clone());
                    }
                    return Some(format!("{target}/{remainder}"));
                }
            }
        }
    }
    None
}

fn extension_candidates(resolved: &str) -> Vec<String> {
    let mut candidates = vec![resolved.to_string()];
    if JS_EXTENSIONS.iter().any(|ext| resolved.ends_with(ext)) {
        return candidates;
    }
    for ext in [".js", ".ts", ".tsx", ".jsx", ".mjs", ".vue"] {
        candidates.push(format!("{resolved}{ext}"));
    }
    for index in ["/index.js", "/index.ts", "/index.tsx"] {
        candidates.push(format!("{resolved}{index}"));
    }
    candidates
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

fn walk_imports(node: Node<'_>, source: &[u8], out: &mut Vec<Import>, seen: &mut Vec<String>) {
    match node.kind() {
        "import_statement" => {
            collect_import_statement(node, source, out, seen);
            return;
        }
        "export_statement" => {
            if collect_export_statement(node, source, out, seen) {
                return;
            }
        }
        "call_expression" => {
            if collect_call_expression(node, source, out, seen) {
                return;
            }
        }
        _ => {}
    }
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        walk_imports(child, source, out, seen);
    }
}

fn collect_import_statement(
    node: Node<'_>,
    source: &[u8],
    out: &mut Vec<Import>,
    seen: &mut Vec<String>,
) {
    let Some(specifier) = source_specifier(node, source) else {
        return;
    };

    let mut names = Vec::new();
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "import_clause" => collect_clause_names(child, source, &mut names),
            "import_require_clause" => {
                if let Some(id) = first_identifier(child, source) {
                    names.push(id);
                }
            }
            _ => {}
        }
    }
    seen.push(specifier.clone());
    out.push(Import { specifier, names });
}

fn collect_export_statement(
    node: Node<'_>,
    source: &[u8],
    out: &mut Vec<Import>,
    seen: &mut Vec<String>,
) -> bool {
    let Some(specifier) = source_specifier(node, source) else {
        return false;
    };

    let mut names = Vec::new();
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "export_clause" {
            collect_export_clause_names(child, source, &mut names);
        }
    }
    seen.push(specifier.clone());
    out.push(Import { specifier, names });
    true
}

fn collect_call_expression(
    node: Node<'_>,
    source: &[u8],
    out: &mut Vec<Import>,
    seen: &mut Vec<String>,
) -> bool {
    let Some(func) = node.child_by_field_name("function") else {
        return false;
    };
    let is_call = match func.kind() {
        "identifier" => node_text(func, source).as_deref() == Some("require"),
        "import" => true,
        _ => false,
    };
    if !is_call {
        return false;
    }

    let Some(args) = node.child_by_field_name("arguments") else {
        return false;
    };
    let mut cursor = args.walk();
    let specifier = args
        .children(&mut cursor)
        .find_map(|child| literal_string(child, source));
    let Some(specifier) = specifier else {
        return false;
    };
    if seen.iter().any(|s| s == &specifier) {
        return true;
    }
    seen.push(specifier.clone());
    out.push(Import {
        specifier,
        names: Vec::new(),
    });
    true
}

fn collect_clause_names(clause: Node<'_>, source: &[u8], names: &mut Vec<String>) {
    let mut cursor = clause.walk();
    for child in clause.children(&mut cursor) {
        match child.kind() {
            "identifier" => {
                if let Some(n) = node_text(child, source) {
                    names.push(n);
                }
            }
            "namespace_import" => {
                if let Some(id) = first_identifier(child, source) {
                    names.push(id);
                }
            }
            "named_imports" => collect_named_imports(child, source, names),
            _ => {}
        }
    }
}

fn collect_named_imports(node: Node<'_>, source: &[u8], names: &mut Vec<String>) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "import_specifier" {
            if let Some(name_node) = child.child_by_field_name("name") {
                if let Some(n) = node_text(name_node, source) {
                    names.push(n);
                }
            }
        }
    }
}

fn collect_export_clause_names(node: Node<'_>, source: &[u8], names: &mut Vec<String>) {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "export_specifier" {
            if let Some(name_node) = child.child_by_field_name("name") {
                if let Some(n) = node_text(name_node, source) {
                    names.push(n);
                }
            }
        }
    }
}

fn first_identifier(node: Node<'_>, source: &[u8]) -> Option<String> {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if child.kind() == "identifier" {
            return node_text(child, source);
        }
    }
    None
}

fn source_specifier(node: Node<'_>, source: &[u8]) -> Option<String> {
    let src_node = node.child_by_field_name("source")?;
    literal_string(src_node, source)
}

fn literal_string(node: Node<'_>, source: &[u8]) -> Option<String> {
    if node.kind() != "string" {
        return None;
    }
    let raw = node_text(node, source)?;
    Some(strip_quotes(&raw))
}

fn strip_quotes(raw: &str) -> String {
    let trimmed = raw.trim();
    let bytes = trimmed.as_bytes();
    if bytes.len() >= 2 {
        let first = bytes[0];
        let last = bytes[bytes.len() - 1];
        if (first == b'"' && last == b'"')
            || (first == b'\'' && last == b'\'')
            || (first == b'`' && last == b'`')
        {
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
        JavaScriptExtractor::new()
            .extract(&ExtractionContext::new(source, "mod.js", "javascript"))
            .expect("javascript extraction")
    }

    fn imports(src: &str) -> Vec<Import> {
        JavaScriptExtractor::new()
            .extract_imports(&ExtractionContext::new(src, "mod.js", "javascript"))
            .expect("javascript imports")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_top_level_function_with_signature() {
        let syms = extract("function add(a, b) { return a + b; }\n");
        assert_eq!(syms.len(), 1);
        assert_eq!(syms[0].name, "add");
        assert_eq!(syms[0].kind, "function");
        assert_eq!(syms[0].language, "javascript");
        let sig = syms[0].signature.as_deref().expect("signature");
        assert!(sig.contains("(a, b)"), "signature was {sig:?}");
        assert_eq!(syms[0].param_count, 2);
    }

    #[test]
    fn class_with_method_is_promoted_via_method_definition_node() {
        let syms = extract("class Dog { bark() {} }\n");
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
    fn preceding_jsdoc_becomes_docstring() {
        let src = "/** say hi */\nfunction say() {}\n";
        let syms = extract(src);
        assert_eq!(syms.len(), 1);
        let doc = syms[0].docstring.as_deref().expect("docstring");
        assert!(doc.contains("say hi"), "docstring was {doc:?}");
    }

    #[test]
    fn arrow_and_variable_declarator_functions_are_not_extracted() {
        let syms = extract("const f = () => 1;\n");
        assert!(
            syms.is_empty(),
            "expected no symbols for variable-bound arrow, got {syms:?}"
        );
    }

    #[test]
    fn advertises_javascript_language() {
        assert_eq!(JavaScriptExtractor::new().languages(), &["javascript"]);
    }

    #[test]
    fn default_import_records_binding_name() {
        let imps = imports("import foo from \"./foo\";\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "./foo");
        assert_eq!(imps[0].names, vec!["foo"]);
    }

    #[test]
    fn named_imports_split_and_aliases_collapse_to_pre_as_name() {
        let imps = imports("import { a, b as c } from \"lib\";\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "lib");
        assert_eq!(imps[0].names, vec!["a", "b"]);
    }

    #[test]
    fn namespace_import_records_identifier() {
        let imps = imports("import * as NS from \"ns\";\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "ns");
        assert_eq!(imps[0].names, vec!["NS"]);
    }

    #[test]
    fn side_effect_import_has_no_names() {
        let imps = imports("import \"./side\";\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "./side");
        assert!(imps[0].names.is_empty());
    }

    #[test]
    fn require_call_records_specifier() {
        let imps = imports("const x = require('pkg');\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "pkg");
        assert!(imps[0].names.is_empty());
    }

    #[test]
    fn dynamic_import_records_specifier() {
        let imps = imports("const m = import('./dyn');\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "./dyn");
    }

    #[test]
    fn re_export_from_source_is_recorded_as_import() {
        let imps = imports("export { a, b } from \"src\";\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "src");
        assert_eq!(imps[0].names, vec!["a", "b"]);
    }

    #[test]
    fn export_star_from_source_records_specifier_without_names() {
        let imps = imports("export * from \"all\";\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "all");
        assert!(imps[0].names.is_empty());
    }

    #[test]
    fn default_plus_named_import_records_both() {
        let imps = imports("import foo, { bar, baz as qux } from \"./x\";\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "./x");
        assert_eq!(imps[0].names, vec!["foo", "bar", "baz"]);
    }

    fn candidates(specifier: &str, source: &str, ctx: &ResolverContext) -> Vec<String> {
        JavaScriptExtractor::new().generate_candidates(specifier, source, ctx)
    }

    fn alias_ctx(entries: &[(&str, &[&str])]) -> ResolverContext {
        let mut ctx = ResolverContext::default();
        for (alias, targets) in entries {
            ctx.tsconfig_aliases.insert(
                (*alias).to_string(),
                targets.iter().map(|t| (*t).to_string()).collect(),
            );
        }
        ctx
    }

    #[test]
    fn relative_specifier_expands_sibling_extensions() {
        let ctx = ResolverContext::default();
        let c = candidates("./utils", "src/a.ts", &ctx);
        assert!(c.contains(&"src/utils".into()));
        assert!(c.contains(&"src/utils.ts".into()));
        assert!(c.contains(&"src/utils.tsx".into()));
        assert!(c.contains(&"src/utils.js".into()));
        assert!(c.contains(&"src/utils.jsx".into()));
        assert!(c.contains(&"src/utils.mjs".into()));
        assert!(c.contains(&"src/utils.vue".into()));
        assert!(c.contains(&"src/utils/index.ts".into()));
        assert!(c.contains(&"src/utils/index.js".into()));
        assert!(c.contains(&"src/utils/index.tsx".into()));
    }

    #[test]
    fn parent_specifier_walks_up_one_directory() {
        let ctx = ResolverContext::default();
        let c = candidates("../x", "src/a/b.ts", &ctx);
        assert!(c.contains(&"src/x".into()));
        assert!(c.contains(&"src/x.ts".into()));
        assert!(c.contains(&"src/x/index.ts".into()));
    }

    #[test]
    fn tsconfig_alias_expands_against_first_target() {
        let ctx = alias_ctx(&[("@", &["resources/js"])]);
        let c = candidates("@/components/Foo", "src/a.ts", &ctx);
        assert!(c.contains(&"resources/js/components/Foo".into()));
        assert!(c.contains(&"resources/js/components/Foo.ts".into()));
        assert!(c.contains(&"resources/js/components/Foo.tsx".into()));
        assert!(c.contains(&"resources/js/components/Foo.vue".into()));
        assert!(c.contains(&"resources/js/components/Foo/index.ts".into()));
    }

    #[test]
    fn tsconfig_alias_matches_longest_prefix() {
        let ctx = alias_ctx(&[("@", &["src"]), ("@lib", &["packages/lib"])]);
        let c = candidates("@lib/util", "a.ts", &ctx);
        assert!(c.iter().any(|p| p.starts_with("packages/lib/util")));
        assert!(!c.iter().any(|p| p.starts_with("src/lib")));
    }

    #[test]
    fn tsconfig_alias_bare_match_returns_target_dir() {
        let ctx = alias_ctx(&[("@", &["resources/js"])]);
        let c = candidates("@", "src/a.ts", &ctx);
        assert_eq!(c[0], "resources/js");
    }

    #[test]
    fn bare_package_specifier_returns_no_candidates() {
        let ctx = ResolverContext::default();
        let c = candidates("react", "src/a.ts", &ctx);
        assert!(c.is_empty());
    }

    #[test]
    fn bare_specifier_with_non_matching_alias_returns_no_candidates() {
        let ctx = alias_ctx(&[("@", &["resources/js"])]);
        let c = candidates("react", "src/a.ts", &ctx);
        assert!(c.is_empty());
    }

    #[test]
    fn specifier_with_known_extension_is_not_extended() {
        let ctx = ResolverContext::default();
        let c = candidates("./widget.vue", "src/a.ts", &ctx);
        assert_eq!(c, vec!["src/widget.vue"]);
    }
}
