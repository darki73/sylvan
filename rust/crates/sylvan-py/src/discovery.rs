//! PyO3 bridge for the discovery pipeline.
//!
//! Exposes `sylvan._rust.discover_files(root, max_files, max_file_size,
//! use_git)`. Returns a plain Python dict with the same shape as
//! `sylvan.indexing.discovery.file_discovery.DiscoveryResult`; the
//! Python proxy layer (landing in a later stage) hydrates that dict back
//! into the dataclass so the public Python API stays unchanged.

use std::path::PathBuf;

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyModule};

use sylvan_core::discovery::DiscoveryResult;
use sylvan_indexing::discovery::{DiscoveryOptions, discover_files as rust_discover_files};

#[pyfunction]
#[pyo3(signature = (root, max_files = 5_000, max_file_size = 512_000, use_git = true))]
fn discover_files<'py>(
    py: Python<'py>,
    root: &str,
    max_files: usize,
    max_file_size: u64,
    use_git: bool,
) -> PyResult<Bound<'py, PyDict>> {
    let options = DiscoveryOptions {
        max_files,
        max_file_size,
        use_git,
    };
    let root_path = PathBuf::from(root);
    let result = py.detach(|| rust_discover_files(&root_path, &options));
    into_py_dict(py, &result)
}

fn into_py_dict<'py>(py: Python<'py>, result: &DiscoveryResult) -> PyResult<Bound<'py, PyDict>> {
    let dict = PyDict::new(py);

    let files = PyList::empty(py);
    for file in &result.files {
        let item = PyDict::new(py);
        item.set_item("path", file.path.to_string_lossy().as_ref())?;
        item.set_item("relative_path", &file.relative_path)?;
        item.set_item("size", file.size)?;
        item.set_item("mtime", file.mtime)?;
        files.append(item)?;
    }
    dict.set_item("files", files)?;

    let skipped = PyDict::new(py);
    for (reason, paths) in &result.skipped {
        let list = PyList::empty(py);
        for path in paths {
            list.append(path)?;
        }
        skipped.set_item(reason, list)?;
    }
    dict.set_item("skipped", skipped)?;

    match &result.git_head {
        Some(head) => dict.set_item("git_head", head)?,
        None => dict.set_item("git_head", py.None())?,
    }

    Ok(dict)
}

/// Register `discover_files` on the parent module.
pub fn register(parent: &Bound<'_, PyModule>) -> PyResult<()> {
    parent.add_function(wrap_pyfunction!(discover_files, parent)?)?;
    Ok(())
}
