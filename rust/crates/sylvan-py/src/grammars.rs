//! PyO3 bridge for configuring the tree-sitter grammar cache.
//!
//! Sylvan stores downloaded grammars under `<sylvan_home>/tree-sitter-grammars/`
//! so they survive a wipe of the user's `~/.cache` and stay colocated
//! with the rest of sylvan's state. The Python layer owns resolution of
//! `sylvan_home` and calls `configure_grammar_cache` early during
//! bootstrap, before any extractor touches `crate::grammars::get_language`.

use std::path::PathBuf;

use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use pyo3::types::PyModule;

use tree_sitter_language_pack::{PackConfig, configure};

/// Register the Rust-side pack with a custom cache directory.
///
/// Idempotent: calling this multiple times with the same path is a no-op
/// on the second call.
#[pyfunction]
fn configure_grammar_cache(cache_dir: &str) -> PyResult<()> {
    configure(&PackConfig {
        cache_dir: Some(PathBuf::from(cache_dir)),
        languages: None,
        groups: None,
    })
    .map_err(|e| PyRuntimeError::new_err(format!("configure grammar cache: {e}")))
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(configure_grammar_cache, m)?)?;
    Ok(())
}
