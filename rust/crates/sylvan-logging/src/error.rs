use std::path::PathBuf;

/// Error returned when a [`LoggingConfig`](crate::LoggingConfig) cannot be
/// parsed from its source representation.
///
/// Deserialization paths fold these errors into their own error types via
/// `serde::de::Error::custom`.
#[derive(Debug, thiserror::Error)]
pub enum ConfigError {
    /// The provided log level string does not match any known variant.
    #[error("invalid log level {value:?}: must be one of trace, debug, info, warn, or error")]
    InvalidLevel {
        /// The input string that failed to parse.
        value: String,
    },
}

/// Error returned from [`init`](crate::init) when the subscriber cannot be
/// installed.
#[derive(Debug, thiserror::Error)]
pub enum InitError {
    /// [`init`](crate::init) was called more than once in this process.
    #[error("sylvan logging has already been initialized for this process")]
    AlreadyInitialized,

    /// The parent directory of the configured log file could not be created.
    #[error("failed to create log directory {path:?}: {source}")]
    CreateDir {
        /// The directory path that could not be created.
        path: PathBuf,
        /// Underlying I/O error.
        #[source]
        source: std::io::Error,
    },

    /// The configured log file path is missing a file name component.
    #[error("log file path {path:?} has no file name component")]
    MissingFileName {
        /// The offending path.
        path: PathBuf,
    },

    /// Invalid configuration surfaced by [`ConfigError`].
    #[error(transparent)]
    Config(#[from] ConfigError),
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn invalid_level_message_lists_valid_options() {
        let err = ConfigError::InvalidLevel {
            value: "nope".into(),
        };
        let message = err.to_string();
        assert!(message.contains("nope"));
        assert!(message.contains("trace"));
        assert!(message.contains("error"));
    }

    #[test]
    fn already_initialized_is_distinct() {
        let err = InitError::AlreadyInitialized;
        assert!(err.to_string().contains("already"));
    }

    #[test]
    fn create_dir_preserves_underlying_source() {
        let io = std::io::Error::new(std::io::ErrorKind::PermissionDenied, "nope");
        let err = InitError::CreateDir {
            path: PathBuf::from("/root/forbidden"),
            source: io,
        };
        assert!(err.to_string().contains("/root/forbidden"));
        let source = std::error::Error::source(&err).unwrap();
        assert!(source.to_string().contains("nope"));
    }

    #[test]
    fn missing_file_name_includes_path() {
        let err = InitError::MissingFileName {
            path: PathBuf::from("/var/log/"),
        };
        assert!(err.to_string().contains("/var/log/"));
    }

    #[test]
    fn config_error_transparently_wraps() {
        let err: InitError = ConfigError::InvalidLevel {
            value: "nope".into(),
        }
        .into();
        let message = err.to_string();
        assert!(message.contains("nope"));
    }
}
