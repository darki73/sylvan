//! File discovery, parsing, extraction, and the indexing pipeline.

#![forbid(unsafe_code)]
#![deny(missing_docs)]

pub mod discovery;

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
