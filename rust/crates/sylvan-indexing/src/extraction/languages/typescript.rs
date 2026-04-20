//! TypeScript and TSX extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the two grammars exposed by
//! `tree-sitter-typescript`. A single [`LanguageSpec`] drives both, so
//! `.ts` and `.tsx` share symbol-node coverage and only differ in the
//! underlying parser.
//!
//! The spec mirrors the Python JavaScript plugin: function / class /
//! method symbols with preceding-comment docstrings, class containers
//! for method scoping, no decorator wrapper, no constant extraction.
//!
//! Import extraction walks the parsed tree for `import_statement` and
//! `export_statement` source clauses, `require(...)` calls, dynamic
//! `import(...)` calls, and the TS-only `import foo = require("bar")`
//! syntax (`import_require_clause`). Each record carries the bare
//! specifier and the list of bound names with aliases collapsed to the
//! pre-`as` identifier.
//!
//! Import resolution mirrors the JavaScript plugin: relative specifiers
//! resolve against the source directory and produce extension variants
//! for `.js`, `.ts`, `.tsx`, `.jsx`, `.mjs`, `.vue`, plus `/index.*`
//! variants. Bare specifiers that match a configured tsconfig alias
//! expand against the alias's first target; anything else returns
//! empty for the orchestrator to route elsewhere.

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
        ("interface_declaration", "type"),
        ("type_alias_declaration", "type"),
        ("enum_declaration", "type"),
    ],
    name_fields: &[
        ("function_declaration", "name"),
        ("class_declaration", "name"),
        ("method_definition", "name"),
        ("interface_declaration", "name"),
        ("type_alias_declaration", "name"),
        ("enum_declaration", "name"),
    ],
    name_resolutions: &[],
    param_fields: &[
        ("function_declaration", "parameters"),
        ("method_definition", "parameters"),
    ],
    return_type_fields: &[
        ("function_declaration", "return_type"),
        ("method_definition", "return_type"),
    ],
    container_node_types: &["class_declaration", "class"],
    docstring_strategy: DocstringStrategy::PrecedingComment,
    decorator_strategy: DecoratorStrategy::PrecedingSiblings {
        kinds: &["decorator"],
    },
    constant_strategy: ConstantStrategy::None,
    parameter_kinds: &[
        "required_parameter",
        "optional_parameter",
        "rest_pattern",
        "identifier",
        "assignment_pattern",
    ],
    method_promotion: &[],
};

/// Built-in TypeScript / TSX extractor.
pub struct TypeScriptExtractor {
    ts_extractor: OnceLock<SpecExtractor>,
    tsx_extractor: OnceLock<SpecExtractor>,
}

impl TypeScriptExtractor {
    /// Construct a fresh instance.
    pub fn new() -> Self {
        Self {
            ts_extractor: OnceLock::new(),
            tsx_extractor: OnceLock::new(),
        }
    }

    fn ts_delegate(&self) -> &SpecExtractor {
        self.ts_extractor.get_or_init(|| {
            SpecExtractor::new(
                &["typescript"],
                crate::grammars::get_language("typescript").expect("typescript grammar"),
                &SPEC,
            )
        })
    }

    fn tsx_delegate(&self) -> &SpecExtractor {
        self.tsx_extractor.get_or_init(|| {
            SpecExtractor::new(
                &["tsx"],
                crate::grammars::get_language("tsx").expect("tsx grammar"),
                &SPEC,
            )
        })
    }

    fn delegate_for(&self, language: &str) -> Option<&SpecExtractor> {
        match language {
            "typescript" => Some(self.ts_delegate()),
            "tsx" => Some(self.tsx_delegate()),
            _ => None,
        }
    }
}

impl Default for TypeScriptExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for TypeScriptExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["typescript", "tsx"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        match self.delegate_for(ctx.language) {
            Some(delegate) => delegate.extract(ctx),
            None => Ok(Vec::new()),
        }
    }

    fn supports_imports(&self) -> bool {
        true
    }

    fn extract_imports(
        &self,
        ctx: &ExtractionContext<'_>,
    ) -> Result<Vec<Import>, ExtractionError> {
        let Some(delegate) = self.delegate_for(ctx.language) else {
            return Ok(Vec::new());
        };
        let tree = delegate.parse(ctx)?;
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
        generate_ts_candidates(specifier, source_path, context)
    }
}

const JS_EXTENSIONS: &[&str] = &[".js", ".ts", ".tsx", ".jsx", ".mjs", ".vue", ".svelte"];

fn generate_ts_candidates(
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
    let mut names = Vec::new();
    let mut require_specifier: Option<String> = None;

    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "import_clause" => collect_clause_names(child, source, &mut names),
            "import_require_clause" => {
                if let Some(id) = first_identifier(child, source) {
                    names.push(id);
                }
                require_specifier = require_clause_specifier(child, source);
            }
            _ => {}
        }
    }

    let specifier = require_specifier.or_else(|| source_specifier(node, source));
    let Some(specifier) = specifier else {
        return;
    };
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

fn require_clause_specifier(node: Node<'_>, source: &[u8]) -> Option<String> {
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        if let Some(spec) = literal_string(child, source) {
            return Some(spec);
        }
    }
    None
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

    fn extract_ts(source: &str) -> Vec<Symbol> {
        TypeScriptExtractor::new()
            .extract(&ExtractionContext::new(source, "mod.ts", "typescript"))
            .expect("typescript extraction")
    }

    fn extract_tsx(source: &str, filename: &str) -> Vec<Symbol> {
        TypeScriptExtractor::new()
            .extract(&ExtractionContext::new(source, filename, "tsx"))
            .expect("tsx extraction")
    }

    fn imports_ts(src: &str) -> Vec<Import> {
        TypeScriptExtractor::new()
            .extract_imports(&ExtractionContext::new(src, "mod.ts", "typescript"))
            .expect("typescript imports")
    }

    fn imports_tsx(src: &str) -> Vec<Import> {
        TypeScriptExtractor::new()
            .extract_imports(&ExtractionContext::new(src, "mod.tsx", "tsx"))
            .expect("tsx imports")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract_ts("").is_empty());
    }

    #[test]
    fn extracts_typed_function_with_signature() {
        let src = "function add(a: number, b: number): number { return a+b; }\n";
        let syms = extract_ts(src);
        assert_eq!(syms.len(), 1);
        let sym = &syms[0];
        assert_eq!(sym.name, "add");
        assert_eq!(sym.kind, "function");
        assert_eq!(sym.language, "typescript");
        let sig = sym.signature.as_deref().expect("signature");
        assert!(sig.contains("(a: number, b: number)"));
        assert!(sig.contains("number"));
    }

    #[test]
    fn class_with_method_is_extracted() {
        let src = "class Dog { bark() {} }\n";
        let syms = extract_ts(src);
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
    fn tsx_grammar_parses_jsx_without_emitting_arrow_const() {
        let syms = extract_tsx("const X = () => <div/>;\n", "mod.tsx");
        assert!(syms.is_empty());
    }

    #[test]
    fn advertises_typescript_and_tsx_languages() {
        assert_eq!(
            TypeScriptExtractor::new().languages(),
            &["typescript", "tsx"]
        );
    }

    #[test]
    fn default_import_records_binding_name() {
        let imps = imports_ts("import foo from \"./foo\";\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "./foo");
        assert_eq!(imps[0].names, vec!["foo"]);
    }

    #[test]
    fn named_imports_split_and_aliases_collapse() {
        let imps = imports_ts("import { a, b as c } from \"lib\";\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "lib");
        assert_eq!(imps[0].names, vec!["a", "b"]);
    }

    #[test]
    fn namespace_import_records_identifier() {
        let imps = imports_ts("import * as NS from \"ns\";\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "ns");
        assert_eq!(imps[0].names, vec!["NS"]);
    }

    #[test]
    fn side_effect_import_has_no_names() {
        let imps = imports_ts("import \"./side\";\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "./side");
        assert!(imps[0].names.is_empty());
    }

    #[test]
    fn type_only_import_records_like_regular_named() {
        let imps = imports_ts("import type { Foo } from \"mod\";\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "mod");
        assert_eq!(imps[0].names, vec!["Foo"]);
    }

    #[test]
    fn ts_import_require_records_specifier_and_binding() {
        let imps = imports_ts("import foo = require(\"bar\");\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "bar");
        assert_eq!(imps[0].names, vec!["foo"]);
    }

    #[test]
    fn require_call_records_specifier() {
        let imps = imports_ts("const x = require('pkg');\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "pkg");
    }

    #[test]
    fn dynamic_import_records_specifier() {
        let imps = imports_ts("const m = import('./dyn');\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "./dyn");
    }

    #[test]
    fn re_export_from_source_is_recorded_as_import() {
        let imps = imports_ts("export { a, b } from \"src\";\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "src");
        assert_eq!(imps[0].names, vec!["a", "b"]);
    }

    #[test]
    fn tsx_imports_are_also_extracted() {
        let imps = imports_tsx("import React from \"react\";\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "react");
        assert_eq!(imps[0].names, vec!["React"]);
    }

    fn candidates(specifier: &str, source: &str, ctx: &ResolverContext) -> Vec<String> {
        TypeScriptExtractor::new().generate_candidates(specifier, source, ctx)
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
        assert!(c.contains(&"src/utils.vue".into()));
        assert!(c.contains(&"src/utils/index.ts".into()));
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
    fn bare_package_specifier_returns_no_candidates() {
        let ctx = ResolverContext::default();
        let c = candidates("react", "src/a.ts", &ctx);
        assert!(c.is_empty());
    }

    #[test]
    fn svelte_alias_variant_preserves_known_extension() {
        let ctx = alias_ctx(&[("$lib", &["src/lib"])]);
        let c = candidates("$lib/Button.svelte", "src/app.ts", &ctx);
        assert_eq!(c, vec!["src/lib/Button.svelte"]);
    }

    #[test]
    fn tsx_grammar_uses_same_resolution_path() {
        let ctx = ResolverContext::default();
        let c = TypeScriptExtractor::new().generate_candidates("./Widget", "app.tsx", &ctx);
        assert!(c.contains(&"Widget".into()));
        assert!(c.contains(&"Widget.tsx".into()));
    }
}
