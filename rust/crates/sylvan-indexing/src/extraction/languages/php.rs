//! PHP extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the PHP grammar. Mirrors
//! the legacy `sylvan.indexing.languages.php` spec: functions,
//! methods, classes, interfaces, traits, and enums, with preceding
//! comment docstrings. PHP source may be embedded in a file that also
//! contains non-PHP preamble (HTML), so we use `LANGUAGE_PHP` rather
//! than `LANGUAGE_PHP_ONLY`.
//!
//! Import extraction walks the parsed tree for
//! `namespace_use_declaration` nodes. Each `namespace_use_clause`
//! produces one record whose specifier is the backslash-separated
//! namespace path; aliasing clauses are ignored so the specifier holds
//! the imported symbol itself, matching the legacy regex output. Group
//! use (`use A\B\{C, D as E};`) is expanded by joining the group prefix
//! to each leaf `namespace_use_group_clause`, yielding one record per
//! leaf. `use function` and `use const` produce identical records to
//! plain `use`, again matching the Python plugin.
//!
//! Import resolution applies PSR-4 autoload mappings from the resolver
//! context (longest namespace prefix wins) and always appends the naive
//! `src/` and `app/` fallbacks so Laravel / Symfony projects without a
//! parsed composer.json still produce useful candidates.

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
    decorator_strategy: DecoratorStrategy::PrecedingSiblings {
        kinds: &["attribute_list"],
    },
    constant_strategy: ConstantStrategy::None,
    parameter_kinds: &[
        "simple_parameter",
        "variadic_parameter",
        "property_promotion_parameter",
    ],
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
        context: &ResolverContext,
    ) -> Vec<String> {
        generate_php_candidates(specifier, context)
    }
}

fn generate_php_candidates(specifier: &str, context: &ResolverContext) -> Vec<String> {
    let mut candidates: Vec<String> = Vec::new();

    if !context.psr4_mappings.is_empty() {
        let mut keys: Vec<&String> = context.psr4_mappings.keys().collect();
        keys.sort_by(|a, b| b.len().cmp(&a.len()));
        for prefix in keys {
            let ns_prefix = prefix.trim_end_matches('\\');
            let with_sep = format!("{ns_prefix}\\");
            if specifier == ns_prefix || specifier.starts_with(&with_sep) {
                let relative = specifier[ns_prefix.len()..].trim_start_matches('\\');
                let relative_path = relative.replace('\\', "/");
                if let Some(bases) = context.psr4_mappings.get(prefix) {
                    for base_dir in bases {
                        if relative_path.is_empty() {
                            candidates.push(format!("{base_dir}.php"));
                        } else {
                            candidates.push(format!("{base_dir}{relative_path}.php"));
                        }
                    }
                }
                if !candidates.is_empty() {
                    break;
                }
            }
        }
    }

    let path_base = specifier.replace('\\', "/");
    candidates.push(format!("{path_base}.php"));
    candidates.push(format!("src/{path_base}.php"));
    candidates.push(format!("app/{path_base}.php"));

    candidates
}

fn walk_imports(node: Node<'_>, source: &[u8], out: &mut Vec<Import>) {
    if node.kind() == "namespace_use_declaration" {
        collect_use_declaration(node, source, out);
        return;
    }
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        walk_imports(child, source, out);
    }
}

fn collect_use_declaration(node: Node<'_>, source: &[u8], out: &mut Vec<Import>) {
    let mut group: Option<Node<'_>> = None;
    let mut prefix: Option<String> = None;
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "namespace_use_clause" => {
                if group.is_none()
                    && let Some(path) = clause_path(child, source)
                {
                    out.push(Import {
                        specifier: path,
                        names: Vec::new(),
                    });
                }
            }
            "namespace_name" => {
                prefix = node_text(child, source);
            }
            "qualified_name" => {
                if prefix.is_none() {
                    prefix = node_text(child, source);
                }
            }
            "namespace_use_group" => {
                group = Some(child);
            }
            _ => {}
        }
    }

    if let Some(group_node) = group {
        let base = prefix.unwrap_or_default();
        collect_use_group(group_node, &base, source, out);
    }
}

fn collect_use_group(group: Node<'_>, prefix: &str, source: &[u8], out: &mut Vec<Import>) {
    let mut cursor = group.walk();
    for child in group.children(&mut cursor) {
        match child.kind() {
            "namespace_use_clause" | "namespace_use_group_clause" => {
                if let Some(leaf) = clause_path(child, source) {
                    let specifier = join_ns(prefix, &leaf);
                    if !specifier.is_empty() {
                        out.push(Import {
                            specifier,
                            names: Vec::new(),
                        });
                    }
                }
            }
            _ => {}
        }
    }
}

fn clause_path(node: Node<'_>, source: &[u8]) -> Option<String> {
    // Plain clause: contains a `qualified_name` holding the full dotted
    // path. Group-leaf clause: first `name` child is the leaf symbol,
    // any `name` after an `as` keyword is the alias we discard.
    let mut cursor = node.walk();
    let mut saw_as = false;
    let mut leaf_name: Option<String> = None;
    for child in node.children(&mut cursor) {
        match child.kind() {
            "qualified_name" => {
                return node_text(child, source);
            }
            "namespace_name" => {
                return node_text(child, source);
            }
            "as" => saw_as = true,
            "name" => {
                if !saw_as && leaf_name.is_none() {
                    leaf_name = node_text(child, source);
                }
            }
            _ => {}
        }
    }
    leaf_name
}

fn join_ns(prefix: &str, leaf: &str) -> String {
    let prefix = prefix.trim_end_matches('\\');
    let leaf = leaf.trim_start_matches('\\');
    if prefix.is_empty() {
        return leaf.to_string();
    }
    if leaf.is_empty() {
        return prefix.to_string();
    }
    format!("{prefix}\\{leaf}")
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
        PhpExtractor::new()
            .extract(&ExtractionContext::new(source, "mod.php", "php"))
            .expect("php extraction")
    }

    fn imports(src: &str) -> Vec<Import> {
        PhpExtractor::new()
            .extract_imports(&ExtractionContext::new(src, "mod.php", "php"))
            .expect("php imports")
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

    #[test]
    fn plain_use_records_namespace_path() {
        let imps = imports("<?php use Foo\\Bar; ?>");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "Foo\\Bar");
        assert!(imps[0].names.is_empty());
    }

    #[test]
    fn aliased_use_keeps_original_namespace_as_specifier() {
        let imps = imports("<?php use Foo\\Bar as Baz; ?>");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "Foo\\Bar");
        assert!(imps[0].names.is_empty());
    }

    #[test]
    fn use_function_records_same_shape_as_plain_use() {
        let imps = imports("<?php use function Foo\\bar; ?>");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "Foo\\bar");
        assert!(imps[0].names.is_empty());
    }

    #[test]
    fn use_const_records_same_shape_as_plain_use() {
        let imps = imports("<?php use const Foo\\BAR; ?>");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "Foo\\BAR");
        assert!(imps[0].names.is_empty());
    }

    #[test]
    fn group_use_expands_each_leaf_into_its_own_record() {
        let imps = imports("<?php use Foo\\{Bar, Baz}; ?>");
        let specs: Vec<&str> = imps.iter().map(|i| i.specifier.as_str()).collect();
        assert_eq!(specs, vec!["Foo\\Bar", "Foo\\Baz"]);
        assert!(imps.iter().all(|i| i.names.is_empty()));
    }

    #[test]
    fn group_use_strips_alias_from_each_leaf() {
        let imps = imports("<?php use Foo\\{Bar, Baz as Q}; ?>");
        let specs: Vec<&str> = imps.iter().map(|i| i.specifier.as_str()).collect();
        assert_eq!(specs, vec!["Foo\\Bar", "Foo\\Baz"]);
    }

    #[test]
    fn multiple_use_declarations_produce_multiple_records() {
        let src = "<?php use Foo\\Bar; use Baz\\Qux; ?>";
        let imps = imports(src);
        assert_eq!(imps.len(), 2);
        assert_eq!(imps[0].specifier, "Foo\\Bar");
        assert_eq!(imps[1].specifier, "Baz\\Qux");
    }

    fn candidates(specifier: &str, ctx: &ResolverContext) -> Vec<String> {
        PhpExtractor::new().generate_candidates(specifier, "does/not/matter.php", ctx)
    }

    fn psr4_ctx(entries: &[(&str, &[&str])]) -> ResolverContext {
        let mut ctx = ResolverContext::default();
        for (prefix, dirs) in entries {
            ctx.psr4_mappings.insert(
                (*prefix).to_string(),
                dirs.iter().map(|d| (*d).to_string()).collect(),
            );
        }
        ctx
    }

    #[test]
    fn plain_namespace_without_psr4_falls_back_to_naive_conversion() {
        let ctx = ResolverContext::default();
        let c = candidates("App\\Models\\User", &ctx);
        assert_eq!(
            c,
            vec![
                "App/Models/User.php",
                "src/App/Models/User.php",
                "app/App/Models/User.php",
            ]
        );
    }

    #[test]
    fn psr4_mapping_expands_prefix_to_base_dir() {
        let ctx = psr4_ctx(&[("App\\", &["src/"])]);
        let c = candidates("App\\Models\\User", &ctx);
        assert!(c.contains(&"src/Models/User.php".into()));
        assert!(c.contains(&"App/Models/User.php".into()));
    }

    #[test]
    fn psr4_longest_prefix_wins() {
        let ctx = psr4_ctx(&[
            ("App\\", &["src/"]),
            ("App\\Http\\", &["app/http/"]),
        ]);
        let c = candidates("App\\Http\\Controllers\\UserController", &ctx);
        assert!(c.contains(&"app/http/Controllers/UserController.php".into()));
        assert!(!c.contains(&"src/Http/Controllers/UserController.php".into()));
    }

    #[test]
    fn psr4_multiple_directories_emit_multiple_candidates() {
        let ctx = psr4_ctx(&[("App\\", &["src/", "lib/"])]);
        let c = candidates("App\\Foo", &ctx);
        assert!(c.contains(&"src/Foo.php".into()));
        assert!(c.contains(&"lib/Foo.php".into()));
    }

    #[test]
    fn psr4_prefix_without_trailing_backslash_matches_same() {
        let ctx = psr4_ctx(&[("App", &["src/"])]);
        let c = candidates("App\\Models\\User", &ctx);
        assert!(c.contains(&"src/Models/User.php".into()));
    }

    #[test]
    fn psr4_exact_namespace_match_emits_base_file() {
        let ctx = psr4_ctx(&[("App\\", &["src/App/"])]);
        let c = candidates("App", &ctx);
        assert!(c.contains(&"src/App/.php".into()));
    }

    #[test]
    fn non_matching_psr4_prefix_falls_back_to_naive() {
        let ctx = psr4_ctx(&[("Vendor\\", &["vendor/"])]);
        let c = candidates("App\\Models\\User", &ctx);
        assert!(!c.iter().any(|p| p.starts_with("vendor/")));
        assert!(c.contains(&"App/Models/User.php".into()));
        assert!(c.contains(&"src/App/Models/User.php".into()));
    }
}
