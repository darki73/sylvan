//! Per-file classification.
//!
//! Consolidates the exclusion logic from the Python
//! `sylvan.security.filters.should_exclude_file` plus stat and
//! content-binary detection. A `classify` call returns the file's size
//! and mtime on acceptance or a [`SkipReason`] on exclusion.

use std::fs;
use std::io::Read;
use std::path::Path;
use std::time::UNIX_EPOCH;

use sylvan_core::discovery::SkipReason;
use sylvan_security::filters::{
    is_binary_content, is_binary_extension, is_secret_file, should_skip_file,
};

/// Successful classification payload.
#[derive(Debug, Clone, Copy)]
pub(crate) struct FileStat {
    pub size: u64,
    pub mtime: f64,
}

const HEAD_BYTES: usize = 8192;

/// Apply the full exclusion pipeline to `path`.
///
/// Order of checks matches the Python implementation so that emitted
/// skip reasons line up byte-for-byte during the cutover parity run.
pub(crate) fn classify(
    path: &Path,
    root: &Path,
    max_file_size: u64,
) -> Result<FileStat, SkipReason> {
    check_path_safety(path, root)?;

    let name = path
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or_default();

    if should_skip_file(name) {
        return Err(SkipReason::SkipPattern);
    }
    if is_secret_file(name) {
        return Err(SkipReason::SecretFile);
    }
    if is_binary_extension(name) {
        return Err(SkipReason::BinaryExtension);
    }

    let meta = fs::metadata(path).map_err(|_| SkipReason::StatError)?;
    let size = meta.len();
    if size > max_file_size {
        return Err(SkipReason::TooLarge(size));
    }
    if size == 0 {
        return Err(SkipReason::Empty);
    }

    let mtime = meta
        .modified()
        .ok()
        .and_then(|t| t.duration_since(UNIX_EPOCH).ok())
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0);

    let mut head = [0u8; HEAD_BYTES];
    let mut file = fs::File::open(path).map_err(|_| SkipReason::ReadError)?;
    let read = file.read(&mut head).map_err(|_| SkipReason::ReadError)?;
    if is_binary_content(&head[..read], HEAD_BYTES) {
        return Err(SkipReason::BinaryContent);
    }

    Ok(FileStat { size, mtime })
}

/// Ensure `path` resolves to a location underneath `root`.
///
/// The Python implementation runs two checks (`validate_path`,
/// `is_symlink_escape`) that collapse in Rust because `canonicalize` is
/// always strict: it requires the file to exist AND resolves symlinks.
/// We disambiguate the two Python reasons by inspecting whether the
/// offending entry is itself a symlink.
fn check_path_safety(path: &Path, root: &Path) -> Result<(), SkipReason> {
    let canonical = path.canonicalize().map_err(|_| SkipReason::PathTraversal)?;
    if canonical.starts_with(root) {
        return Ok(());
    }
    let is_symlink = path
        .symlink_metadata()
        .map(|m| m.file_type().is_symlink())
        .unwrap_or(false);
    Err(if is_symlink {
        SkipReason::SymlinkEscape
    } else {
        SkipReason::PathTraversal
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn write_file(dir: &Path, name: &str, contents: &[u8]) -> std::path::PathBuf {
        let path = dir.join(name);
        let mut file = fs::File::create(&path).unwrap();
        file.write_all(contents).unwrap();
        path
    }

    #[test]
    fn accepts_small_text_file() {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path().canonicalize().unwrap();
        let path = write_file(&root, "hello.txt", b"hello world\n");
        let stat = classify(&path, &root, 512_000).unwrap();
        assert_eq!(stat.size, 12);
        assert!(stat.mtime > 0.0);
    }

    #[test]
    fn skips_empty_file() {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path().canonicalize().unwrap();
        let path = write_file(&root, "empty.txt", b"");
        assert!(matches!(
            classify(&path, &root, 512_000),
            Err(SkipReason::Empty)
        ));
    }

    #[test]
    fn skips_oversize_file() {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path().canonicalize().unwrap();
        let path = write_file(&root, "big.txt", &vec![b'x'; 2048]);
        assert!(matches!(
            classify(&path, &root, 1024),
            Err(SkipReason::TooLarge(n)) if n == 2048
        ));
    }

    #[test]
    fn skips_binary_extension() {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path().canonicalize().unwrap();
        let path = write_file(&root, "tool.exe", b"MZ\x90\x00");
        assert!(matches!(
            classify(&path, &root, 512_000),
            Err(SkipReason::BinaryExtension)
        ));
    }

    #[test]
    fn skips_secret_file() {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path().canonicalize().unwrap();
        let path = write_file(&root, ".env", b"SECRET=1\n");
        assert!(matches!(
            classify(&path, &root, 512_000),
            Err(SkipReason::SecretFile)
        ));
    }

    #[test]
    fn skips_minified_asset() {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path().canonicalize().unwrap();
        let path = write_file(&root, "app.min.js", b"var a=1;");
        assert!(matches!(
            classify(&path, &root, 512_000),
            Err(SkipReason::SkipPattern)
        ));
    }

    #[test]
    fn skips_null_byte_content() {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path().canonicalize().unwrap();
        let path = write_file(&root, "looks-like-text.log", b"hello\0world");
        assert!(matches!(
            classify(&path, &root, 512_000),
            Err(SkipReason::BinaryContent)
        ));
    }

    #[test]
    fn reports_path_traversal_on_missing_file() {
        let dir = tempfile::tempdir().unwrap();
        let root = dir.path().canonicalize().unwrap();
        let missing = root.join("does-not-exist.txt");
        assert!(matches!(
            classify(&missing, &root, 512_000),
            Err(SkipReason::PathTraversal)
        ));
    }
}
