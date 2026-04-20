//! PyO3 bridge for per-file symbol extraction.
//!
//! Exposes `sylvan._rust.extract_symbols(content, filename, language)`
//! returning a list of dicts matching the Python `Symbol` dataclass
//! field-for-field. The Python proxy constructs `Symbol` objects from
//! these dicts so the rest of the indexing pipeline never sees the
//! wire format.
//!
//! A separate `supported_languages()` helper lets the Python caller
//! decide at runtime whether to delegate, without having to mirror the
//! Rust registry table in two places.

use std::sync::OnceLock;

use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyModule};

use sylvan_core::{ExtractionContext, Symbol};
use sylvan_indexing::extraction::Registry;

fn registry() -> &'static Registry {
    static R: OnceLock<Registry> = OnceLock::new();
    R.get_or_init(Registry::with_builtins)
}

fn symbol_to_dict<'py>(py: Python<'py>, sym: &Symbol) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("symbol_id", &sym.symbol_id)?;
    d.set_item("name", &sym.name)?;
    d.set_item("qualified_name", &sym.qualified_name)?;
    d.set_item("kind", &sym.kind)?;
    d.set_item("language", &sym.language)?;
    d.set_item("signature", sym.signature.clone())?;
    d.set_item("docstring", sym.docstring.clone())?;
    d.set_item("summary", sym.summary.clone())?;
    d.set_item("decorators", sym.decorators.clone())?;
    d.set_item("keywords", sym.keywords.clone())?;
    d.set_item("parent_symbol_id", sym.parent_symbol_id.clone())?;
    d.set_item("line_start", sym.line_start)?;
    d.set_item("line_end", sym.line_end)?;
    d.set_item("byte_offset", sym.byte_offset)?;
    d.set_item("byte_length", sym.byte_length)?;
    d.set_item("content_hash", sym.content_hash.clone())?;
    d.set_item("cyclomatic", sym.cyclomatic)?;
    d.set_item("max_nesting", sym.max_nesting)?;
    d.set_item("param_count", sym.param_count)?;
    Ok(d)
}

/// Extract fully-enriched symbols for `content`. Returns an empty list
/// when `language` has no registered Rust extractor, letting the Python
/// caller transparently fall back to the legacy implementation.
#[pyfunction]
#[pyo3(signature = (content, filename, language))]
fn extract_symbols<'py>(
    py: Python<'py>,
    content: &str,
    filename: &str,
    language: &str,
) -> PyResult<Bound<'py, PyList>> {
    let reg = registry();
    let ctx = ExtractionContext::new(content, filename, language);
    let symbols = reg
        .extract(&ctx)
        .map_err(|e| PyRuntimeError::new_err(format!("{e}")))?;

    let list = PyList::empty(py);
    for sym in &symbols {
        list.append(symbol_to_dict(py, sym)?)?;
    }
    Ok(list)
}

/// Sorted list of language identifiers backed by a Rust extractor.
#[pyfunction]
fn supported_languages<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
    let reg = registry();
    let list = PyList::empty(py);
    for lang in reg.languages() {
        list.append(lang)?;
    }
    Ok(list)
}

/// Register extraction functions on the parent module.
pub fn register(parent: &Bound<'_, PyModule>) -> PyResult<()> {
    parent.add_function(wrap_pyfunction!(extract_symbols, parent)?)?;
    parent.add_function(wrap_pyfunction!(supported_languages, parent)?)?;
    Ok(())
}
