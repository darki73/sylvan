//! Protobuf extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the Protobuf grammar. Symbols
//! come from `message`, `enum`, `service`, and `rpc` nodes. Each has an
//! unlabeled child whose kind encodes the name (`message_name`,
//! `enum_name`, `service_name`, `rpc_name`). Preceding `// ...` comments
//! become the docstring.

use std::sync::OnceLock;

use sylvan_core::{ExtractionContext, ExtractionError, LanguageExtractor, Symbol};

use crate::extraction::spec::{
    ConstantStrategy, DecoratorStrategy, DocstringStrategy, LanguageSpec, NameResolution,
    SpecExtractor,
};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[
        ("message", "type"),
        ("enum", "type"),
        ("service", "type"),
        ("rpc", "function"),
    ],
    name_fields: &[],
    name_resolutions: &[
        ("message", NameResolution::ChildKind("message_name")),
        ("enum", NameResolution::ChildKind("enum_name")),
        ("service", NameResolution::ChildKind("service_name")),
        ("rpc", NameResolution::ChildKind("rpc_name")),
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

/// Built-in Protobuf extractor.
pub struct ProtoExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl ProtoExtractor {
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
                &["proto"],
                crate::grammars::get_language("proto").expect("proto grammar"),
                &SPEC,
            )
        })
    }
}

impl Default for ProtoExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for ProtoExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["proto"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        self.delegate().extract(ctx)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        ProtoExtractor::new()
            .extract(&ExtractionContext::new(source, "api.proto", "proto"))
            .expect("proto extraction")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_message_definition() {
        let syms =
            extract("syntax = \"proto3\";\nmessage User { string name = 1; }\n");
        assert!(syms.iter().any(|s| s.name == "User" && s.kind == "type"));
    }

    #[test]
    fn extracts_enum_definition() {
        let syms = extract("enum Kind { A = 0; B = 1; }\n");
        assert!(syms.iter().any(|s| s.name == "Kind" && s.kind == "type"));
    }

    #[test]
    fn extracts_service_and_rpc() {
        let syms = extract("service Api { rpc Get(Req) returns (Resp); }\n");
        assert!(syms.iter().any(|s| s.name == "Api" && s.kind == "type"));
        assert!(syms
            .iter()
            .any(|s| s.name == "Get" && s.kind == "function"));
    }

    #[test]
    fn advertises_proto_language() {
        let ex = ProtoExtractor::new();
        assert_eq!(ex.languages(), &["proto"]);
    }
}
