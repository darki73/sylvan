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

use std::collections::BTreeMap;

use sylvan_core::{ExtractionContext, Import, ResolverContext, Symbol};
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

fn import_to_dict<'py>(py: Python<'py>, imp: &Import) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    d.set_item("specifier", &imp.specifier)?;
    d.set_item("names", imp.names.clone())?;
    Ok(d)
}

/// Extract raw import statements for `content`. Returns an empty list
/// when `language` has no Rust extractor or the extractor does not
/// speak imports.
#[pyfunction]
#[pyo3(signature = (content, filename, language))]
fn extract_imports<'py>(
    py: Python<'py>,
    content: &str,
    filename: &str,
    language: &str,
) -> PyResult<Bound<'py, PyList>> {
    let reg = registry();
    let ctx = ExtractionContext::new(content, filename, language);
    let imports = reg
        .extract_imports(&ctx)
        .map_err(|e| PyRuntimeError::new_err(format!("{e}")))?;

    let list = PyList::empty(py);
    for imp in &imports {
        list.append(import_to_dict(py, imp)?)?;
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

/// Subset of `supported_languages()` whose extractors also implement
/// import extraction. Lets the Python proxy delegate per-language
/// without masking the legacy extractor's output for languages that
/// haven't been ported yet.
#[pyfunction]
fn import_supported_languages<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
    let reg = registry();
    let list = PyList::empty(py);
    for lang in reg.import_languages() {
        list.append(lang)?;
    }
    Ok(list)
}

/// Subset of `supported_languages()` whose extractors implement
/// import-specifier resolution. Parallel to `import_supported_languages`.
#[pyfunction]
fn resolution_supported_languages<'py>(py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
    let reg = registry();
    let list = PyList::empty(py);
    for lang in reg.resolution_languages() {
        list.append(lang)?;
    }
    Ok(list)
}

fn context_from_dicts(
    psr4: Option<&Bound<'_, PyDict>>,
    tsconfig: Option<&Bound<'_, PyDict>>,
) -> PyResult<ResolverContext> {
    let mut out = ResolverContext::default();
    if let Some(d) = psr4 {
        out.psr4_mappings = dict_to_map(d)?;
    }
    if let Some(d) = tsconfig {
        out.tsconfig_aliases = dict_to_map(d)?;
    }
    Ok(out)
}

fn dict_to_map(d: &Bound<'_, PyDict>) -> PyResult<BTreeMap<String, Vec<String>>> {
    let mut out = BTreeMap::new();
    for (k, v) in d.iter() {
        let key: String = k.extract()?;
        let values: Vec<String> = v.extract()?;
        out.insert(key, values);
    }
    Ok(out)
}

/// Generate candidate file paths for an import specifier. Returns an
/// empty list when `language` has no Rust resolver registered.
#[pyfunction]
#[pyo3(signature = (specifier, source_path, language, psr4_mappings=None, tsconfig_aliases=None))]
fn generate_candidates<'py>(
    py: Python<'py>,
    specifier: &str,
    source_path: &str,
    language: &str,
    psr4_mappings: Option<&Bound<'_, PyDict>>,
    tsconfig_aliases: Option<&Bound<'_, PyDict>>,
) -> PyResult<Bound<'py, PyList>> {
    let reg = registry();
    let ctx = context_from_dicts(psr4_mappings, tsconfig_aliases)?;
    let candidates = reg.generate_candidates(language, specifier, source_path, &ctx);
    let list = PyList::empty(py);
    for c in candidates {
        list.append(c)?;
    }
    Ok(list)
}

/// Register extraction functions on the parent module.
pub fn register(parent: &Bound<'_, PyModule>) -> PyResult<()> {
    parent.add_function(wrap_pyfunction!(extract_symbols, parent)?)?;
    parent.add_function(wrap_pyfunction!(extract_imports, parent)?)?;
    parent.add_function(wrap_pyfunction!(supported_languages, parent)?)?;
    parent.add_function(wrap_pyfunction!(import_supported_languages, parent)?)?;
    parent.add_function(wrap_pyfunction!(generate_candidates, parent)?)?;
    parent.add_function(wrap_pyfunction!(resolution_supported_languages, parent)?)?;
    Ok(())
}
