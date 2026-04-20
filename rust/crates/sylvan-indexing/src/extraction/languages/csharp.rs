//! C# extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the C# grammar. Mirrors the
//! Python plugin in `sylvan.indexing.languages.csharp`: class, interface,
//! struct, enum, and method declarations, signature stitching, preceding
//! `///` / `//` / `/* */` docstrings, `[Attribute]` byte-range expansion,
//! and `field_declaration` / `property_declaration` treated as
//! constant-like top-level patterns.
//!
//! Import extraction walks the parsed tree for `using_directive` nodes.
//! The dotted namespace lives in a `qualified_name` or `identifier`
//! child. Matching the legacy Python regex, the full dotted path becomes
//! the specifier and `names` is always empty, covering plain
//! `using System;`, dotted `using System.Collections.Generic;`, and
//! `using static System.Math;`. Aliased directives
//! (`using X = System.Collections.Generic.List;`) record the right-hand
//! namespace as the specifier, which the legacy regex misses.
//!
//! Import resolution converts the dotted namespace into a path and
//! emits two candidates: one against the repo root and one against
//! `src/`, both with a `.cs` extension, matching the legacy plugin's
//! naive namespace-to-file mapping.
//!
//! Features left for later migration stages: complexity scoring.

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
        ("struct_declaration", "class"),
        ("enum_declaration", "type"),
    ],
    name_fields: &[
        ("method_declaration", "name"),
        ("class_declaration", "name"),
        ("interface_declaration", "name"),
        ("struct_declaration", "name"),
        ("enum_declaration", "name"),
    ],
    name_resolutions: &[],
    param_fields: &[("method_declaration", "parameters")],
    return_type_fields: &[("method_declaration", "type")],
    container_node_types: &[
        "class_declaration",
        "interface_declaration",
        "struct_declaration",
        "enum_declaration",
    ],
    docstring_strategy: DocstringStrategy::PrecedingComment,
    decorator_strategy: DecoratorStrategy::PrecedingSiblings {
        kinds: &["attribute_list"],
    },
    constant_strategy: ConstantStrategy::ModifiedField {
        field_kinds: &["field_declaration"],
        modifiers: ModifierLocation::DirectByText { kind: "modifier" },
        required_modifiers: &["const"],
        declarator_kind: "variable_declarator",
        name_field: "name",
        uppercase_only: false,
    },
    parameter_kinds: &["parameter"],
    method_promotion: &[],
};

/// Built-in C# extractor.
pub struct CSharpExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl CSharpExtractor {
    /// Construct a fresh instance.
    pub fn new() -> Self {
        Self {
            inner: OnceLock::new(),
        }
    }

    fn delegate(&self) -> &SpecExtractor {
        self.inner.get_or_init(|| {
            SpecExtractor::new(&["csharp"], crate::grammars::get_language("csharp").expect("csharp grammar"), &SPEC)
        })
    }
}

impl Default for CSharpExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for CSharpExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["csharp", "c_sharp"]
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
        let path_base = specifier.replace('.', "/");
        vec![format!("{path_base}.cs"), format!("src/{path_base}.cs")]
    }
}

fn walk_imports(node: Node<'_>, source: &[u8], out: &mut Vec<Import>) {
    if node.kind() == "using_directive" {
        if let Some(imp) = collect_using(node, source) {
            out.push(imp);
        }
        return;
    }
    let mut cursor = node.walk();
    for child in node.children(&mut cursor) {
        walk_imports(child, source, out);
    }
}

fn collect_using(node: Node<'_>, source: &[u8]) -> Option<Import> {
    let mut cursor = node.walk();
    let mut best: Option<String> = None;
    for child in node.children(&mut cursor) {
        match child.kind() {
            "qualified_name" | "identifier" => {
                if let Some(text) = node_text(child, source) {
                    best = Some(text);
                }
            }
            "name_equals" => {
                // Skip the alias left-hand side; keep scanning for the
                // right-hand namespace node that follows it.
            }
            _ => {}
        }
    }
    let specifier = best?;
    if specifier.is_empty() {
        return None;
    }
    Some(Import {
        specifier,
        names: Vec::new(),
    })
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
        CSharpExtractor::new()
            .extract(&ExtractionContext::new(source, "mod.cs", "csharp"))
            .expect("csharp extraction")
    }

    fn imports(src: &str) -> Vec<Import> {
        CSharpExtractor::new()
            .extract_imports(&ExtractionContext::new(src, "mod.cs", "csharp"))
            .expect("csharp imports")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_class_with_method() {
        let syms = extract("class Dog { public void Bark() {} }");
        let cls = syms.iter().find(|s| s.kind == "class").expect("class");
        let method = syms.iter().find(|s| s.kind == "method").expect("method");
        assert_eq!(cls.name, "Dog");
        assert_eq!(method.name, "Bark");
        assert_eq!(method.qualified_name, "Dog.Bark");
        assert_eq!(method.parent_symbol_id.as_deref(), Some(cls.symbol_id.as_str()));
    }

    #[test]
    fn extracts_interface() {
        let syms = extract("interface IFoo { void Do(); }");
        let iface = syms.iter().find(|s| s.kind == "type").expect("interface");
        assert_eq!(iface.name, "IFoo");
    }

    #[test]
    fn preceding_doc_comment_becomes_docstring() {
        let src = "/// doc\nclass X {}\n";
        let syms = extract(src);
        let cls = syms.iter().find(|s| s.kind == "class").expect("class");
        assert!(
            cls.docstring.as_deref().unwrap_or("").contains("doc"),
            "expected docstring to contain 'doc', got {:?}",
            cls.docstring
        );
    }

    #[test]
    fn advertises_csharp_language() {
        assert_eq!(CSharpExtractor::new().languages(), &["csharp"]);
    }

    #[test]
    fn const_field_emits_constant_under_class() {
        let src = "class C { public const int Max = 10; }";
        let syms = extract(src);
        let cls = syms.iter().find(|s| s.kind == "class").expect("class");
        let c = syms
            .iter()
            .find(|s| s.kind == "constant" && s.name == "Max")
            .expect("constant");
        assert_eq!(c.qualified_name, "C.Max");
        assert_eq!(c.parent_symbol_id.as_deref(), Some(cls.symbol_id.as_str()));
    }

    #[test]
    fn non_const_field_is_not_a_constant() {
        let src = "class C { public int Mutable = 0; }";
        let syms = extract(src);
        assert!(syms.iter().all(|s| s.kind != "constant"));
    }

    #[test]
    fn plain_using_records_single_identifier() {
        let imps = imports("using System;\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "System");
        assert!(imps[0].names.is_empty());
    }

    #[test]
    fn dotted_using_keeps_full_namespace() {
        let imps = imports("using System.Collections.Generic;\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "System.Collections.Generic");
        assert!(imps[0].names.is_empty());
    }

    #[test]
    fn static_using_keeps_full_namespace() {
        let imps = imports("using static System.Math;\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "System.Math");
        assert!(imps[0].names.is_empty());
    }

    #[test]
    fn aliased_using_records_right_hand_namespace() {
        let imps = imports("using Foo = System.Collections.Generic.List;\n");
        assert_eq!(imps.len(), 1);
        assert_eq!(imps[0].specifier, "System.Collections.Generic.List");
        assert!(imps[0].names.is_empty());
    }

    fn candidates(specifier: &str) -> Vec<String> {
        let ctx = ResolverContext::default();
        CSharpExtractor::new().generate_candidates(specifier, "mod.cs", &ctx)
    }

    #[test]
    fn dotted_namespace_expands_to_root_and_src_variants() {
        let c = candidates("MyApp.Models.User");
        assert_eq!(
            c,
            vec!["MyApp/Models/User.cs", "src/MyApp/Models/User.cs",]
        );
    }

    #[test]
    fn single_segment_specifier_emits_bare_cs_file() {
        let c = candidates("System");
        assert_eq!(c, vec!["System.cs", "src/System.cs"]);
    }

    #[test]
    fn multiple_usings_produce_multiple_records() {
        let src = "using System;\nusing System.IO;\n";
        let imps = imports(src);
        assert_eq!(imps.len(), 2);
        assert_eq!(imps[0].specifier, "System");
        assert_eq!(imps[1].specifier, "System.IO");
    }
}
