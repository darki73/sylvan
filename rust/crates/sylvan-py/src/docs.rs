//! PyO3 bridge for markdown / MDX document parsing.
//!
//! Exposes `sylvan._rust.parse_markdown(content)` returning a list of
//! dicts `{"title", "level", "start_line", "end_line", "byte_start",
//! "byte_end", "body"}`. The Python proxy hydrates `Section` objects
//! via the existing `section_builder` helpers.

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyModule};

use sylvan_indexing::docs::parse_markdown as rust_parse_markdown;

/// Parse `content` (markdown or MDX) and return per-section metadata.
#[pyfunction]
#[pyo3(signature = (content))]
fn parse_markdown<'py>(py: Python<'py>, content: &str) -> PyResult<Bound<'py, PyList>> {
    let sections = rust_parse_markdown(content);
    let list = PyList::empty(py);
    for section in sections {
        let item = PyDict::new(py);
        item.set_item("title", &section.title)?;
        item.set_item("level", section.level)?;
        item.set_item("start_line", section.start_line)?;
        item.set_item("end_line", section.end_line)?;
        item.set_item("byte_start", section.byte_start)?;
        item.set_item("byte_end", section.byte_end)?;
        item.set_item("body", &section.body)?;
        list.append(item)?;
    }
    Ok(list)
}

/// Register the markdown parser on the parent module.
pub fn register(parent: &Bound<'_, PyModule>) -> PyResult<()> {
    parent.add_function(wrap_pyfunction!(parse_markdown, parent)?)?;
    Ok(())
}
