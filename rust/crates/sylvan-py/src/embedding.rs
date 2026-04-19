//! PyO3 bridge for the embedding provider.
//!
//! Exposes `sylvan._rust.EmbeddingModel` as a pyclass that:
//!
//! - downloads a known model into the caller-supplied cache directory
//!   (or the sylvan default) on first load,
//! - loads it via the safe `ort-sys` wrapper in
//!   [`sylvan_providers::embedding`], and
//! - exposes `embed(texts) -> list[list[float]]` for batched inference.
//!
//! The Python proxy (`sylvan.providers.builtin.sentence_transformers`)
//! owns config resolution, DLL discovery, and the provider trait
//! glue; this layer is a thin pyclass wrapper only.

use std::path::PathBuf;

use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;
use pyo3::types::{PyList, PyModule};

use sylvan_providers::embedding::{DEFAULT_MODEL, download_into};
use sylvan_providers::{EmbeddingModel as RustEmbeddingModel, EmbeddingModelConfig};

/// A loaded embedding model.
///
/// Constructor downloads the model (if not cached) and loads the ONNX
/// session. Dropping the instance releases all ORT resources.
#[pyclass]
pub struct EmbeddingModel {
    inner: RustEmbeddingModel,
}

#[pymethods]
impl EmbeddingModel {
    /// Load an embedding model by name.
    ///
    /// Parameters:
    ///   model_name: HuggingFace-style identifier; defaults to the
    ///     sentence-transformers MiniLM model.
    ///   cache_dir: Directory to store downloaded weights and
    ///     tokenizer. Defaults to the `sylvan-providers`-resolved
    ///     path (`$SYLVAN_HOME/models`, i.e. `~/.sylvan/models`).
    ///   ort_library_path: Optional explicit path to an ONNX Runtime
    ///     shared library. When omitted, Rust downloads the right
    ///     binary for the host platform into
    ///     `$SYLVAN_HOME/runtime/` on first use.
    #[new]
    #[pyo3(signature = (model_name = None, cache_dir = None, ort_library_path = None))]
    fn new(
        model_name: Option<&str>,
        cache_dir: Option<&str>,
        ort_library_path: Option<&str>,
    ) -> PyResult<Self> {
        let name = model_name.unwrap_or(DEFAULT_MODEL);
        let cache = match cache_dir {
            Some(p) => PathBuf::from(p),
            None => sylvan_providers::embedding::sylvan_model_dir()
                .map_err(|err| PyRuntimeError::new_err(err.to_string()))?,
        };
        let ort_library = match ort_library_path {
            Some(p) => PathBuf::from(p),
            None => sylvan_providers::embedding::ensure_runtime()
                .map_err(|err| PyRuntimeError::new_err(err.to_string()))?,
        };
        let downloaded =
            download_into(name, &cache).map_err(|err| PyRuntimeError::new_err(err.to_string()))?;
        let config = EmbeddingModelConfig::new(
            ort_library,
            downloaded.model_path,
            downloaded.tokenizer_path,
        );
        let inner = RustEmbeddingModel::load(&config)
            .map_err(|err| PyRuntimeError::new_err(err.to_string()))?;
        Ok(Self { inner })
    }

    /// Number of dimensions in each output vector.
    fn dimensions(&self) -> usize {
        self.inner.dimensions()
    }

    /// Embed a list of strings. Returns a list of float lists, one per input.
    fn embed<'py>(&self, py: Python<'py>, texts: Vec<String>) -> PyResult<Bound<'py, PyList>> {
        let refs: Vec<&str> = texts.iter().map(String::as_str).collect();
        let vectors = self
            .inner
            .embed(&refs)
            .map_err(|err| PyRuntimeError::new_err(err.to_string()))?;
        let list = PyList::empty(py);
        for vec in vectors {
            list.append(PyList::new(py, vec)?)?;
        }
        Ok(list)
    }
}

/// Register the `EmbeddingModel` class on the parent module.
pub fn register(parent: &Bound<'_, PyModule>) -> PyResult<()> {
    parent.add_class::<EmbeddingModel>()?;
    Ok(())
}
