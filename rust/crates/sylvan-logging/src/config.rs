use std::collections::HashMap;
use std::path::PathBuf;

use serde::Deserialize;

use crate::level::Level;

/// Top-level logging configuration.
///
/// Typically deserialized from the `logging:` section of sylvan's YAML
/// config file. Unknown fields are rejected so typos fail at startup
/// rather than being silently ignored.
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields, default)]
pub struct LoggingConfig {
    /// Minimum level emitted by the console sink (and the default for any
    /// additional sinks that do not override it).
    pub level: Level,
    /// Console output format. Defaults to [`Format::Pretty`].
    pub format: Format,
    /// Per-module level overrides. Keys are target module paths (e.g.
    /// `"aiosqlite"`, `"sylvan::indexing"`); values are the effective
    /// minimum level for that subtree.
    pub overrides: HashMap<String, Level>,
    /// Optional file sink. When absent, logs are emitted only to the
    /// console.
    pub file: Option<FileConfig>,
}

impl Default for LoggingConfig {
    fn default() -> Self {
        Self {
            level: Level::Info,
            format: Format::default(),
            overrides: HashMap::new(),
            file: None,
        }
    }
}

/// Output format for a log sink.
#[derive(Debug, Clone, Copy, Deserialize, Default, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Format {
    /// Multi-line, colored, human-friendly output.
    #[default]
    Pretty,
    /// Single-line, uncolored, machine-grep-friendly output.
    Compact,
    /// Newline-delimited JSON records.
    Json,
}

/// File sink configuration.
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FileConfig {
    /// Full path to the log file. Parent directories are created on init
    /// if missing.
    pub path: PathBuf,
    /// Rotation policy. Defaults to [`Rotation::Daily`].
    #[serde(default)]
    pub rotation: Rotation,
    /// Format override for the file sink. When `None`, inherits the
    /// top-level console format.
    #[serde(default)]
    pub format: Option<Format>,
}

/// How the file sink rotates on-disk files.
#[derive(Debug, Clone, Copy, Deserialize, Default, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Rotation {
    /// Never rotate. Single growing file.
    Never,
    /// Rotate once per day at UTC midnight.
    #[default]
    Daily,
    /// Rotate once per hour at UTC top-of-hour.
    Hourly,
    /// Rotate once per minute. Intended for integration tests.
    Minutely,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_matches_spec() {
        let c = LoggingConfig::default();
        assert_eq!(c.level, Level::Info);
        assert_eq!(c.format, Format::Pretty);
        assert!(c.overrides.is_empty());
        assert!(c.file.is_none());
    }

    #[test]
    fn deserializes_empty_into_defaults() {
        let c: LoggingConfig = serde_json::from_str("{}").unwrap();
        assert_eq!(c.level, Level::Info);
        assert_eq!(c.format, Format::Pretty);
    }

    #[test]
    fn deserializes_all_fields() {
        let json = r#"{
            "level": "debug",
            "format": "json",
            "overrides": {"aiosqlite": "warn", "httpx": "error"},
            "file": {
                "path": "/var/log/sylvan.log",
                "rotation": "hourly",
                "format": "pretty"
            }
        }"#;
        let c: LoggingConfig = serde_json::from_str(json).unwrap();
        assert_eq!(c.level, Level::Debug);
        assert_eq!(c.format, Format::Json);
        assert_eq!(c.overrides.get("aiosqlite").copied(), Some(Level::Warn));
        assert_eq!(c.overrides.get("httpx").copied(), Some(Level::Error));
        let file = c.file.expect("file config present");
        assert_eq!(file.path, PathBuf::from("/var/log/sylvan.log"));
        assert_eq!(file.rotation, Rotation::Hourly);
        assert_eq!(file.format, Some(Format::Pretty));
    }

    #[test]
    fn rejects_unknown_top_level_field() {
        let err = serde_json::from_str::<LoggingConfig>(r#"{"levle":"info"}"#).unwrap_err();
        assert!(err.to_string().contains("levle"));
    }

    #[test]
    fn rejects_unknown_file_field() {
        let err =
            serde_json::from_str::<LoggingConfig>(r#"{"file":{"path":"/x","rotate":"daily"}}"#)
                .unwrap_err();
        assert!(err.to_string().contains("rotate"));
    }

    #[test]
    fn rejects_invalid_level_string() {
        let err = serde_json::from_str::<LoggingConfig>(r#"{"level":"loud"}"#).unwrap_err();
        assert!(err.to_string().contains("loud"));
    }

    #[test]
    fn file_rotation_defaults_to_daily() {
        let c: LoggingConfig = serde_json::from_str(r#"{"file":{"path":"/x"}}"#).unwrap();
        assert_eq!(c.file.unwrap().rotation, Rotation::Daily);
    }

    #[test]
    fn format_deserializes_all_variants() {
        assert_eq!(
            serde_json::from_str::<Format>("\"pretty\"").unwrap(),
            Format::Pretty
        );
        assert_eq!(
            serde_json::from_str::<Format>("\"compact\"").unwrap(),
            Format::Compact
        );
        assert_eq!(
            serde_json::from_str::<Format>("\"json\"").unwrap(),
            Format::Json
        );
    }

    #[test]
    fn rotation_deserializes_all_variants() {
        assert_eq!(
            serde_json::from_str::<Rotation>("\"never\"").unwrap(),
            Rotation::Never
        );
        assert_eq!(
            serde_json::from_str::<Rotation>("\"daily\"").unwrap(),
            Rotation::Daily
        );
        assert_eq!(
            serde_json::from_str::<Rotation>("\"hourly\"").unwrap(),
            Rotation::Hourly
        );
        assert_eq!(
            serde_json::from_str::<Rotation>("\"minutely\"").unwrap(),
            Rotation::Minutely
        );
    }
}
