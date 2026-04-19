//! Embedding and summarization providers. CPU-only.
//!
//! The embedding subsystem wraps raw `ort-sys` FFI with RAII-safe
//! abstractions; bench numbers across the PoC runs showed this beats
//! the `ort` 2.0 high-level wrapper by ~30% while still matching
//! Python fastembed's output bit-for-bit.

#![forbid(unsafe_op_in_unsafe_fn)]
#![deny(missing_docs)]

pub mod embedding;

pub use embedding::{EmbeddingModel, EmbeddingModelConfig, ModelKind, ProviderError};

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
