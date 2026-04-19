//! PyO3 bridge for the filesystem watcher.
//!
//! Exposes a `Watcher` pyclass backed by
//! [`sylvan_indexing::watch::Watcher`]. Construction starts watching
//! immediately; `next_batch` blocks in Rust land (with the GIL
//! released) until either the next debounced batch arrives or the
//! supplied timeout elapses.

use std::path::PathBuf;
use std::time::Duration;

use pyo3::IntoPyObjectExt;
use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use pyo3::types::{PyList, PyModule, PyTuple};

use sylvan_indexing::watch::{ChangeKind, Watcher as RustWatcher};

/// A running filesystem watcher.
///
/// Parameters:
///   root: Directory to watch recursively.
///   debounce_ms: Debounce window in milliseconds. Events occurring
///     within this window are folded into one batch.
#[pyclass]
pub struct Watcher {
    inner: Option<RustWatcher>,
}

#[pymethods]
impl Watcher {
    #[new]
    #[pyo3(signature = (root, debounce_ms = 2000))]
    fn new(root: &str, debounce_ms: u64) -> PyResult<Self> {
        let inner = RustWatcher::start(&PathBuf::from(root), Duration::from_millis(debounce_ms))
            .map_err(|err| PyRuntimeError::new_err(err.to_string()))?;
        Ok(Self { inner: Some(inner) })
    }

    /// Block up to `timeout_ms` waiting for the next change batch.
    ///
    /// Returns an empty list on timeout. Each entry is `(kind, path)`
    /// where `kind` is `"added"`, `"modified"`, or `"removed"`.
    #[pyo3(signature = (timeout_ms = 1000))]
    fn next_batch<'py>(&self, py: Python<'py>, timeout_ms: u64) -> PyResult<Bound<'py, PyList>> {
        let inner = self
            .inner
            .as_ref()
            .ok_or_else(|| PyRuntimeError::new_err("watcher has been closed"))?;
        // Callers should invoke from `asyncio.to_thread` to keep the
        // asyncio loop responsive; the worker thread there already
        // detaches from the GIL for us.
        let timeout = Duration::from_millis(timeout_ms);
        let batch = inner.next_batch(timeout).unwrap_or_default();

        let list = PyList::empty(py);
        for change in batch {
            let kind = match change.kind {
                ChangeKind::Added => "added",
                ChangeKind::Modified => "modified",
                ChangeKind::Removed => "removed",
            };
            let path = change.path.to_string_lossy().into_owned();
            let tuple = PyTuple::new(py, [kind.into_py_any(py)?, path.into_py_any(py)?])?;
            list.append(tuple)?;
        }
        Ok(list)
    }

    /// Stop watching. Subsequent `next_batch` calls raise.
    fn close(&mut self) {
        self.inner = None;
    }
}

/// Register the `Watcher` class on the parent module.
pub fn register(parent: &Bound<'_, PyModule>) -> PyResult<()> {
    parent.add_class::<Watcher>()?;
    Ok(())
}
