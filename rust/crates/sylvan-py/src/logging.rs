//! PyO3 bridge between Python's logging call sites and `sylvan-logging`.
//!
//! Exposes three functions at `sylvan._rust.logging`:
//!
//! * `init_from_json(config_json)` — installs the process-wide tracing
//!   subscriber. One-shot; subsequent calls are no-ops.
//! * `emit(level, target, message)` — forwards an already-formatted log
//!   line from a stdlib `logging.LogRecord` (used by the bridge handler
//!   that catches third-party Python loggers such as `httpx`).
//! * `emit_structured(level, logger, event, fields_json)` — forwards a
//!   structured event from sylvan's own Python code. Rendering (event +
//!   key=val pairs) happens here, so Python never formats anything.

use std::fmt::Write as _;
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
    dispatch(normalize_level(level)?, target, message);
    Ok(())
}

#[pyfunction]
fn emit_structured(level: &str, logger: &str, event: &str, fields_json: &str) -> PyResult<()> {
    let rendered = render_structured(event, fields_json);
    dispatch(normalize_level(level)?, logger, &rendered);
    Ok(())
}

fn render_structured(event: &str, fields_json: &str) -> String {
    if fields_json.is_empty() {
        return event.to_string();
    }
    let Ok(serde_json::Value::Object(map)) = serde_json::from_str::<serde_json::Value>(fields_json)
    else {
        // Caller passed something we cannot decode; surface it verbatim
        // so the signal is not silently dropped.
        return format!("{event} fields={fields_json}");
    };
    if map.is_empty() {
        return event.to_string();
    }
    let mut rendered = event.to_string();
    // Stable key order keeps log output deterministic.
    let mut keys: Vec<&String> = map.keys().collect();
    keys.sort();
    for key in keys {
        let value = &map[key];
        let _ = write!(rendered, " {key}=");
        write_value(&mut rendered, value);
    }
    rendered
}

fn write_value(out: &mut String, value: &serde_json::Value) {
    match value {
        serde_json::Value::String(s) => {
            // Only quote when the string contains whitespace or `=`; keeps
            // single-word values (paths, ids, enum names) clean.
            if s.chars().any(|c| c.is_whitespace() || c == '=' || c == '"') {
                let _ = write!(out, "{s:?}");
            } else {
                out.push_str(s);
            }
        }
        serde_json::Value::Null => out.push_str("null"),
        serde_json::Value::Bool(b) => {
            let _ = write!(out, "{b}");
        }
        serde_json::Value::Number(n) => {
            let _ = write!(out, "{n}");
        }
        other => {
            // Arrays and objects: emit as compact JSON.
            let _ = write!(out, "{}", other);
        }
    }
}

fn dispatch(level: PyLevel, logger: &str, message: &str) {
    // tracing's macros require `'static` targets, so events emitted from
    // Python share a synthetic target. The originating Python logger
    // name rides along as a `logger` field.
    match level {
        PyLevel::Trace => {
            tracing::trace!(target: "sylvan.python", logger = logger, "{message}")
        }
        PyLevel::Debug => {
            tracing::debug!(target: "sylvan.python", logger = logger, "{message}")
        }
        PyLevel::Info => {
            tracing::info!(target: "sylvan.python", logger = logger, "{message}")
        }
        PyLevel::Warn => {
            tracing::warn!(target: "sylvan.python", logger = logger, "{message}")
        }
        PyLevel::Error => {
            tracing::error!(target: "sylvan.python", logger = logger, "{message}")
        }
    }
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
    logging.add_function(wrap_pyfunction!(emit_structured, &logging)?)?;
    parent.add_submodule(&logging)?;
    Ok(())
}
