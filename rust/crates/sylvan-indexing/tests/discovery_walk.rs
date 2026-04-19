//! Integration tests for the non-git walker backend.
//!
//! Builds small synthetic file trees in a tempdir and asserts that
//! `discover_files` produces the expected accepted-files / skip-reason
//! shape.

use std::fs;
use std::io::Write;
use std::path::Path;

use sylvan_indexing::discovery::{DiscoveryOptions, discover_files};

fn write(dir: &Path, rel: &str, contents: &[u8]) {
    let path = dir.join(rel);
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).unwrap();
    }
    let mut file = fs::File::create(&path).unwrap();
    file.write_all(contents).unwrap();
}

fn opts_non_git() -> DiscoveryOptions {
    DiscoveryOptions {
        use_git: false,
        ..Default::default()
    }
}

#[test]
fn walks_simple_tree() {
    let dir = tempfile::tempdir().unwrap();
    write(dir.path(), "a.py", b"print('a')\n");
    write(dir.path(), "b.py", b"print('b')\n");
    write(dir.path(), "sub/c.py", b"print('c')\n");

    let result = discover_files(dir.path(), &opts_non_git());

    assert_eq!(result.files.len(), 3);
    let mut rels: Vec<_> = result
        .files
        .iter()
        .map(|f| f.relative_path.clone())
        .collect();
    rels.sort();
    assert_eq!(rels, vec!["a.py", "b.py", "sub/c.py"]);
    assert!(result.skipped.is_empty());
    assert!(result.git_head.is_none());
}

#[test]
fn skips_binary_extensions_and_secrets() {
    let dir = tempfile::tempdir().unwrap();
    write(dir.path(), "a.py", b"print('a')\n");
    write(dir.path(), "icon.png", b"\x89PNG\r\n\x1a\n");
    write(dir.path(), ".env", b"SECRET=1\n");

    let result = discover_files(dir.path(), &opts_non_git());

    assert_eq!(result.files.len(), 1);
    assert_eq!(result.files[0].relative_path, "a.py");
    assert_eq!(
        result.skipped.get("binary_extension").map(|v| v.len()),
        Some(1)
    );
    assert_eq!(result.skipped.get("secret_file").map(|v| v.len()), Some(1));
}

#[test]
fn skips_node_modules_subtree() {
    let dir = tempfile::tempdir().unwrap();
    write(dir.path(), "src/main.js", b"console.log(1)\n");
    write(
        dir.path(),
        "node_modules/lodash/index.js",
        b"module.exports={};\n",
    );
    write(dir.path(), "node_modules/lodash/LICENSE", b"MIT\n");

    let result = discover_files(dir.path(), &opts_non_git());

    let rels: Vec<_> = result
        .files
        .iter()
        .map(|f| f.relative_path.clone())
        .collect();
    assert_eq!(rels, vec!["src/main.js"]);
    // The walker prunes node_modules at the directory entry, so the file
    // count under it does not even surface as skipped entries.
    for rel in &rels {
        assert!(!rel.contains("node_modules"));
    }
}

#[test]
fn respects_max_files_limit() {
    let dir = tempfile::tempdir().unwrap();
    for i in 0..5 {
        write(dir.path(), &format!("f{i}.py"), b"x = 1\n");
    }

    let options = DiscoveryOptions {
        max_files: 2,
        use_git: false,
        ..Default::default()
    };
    let result = discover_files(dir.path(), &options);

    assert_eq!(result.files.len(), 2);
    let overflow = result
        .skipped
        .get("max_files_reached")
        .map(|v| v.len())
        .unwrap_or(0);
    assert_eq!(overflow, 3);
}

#[test]
fn records_empty_file_as_skipped() {
    let dir = tempfile::tempdir().unwrap();
    write(dir.path(), "empty.py", b"");
    write(dir.path(), "real.py", b"x = 1\n");

    let result = discover_files(dir.path(), &opts_non_git());

    assert_eq!(result.files.len(), 1);
    assert_eq!(result.skipped.get("empty").map(|v| v.len()), Some(1));
}

#[test]
fn records_oversize_file_as_too_large() {
    let dir = tempfile::tempdir().unwrap();
    write(dir.path(), "ok.py", b"x = 1\n");
    write(dir.path(), "huge.py", &vec![b'x'; 2048]);

    let options = DiscoveryOptions {
        max_file_size: 1024,
        use_git: false,
        ..Default::default()
    };
    let result = discover_files(dir.path(), &options);

    assert_eq!(result.files.len(), 1);
    // too_large reasons carry the offending size; bucket keys include it.
    let too_large_count: usize = result
        .skipped
        .iter()
        .filter(|(k, _)| k.starts_with("too_large:"))
        .map(|(_, v)| v.len())
        .sum();
    assert_eq!(too_large_count, 1);
}

#[test]
fn returns_empty_result_for_nonexistent_root() {
    let dir = tempfile::tempdir().unwrap();
    let missing = dir.path().join("does-not-exist");
    let result = discover_files(&missing, &opts_non_git());
    assert!(result.files.is_empty());
    assert!(result.skipped.is_empty());
}
