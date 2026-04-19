//! Domain types for the discovery pipeline.

use std::collections::HashMap;
use std::path::PathBuf;

/// A file accepted for indexing during a discovery pass.
#[derive(Debug, Clone, PartialEq)]
pub struct DiscoveredFile {
    /// Absolute path to the file on disk.
    pub path: PathBuf,
    /// Path relative to the discovery root, using forward slashes.
    pub relative_path: String,
    /// File size in bytes.
    pub size: u64,
    /// Last-modification time as a Unix timestamp in seconds.
    pub mtime: f64,
}

/// Reason a file was skipped.
///
/// String values match the machine-readable reason strings the Python
/// implementation writes into `DiscoveryResult.skipped`. Parity between
/// the two is enforced by the drift test in `tests/test_filter_drift.py`
/// and, for this enum, by the Python test that consumes the Rust output
/// once the walker lands in a later stage.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub enum SkipReason {
    /// Directory listed in `SKIP_DIRS` or starting with `.`.
    SkipDir,
    /// File name matching a `SKIP_FILE_PATTERNS` entry.
    SkipPattern,
    /// File name matching a `SECRET_PATTERNS` entry.
    SecretFile,
    /// Extension listed in `BINARY_EXTENSIONS`.
    BinaryExtension,
    /// Content starts with a null byte within the first 8192 bytes.
    BinaryContent,
    /// File exceeds `max_file_size`. Carries the offending size.
    TooLarge(u64),
    /// Zero-byte file.
    Empty,
    /// `stat` failed on the path.
    StatError,
    /// `read` failed while inspecting the leading bytes.
    ReadError,
    /// Path resolved outside the discovery root.
    PathTraversal,
    /// Path followed a symlink that escaped the discovery root.
    SymlinkEscape,
    /// Discovery hit `max_files`; further files are not enumerated.
    MaxFilesReached,
    /// File is matched by `.gitignore` (not tracked in the git index).
    Gitignore,
}

impl SkipReason {
    /// Return the machine-readable reason string used by `DiscoveryResult`.
    ///
    /// Matches the string values the Python implementation writes, so
    /// downstream consumers on either side of the PyO3 boundary see the
    /// same vocabulary.
    pub fn as_str(&self) -> String {
        match self {
            Self::SkipDir => "skip_dir".into(),
            Self::SkipPattern => "skip_pattern".into(),
            Self::SecretFile => "secret_file".into(),
            Self::BinaryExtension => "binary_extension".into(),
            Self::BinaryContent => "binary_content".into(),
            Self::TooLarge(size) => format!("too_large:{size}"),
            Self::Empty => "empty".into(),
            Self::StatError => "stat_error".into(),
            Self::ReadError => "read_error".into(),
            Self::PathTraversal => "path_traversal".into(),
            Self::SymlinkEscape => "symlink_escape".into(),
            Self::MaxFilesReached => "max_files_reached".into(),
            Self::Gitignore => "gitignore".into(),
        }
    }
}

/// Aggregate result of a discovery pass.
///
/// Mirrors `sylvan.indexing.discovery.file_discovery.DiscoveryResult`:
/// every file accepted for indexing lands in [`Self::files`]; every file
/// or directory deemed unindexable lands in [`Self::skipped`] under the
/// relevant reason string.
#[derive(Debug, Clone, Default)]
pub struct DiscoveryResult {
    /// Files the discovery pass accepted.
    pub files: Vec<DiscoveredFile>,
    /// Paths that were skipped, grouped by machine-readable reason.
    pub skipped: HashMap<String, Vec<String>>,
    /// Git HEAD at the time of discovery. `None` when the root is not a
    /// git repository or when git lookup was not requested.
    pub git_head: Option<String>,
}

impl DiscoveryResult {
    /// Record `path` as skipped for `reason`.
    pub fn add_skipped(&mut self, path: impl Into<String>, reason: SkipReason) {
        self.skipped
            .entry(reason.as_str())
            .or_default()
            .push(path.into());
    }

    /// Total number of paths encountered (accepted + skipped).
    pub fn total_found(&self) -> usize {
        self.files.len() + self.skipped.values().map(Vec::len).sum::<usize>()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_result_is_empty() {
        let result = DiscoveryResult::default();
        assert!(result.files.is_empty());
        assert!(result.skipped.is_empty());
        assert_eq!(result.total_found(), 0);
    }

    #[test]
    fn add_skipped_groups_by_reason() {
        let mut result = DiscoveryResult::default();
        result.add_skipped("a.exe", SkipReason::BinaryExtension);
        result.add_skipped("b.exe", SkipReason::BinaryExtension);
        result.add_skipped(".env", SkipReason::SecretFile);
        assert_eq!(result.skipped["binary_extension"].len(), 2);
        assert_eq!(result.skipped["secret_file"].len(), 1);
    }

    #[test]
    fn total_found_counts_files_and_skipped() {
        let mut result = DiscoveryResult::default();
        result.files.push(DiscoveredFile {
            path: PathBuf::from("/x/a.py"),
            relative_path: "a.py".into(),
            size: 100,
            mtime: 0.0,
        });
        result.add_skipped("b.exe", SkipReason::BinaryExtension);
        assert_eq!(result.total_found(), 2);
    }

    #[test]
    fn skip_reason_strings_match_python_vocabulary() {
        assert_eq!(SkipReason::SkipDir.as_str(), "skip_dir");
        assert_eq!(SkipReason::SkipPattern.as_str(), "skip_pattern");
        assert_eq!(SkipReason::SecretFile.as_str(), "secret_file");
        assert_eq!(SkipReason::BinaryExtension.as_str(), "binary_extension");
        assert_eq!(SkipReason::BinaryContent.as_str(), "binary_content");
        assert_eq!(SkipReason::Empty.as_str(), "empty");
        assert_eq!(SkipReason::StatError.as_str(), "stat_error");
        assert_eq!(SkipReason::ReadError.as_str(), "read_error");
        assert_eq!(SkipReason::PathTraversal.as_str(), "path_traversal");
        assert_eq!(SkipReason::SymlinkEscape.as_str(), "symlink_escape");
        assert_eq!(SkipReason::MaxFilesReached.as_str(), "max_files_reached");
        assert_eq!(SkipReason::Gitignore.as_str(), "gitignore");
    }

    #[test]
    fn too_large_includes_size() {
        assert_eq!(SkipReason::TooLarge(12345).as_str(), "too_large:12345");
    }
}
