//! GraphQL extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the GraphQL grammar. The
//! grammar nests real type-carrying nodes (`object_type_definition`,
//! `interface_type_definition`, `enum_type_definition`,
//! `union_type_definition`, `scalar_type_definition`,
//! `input_object_type_definition`) under generic
//! `type_definition` / `type_system_definition` wrappers, so the spec
//! targets the inner nodes directly. Each exposes its name as an
//! unlabeled direct child of kind `name`.

use std::sync::OnceLock;

use sylvan_core::{ExtractionContext, ExtractionError, LanguageExtractor, Symbol};

use crate::extraction::spec::{
    ConstantStrategy, DecoratorStrategy, DocstringStrategy, LanguageSpec, NameResolution,
    SpecExtractor,
};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[
        ("object_type_definition", "type"),
        ("interface_type_definition", "type"),
        ("enum_type_definition", "type"),
        ("union_type_definition", "type"),
        ("scalar_type_definition", "type"),
        ("input_object_type_definition", "type"),
        ("field_definition", "function"),
        ("operation_definition", "function"),
    ],
    name_fields: &[],
    name_resolutions: &[
        ("object_type_definition", NameResolution::ChildKind("name")),
        ("interface_type_definition", NameResolution::ChildKind("name")),
        ("enum_type_definition", NameResolution::ChildKind("name")),
        ("union_type_definition", NameResolution::ChildKind("name")),
        ("scalar_type_definition", NameResolution::ChildKind("name")),
        (
            "input_object_type_definition",
            NameResolution::ChildKind("name"),
        ),
        ("field_definition", NameResolution::ChildKind("name")),
        ("operation_definition", NameResolution::ChildKind("name")),
    ],
    param_fields: &[],
    return_type_fields: &[],
    container_node_types: &[],
    docstring_strategy: DocstringStrategy::PrecedingComment,
    decorator_strategy: DecoratorStrategy::None,
    constant_strategy: ConstantStrategy::None,
    parameter_kinds: &[],
    method_promotion: &[],
};

/// Built-in GraphQL extractor.
pub struct GraphQLExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl GraphQLExtractor {
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
                &["graphql"],
                crate::grammars::get_language("graphql").expect("graphql grammar"),
                &SPEC,
            )
        })
    }
}

impl Default for GraphQLExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for GraphQLExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["graphql"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        self.delegate().extract(ctx)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        GraphQLExtractor::new()
            .extract(&ExtractionContext::new(source, "schema.graphql", "graphql"))
            .expect("graphql extraction")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_object_type() {
        let syms = extract("type User {\n  id: ID!\n  name: String\n}\n");
        assert!(syms.iter().any(|s| s.name == "User" && s.kind == "type"));
    }

    #[test]
    fn extracts_interface_type() {
        let syms = extract("interface Node { id: ID! }\n");
        assert!(syms.iter().any(|s| s.name == "Node" && s.kind == "type"));
    }

    #[test]
    fn extracts_enum_type() {
        let syms = extract("enum Role { ADMIN USER }\n");
        assert!(syms.iter().any(|s| s.name == "Role" && s.kind == "type"));
    }

    #[test]
    fn extracts_operation() {
        let syms = extract("query GetUser { user { id } }\n");
        assert!(syms
            .iter()
            .any(|s| s.name == "GetUser" && s.kind == "function"));
    }

    #[test]
    fn advertises_graphql_language() {
        let ex = GraphQLExtractor::new();
        assert_eq!(ex.languages(), &["graphql"]);
    }
}
