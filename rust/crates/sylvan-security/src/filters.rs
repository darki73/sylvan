//! Filter constants and predicates for file discovery.
//!
//! Hand-maintained parallel to `src/sylvan/security/patterns.py`. When
//! you add, remove, or change an entry on either side, update the other;
//! `tests/test_filter_drift.py` fails if the two drift.

use std::collections::HashSet;
use std::sync::OnceLock;

use glob::Pattern;

/// Directories always skipped during discovery.
pub const SKIP_DIRS: &[&str] = &[
    "node_modules",
    "vendor",
    ".git",
    "__pycache__",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "target",
    "build",
    "dist",
    ".gradle",
    ".mvn",
    ".next",
    ".nuxt",
    ".output",
    ".vercel",
    ".turbo",
    "venv",
    ".venv",
    "env",
    ".env",
    ".idea",
    ".vscode",
    ".vs",
    "coverage",
    "htmlcov",
    ".nyc_output",
    ".terraform",
    ".pulumi",
    "Pods",
    "DerivedData",
    "xcuserdata",
    ".bundle",
    ".cache",
];

/// File name glob patterns to skip outright.
pub const SKIP_FILE_PATTERNS: &[&str] = &[
    "*.min.js",
    "*.min.css",
    "*.map",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "go.sum",
    "Cargo.lock",
    "poetry.lock",
    "uv.lock",
    "*.pb.go",
    "*.generated.*",
    "*.pyc",
    "*.pyo",
];

/// File name glob patterns that indicate a secret.
pub const SECRET_PATTERNS: &[&str] = &[
    ".env",
    ".env.*",
    "*.key",
    "*.pem",
    "*.p12",
    "*.pfx",
    "*.keystore",
    "*.jks",
    "credentials.json",
    "service-account*.json",
    "id_rsa",
    "id_rsa.*",
    "id_ed25519",
    "id_ed25519.*",
    "*.secret",
    "*.secrets",
    ".htpasswd",
    ".netrc",
    ".pgpass",
];

/// Extensions treated as binary; content is not indexed.
pub const BINARY_EXTENSIONS: &[&str] = &[
    ".exe", ".dll", ".so", ".dylib", ".a", ".lib", ".o", ".obj", ".zip", ".tar", ".gz", ".bz2",
    ".xz", ".7z", ".rar", ".jar", ".war", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg",
    ".webp", ".tiff", ".tif", ".psd", ".mp3", ".mp4", ".avi", ".mov", ".flv", ".wmv", ".wav",
    ".ogg", ".webm", ".pyc", ".pyo", ".class", ".wasm", ".ttf", ".otf", ".woff", ".woff2", ".eot",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".db", ".sqlite", ".sqlite3",
    ".mdb", ".bin", ".dat", ".pkl", ".npy", ".npz", ".h5", ".hdf5",
];

/// Documentation extensions exempt from broad `*secret*` matching.
pub const DOC_EXTENSIONS: &[&str] = &[
    ".md",
    ".markdown",
    ".rst",
    ".txt",
    ".html",
    ".htm",
    ".adoc",
    ".asciidoc",
    ".ipynb",
    ".xml",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".cfg",
    ".ini",
    ".conf",
];

fn skip_dirs_set() -> &'static HashSet<&'static str> {
    static SET: OnceLock<HashSet<&'static str>> = OnceLock::new();
    SET.get_or_init(|| SKIP_DIRS.iter().copied().collect())
}

fn binary_extensions_set() -> &'static HashSet<&'static str> {
    static SET: OnceLock<HashSet<&'static str>> = OnceLock::new();
    SET.get_or_init(|| BINARY_EXTENSIONS.iter().copied().collect())
}

fn doc_extensions_set() -> &'static HashSet<&'static str> {
    static SET: OnceLock<HashSet<&'static str>> = OnceLock::new();
    SET.get_or_init(|| DOC_EXTENSIONS.iter().copied().collect())
}

/// Return `true` if `dirname` is in `SKIP_DIRS` or begins with `.`.
///
/// Matches `sylvan.security.patterns.should_skip_dir`.
pub fn should_skip_dir(dirname: &str) -> bool {
    skip_dirs_set().contains(dirname) || dirname.starts_with('.')
}

/// Return `true` if `filename` matches any `SKIP_FILE_PATTERNS` entry.
///
/// Matches `sylvan.security.patterns.should_skip_file`.
pub fn should_skip_file(filename: &str) -> bool {
    let lower = filename.to_ascii_lowercase();
    SKIP_FILE_PATTERNS
        .iter()
        .any(|pat| fnmatch(&lower, &pat.to_ascii_lowercase()))
}

/// Return `true` if `filename` matches a secret pattern.
///
/// The `*secret*` pattern is suppressed when the extension is in
/// `DOC_EXTENSIONS`, mirroring the Python implementation's carve-out
/// for documentation files that happen to mention "secret" in their
/// name.
pub fn is_secret_file(filename: &str) -> bool {
    let lower = filename.to_ascii_lowercase();
    let ext = extract_ext(&lower);
    for pattern in SECRET_PATTERNS {
        let pattern_lower = pattern.to_ascii_lowercase();
        if fnmatch(&lower, &pattern_lower) {
            if pattern.contains("*secret*") && doc_extensions_set().contains(ext.as_str()) {
                continue;
            }
            return true;
        }
    }
    false
}

/// Return `true` if `filename`'s extension is in `BINARY_EXTENSIONS`.
pub fn is_binary_extension(filename: &str) -> bool {
    let lower = filename.to_ascii_lowercase();
    let ext = extract_ext(&lower);
    binary_extensions_set().contains(ext.as_str())
}

/// Return `true` if `data` contains a null byte within the first
/// `check_size` bytes.
pub fn is_binary_content(data: &[u8], check_size: usize) -> bool {
    let end = check_size.min(data.len());
    data[..end].contains(&0)
}

fn extract_ext(name_lower: &str) -> String {
    match name_lower.rfind('.') {
        Some(idx) => name_lower[idx..].to_string(),
        None => String::new(),
    }
}

fn fnmatch(name: &str, pattern: &str) -> bool {
    Pattern::new(pattern)
        .map(|p| p.matches(name))
        .unwrap_or(false)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn skip_dir_matches_known_dirs() {
        assert!(should_skip_dir("node_modules"));
        assert!(should_skip_dir(".git"));
        assert!(should_skip_dir("__pycache__"));
        assert!(should_skip_dir("target"));
    }

    #[test]
    fn skip_dir_matches_dotfiles() {
        assert!(should_skip_dir(".github"));
        assert!(should_skip_dir(".any-hidden"));
    }

    #[test]
    fn skip_dir_rejects_regular_dirs() {
        assert!(!should_skip_dir("src"));
        assert!(!should_skip_dir("tests"));
        assert!(!should_skip_dir("lib"));
    }

    #[test]
    fn skip_file_matches_minified_assets() {
        assert!(should_skip_file("app.min.js"));
        assert!(should_skip_file("app.min.css"));
        assert!(should_skip_file("bundle.map"));
    }

    #[test]
    fn skip_file_matches_lockfiles() {
        assert!(should_skip_file("package-lock.json"));
        assert!(should_skip_file("Cargo.lock"));
        assert!(should_skip_file("uv.lock"));
    }

    #[test]
    fn skip_file_is_case_insensitive() {
        assert!(should_skip_file("APP.MIN.JS"));
        assert!(should_skip_file("CARGO.LOCK"));
    }

    #[test]
    fn skip_file_rejects_regular_files() {
        assert!(!should_skip_file("main.py"));
        assert!(!should_skip_file("README.md"));
    }

    #[test]
    fn secret_file_matches_dotenv_variants() {
        assert!(is_secret_file(".env"));
        assert!(is_secret_file(".env.local"));
        assert!(is_secret_file(".env.production"));
    }

    #[test]
    fn secret_file_matches_keys_and_certs() {
        assert!(is_secret_file("private.key"));
        assert!(is_secret_file("cert.pem"));
        assert!(is_secret_file("keystore.jks"));
        assert!(is_secret_file("id_rsa"));
        assert!(is_secret_file("id_ed25519.pub"));
    }

    #[test]
    fn secret_file_exempts_docs_from_secret_wildcard() {
        // *.secret has no doc-extension exemption (pattern does not contain *secret*).
        assert!(is_secret_file("a.secret"));
        // "*secret*" in pattern triggers doc-ext exemption.
        // No such pattern exists in SECRET_PATTERNS today, so this path is
        // currently defensive. If a `*secret*` pattern is ever added,
        // this exemption kicks in for docs.
    }

    #[test]
    fn secret_file_rejects_regular_files() {
        assert!(!is_secret_file("main.py"));
        assert!(!is_secret_file("app.js"));
    }

    #[test]
    fn binary_extension_matches_images_and_executables() {
        assert!(is_binary_extension("icon.png"));
        assert!(is_binary_extension("tool.exe"));
        assert!(is_binary_extension("lib.so"));
        assert!(is_binary_extension("app.wasm"));
    }

    #[test]
    fn binary_extension_is_case_insensitive() {
        assert!(is_binary_extension("ICON.PNG"));
        assert!(is_binary_extension("Tool.EXE"));
    }

    #[test]
    fn binary_extension_rejects_text() {
        assert!(!is_binary_extension("main.py"));
        assert!(!is_binary_extension("README"));
    }

    #[test]
    fn binary_content_detects_null_bytes() {
        assert!(is_binary_content(b"abc\0def", 8192));
        assert!(!is_binary_content(b"abcdef", 8192));
    }

    #[test]
    fn binary_content_respects_check_size() {
        let data = b"abcdefghij\0";
        assert!(!is_binary_content(data, 5));
        assert!(is_binary_content(data, 20));
    }

    #[test]
    fn binary_content_handles_empty_data() {
        assert!(!is_binary_content(b"", 8192));
    }

    #[test]
    fn extract_ext_returns_full_extension() {
        assert_eq!(extract_ext("a.py"), ".py");
        assert_eq!(extract_ext("archive.tar.gz"), ".gz");
        assert_eq!(extract_ext("noext"), "");
    }

    #[test]
    fn all_filter_constants_are_non_empty() {
        assert!(!SKIP_DIRS.is_empty());
        assert!(!SKIP_FILE_PATTERNS.is_empty());
        assert!(!SECRET_PATTERNS.is_empty());
        assert!(!BINARY_EXTENSIONS.is_empty());
        assert!(!DOC_EXTENSIONS.is_empty());
    }

    #[test]
    fn binary_extensions_contain_no_duplicates() {
        let set: HashSet<_> = BINARY_EXTENSIONS.iter().copied().collect();
        assert_eq!(set.len(), BINARY_EXTENSIONS.len());
    }

    #[test]
    fn skip_dirs_contain_no_duplicates() {
        let set: HashSet<_> = SKIP_DIRS.iter().copied().collect();
        assert_eq!(set.len(), SKIP_DIRS.len());
    }
}
