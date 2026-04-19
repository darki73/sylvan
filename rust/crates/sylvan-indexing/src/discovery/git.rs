//! Git subprocess helpers for discovery.
//!
//! The PoC benchmark confirmed subprocess `git ls-files` wins over the
//! pure-Rust `gix` backend on small-to-medium repositories and matches
//! the Python implementation byte-for-byte, including the
//! untracked-but-not-gitignored case via `--others --exclude-standard`.

use std::path::{Path, PathBuf};
use std::process::Command;

/// Return `true` if `root` or any ancestor up to 50 levels contains a
/// `.git` entry.
///
/// Mirrors `sylvan.indexing.discovery.file_discovery._is_git_repo`.
pub fn is_git_repo(root: &Path) -> bool {
    let mut current: PathBuf = root.to_path_buf();
    for _ in 0..50 {
        if current.join(".git").exists() {
            return true;
        }
        match current.parent() {
            Some(parent) if parent != current => current = parent.to_path_buf(),
            _ => return false,
        }
    }
    false
}

/// Return the current HEAD commit hash, or `None` if the root is not a
/// git repo or the lookup failed.
pub fn git_head(root: &Path) -> Option<String> {
    if !is_git_repo(root) {
        return None;
    }
    let output = Command::new("git")
        .current_dir(root)
        .args(["rev-parse", "HEAD"])
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let s = String::from_utf8(output.stdout).ok()?;
    Some(s.trim().to_string())
}

/// Run `git ls-files --cached --others --exclude-standard` in `root`.
///
/// Returns `None` when `root` is not a git work tree or when the
/// subprocess fails. Returns `Some(paths)` with forward-slash separators
/// otherwise.
pub fn git_ls_files(root: &Path) -> Option<Vec<String>> {
    if !is_git_repo(root) {
        return None;
    }
    let output = Command::new("git")
        .current_dir(root)
        .args(["ls-files", "--cached", "--others", "--exclude-standard"])
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let stdout = String::from_utf8_lossy(&output.stdout);
    Some(
        stdout
            .lines()
            .filter(|l| !l.is_empty())
            .map(String::from)
            .collect(),
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn is_git_repo_returns_false_for_tempdir() {
        let dir = tempfile::tempdir().unwrap();
        assert!(!is_git_repo(dir.path()));
    }

    #[test]
    fn git_head_returns_none_for_tempdir() {
        let dir = tempfile::tempdir().unwrap();
        assert!(git_head(dir.path()).is_none());
    }

    #[test]
    fn git_ls_files_returns_none_for_tempdir() {
        let dir = tempfile::tempdir().unwrap();
        assert!(git_ls_files(dir.path()).is_none());
    }
}
