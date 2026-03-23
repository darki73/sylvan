"""Skip patterns, secret patterns, and binary detection for file filtering."""

import fnmatch

# Directories to always skip during indexing
SKIP_DIRS: frozenset[str] = frozenset({
    "node_modules", "vendor", ".git", "__pycache__", ".tox",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "target", "build", "dist", ".gradle", ".mvn",
    ".next", ".nuxt", ".output", ".vercel", ".turbo",
    "venv", ".venv", "env", ".env",
    ".idea", ".vscode", ".vs",
    "coverage", "htmlcov", ".nyc_output",
    ".terraform", ".pulumi",
    "Pods", "DerivedData", "xcuserdata",
    ".bundle", ".cache",
})

# File patterns to skip
SKIP_FILE_PATTERNS: frozenset[str] = frozenset({
    "*.min.js", "*.min.css", "*.map",
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "go.sum", "Cargo.lock", "poetry.lock", "uv.lock",
    "*.pb.go", "*.generated.*",
    "*.pyc", "*.pyo",
})

# Secret file patterns (filename-based)
SECRET_PATTERNS: frozenset[str] = frozenset({
    ".env", ".env.*", "*.key", "*.pem", "*.p12", "*.pfx",
    "*.keystore", "*.jks",
    "credentials.json", "service-account*.json",
    "id_rsa", "id_rsa.*", "id_ed25519", "id_ed25519.*",
    "*.secret", "*.secrets",
    ".htpasswd", ".netrc", ".pgpass",
})

# Binary file extensions
BINARY_EXTENSIONS: frozenset[str] = frozenset({
    # Executables
    ".exe", ".dll", ".so", ".dylib", ".a", ".lib", ".o", ".obj",
    # Archives
    ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar", ".jar", ".war",
    # Images
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp",
    ".tiff", ".tif", ".psd",
    # Media
    ".mp3", ".mp4", ".avi", ".mov", ".flv", ".wmv", ".wav", ".ogg", ".webm",
    # Compiled/bytecode
    ".pyc", ".pyo", ".class", ".wasm",
    # Fonts
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    # Documents (not text)
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    # Databases
    ".db", ".sqlite", ".sqlite3", ".mdb",
    # Misc binary
    ".bin", ".dat", ".pkl", ".npy", ".npz", ".h5", ".hdf5",
})

# Extensions that are documentation (exempt from broad secret matching)
DOC_EXTENSIONS: frozenset[str] = frozenset({
    ".md", ".markdown", ".rst", ".txt", ".html", ".htm",
    ".adoc", ".asciidoc", ".ipynb", ".xml", ".json", ".yaml", ".yml",
    ".toml", ".cfg", ".ini", ".conf",
})


def is_secret_file(filename: str) -> bool:
    """Check if a filename matches secret patterns.

    Args:
        filename: File name (not path) to check.

    Returns:
        ``True`` if the file matches a known secret pattern.
    """
    name_lower = filename.lower()
    for pattern in SECRET_PATTERNS:
        if fnmatch.fnmatch(name_lower, pattern.lower()):
            ext = "." + name_lower.rsplit(".", 1)[-1] if "." in name_lower else ""
            if "*secret*" in pattern and ext in DOC_EXTENSIONS:
                continue
            return True
    return False


def is_binary_extension(filename: str) -> bool:
    """Check if a file has a binary extension.

    Args:
        filename: File name (not path) to check.

    Returns:
        ``True`` if the file extension is in the binary set.
    """
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in BINARY_EXTENSIONS


def is_binary_content(data: bytes, check_size: int = 8192) -> bool:
    """Check for null bytes in the first N bytes (heuristic binary detection).

    Args:
        data: Raw file content bytes.
        check_size: Number of leading bytes to inspect.

    Returns:
        ``True`` if a null byte is found within the check window.
    """
    return b"\x00" in data[:check_size]


def should_skip_dir(dirname: str) -> bool:
    """Check if a directory should be skipped entirely.

    Args:
        dirname: Directory name (not path) to check.

    Returns:
        ``True`` if the directory is in the skip set or starts with ``.``.
    """
    return dirname in SKIP_DIRS or dirname.startswith(".")


def should_skip_file(filename: str) -> bool:
    """Check if a file matches skip patterns.

    Args:
        filename: File name (not path) to check.

    Returns:
        ``True`` if the file matches a skip pattern.
    """
    name_lower = filename.lower()
    return any(fnmatch.fnmatch(name_lower, pattern.lower()) for pattern in SKIP_FILE_PATTERNS)
