//! Core types for extracted code symbols.
//!
//! Mirrors `sylvan.database.validation.Symbol` from the Python side
//! field-for-field so PyO3 conversions stay mechanical and Python
//! callers see unchanged shapes.

use std::fmt;
use std::str::FromStr;

/// Error returned when parsing an unknown [`SymbolKind`] string.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UnknownSymbolKind(pub String);

impl fmt::Display for UnknownSymbolKind {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "unknown symbol kind: {}", self.0)
    }
}

impl std::error::Error for UnknownSymbolKind {}

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

}

impl FromStr for SymbolKind {
    type Err = UnknownSymbolKind;

    /// Parse from the canonical lowercase string. The extraction
    /// pipeline uses enum variants directly; persisted rows read from
    /// SQLite take this path.
    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "function" => Ok(Self::Function),
            "class" => Ok(Self::Class),
            "method" => Ok(Self::Method),
            "constant" => Ok(Self::Constant),
            "type" => Ok(Self::Type),
            "template" => Ok(Self::Template),
            "import" => Ok(Self::Import),
            other => Err(UnknownSymbolKind(other.to_string())),
        }
    }
}

/// A single extracted symbol.
///
/// Field names and types match the Python `Symbol` dataclass. Defaults
/// mirror the dataclass too, so building a partially-populated Symbol
/// from Rust produces the same serialised shape Python callers expect.
#[derive(Debug, Clone, Default, PartialEq)]
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
            assert_eq!(kind.as_str().parse::<SymbolKind>().unwrap(), kind);
        }
    }

    #[test]
    fn symbol_kind_rejects_unknown_strings() {
        assert!("nope".parse::<SymbolKind>().is_err());
        assert!("".parse::<SymbolKind>().is_err());
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
