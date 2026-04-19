use std::fmt;
use std::fs;
use std::path::Path;

use tracing::Subscriber;
use tracing_appender::non_blocking::WorkerGuard;
use tracing_appender::rolling;
use tracing_subscriber::filter::{EnvFilter, LevelFilter};
use tracing_subscriber::fmt as tfmt;
use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::registry::LookupSpan;
use tracing_subscriber::{Layer, Registry};

use crate::config::{FileConfig, Format, LoggingConfig, Rotation};
use crate::error::InitError;

/// Holds resources (worker threads, file handles) for any non-blocking
/// sinks created during [`init`]. Drop at shutdown to flush pending events.
///
/// The guard never needs to be named explicitly; `let _guard = init(...)?;`
/// at the binary edge is the intended pattern.
pub struct LoggingGuard {
    _worker_guards: Vec<WorkerGuard>,
}

impl fmt::Debug for LoggingGuard {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("LoggingGuard")
            .field("worker_guards", &self._worker_guards.len())
            .finish()
    }
}

/// Install `config` as the process-wide tracing subscriber.
///
/// At most one subscriber may be installed per process; calling [`init`]
/// after another subscriber is already installed (by sylvan or anyone
/// else) returns [`InitError::AlreadyInitialized`].
///
/// # Errors
///
/// * [`InitError::AlreadyInitialized`] if a subscriber is already installed.
/// * [`InitError::CreateDir`] if the file sink points at a directory that
///   cannot be created.
/// * [`InitError::MissingFileName`] if the file path has no final
///   file-name component.
pub fn init(config: &LoggingConfig) -> Result<LoggingGuard, InitError> {
    let (subscriber, guards) = build_layered(config)?;
    tracing::subscriber::set_global_default(subscriber)
        .map_err(|_| InitError::AlreadyInitialized)?;
    Ok(LoggingGuard {
        _worker_guards: guards,
    })
}

/// Build a filter + console layer + optional file layer, wrap them in a
/// [`Registry`], and return both the composed subscriber and any worker
/// guards.
///
/// Exposed so callers can install the subscriber locally in tests via
/// `tracing::subscriber::with_default`. Production callers should use
/// [`init`] instead.
///
/// # Errors
///
/// Same conditions as [`init`] except [`InitError::AlreadyInitialized`].
pub fn build_layered(
    config: &LoggingConfig,
) -> Result<
    (
        impl Subscriber + Send + Sync + for<'a> LookupSpan<'a>,
        Vec<WorkerGuard>,
    ),
    InitError,
> {
    let filter = build_filter(config);
    let console = console_layer(config.format);
    let (file_layer, guards) = match &config.file {
        Some(file_cfg) => {
            let (layer, guard) = build_file_layer(file_cfg, config.format)?;
            (Some(layer), vec![guard])
        }
        None => (None, Vec::new()),
    };
    let subscriber = Registry::default()
        .with(filter)
        .with(console)
        .with(file_layer);
    Ok((subscriber, guards))
}

fn build_filter(config: &LoggingConfig) -> EnvFilter {
    let base: LevelFilter = config.level.into();
    let mut filter = EnvFilter::default().add_directive(base.into());
    for (module, level) in &config.overrides {
        // Directive strings constructed from validated Level values are
        // syntactically valid for EnvFilter. If that ever becomes false
        // we surface the failure via a panic-on-install unit test, not a
        // runtime error path.
        let directive = format!("{module}={level}")
            .parse()
            .expect("Level values always format to valid EnvFilter directives");
        filter = filter.add_directive(directive);
    }
    filter
}

fn console_layer<S>(format: Format) -> Box<dyn Layer<S> + Send + Sync>
where
    S: Subscriber + for<'a> LookupSpan<'a>,
{
    match format {
        Format::Pretty => tfmt::layer().pretty().boxed(),
        Format::Compact => tfmt::layer().compact().boxed(),
        Format::Json => tfmt::layer().json().boxed(),
    }
}

fn build_file_layer<S>(
    cfg: &FileConfig,
    default_format: Format,
) -> Result<(Box<dyn Layer<S> + Send + Sync>, WorkerGuard), InitError>
where
    S: Subscriber + for<'a> LookupSpan<'a>,
{
    ensure_parent_dir(&cfg.path)?;
    let dir = cfg.path.parent().unwrap_or_else(|| Path::new("."));
    let file_name = cfg
        .path
        .file_name()
        .ok_or_else(|| InitError::MissingFileName {
            path: cfg.path.clone(),
        })?;
    let writer = match cfg.rotation {
        Rotation::Never => rolling::never(dir, file_name),
        Rotation::Daily => rolling::daily(dir, file_name),
        Rotation::Hourly => rolling::hourly(dir, file_name),
        Rotation::Minutely => rolling::minutely(dir, file_name),
    };
    let (non_blocking, guard) = tracing_appender::non_blocking(writer);
    let format = cfg.format.unwrap_or(default_format);
    let layer: Box<dyn Layer<S> + Send + Sync> = match format {
        Format::Pretty => tfmt::layer()
            .with_writer(non_blocking)
            .with_ansi(false)
            .pretty()
            .boxed(),
        Format::Compact => tfmt::layer()
            .with_writer(non_blocking)
            .with_ansi(false)
            .compact()
            .boxed(),
        Format::Json => tfmt::layer().with_writer(non_blocking).json().boxed(),
    };
    Ok((layer, guard))
}

fn ensure_parent_dir(path: &Path) -> Result<(), InitError> {
    let Some(parent) = path.parent() else {
        return Ok(());
    };
    if parent.as_os_str().is_empty() {
        return Ok(());
    }
    fs::create_dir_all(parent).map_err(|source| InitError::CreateDir {
        path: parent.to_path_buf(),
        source,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::level::Level;
    use std::collections::HashMap;
    use std::path::PathBuf;

    #[test]
    fn build_layered_returns_no_guards_without_file_sink() {
        let config = LoggingConfig::default();
        let (_subscriber, guards) = build_layered(&config).unwrap();
        assert!(guards.is_empty());
    }

    #[test]
    fn build_layered_returns_one_guard_with_file_sink() {
        let dir = tempfile::tempdir().unwrap();
        let config = LoggingConfig {
            file: Some(FileConfig {
                path: dir.path().join("sylvan.log"),
                rotation: Rotation::Never,
                format: None,
            }),
            ..LoggingConfig::default()
        };
        let (_subscriber, guards) = build_layered(&config).unwrap();
        assert_eq!(guards.len(), 1);
    }

    #[test]
    fn build_layered_accepts_all_formats() {
        for format in [Format::Pretty, Format::Compact, Format::Json] {
            let config = LoggingConfig {
                format,
                ..LoggingConfig::default()
            };
            let _ = build_layered(&config).unwrap();
        }
    }

    #[test]
    fn build_layered_accepts_all_rotations() {
        for rotation in [
            Rotation::Never,
            Rotation::Daily,
            Rotation::Hourly,
            Rotation::Minutely,
        ] {
            let dir = tempfile::tempdir().unwrap();
            let config = LoggingConfig {
                file: Some(FileConfig {
                    path: dir.path().join("sylvan.log"),
                    rotation,
                    format: None,
                }),
                ..LoggingConfig::default()
            };
            let _ = build_layered(&config).unwrap();
        }
    }

    #[test]
    fn build_layered_honours_file_format_override() {
        let dir = tempfile::tempdir().unwrap();
        let config = LoggingConfig {
            format: Format::Pretty,
            file: Some(FileConfig {
                path: dir.path().join("sylvan.log"),
                rotation: Rotation::Never,
                format: Some(Format::Json),
            }),
            ..LoggingConfig::default()
        };
        let _ = build_layered(&config).unwrap();
    }

    #[test]
    fn build_layered_creates_missing_parent_dir() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("nested/deep/sylvan.log");
        let config = LoggingConfig {
            file: Some(FileConfig {
                path: path.clone(),
                rotation: Rotation::Never,
                format: None,
            }),
            ..LoggingConfig::default()
        };
        let _ = build_layered(&config).unwrap();
        assert!(path.parent().unwrap().is_dir());
    }

    #[test]
    fn build_layered_reports_missing_file_name() {
        let config = LoggingConfig {
            file: Some(FileConfig {
                path: PathBuf::from("/"),
                rotation: Rotation::Never,
                format: None,
            }),
            ..LoggingConfig::default()
        };
        let err = build_layered(&config)
            .map(|_| ())
            .expect_err("expected MissingFileName");
        assert!(matches!(err, InitError::MissingFileName { .. }));
    }

    #[test]
    fn build_filter_honours_base_level() {
        let config = LoggingConfig {
            level: Level::Warn,
            ..LoggingConfig::default()
        };
        // The filter is opaque, but rendering it via Display must contain
        // the base directive so the test does exercise the path.
        let rendered = build_filter(&config).to_string();
        assert!(rendered.to_lowercase().contains("warn"));
    }

    #[test]
    fn build_filter_honours_module_overrides() {
        let mut overrides = HashMap::new();
        overrides.insert("aiosqlite".to_string(), Level::Error);
        let config = LoggingConfig {
            level: Level::Info,
            overrides,
            ..LoggingConfig::default()
        };
        let rendered = build_filter(&config).to_string();
        assert!(rendered.contains("aiosqlite"));
    }

    #[test]
    fn ensure_parent_dir_accepts_bare_file_name() {
        ensure_parent_dir(Path::new("sylvan.log")).unwrap();
    }
}
