//! Core types for extracted code symbols.
//!
//! Mirrors `sylvan.database.validation.Symbol` from the Python side
//! field-for-field so PyO3 conversions stay mechanical and Python
//! callers see unchanged shapes.

/// Recognised symbol kinds.
///
/// String values match the legacy Python `SymbolKind` enum; persisted
/// rows and cross-language comparisons depend on the exact spellings.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum SymbolKind {
    /// Free function.
    Function,
    /// Class declaration.
    Class,
    /// Class method.
    Method,
    /// Module-level or class-level constant.
    Constant,
    /// Type alias or user-defined type.
    Type,
    /// Template / generic type declaration.
    Template,
    /// Imported symbol surfacing in the current module.
    Import,
}

impl SymbolKind {
    /// Canonical lowercase string, matching the Python enum values.
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Function => "function",
            Self::Class => "class",
            Self::Method => "method",
            Self::Constant => "constant",
            Self::Type => "type",
            Self::Template => "template",
            Self::Import => "import",
        }
    }

    /// Parse from the canonical lowercase string. Returns `None` for
    /// unrecognised values; the extraction pipeline is expected to use
    /// only the enum variants directly, but persisted rows read from
    /// SQLite may need this path.
    pub fn from_str(s: &str) -> Option<Self> {
        match s {
            "function" => Some(Self::Function),
            "class" => Some(Self::Class),
            "method" => Some(Self::Method),
            "constant" => Some(Self::Constant),
            "type" => Some(Self::Type),
            "template" => Some(Self::Template),
            "import" => Some(Self::Import),
            _ => None,
        }
    }
}

/// A single extracted symbol.
///
/// Field names and types match the Python `Symbol` dataclass. Defaults
/// mirror the dataclass too, so building a partially-populated Symbol
/// from Rust produces the same serialised shape Python callers expect.
#[derive(Debug, Clone, PartialEq)]
pub struct Symbol {
    /// Stable unique identifier: `"{path}::{qualified_name}[#{kind}]"`.
    pub symbol_id: String,
    /// Short symbol name (leaf component of `qualified_name`).
    pub name: String,
    /// Fully qualified name including parent classes / modules.
    pub qualified_name: String,
    /// Symbol kind as its canonical string (matches [`SymbolKind::as_str`]).
    pub kind: String,
    /// Programming language of the source file.
    pub language: String,
    /// Function / method signature, or `None` for non-callables.
    pub signature: Option<String>,
    /// Extracted docstring text, or `None` when absent.
    pub docstring: Option<String>,
    /// AI-generated or heuristic summary, or `None` when not computed.
    pub summary: Option<String>,
    /// Decorator / annotation names applied to this symbol.
    pub decorators: Vec<String>,
    /// Keywords extracted for search boosting.
    pub keywords: Vec<String>,
    /// Parent symbol id for nested symbols, or `None` at module scope.
    pub parent_symbol_id: Option<String>,
    /// Starting line number (1-based), or `None` if unknown.
    pub line_start: Option<u32>,
    /// Ending line number (1-based), or `None` if unknown.
    pub line_end: Option<u32>,
    /// Byte offset of the symbol body into the file's content blob.
    pub byte_offset: u32,
    /// Byte length of the symbol body.
    pub byte_length: u32,
    /// SHA-256 of the symbol body, or `None` if not hashed.
    pub content_hash: Option<String>,
    /// Cyclomatic complexity score.
    pub cyclomatic: u32,
    /// Maximum nesting depth observed in the body.
    pub max_nesting: u32,
    /// Declared parameter count (after receiver stripping).
    pub param_count: u32,
}

impl Default for Symbol {
    fn default() -> Self {
        Self {
            symbol_id: String::new(),
            name: String::new(),
            qualified_name: String::new(),
            kind: String::new(),
            language: String::new(),
            signature: None,
            docstring: None,
            summary: None,
            decorators: Vec::new(),
            keywords: Vec::new(),
            parent_symbol_id: None,
            line_start: None,
            line_end: None,
            byte_offset: 0,
            byte_length: 0,
            content_hash: None,
            cyclomatic: 0,
            max_nesting: 0,
            param_count: 0,
        }
    }
}

/// Build the canonical symbol id: `"{file_path}::{qualified_name}#{kind}"`.
///
/// When `kind` is an empty string the `#` suffix is omitted, matching
/// the Python `make_symbol_id` helper.
pub fn make_symbol_id(file_path: &str, qualified_name: &str, kind: &str) -> String {
    if kind.is_empty() {
        format!("{file_path}::{qualified_name}")
    } else {
        format!("{file_path}::{qualified_name}#{kind}")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn symbol_kind_round_trips_through_string() {
        for kind in [
            SymbolKind::Function,
            SymbolKind::Class,
            SymbolKind::Method,
            SymbolKind::Constant,
            SymbolKind::Type,
            SymbolKind::Template,
            SymbolKind::Import,
        ] {
            assert_eq!(SymbolKind::from_str(kind.as_str()), Some(kind));
        }
    }

    #[test]
    fn symbol_kind_rejects_unknown_strings() {
        assert_eq!(SymbolKind::from_str("nope"), None);
        assert_eq!(SymbolKind::from_str(""), None);
    }

    #[test]
    fn symbol_id_includes_kind_suffix() {
        assert_eq!(
            make_symbol_id("src/main.py", "Foo.bar", "method"),
            "src/main.py::Foo.bar#method"
        );
    }

    #[test]
    fn symbol_id_without_kind_omits_suffix() {
        assert_eq!(
            make_symbol_id("src/main.py", "Foo.bar", ""),
            "src/main.py::Foo.bar"
        );
    }

    #[test]
    fn default_symbol_matches_python_dataclass_defaults() {
        let s = Symbol::default();
        assert_eq!(s.symbol_id, "");
        assert!(s.decorators.is_empty());
        assert!(s.keywords.is_empty());
        assert_eq!(s.byte_offset, 0);
        assert_eq!(s.cyclomatic, 0);
        assert!(s.signature.is_none());
        assert!(s.line_start.is_none());
    }
}
