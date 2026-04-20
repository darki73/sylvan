//! SQL extractor.
//!
//! Wraps the shared [`SpecExtractor`] with the SQL grammar. Symbols come
//! from `create_function`, `create_table`, `create_view`, and
//! `create_index` nodes; the identifier lives on an inner
//! `object_reference` node via its `name` field. Preceding `-- ...`
//! comments become the docstring.

use std::sync::OnceLock;

use sylvan_core::{ExtractionContext, ExtractionError, LanguageExtractor, Symbol};

use crate::extraction::spec::{
    ConstantStrategy, DecoratorStrategy, DocstringStrategy, LanguageSpec, NameLeaf,
    NameResolution, SpecExtractor,
};

static SPEC: LanguageSpec = LanguageSpec {
    symbol_node_types: &[
        ("create_function", "function"),
        ("create_table", "type"),
        ("create_view", "type"),
        ("create_index", "type"),
    ],
    name_fields: &[],
    name_resolutions: &[
        (
            "create_function",
            NameResolution::Descend {
                path: &["object_reference"],
                leaf: NameLeaf::Field("name"),
            },
        ),
        (
            "create_table",
            NameResolution::Descend {
                path: &["object_reference"],
                leaf: NameLeaf::Field("name"),
            },
        ),
        (
            "create_view",
            NameResolution::Descend {
                path: &["object_reference"],
                leaf: NameLeaf::Field("name"),
            },
        ),
        (
            "create_index",
            NameResolution::Descend {
                path: &["object_reference"],
                leaf: NameLeaf::Field("name"),
            },
        ),
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

/// Built-in SQL extractor.
pub struct SqlExtractor {
    inner: OnceLock<SpecExtractor>,
}

impl SqlExtractor {
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
                &["sql"],
                crate::grammars::get_language("sql").expect("sql grammar"),
                &SPEC,
            )
        })
    }
}

impl Default for SqlExtractor {
    fn default() -> Self {
        Self::new()
    }
}

impl LanguageExtractor for SqlExtractor {
    fn languages(&self) -> &'static [&'static str] {
        &["sql"]
    }

    fn extract(&self, ctx: &ExtractionContext<'_>) -> Result<Vec<Symbol>, ExtractionError> {
        self.delegate().extract(ctx)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn extract(source: &str) -> Vec<Symbol> {
        SqlExtractor::new()
            .extract(&ExtractionContext::new(source, "schema.sql", "sql"))
            .expect("sql extraction")
    }

    #[test]
    fn empty_file_yields_no_symbols() {
        assert!(extract("").is_empty());
    }

    #[test]
    fn extracts_create_table() {
        let syms = extract("CREATE TABLE users (id INT PRIMARY KEY);\n");
        assert_eq!(syms.len(), 1);
        assert_eq!(syms[0].name, "users");
        assert_eq!(syms[0].kind, "type");
    }

    #[test]
    fn extracts_create_function() {
        let syms = extract(
            "CREATE FUNCTION f() RETURNS INT AS $$ SELECT 1 $$ LANGUAGE sql;\n",
        );
        assert!(syms.iter().any(|s| s.name == "f" && s.kind == "function"));
    }

    #[test]
    fn extracts_create_view() {
        let syms = extract("CREATE VIEW v AS SELECT 1;\n");
        assert!(syms.iter().any(|s| s.name == "v" && s.kind == "type"));
    }

    #[test]
    fn advertises_sql_language() {
        let ex = SqlExtractor::new();
        assert_eq!(ex.languages(), &["sql"]);
    }
}
