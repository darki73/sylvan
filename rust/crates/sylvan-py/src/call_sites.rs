//! PyO3 bridge for call-site extraction.
//!
//! Exposes `sylvan._rust.extract_call_sites(symbols, content, language)`
//! returning a list of `(caller_symbol_id, callee_name, line)` tuples.
//! The Python proxy filters symbols to `function`/`method` kinds before
//! invoking this binding, matching the original Python implementation.

use pyo3::IntoPyObjectExt;
use pyo3::prelude::*;
use pyo3::types::{PyList, PyModule, PyTuple};

use sylvan_indexing::call_sites::{SymbolRange, extract_call_sites as rust_extract_call_sites};

/// Walk `content` and return every call site.
///
/// `symbols` is a list of `(symbol_id, byte_offset, byte_length)`
/// tuples describing each function/method's span in the source.
#[pyfunction]
#[pyo3(signature = (symbols, content, language))]
fn extract_call_sites<'py>(
    py: Python<'py>,
    symbols: Vec<(String, u32, u32)>,
    content: &str,
    language: &str,
) -> PyResult<Bound<'py, PyList>> {
    let ranges: Vec<SymbolRange> = symbols
        .into_iter()
        .map(|(symbol_id, byte_offset, byte_length)| SymbolRange {
            symbol_id,
            byte_offset,
            byte_length,
        })
        .collect();

    let calls = rust_extract_call_sites(&ranges, content, language);

    let list = PyList::empty(py);
    for call in calls {
        let tuple = PyTuple::new(
            py,
            [
                call.caller_symbol_id.into_py_any(py)?,
                call.callee_name.into_py_any(py)?,
                call.line.into_py_any(py)?,
            ],
        )?;
        list.append(tuple)?;
    }
    Ok(list)
}

/// Register the call-site function on the parent module.
pub fn register(parent: &Bound<'_, PyModule>) -> PyResult<()> {
    parent.add_function(wrap_pyfunction!(extract_call_sites, parent)?)?;
    Ok(())
}
