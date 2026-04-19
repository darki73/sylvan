//! PyO3 bridge between Python's `logging` module and `sylvan-logging`.
//!
//! Exposes two functions at `sylvan._rust.logging`:
//!
//! * `init_from_json(config_json)` — installs the process-wide tracing
//!   subscriber. One-shot; subsequent calls are no-ops unless the first
//!   one failed.
//! * `emit(level, target, message)` — translates a Python `LogRecord`
//!   into a tracing event so Python log calls funnel through the same
//!   pipeline as native Rust events.

use std::sync::Mutex;

use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyModule;

use sylvan_logging::{LoggingConfig, LoggingGuard, init as init_logging};

static GUARD: Mutex<Option<LoggingGuard>> = Mutex::new(None);

#[pyfunction]
fn init_from_json(config_json: &str) -> PyResult<()> {
    let mut slot = GUARD
        .lock()
        .map_err(|err| PyRuntimeError::new_err(format!("logging guard poisoned: {err}")))?;
    if slot.is_some() {
        return Ok(());
    }
    let config: LoggingConfig = serde_json::from_str(config_json)
        .map_err(|err| PyValueError::new_err(format!("invalid logging config: {err}")))?;
    let guard = init_logging(&config)
        .map_err(|err| PyRuntimeError::new_err(format!("logging init failed: {err}")))?;
    *slot = Some(guard);
    Ok(())
}

#[pyfunction]
fn emit(level: &str, target: &str, message: &str) -> PyResult<()> {
    // tracing's event macro requires a `'static` target, so events
    // originating from Python get a synthetic target and carry the real
    // Python logger name as a `logger` field. Subscribers can filter on
    // the field when per-logger granularity matters.
    match normalize_level(level)? {
        PyLevel::Trace => tracing::trace!(target: "sylvan.python", logger = target, "{message}"),
        PyLevel::Debug => tracing::debug!(target: "sylvan.python", logger = target, "{message}"),
        PyLevel::Info => tracing::info!(target: "sylvan.python", logger = target, "{message}"),
        PyLevel::Warn => tracing::warn!(target: "sylvan.python", logger = target, "{message}"),
        PyLevel::Error => tracing::error!(target: "sylvan.python", logger = target, "{message}"),
    }
    Ok(())
}

enum PyLevel {
    Trace,
    Debug,
    Info,
    Warn,
    Error,
}

fn normalize_level(level: &str) -> PyResult<PyLevel> {
    match level.trim().to_ascii_lowercase().as_str() {
        // Python's logging module uses all-caps names; accept both.
        "trace" | "notset" => Ok(PyLevel::Trace),
        "debug" => Ok(PyLevel::Debug),
        "info" => Ok(PyLevel::Info),
        "warn" | "warning" => Ok(PyLevel::Warn),
        "error" | "critical" | "fatal" => Ok(PyLevel::Error),
        _ => Err(PyValueError::new_err(format!(
            "unknown log level: {level:?}"
        ))),
    }
}

/// Register the `logging` submodule on `parent`.
pub fn register(parent: &Bound<'_, PyModule>) -> PyResult<()> {
    let logging = PyModule::new(parent.py(), "logging")?;
    logging.add_function(wrap_pyfunction!(init_from_json, &logging)?)?;
    logging.add_function(wrap_pyfunction!(emit, &logging)?)?;
    parent.add_submodule(&logging)?;
    Ok(())
}
