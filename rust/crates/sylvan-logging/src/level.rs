use core::fmt;
use core::str::FromStr;

use serde::{Deserialize, Deserializer};

use crate::error::ConfigError;

/// A log level expressed as an owned enum.
///
/// Wraps `tracing::Level` so sylvan's config surface (YAML, env vars) can
/// parse and serialize levels without exposing the transitive tracing
/// types. `WARNING` is accepted as an alias for `warn` for compatibility
/// with Python's `logging` module vocabulary.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, PartialOrd, Ord)]
pub enum Level {
    /// Per-iteration loop state, hot-path internals.
    Trace,
    /// Per-operation intermediate decisions.
    Debug,
    /// User-visible operational events.
    #[default]
    Info,
    /// Recoverable problems the user might want to see.
    Warn,
    /// Operation failed.
    Error,
}

impl FromStr for Level {
    type Err = ConfigError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.trim().to_ascii_lowercase().as_str() {
            "trace" => Ok(Self::Trace),
            "debug" => Ok(Self::Debug),
            "info" => Ok(Self::Info),
            "warn" | "warning" => Ok(Self::Warn),
            "error" => Ok(Self::Error),
            _ => Err(ConfigError::InvalidLevel {
                value: s.to_string(),
            }),
        }
    }
}

impl fmt::Display for Level {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let s = match self {
            Self::Trace => "trace",
            Self::Debug => "debug",
            Self::Info => "info",
            Self::Warn => "warn",
            Self::Error => "error",
        };
        f.write_str(s)
    }
}

impl<'de> Deserialize<'de> for Level {
    fn deserialize<D: Deserializer<'de>>(d: D) -> Result<Self, D::Error> {
        let s = String::deserialize(d)?;
        Self::from_str(&s).map_err(serde::de::Error::custom)
    }
}

impl From<Level> for tracing::Level {
    fn from(value: Level) -> Self {
        match value {
            Level::Trace => tracing::Level::TRACE,
            Level::Debug => tracing::Level::DEBUG,
            Level::Info => tracing::Level::INFO,
            Level::Warn => tracing::Level::WARN,
            Level::Error => tracing::Level::ERROR,
        }
    }
}

impl From<Level> for tracing::metadata::LevelFilter {
    fn from(value: Level) -> Self {
        tracing::Level::from(value).into()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_is_info() {
        assert_eq!(Level::default(), Level::Info);
    }

    #[test]
    fn parses_canonical_names() {
        for (input, expected) in [
            ("trace", Level::Trace),
            ("debug", Level::Debug),
            ("info", Level::Info),
            ("warn", Level::Warn),
            ("error", Level::Error),
        ] {
            assert_eq!(input.parse::<Level>().unwrap(), expected);
        }
    }

    #[test]
    fn parses_case_insensitively() {
        assert_eq!("INFO".parse::<Level>().unwrap(), Level::Info);
        assert_eq!("Debug".parse::<Level>().unwrap(), Level::Debug);
    }

    #[test]
    fn parses_warning_alias() {
        assert_eq!("warning".parse::<Level>().unwrap(), Level::Warn);
        assert_eq!("WARNING".parse::<Level>().unwrap(), Level::Warn);
    }

    #[test]
    fn trims_whitespace() {
        assert_eq!("  info  ".parse::<Level>().unwrap(), Level::Info);
    }

    #[test]
    fn invalid_level_is_a_loud_error() {
        let err = "loud".parse::<Level>().unwrap_err();
        let message = err.to_string();
        assert!(message.contains("loud"));
        assert!(message.contains("trace"));
        assert!(message.contains("error"));
    }

    #[test]
    fn display_round_trips_through_parse() {
        for level in [
            Level::Trace,
            Level::Debug,
            Level::Info,
            Level::Warn,
            Level::Error,
        ] {
            let rendered = level.to_string();
            assert_eq!(rendered.parse::<Level>().unwrap(), level);
        }
    }

    #[test]
    fn converts_to_tracing_level() {
        assert_eq!(tracing::Level::from(Level::Trace), tracing::Level::TRACE);
        assert_eq!(tracing::Level::from(Level::Debug), tracing::Level::DEBUG);
        assert_eq!(tracing::Level::from(Level::Info), tracing::Level::INFO);
        assert_eq!(tracing::Level::from(Level::Warn), tracing::Level::WARN);
        assert_eq!(tracing::Level::from(Level::Error), tracing::Level::ERROR);
    }

    #[test]
    fn converts_to_tracing_level_filter() {
        use tracing::metadata::LevelFilter;
        assert_eq!(LevelFilter::from(Level::Info), LevelFilter::INFO);
    }

    #[test]
    fn ordering_matches_severity() {
        assert!(Level::Error > Level::Warn);
        assert!(Level::Warn > Level::Info);
        assert!(Level::Info > Level::Debug);
        assert!(Level::Debug > Level::Trace);
    }

    #[test]
    fn deserializes_from_json() {
        let level: Level = serde_json::from_str("\"warn\"").unwrap();
        assert_eq!(level, Level::Warn);
    }

    #[test]
    fn deserialize_rejects_garbage() {
        let err = serde_json::from_str::<Level>("\"loud\"").unwrap_err();
        assert!(err.to_string().contains("loud"));
    }
}
