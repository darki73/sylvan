//! File discovery.
//!
//! Port of `sylvan.indexing.discovery.file_discovery` from the Python
//! implementation. Preserves the same skip-reason vocabulary and order
//! of checks so cutover is a byte-comparable parity exercise.

mod classify;
mod git;
mod walker;

use std::path::{Path, PathBuf};

use sylvan_core::discovery::{DiscoveryResult, SkipReason};
use sylvan_security::filters::should_skip_dir;

pub use git::{git_head, git_ls_files, is_git_repo};

/// Options controlling a discovery pass.
///
/// Defaults mirror the Python implementation's defaults.
#[derive(Debug, Clone)]
pub struct DiscoveryOptions {
    /// Upper bound on accepted files. Excess files are recorded under
    /// `SkipReason::MaxFilesReached`.
    pub max_files: usize,
    /// Maximum accepted file size in bytes. Oversize files are recorded
    /// under `SkipReason::TooLarge(size)`.
    pub max_file_size: u64,
    /// If `true`, attempt git-based discovery when the root is a git
    /// work tree. Falls back to directory walking when git is
    /// unavailable or when this is `false`.
    pub use_git: bool,
}

impl Default for DiscoveryOptions {
    fn default() -> Self {
        Self {
            max_files: 5_000,
            max_file_size: 512_000,
            use_git: true,
        }
    }
}

/// Discover indexable files under `root`.
///
/// Uses `git ls-files --cached --others --exclude-standard` when `root`
/// is inside a git work tree and `options.use_git` is `true`. Otherwise
/// walks the tree with gitignore-aware filtering via the `ignore` crate.
///
/// The `root` itself is canonicalized; paths in the returned
/// [`DiscoveryResult`] are reported relative to that canonical root,
/// always using forward slashes.
pub fn discover_files(root: &Path, options: &DiscoveryOptions) -> DiscoveryResult {
    let root = match root.canonicalize() {
        Ok(p) => p,
        Err(_) => {
            // An unresolvable root yields an empty result rather than an
            // error so callers can still inspect the empty diagnostics.
            return DiscoveryResult::default();
        }
    };
    let mut result = DiscoveryResult::default();
    if options.use_git {
        result.git_head = git_head(&root);
    }
    let git_files = if options.use_git {
        git_ls_files(&root)
    } else {
        None
    };
    match git_files {
        Some(files) => discover_via_git(&root, files, options, &mut result),
        None => walker::discover_via_walk(&root, options, &mut result),
    }
    result
}

/// Populate `result` from a `git ls-files` listing.
///
/// Pulled up into the module root because it is the lightest of the two
/// backends; the walker sits in its own module to keep `ignore`-related
/// imports contained.
pub(crate) fn discover_via_git(
    root: &Path,
    git_files: Vec<String>,
    options: &DiscoveryOptions,
    result: &mut DiscoveryResult,
) {
    for rel_path in git_files {
        let normalized = normalize_separators(&rel_path);
        if result.files.len() >= options.max_files {
            result.add_skipped(normalized, SkipReason::MaxFilesReached);
            continue;
        }
        let full_path = root.join(strip_leading_separator(&normalized));
        if has_skippable_directory(&normalized) {
            result.add_skipped(normalized, SkipReason::SkipDir);
            continue;
        }
        record(root, &full_path, &normalized, options.max_file_size, result);
    }
}

/// Classify `full_path`, append to `result.files` on success, or add to
/// the skipped bucket on failure.
pub(crate) fn record(
    root: &Path,
    full_path: &Path,
    relative: &str,
    max_file_size: u64,
    result: &mut DiscoveryResult,
) {
    match classify::classify(full_path, root, max_file_size) {
        Ok(stat) => result.files.push(sylvan_core::discovery::DiscoveredFile {
            path: PathBuf::from(full_path),
            relative_path: relative.to_string(),
            size: stat.size,
            mtime: stat.mtime,
        }),
        Err(reason) => result.add_skipped(relative.to_string(), reason),
    }
}

pub(crate) fn has_skippable_directory(rel_path: &str) -> bool {
    let parts: Vec<&str> = rel_path.split('/').filter(|p| !p.is_empty()).collect();
    if parts.len() < 2 {
        return false;
    }
    parts[..parts.len() - 1]
        .iter()
        .any(|part| should_skip_dir(part))
}

pub(crate) fn normalize_separators(path: &str) -> String {
    path.replace('\\', "/")
}

fn strip_leading_separator(path: &str) -> &str {
    path.trim_start_matches('/')
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn has_skippable_directory_detects_skip_dirs() {
        assert!(has_skippable_directory("node_modules/foo/bar.js"));
        assert!(has_skippable_directory("src/target/build.rs"));
    }

    #[test]
    fn has_skippable_directory_allows_clean_paths() {
        assert!(!has_skippable_directory("src/main.rs"));
        assert!(!has_skippable_directory("lib/util.py"));
    }

    #[test]
    fn has_skippable_directory_handles_bare_filenames() {
        assert!(!has_skippable_directory("README.md"));
        assert!(!has_skippable_directory(""));
    }

    #[test]
    fn has_skippable_directory_detects_dotdirs() {
        // Any dotdir qualifies via should_skip_dir's `starts_with('.')`.
        assert!(has_skippable_directory(".github/workflows/ci.yml"));
    }

    #[test]
    fn normalize_separators_converts_backslash() {
        assert_eq!(normalize_separators("a\\b\\c"), "a/b/c");
    }

    #[test]
    fn default_options_match_python_defaults() {
        let o = DiscoveryOptions::default();
        assert_eq!(o.max_files, 5_000);
        assert_eq!(o.max_file_size, 512_000);
        assert!(o.use_git);
    }
}
