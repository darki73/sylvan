//! Java extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the Java grammar. Mirrors
//! the spec declared in the legacy Python plugin: class, interface,
//! enum, method, and constructor declarations. Docstrings come from
//! preceding `//` or `/** ... */` comments. Java annotations
//! (`@Override`, `@Deprecated`) live inside a `modifiers` child of the
//! declaration rather than a wrapper, so the spec uses
//! [`DecoratorStrategy::InnerModifiers`] to reach them.
//!
//! Import extraction walks the parsed tree for `import_declaration`
//! nodes. The dotted path lives in a `scoped_identifier` /
//! `identifier` child and `.*` wildcards surface as an `asterisk`
//! child. Matching the legacy Python plugin's split behaviour, the
//! trailing identifier becomes the sole `names` entry when present,
//! while wildcard (`package.*`) and static wildcard imports keep the
//! dotted package as specifier and place `*` in the `names` list.
//!
//! Import resolution converts the dotted package to a path and emits
//! candidates against the repo root plus the Maven / Gradle layouts
//! `src/main/java/`, `src/main/kotlin/`, and `src/`. The extension is
//! derived from the source file — `.kt` / `.kts` source yields `.kt`
//! candidates, everything else yields `.java`.
//!
//! Features left for later migration stages: complexity tuning.

use std::sync::OnceLock;

use sylvan_core::{
    ExtractionContext, ExtractionError, Import, LanguageExtractor, ResolverContext, Symbol,
};
use tree_sitter::Node;

use crate::extraction::spec::{
    ConstantStrategy, DecoratorStrategy, DocstringStrategy, LanguageSpec, ModifierLocation,
    SpecExtractor,
};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[
        ("method_declaration", "method"),
        ("class_declaration", "class"),
        ("interface_declaration", "type"),
        ("enum_declaration", "type"),
        ("constructor_declaration", "method"),
    ],
    name_fields: &[
        ("method_declaration", "name"),
        ("class_declaration", "name"),
        ("interface_declaration", "name"),
        ("enum_declaration", "name"),
        ("constructor_declaration", "name"),
    ],
    name_resolutions: &[],
    param_fields: &[
        ("method_declaration", "parameters"),
        ("constructor_declaration", "parameters"),
    ],
    return_type_fields: &[("method_declaration", "type")],
    container_node_types: &[
        "class_declaration",
        "interface_declaration",
        "enum_declaration",
    ],
    docstring_strategy: DocstringStrategy::PrecedingComment,
    decorator_strategy: DecoratorStrategy::InnerModifiers {
        container: "modifiers",
        kinds: &["annotation", "marker_annotation"],
    },
    constant_strategy: ConstantStrategy::ModifiedField {
        field_kinds: &["field_declaration"],
        modifiers: ModifierLocation::Container { name: "modifiers" },
        required_modifiers: &["static", "final"],
        declarator_kind: "variable_declarator",
        name_field: "name",
        uppercase_only: true,
    },
    parameter_kinds: &["formal_parameter", "spread_parameter"],
    method_promotion: &[],
};

/// Built-in Java extractor.
pub struct JavaExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl JavaExtractor {
    /// Construct a fresh instance.
    pub fn new() -> Self {
        Self {
            inner: OnceLock::new(),
        }
    }

    fn delegate(&self) -> &SpecExtractor {
        self.inner.get_or_init(|| {
            SpecExtractor::new(&["java"], crate::grammars::get_language("java").expect("java grammar"), &SPEC)
        })
    }
}

impl Default for JavaExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for JavaExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["java"]
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
        generate_java_candidates(specifier, source_path)
    }
}

fn generate_java_candidates(specifier: &str, source_path: &str) -> Vec<String> {
    let path_base = specifier.replace('.', "/");
    let ext = if source_path.ends_with(".kt") || source_path.ends_with(".kts") {
        ".kt"
    } else {
        ".java"
    };
    let mut out = Vec::with_capacity(4);
    for prefix in ["", "src/main/java/", "src/main/kotlin/", "src/"] {
        out.push(format!("{prefix}{path_base}{ext}"));
    }
    out
}

fn walk_imports(node: Node<'_>, source: &[u8], out: &mut Vec<Import>) {
    if node.kind() == "import_declaration" {
        if let Some(imp) = collect_import(node, source) {
            out.push(imp);
        }
        return;
    }
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        walk_imports(child, source, out);
    }
}

fn collect_import(node: Node<'_>, source: &[u8]) -> Option<Import> {
    let mut path: Option<String> = None;
    let mut wildcard = false;
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        match child.kind() {
            "scoped_identifier" | "identifier" => {
                if path.is_none() {
                    path = node_text(child, source);
                }
            }
            "asterisk" => wildcard = true,
            _ => {}
        }
    }

    let dotted = path?;
    if dotted.is_empty() {
        return None;
    }

    if wildcard {
        return Some(Import {
            specifier: dotted,
            names: vec!["*".to_string()],
        });
    }

    match dotted.rsplit_once('.') {
        Some((base, tail)) if !base.is_empty() && !tail.is_empty() => Some(Import {
            specifier: base.to_string(),
            names: vec![tail.to_string()],
        }),
        _ => Some(Import {
            specifier: dotted,
            names: Vec::new(),
        }),
    }
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
        JavaExtractor::new()
            .extract(&ExtractionContext::new(source, "Mod.java", "java"))
            .expect("java extraction")
    }

    fn imports(src: &str) -> Vec<Import> {
        JavaExtractor::new()
            .extract_imports(&ExtractionContext::new(src, "Mod.java", "java"))
            .expect("java imports")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn class_with_method_nests_method_under_class() {
        let syms = extract("class Foo { void bar() {} }");
        assert_eq!(syms.len(), 2);
        let cls = syms.iter().find(|s| s.kind == "class").expect("class");
        let method = syms.iter().find(|s| s.kind == "method").expect("method");
        assert_eq!(cls.name, "Foo");
        assert_eq!(method.name, "bar");
        assert_eq!(method.qualified_name, "Foo.bar");
        assert_eq!(method.parent_symbol_id.as_deref(), Some(cls.symbol_id.as_str()));
    }

    #[test]
    fn constructor_is_emitted_as_method() {
        let syms = extract("public class Foo { public Foo() {} }");
        let cls = syms.iter().find(|s| s.kind == "class").expect("class");
        assert_eq!(cls.name, "Foo");
        let ctor = syms
            .iter()
            .find(|s| s.kind == "method" && s.name == "Foo")
            .expect("constructor");
        assert_eq!(ctor.qualified_name, "Foo.Foo");
        assert_eq!(ctor.parent_symbol_id.as_deref(), Some(cls.symbol_id.as_str()));
    }

    #[test]
    fn interface_declaration_becomes_type_symbol() {
        let syms = extract("interface I { void doIt(); }");
        let iface = syms.iter().find(|s| s.kind == "type").expect("interface");
        assert_eq!(iface.name, "I");
    }

    #[test]
    fn preceding_block_comment_becomes_docstring() {
        let src = "/** doc */\nclass X {}\n";
        let syms = extract(src);
        let cls = syms.iter().find(|s| s.kind == "class").expect("class");
        let doc = cls.docstring.as_deref().expect("docstring");
        assert!(doc.contains("doc"), "docstring was {doc:?}");
    }

    #[test]
    fn signature_includes_params() {
        let src = "class G { public void greet(String name) {} }";
        let syms = extract(src);
        let method = syms.iter().find(|s| s.kind == "method").expect("method");
        let sig = method.signature.as_deref().expect("signature");
        assert!(
            sig.contains("greet(String name)"),
            "signature was {sig:?}"
        );
    }

    #[test]
    fn advertises_java_language() {
        assert_eq!(JavaExtractor::new().languages(), &["java"]);
    }

    #[test]
    fn static_final_uppercase_field_emits_constant_under_class() {
        let src = "class C { public static final int MAX = 10; }";
        let syms = extract(src);
        let cls = syms.iter().find(|s| s.kind == "class").expect("class");
        let c = syms
            .iter()
            .find(|s| s.kind == "constant" && s.name == "MAX")
            .expect("constant");
        assert_eq!(c.qualified_name, "C.MAX");
        assert_eq!(c.parent_symbol_id.as_deref(), Some(cls.symbol_id.as_str()));
    }

    #[test]
    fn non_final_field_is_not_a_constant() {
        let src = "class C { public static int mutable = 0; }";
        let syms = extract(src);
        assert!(syms.iter().all(|s| s.kind != "constant"));
    }

    #[test]
    fn plain_import_splits_package_and_trailing_name() {
        let imps = imports("import java.util.List;\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "java.util");
        assert_eq!(imps[0].names, vec!["List"]);
    }

    #[test]
    fn wildcard_import_records_star_as_name() {
        let imps = imports("import java.util.*;\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "java.util");
        assert_eq!(imps[0].names, vec!["*"]);
    }

    #[test]
    fn static_import_splits_class_and_member() {
        let imps = imports("import static java.lang.Math.PI;\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "java.lang.Math");
        assert_eq!(imps[0].names, vec!["PI"]);
    }

    #[test]
    fn static_wildcard_import_records_star() {
        let imps = imports("import static java.lang.Math.*;\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "java.lang.Math");
        assert_eq!(imps[0].names, vec!["*"]);
    }

    fn candidates(specifier: &str, source: &str) -> Vec<String> {
        let ctx = ResolverContext::default();
        JavaExtractor::new().generate_candidates(specifier, source, &ctx)
    }

    #[test]
    fn dotted_package_expands_to_java_layout_variants() {
        let c = candidates("com.example.util.Helper", "Mod.java");
        assert_eq!(
            c,
            vec![
                "com/example/util/Helper.java",
                "src/main/java/com/example/util/Helper.java",
                "src/main/kotlin/com/example/util/Helper.java",
                "src/com/example/util/Helper.java",
            ]
        );
    }

    #[test]
    fn kotlin_source_file_selects_kt_extension() {
        let c = candidates("com.example.Util", "App.kt");
        assert_eq!(
            c,
            vec![
                "com/example/Util.kt",
                "src/main/java/com/example/Util.kt",
                "src/main/kotlin/com/example/Util.kt",
                "src/com/example/Util.kt",
            ]
        );
    }

    #[test]
    fn kts_source_file_selects_kt_extension() {
        let c = candidates("pkg.X", "build.gradle.kts");
        assert!(c.iter().all(|p| p.ends_with(".kt")));
    }

    #[test]
    fn single_segment_specifier_still_emits_candidates() {
        let c = candidates("Foo", "Mod.java");
        assert!(c.contains(&"Foo.java".to_string()));
        assert!(c.contains(&"src/main/java/Foo.java".to_string()));
    }

    #[test]
    fn multiple_imports_produce_multiple_records() {
        let src = "import java.util.List;\nimport java.io.File;\n";
        let imps = imports(src);
        assert_eq!(imps.len(), 2);
        assert_eq!(imps[0].specifier, "java.util");
        assert_eq!(imps[0].names, vec!["List"]);
        assert_eq!(imps[1].specifier, "java.io");
        assert_eq!(imps[1].names, vec!["File"]);
    }
}
