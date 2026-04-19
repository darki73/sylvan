//! PyO3 bridge for per-symbol complexity metrics.
//!
//! Exposes `sylvan._rust.compute_complexity(source, language)` returning
//! a dict `{"cyclomatic": int, "max_nesting": int, "param_count": int}`
//! matching the legacy Python contract byte-for-byte.

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyModule};

use sylvan_indexing::complexity::compute_complexity as rust_compute_complexity;

/// Compute cyclomatic complexity, max nesting, and parameter count for
/// a symbol's source body.
#[pyfunction]
#[pyo3(signature = (source, language))]
fn compute_complexity<'py>(
    py: Python<'py>,
    source: &str,
    language: &str,
) -> PyResult<Bound<'py, PyDict>> {
    let metrics = rust_compute_complexity(source, language);
    let dict = PyDict::new(py);
    dict.set_item("cyclomatic", metrics.cyclomatic)?;
    dict.set_item("max_nesting", metrics.max_nesting)?;
    dict.set_item("param_count", metrics.param_count)?;
    Ok(dict)
}

/// Register the complexity function on the parent module.
pub fn register(parent: &Bound<'_, PyModule>) -> PyResult<()> {
    parent.add_function(wrap_pyfunction!(compute_complexity, parent)?)?;
    Ok(())
}
