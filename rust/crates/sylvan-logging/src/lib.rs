//! Observability for sylvan.
//!
//! Wraps the `tracing` ecosystem with sylvan's configuration shape:
//! explicit init at the binary edge, config-driven sinks, per-module level
//! overrides as data, non-blocking file writer. See RFCs `observability.md`
//! and `logging-levels.md`.

#![forbid(unsafe_code)]
#![deny(missing_docs)]

mod config;
mod error;
mod level;
mod subscriber;

pub use config::{FileConfig, Format, LoggingConfig, Rotation};
pub use error::{ConfigError, InitError};
pub use level::Level;
pub use subscriber::{LoggingGuard, build_layered, init};
