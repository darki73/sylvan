//! Filter rules, secret detection, and path validation.

#![forbid(unsafe_code)]
#![deny(missing_docs)]

pub mod filters;

pub use filters::{
    BINARY_EXTENSIONS, DOC_EXTENSIONS, SECRET_PATTERNS, SKIP_DIRS, SKIP_FILE_PATTERNS,
    is_binary_content, is_binary_extension, is_secret_file, should_skip_dir, should_skip_file,
};

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
