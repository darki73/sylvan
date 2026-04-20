//! Rust extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the Rust grammar. Mirrors
//! the Rust [`LanguageSpec`] in the legacy Python plugin: functions,
//! impl/struct/enum/trait/type items, preceding-comment docstrings,
//! and parameter/return-type fields for signature stitching. No
//! decorators, no method promotion, no module-level constant
//! emission (the spec lists const/static/let patterns but the walker
//! only acts on patterns that resolve through `try_emit_constant`'s
//! assignment shape, so they pass through as non-symbol nodes here).
//!
//! Import extraction walks the parsed tree for `use_declaration`
//! nodes and traverses the `argument` subtree. Plain
//! `use a::b::c;` paths collapse to a single record with the leaf as
//! the lone name, matching the legacy Python regex split. Group use
//! (`use a::b::{c, d};`) produces a single record with the base path
//! as specifier and the leaf identifiers as names; nested groups are
//! flattened so every leaf surfaces in `names`. `use_as_clause` keeps
//! the aliased leaf (not the original) to reflect the name actually
//! bound in the module. Wildcard imports (`use a::b::*;`) emit `*`
//! as the lone name.
//!
//! Import resolution rejects `std::` and `core::` specifiers outright.
//! `crate::`-rooted paths strip the prefix and map the remaining
//! segments to `src/…` and repo-root variants, both as `<path>.rs` and
//! `<path>/mod.rs`. Bare `::`-separated paths with more than one
//! segment return the same `src/…` / plain file pair without a
//! `mod.rs` fallback, matching the legacy plugin. Single-segment paths
//! return no candidates since the resolver cannot distinguish a local
//! module from an external crate name without more context.
//!
//! Features left for later migration stages: self-receiver stripping,
//! and Rust-specific complexity.

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
        ("function_item", "function"),
        ("impl_item", "class"),
        ("struct_item", "class"),
        ("enum_item", "type"),
        ("trait_item", "type"),
        ("type_item", "type"),
    ],
    name_fields: &[
        ("function_item", "name"),
        ("impl_item", "type"),
        ("struct_item", "name"),
        ("enum_item", "name"),
        ("trait_item", "name"),
        ("type_item", "name"),
    ],
    name_resolutions: &[],
    param_fields: &[("function_item", "parameters")],
    return_type_fields: &[("function_item", "return_type")],
    container_node_types: &["impl_item", "trait_item"],
    docstring_strategy: DocstringStrategy::PrecedingComment,
    decorator_strategy: DecoratorStrategy::PrecedingSiblings {
        kinds: &["attribute_item", "inner_attribute_item"],
    },
    constant_strategy: ConstantStrategy::DirectItems {
        item_kinds: &["const_item", "static_item"],
        name_field: "name",
        uppercase_only: false,
    },
    parameter_kinds: &["parameter", "self_parameter"],
    method_promotion: &[],
};

/// Built-in Rust extractor.
pub struct RustExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl RustExtractor {
    /// Construct a fresh instance.
    pub fn new() -> Self {
        Self {
            inner: OnceLock::new(),
        }
    }

    fn delegate(&self) -> &SpecExtractor {
        self.inner.get_or_init(|| {
            SpecExtractor::new(&["rust"], crate::grammars::get_language("rust").expect("rust grammar"), &SPEC)
        })
    }
}

impl Default for RustExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for RustExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["rust"]
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
        _source_path: &str,
        _context: &ResolverContext,
    ) -> Vec<String> {
        generate_rust_candidates(specifier)
    }
}

fn generate_rust_candidates(specifier: &str) -> Vec<String> {
    if specifier.starts_with("std::") || specifier.starts_with("core::") {
        return Vec::new();
    }

    if let Some(remainder) = specifier.strip_prefix("crate::") {
        let parts: Vec<&str> = remainder.split("::").collect();
        let module_path = if parts.len() > 1 {
            parts[..parts.len() - 1].join("/")
        } else {
            parts[0].to_string()
        };
        return vec![
            format!("src/{module_path}.rs"),
            format!("src/{module_path}/mod.rs"),
            format!("{module_path}.rs"),
            format!("{module_path}/mod.rs"),
        ];
    }

    let parts: Vec<&str> = specifier.split("::").collect();
    if parts.len() > 1 {
        let module_path = parts[..parts.len() - 1].join("/");
        return vec![
            format!("src/{module_path}.rs"),
            format!("src/{module_path}/mod.rs"),
            format!("{module_path}.rs"),
        ];
    }

    Vec::new()
}

fn walk_imports(node: Node<'_>, source: &[u8], out: &mut Vec<Import>) {
    if node.kind() == "use_declaration" {
        if let Some(imp) = collect_use(node, source) {
            out.push(imp);
        }
        return;
    }
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        walk_imports(child, source, out);
    }
}

fn collect_use(node: Node<'_>, source: &[u8]) -> Option<Import> {
    let argument = node.child_by_field_name("argument")?;
    let mut names = Vec::new();
    let specifier = resolve_use_tree(argument, source, "", &mut names)?;
    Some(Import { specifier, names })
}

fn resolve_use_tree(
    node: Node<'_>,
    source: &[u8],
    base: &str,
    names: &mut Vec<String>,
) -> Option<String> {
    match node.kind() {
        "scoped_identifier" => {
            let full = node_text(node, source)?;
            let full = full.trim().to_string();
            if let Some(name) = node
                .child_by_field_name("name")
                .and_then(|n| node_text(n, source))
            {
                names.push(name);
            }
            Some(join_path(base, &full))
        }
        "identifier" | "self" | "super" | "crate" | "metavariable" => {
            let leaf = node_text(node, source)?;
            names.push(leaf.clone());
            Some(join_path(base, &leaf))
        }
        "use_wildcard" => {
            names.push("*".to_string());
            let path = node
                .child_by_field_name("path")
                .and_then(|p| node_text(p, source));
            match path {
                Some(p) => Some(join_path(base, p.trim())),
                None => {
                    let raw = node_text(node, source)?;
                    let trimmed = raw.trim().trim_end_matches("::*").trim_end_matches('*');
                    Some(join_path(base, trimmed.trim_end_matches("::")))
                }
            }
        }
        "use_as_clause" => {
            let alias = node
                .child_by_field_name("alias")
                .and_then(|a| node_text(a, source));
            let path_node = node.child_by_field_name("path")?;
            let path_text = node_text(path_node, source)?;
            if let Some(alias) = alias {
                names.push(alias);
            } else if let Some(leaf) = leaf_name(path_node, source) {
                names.push(leaf);
            }
            Some(join_path(base, path_text.trim()))
        }
        "scoped_use_list" => {
            let path_text = node
                .child_by_field_name("path")
                .and_then(|p| node_text(p, source))
                .map(|s| s.trim().to_string())
                .unwrap_or_default();
            let combined = join_path(base, &path_text);
            if let Some(list) = node.child_by_field_name("list") {
                expand_use_list(list, source, &combined, names);
            }
            Some(combined)
        }
        "use_list" => {
            expand_use_list(node, source, base, names);
            Some(base.to_string())
        }
        _ => {
            let text = node_text(node, source)?;
            Some(join_path(base, text.trim()))
        }
    }
}

fn expand_use_list(list: Node<'_>, source: &[u8], base: &str, names: &mut Vec<String>) {
    let mut cursor = list.walk();
    for child in list.children(&mut cursor) {
        match child.kind() {
            "," | "{" | "}" => continue,
            _ => {
                let mut discard = String::new();
                collect_list_item(child, source, base, names, &mut discard);
            }
        }
    }
}

fn collect_list_item(
    node: Node<'_>,
    source: &[u8],
    base: &str,
    names: &mut Vec<String>,
    _specifier: &mut String,
) {
    match node.kind() {
        "identifier" | "self" | "super" | "crate" => {
            if let Some(text) = node_text(node, source) {
                names.push(text);
            }
        }
        "scoped_identifier" => {
            if let Some(name) = node
                .child_by_field_name("name")
                .and_then(|n| node_text(n, source))
            {
                names.push(name);
            }
        }
        "use_as_clause" => {
            if let Some(alias) = node
                .child_by_field_name("alias")
                .and_then(|a| node_text(a, source))
            {
                names.push(alias);
            } else if let Some(path) = node.child_by_field_name("path") {
                if let Some(leaf) = leaf_name(path, source) {
                    names.push(leaf);
                }
            }
        }
        "use_wildcard" => {
            names.push("*".to_string());
        }
        "scoped_use_list" => {
            let path_text = node
                .child_by_field_name("path")
                .and_then(|p| node_text(p, source))
                .map(|s| s.trim().to_string())
                .unwrap_or_default();
            let combined = join_path(base, &path_text);
            if let Some(list) = node.child_by_field_name("list") {
                expand_use_list(list, source, &combined, names);
            }
        }
        "use_list" => {
            expand_use_list(node, source, base, names);
        }
        _ => {}
    }
}

fn leaf_name(node: Node<'_>, source: &[u8]) -> Option<String> {
    match node.kind() {
        "scoped_identifier" => node
            .child_by_field_name("name")
            .and_then(|n| node_text(n, source)),
        _ => node_text(node, source),
    }
}

fn join_path(base: &str, addition: &str) -> String {
    let a = addition.trim();
    if base.is_empty() {
        return a.to_string();
    }
    if a.is_empty() {
        return base.to_string();
    }
    format!("{base}::{a}")
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
        RustExtractor::new()
            .extract(&ExtractionContext::new(source, "lib.rs", "rust"))
            .expect("rust extraction")
    }

    fn imports(src: &str) -> Vec<Import> {
        RustExtractor::new()
            .extract_imports(&ExtractionContext::new(src, "lib.rs", "rust"))
            .expect("rust imports")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_top_level_function() {
        let syms = extract("fn greet() {}\n");
        assert_eq!(syms.len(), 1);
        assert_eq!(syms[0].name, "greet");
        assert_eq!(syms[0].kind, "function");
        assert_eq!(syms[0].qualified_name, "greet");
        assert_eq!(syms[0].language, "rust");
        let sig = syms[0].signature.as_deref().expect("signature");
        assert_eq!(sig, "fn greet()");
    }

    #[test]
    fn extracts_struct_symbol() {
        let syms = extract("struct Point { x: i32 }\n");
        let point = syms
            .iter()
            .find(|s| s.name == "Point")
            .expect("struct symbol");
        assert_eq!(point.kind, "class");
        assert_eq!(point.qualified_name, "Point");
    }

    #[test]
    fn impl_item_is_container_and_nests_methods() {
        let syms = extract("impl Foo { fn bar(&self) {} }\n");
        let parent = syms
            .iter()
            .find(|s| s.name == "Foo" && s.kind == "class")
            .expect("impl symbol");
        let bar = syms
            .iter()
            .find(|s| s.name == "bar")
            .expect("nested fn symbol");
        assert_eq!(bar.kind, "function");
        assert_eq!(bar.qualified_name, "Foo.bar");
        assert_eq!(
            bar.parent_symbol_id.as_deref(),
            Some(parent.symbol_id.as_str())
        );
    }

    #[test]
    fn preceding_triple_slash_comment_is_docstring() {
        let src = "/// doc\nfn x() {}\n";
        let syms = extract(src);
        let doc = syms[0].docstring.as_deref().expect("docstring");
        assert!(doc.contains("doc"), "expected doc fragment, got {doc:?}");
    }

    #[test]
    fn advertises_rust_language() {
        assert_eq!(RustExtractor::new().languages(), &["rust"]);
    }

    #[test]
    fn const_item_emits_constant() {
        let syms = extract("const MAX: u32 = 5;\n");
        let c = syms.iter().find(|s| s.kind == "constant").expect("constant");
        assert_eq!(c.name, "MAX");
    }

    #[test]
    fn static_item_emits_constant() {
        let syms = extract("static TABLE: &[u8] = &[];\n");
        let c = syms.iter().find(|s| s.kind == "constant").expect("constant");
        assert_eq!(c.name, "TABLE");
    }

    #[test]
    fn plain_use_records_path_and_leaf_name() {
        let imps = imports("use std::collections::HashMap;\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "std::collections::HashMap");
        assert_eq!(imps[0].names, vec!["HashMap"]);
    }

    #[test]
    fn group_use_flattens_into_names() {
        let imps = imports("use std::io::{Read, Write};\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "std::io");
        assert_eq!(imps[0].names, vec!["Read", "Write"]);
    }

    #[test]
    fn nested_group_use_flattens_leaf_names() {
        let imps = imports("use a::{b::{c, d}, e};\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "a");
        assert_eq!(imps[0].names, vec!["c", "d", "e"]);
    }

    #[test]
    fn aliased_use_keeps_alias_as_bound_name() {
        let imps = imports("use std::io::Result as IoResult;\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "std::io::Result");
        assert_eq!(imps[0].names, vec!["IoResult"]);
    }

    #[test]
    fn wildcard_use_records_star_name() {
        let imps = imports("use std::prelude::*;\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "std::prelude");
        assert_eq!(imps[0].names, vec!["*"]);
    }

    #[test]
    fn multiple_use_declarations_produce_multiple_records() {
        let src = "use std::io;\nuse std::fmt::Debug;\n";
        let imps = imports(src);
        assert_eq!(imps.len(), 2);
        assert_eq!(imps[0].specifier, "std::io");
        assert_eq!(imps[0].names, vec!["io"]);
        assert_eq!(imps[1].specifier, "std::fmt::Debug");
        assert_eq!(imps[1].names, vec!["Debug"]);
    }

    fn candidates(specifier: &str) -> Vec<String> {
        let ctx = ResolverContext::default();
        RustExtractor::new().generate_candidates(specifier, "src/lib.rs", &ctx)
    }

    #[test]
    fn std_prefixed_path_yields_no_candidates() {
        assert!(candidates("std::collections::HashMap").is_empty());
    }

    #[test]
    fn core_prefixed_path_yields_no_candidates() {
        assert!(candidates("core::mem::drop").is_empty());
    }

    #[test]
    fn crate_rooted_path_expands_to_src_and_root_variants() {
        let c = candidates("crate::module::Thing");
        assert_eq!(
            c,
            vec![
                "src/module.rs",
                "src/module/mod.rs",
                "module.rs",
                "module/mod.rs",
            ]
        );
    }

    #[test]
    fn crate_rooted_single_segment_uses_segment_as_module() {
        let c = candidates("crate::module");
        assert_eq!(
            c,
            vec![
                "src/module.rs",
                "src/module/mod.rs",
                "module.rs",
                "module/mod.rs",
            ]
        );
    }

    #[test]
    fn external_multi_segment_emits_src_and_plain_rs() {
        let c = candidates("serde::Deserialize");
        assert_eq!(c, vec!["src/serde.rs", "src/serde/mod.rs", "serde.rs"]);
    }

    #[test]
    fn single_segment_yields_no_candidates() {
        assert!(candidates("serde").is_empty());
    }

    #[test]
    fn crate_relative_use_keeps_crate_prefix() {
        let imps = imports("use crate::module::Thing;\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "crate::module::Thing");
        assert_eq!(imps[0].names, vec!["Thing"]);
    }
}
