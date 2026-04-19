//! Shared types, port traits, and errors. Depended on by every other sylvan crate.

#![forbid(unsafe_code)]
#![deny(missing_docs)]

pub mod discovery;
pub mod extraction;
pub mod symbol;

pub use extraction::{ExtractionContext, ExtractionError, LanguageExtractor};
pub use symbol::{Symbol, SymbolKind, UnknownSymbolKind, make_symbol_id};

/// Crate version, baked in at compile time.
pub fn version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

#[cfg(test)]
mod tests {
    #[test]
    fn version_matches_cargo_pkg_version() {
        assert_eq!(super::version(), env!("CARGO_PKG_VERSION"));
    }
}
