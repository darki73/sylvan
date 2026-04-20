//! PyO3 bindings exposed to Python as `sylvan._rust`.
//!
//! `cargo test -p sylvan-py` does not work: the `extension-module` PyO3
//! feature leaves libpython unresolved at link time. Exercise the binding
//! layer through Python integration tests.

#![deny(missing_docs)]

mod call_sites;
mod complexity;
mod discovery;
mod docs;
mod embedding;
mod extraction;
mod logging;
mod watch;

use pyo3::prelude::*;

/// Loaded extension's version.
#[pyfunction]
fn version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

/// The `sylvan._rust` Python module.
#[pymodule]
fn _rust(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(version, m)?)?;
    call_sites::register(m)?;
    complexity::register(m)?;
    discovery::register(m)?;
    docs::register(m)?;
    embedding::register(m)?;
    extraction::register(m)?;
    logging::register(m)?;
    watch::register(m)?;
    Ok(())
}
