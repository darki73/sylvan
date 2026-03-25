"""Post-indexing import specifier-to-file resolution.

Converts import specifiers (e.g. ``sylvan.search.embeddings``, ``./utils``)
into candidate file paths and matches them against the repo's indexed files
to populate ``resolved_file_id`` in the ``file_imports`` table.
"""

from __future__ import annotations

import posixpath

from sylvan.logging import get_logger

logger = get_logger(__name__)

# Go standard library packages (single-segment, no dots).
_GO_STDLIB = frozenset(
    {
        "archive",
        "bufio",
        "builtin",
        "bytes",
        "cmp",
        "compress",
        "container",
        "context",
        "crypto",
        "database",
        "debug",
        "embed",
        "encoding",
        "errors",
        "expvar",
        "flag",
        "fmt",
        "go",
        "hash",
        "html",
        "image",
        "index",
        "io",
        "iter",
        "log",
        "maps",
        "math",
        "mime",
        "net",
        "os",
        "path",
        "plugin",
        "reflect",
        "regexp",
        "runtime",
        "slices",
        "sort",
        "strconv",
        "strings",
        "structs",
        "sync",
        "syscall",
        "testing",
        "text",
        "time",
        "unicode",
        "unsafe",
    }
)

# Common C/C++ system headers (angle-bracket includes to skip).
_C_SYSTEM_HEADERS = frozenset(
    {
        "stdio.h",
        "stdlib.h",
        "string.h",
        "math.h",
        "time.h",
        "assert.h",
        "ctype.h",
        "errno.h",
        "float.h",
        "limits.h",
        "locale.h",
        "setjmp.h",
        "signal.h",
        "stdarg.h",
        "stddef.h",
        "stdint.h",
        "stdbool.h",
        "iostream",
        "fstream",
        "sstream",
        "vector",
        "string",
        "map",
        "set",
        "unordered_map",
        "unordered_set",
        "algorithm",
        "memory",
        "functional",
        "utility",
        "numeric",
        "cassert",
        "cmath",
        "cstdio",
        "cstdlib",
        "cstring",
        "ctime",
        "climits",
        "cfloat",
    }
)


async def resolve_imports(repo_id: int) -> int:
    """Resolve file_imports specifiers to file IDs within a repo.

    Loads all indexed file paths for the repo, then for each unresolved
    import generates language-aware candidate paths and looks them up.
    Stale resolutions pointing to deleted/moved files are invalidated first.

    Args:
        repo_id: Repository to resolve imports for.

    Returns:
        Number of imports resolved.
    """
    from sylvan.config import get_config
    from sylvan.database.orm import FileRecord
    from sylvan.database.orm.runtime.connection_manager import get_backend

    backend = get_backend()

    # Invalidate resolutions pointing to deleted/moved files.
    await backend.execute(
        """UPDATE file_imports SET resolved_file_id = NULL
           WHERE resolved_file_id IS NOT NULL
           AND resolved_file_id NOT IN (SELECT id FROM files WHERE repo_id = ?)""",
        [repo_id],
    )

    # Build path -> file_id lookup for this repo.
    source_roots = get_config().indexing.source_roots
    files = await FileRecord.where(repo_id=repo_id).select("id", "path").get()
    path_to_id: dict[str, int] = {}
    for f in files:
        path_to_id[f.path] = f.id
        # Also index without configured source-root prefixes for package resolution.
        for prefix in source_roots:
            if prefix and f.path.startswith(prefix):
                path_to_id[f.path[len(prefix) :]] = f.id

    # Get all unresolved imports with their source file info.
    rows = await backend.fetch_all(
        """SELECT fi.id, fi.specifier, fi.file_id, f.path, f.language
           FROM file_imports fi
           JOIN files f ON f.id = fi.file_id
           WHERE fi.resolved_file_id IS NULL
           AND f.repo_id = ?""",
        [repo_id],
    )

    resolved_count = 0
    updates: list[tuple[int, int]] = []  # (resolved_file_id, import_id)

    for row in rows:
        specifier = row["specifier"]
        language = row["language"]
        source_path = row["path"]

        candidates = _generate_candidates(specifier, language, source_path)

        for candidate in candidates:
            file_id = path_to_id.get(candidate)
            if file_id is not None:
                updates.append((file_id, row["id"]))
                resolved_count += 1
                break

    # Batch update inside a single transaction to avoid per-statement round-trips.
    if updates:
        async with backend.transaction():
            for file_id, import_id in updates:
                await backend.execute(
                    "UPDATE file_imports SET resolved_file_id = ? WHERE id = ?",
                    [file_id, import_id],
                )

    logger.info(
        "imports_resolved",
        repo_id=repo_id,
        total=len(rows),
        resolved=resolved_count,
    )
    return resolved_count


def _generate_candidates(
    specifier: str,
    language: str,
    source_path: str,
) -> list[str]:
    """Generate candidate file paths from an import specifier.

    Args:
        specifier: The raw import specifier string.
        language: Programming language of the importing file.
        source_path: Relative path of the file containing the import.

    Returns:
        Ordered list of candidate file paths to try matching.
    """
    match language:
        case "python":
            return _python_candidates(specifier, source_path)
        case "javascript" | "typescript" | "tsx" | "jsx":
            return _js_candidates(specifier, source_path)
        case "go":
            return _go_candidates(specifier, source_path)
        case "rust":
            return _rust_candidates(specifier, source_path)
        case "java" | "kotlin":
            return _java_candidates(specifier, source_path, language)
        case "c" | "cpp":
            return _c_candidates(specifier, source_path)
        case "ruby":
            return _ruby_candidates(specifier, source_path)
        case "php":
            return _php_candidates(specifier, source_path)
        case "c_sharp":
            return _csharp_candidates(specifier, source_path)
        case _:
            return []


def _python_candidates(specifier: str, source_path: str) -> list[str]:
    """Generate candidate paths for a Python import specifier.

    Args:
        specifier: Python import specifier (e.g. ``sylvan.search.embeddings``).
        source_path: Relative path of the importing file.

    Returns:
        Candidate file paths.
    """
    # Handle relative imports (leading dots).
    if specifier.startswith("."):
        return _python_relative_candidates(specifier, source_path)

    # Bare imports (no dots) -- could be a local namespace package.
    if "." not in specifier:
        candidates = []
        for prefix in ("", "src/", "lib/"):
            candidates.append(f"{prefix}{specifier}/__init__.py")
            candidates.append(f"{prefix}{specifier}.py")
        return _dedupe(candidates)

    path_base = specifier.replace(".", "/")

    candidates: list[str] = []
    for prefix in ("", "src/", "lib/"):
        candidates.append(f"{prefix}{path_base}.py")
        candidates.append(f"{prefix}{path_base}/__init__.py")

    return _dedupe(candidates)


def _python_relative_candidates(specifier: str, source_path: str) -> list[str]:
    """Generate candidates for Python relative imports.

    Args:
        specifier: A relative specifier like ``.utils`` or ``..config``.
        source_path: Relative path of the importing file.

    Returns:
        Candidate file paths.
    """
    # Count leading dots.
    dots = 0
    for ch in specifier:
        if ch == ".":
            dots += 1
        else:
            break

    remainder = specifier[dots:]
    source_dir = posixpath.dirname(source_path)

    # Each dot beyond the first goes up one directory.
    base = source_dir
    for _ in range(dots - 1):
        base = posixpath.dirname(base)

    if remainder:
        path_base = posixpath.join(base, remainder.replace(".", "/"))
    else:
        path_base = base

    path_base = posixpath.normpath(path_base)

    return [
        f"{path_base}.py",
        f"{path_base}/__init__.py",
    ]


def _js_candidates(specifier: str, source_path: str) -> list[str]:
    """Generate candidate paths for a JS/TS import specifier.

    Args:
        specifier: Import specifier (e.g. ``./utils``, ``react``).
        source_path: Relative path of the importing file.

    Returns:
        Candidate file paths.
    """
    # Skip bare specifiers (npm packages).
    if not specifier.startswith(".") and not specifier.startswith("/"):
        return []

    source_dir = posixpath.dirname(source_path)
    resolved = posixpath.normpath(posixpath.join(source_dir, specifier))

    candidates = [resolved]

    # If the specifier already has a file extension, just use as-is.
    if _has_js_extension(specifier):
        return candidates

    for ext in (".js", ".ts", ".tsx", ".jsx", ".mjs", ".vue"):
        candidates.append(f"{resolved}{ext}")
    for index in ("/index.js", "/index.ts", "/index.tsx"):
        candidates.append(f"{resolved}{index}")

    return candidates


def _has_js_extension(specifier: str) -> bool:
    """Check if a specifier already has a JS/TS file extension.

    Args:
        specifier: The import specifier.

    Returns:
        True if it ends with a known JS/TS extension.
    """
    return specifier.endswith(
        (".js", ".ts", ".tsx", ".jsx", ".mjs", ".vue", ".svelte"),
    )


def _go_candidates(specifier: str, source_path: str) -> list[str]:
    """Generate candidate paths for a Go import specifier.

    Args:
        specifier: Go import path (e.g. ``github.com/org/repo/pkg``).
        source_path: Relative path of the importing file.

    Returns:
        Candidate file paths.
    """
    # Skip stdlib (single-segment, no dots).
    if "/" not in specifier:
        return []

    first_segment = specifier.split("/", maxsplit=1)[0]
    if first_segment in _GO_STDLIB:
        return []

    # Try matching the last N segments against file directories.
    parts = specifier.split("/")
    candidates: list[str] = []

    # Try progressively shorter suffixes.
    for i in range(len(parts)):
        suffix = "/".join(parts[i:])
        candidates.append(suffix)

    return candidates


def _rust_candidates(specifier: str, source_path: str) -> list[str]:
    """Generate candidate paths for a Rust use specifier.

    Args:
        specifier: Rust use path (e.g. ``crate::module::item``).
        source_path: Relative path of the importing file.

    Returns:
        Candidate file paths.
    """
    # Skip std and external crates.
    if specifier.startswith("std::") or specifier.startswith("core::"):
        return []

    if specifier.startswith("crate::"):
        remainder = specifier[len("crate::") :]
        # Remove the last segment (it's typically the item, not a module).
        parts = remainder.split("::")
        if len(parts) > 1:
            module_path = "/".join(parts[:-1])
        else:
            module_path = parts[0]

        candidates = [
            f"src/{module_path}.rs",
            f"src/{module_path}/mod.rs",
            f"{module_path}.rs",
            f"{module_path}/mod.rs",
        ]
        return candidates

    # For other paths, try converting :: to / and matching.
    parts = specifier.split("::")
    if len(parts) > 1:
        module_path = "/".join(parts[:-1])
        return [
            f"src/{module_path}.rs",
            f"src/{module_path}/mod.rs",
            f"{module_path}.rs",
        ]

    return []


def _java_candidates(
    specifier: str,
    source_path: str,
    language: str,
) -> list[str]:
    """Generate candidate paths for a Java/Kotlin import specifier.

    Args:
        specifier: Java import path (e.g. ``com.example.util``).
        source_path: Relative path of the importing file.
        language: Either ``java`` or ``kotlin``.

    Returns:
        Candidate file paths.
    """
    path_base = specifier.replace(".", "/")
    ext = ".kt" if language == "kotlin" else ".java"

    candidates: list[str] = []
    for prefix in ("", "src/main/java/", "src/main/kotlin/", "src/"):
        candidates.append(f"{prefix}{path_base}{ext}")

    return candidates


def _c_candidates(specifier: str, source_path: str) -> list[str]:
    """Generate candidate paths for a C/C++ include specifier.

    Args:
        specifier: Include path (e.g. ``myheader.h``).
        source_path: Relative path of the importing file.

    Returns:
        Candidate file paths.
    """
    # Skip system headers.
    if specifier in _C_SYSTEM_HEADERS:
        return []

    source_dir = posixpath.dirname(source_path)

    candidates: list[str] = []
    # Try relative to the importing file first.
    if source_dir:
        candidates.append(posixpath.normpath(posixpath.join(source_dir, specifier)))
    # Try project-relative.
    candidates.append(specifier)
    for prefix in ("include/", "src/"):
        candidates.append(f"{prefix}{specifier}")

    return _dedupe(candidates)


def _ruby_candidates(specifier: str, source_path: str) -> list[str]:
    """Generate candidate paths for a Ruby require specifier.

    Args:
        specifier: Ruby require path (e.g. ``../lib/foo``).
        source_path: Relative path of the importing file.

    Returns:
        Candidate file paths.
    """
    # Relative paths.
    if specifier.startswith("."):
        source_dir = posixpath.dirname(source_path)
        resolved = posixpath.normpath(posixpath.join(source_dir, specifier))
        candidates = [resolved]
        if not resolved.endswith(".rb"):
            candidates.append(f"{resolved}.rb")
        return candidates

    # Absolute-style require.
    candidates = [specifier]
    if not specifier.endswith(".rb"):
        candidates.append(f"{specifier}.rb")
    for prefix in ("lib/", "app/"):
        candidates.append(f"{prefix}{specifier}")
        if not specifier.endswith(".rb"):
            candidates.append(f"{prefix}{specifier}.rb")

    return candidates


def _php_candidates(specifier: str, source_path: str) -> list[str]:
    """Generate candidate paths for a PHP use/require specifier.

    Args:
        specifier: PHP namespace path (e.g. ``App\\Models\\User``).
        source_path: Relative path of the importing file.

    Returns:
        Candidate file paths.
    """
    # Convert backslashes to forward slashes.
    path_base = specifier.replace("\\", "/")

    candidates = [
        f"{path_base}.php",
        f"src/{path_base}.php",
        f"app/{path_base}.php",
    ]
    return candidates


def _csharp_candidates(specifier: str, source_path: str) -> list[str]:
    """Generate candidate paths for a C# using specifier.

    Args:
        specifier: C# namespace (e.g. ``MyApp.Models``).
        source_path: Relative path of the importing file.

    Returns:
        Candidate file paths.
    """
    path_base = specifier.replace(".", "/")

    candidates = [
        f"{path_base}.cs",
        f"src/{path_base}.cs",
    ]
    return candidates


async def resolve_cross_repo_imports(repo_ids: list[int]) -> int:
    """Resolve imports across multiple repos in a workspace.

    Loads file paths from ALL repos in the list, then resolves any remaining
    NULL resolved_file_id imports by looking across repos. Uses the same
    language-aware candidate generation as single-repo resolution.

    This should only be called from workspace tools, not from regular indexing.

    Args:
        repo_ids: List of repository database IDs to resolve across.

    Returns:
        Number of cross-repo imports resolved.
    """
    from sylvan.config import get_config
    from sylvan.database.orm.runtime.connection_manager import get_backend

    backend = get_backend()
    source_roots = get_config().indexing.source_roots

    # Build path -> file_id lookup across ALL repos.
    placeholder_list = ",".join("?" * len(repo_ids))
    all_files = await backend.fetch_all(
        f"SELECT id, path FROM files WHERE repo_id IN ({placeholder_list})",
        repo_ids,
    )
    path_to_id: dict[str, int] = {}
    for row in all_files:
        path_to_id[row["path"]] = row["id"]
        for prefix in source_roots:
            if prefix and row["path"].startswith(prefix):
                path_to_id[row["path"][len(prefix) :]] = row["id"]

    # Get all unresolved imports across these repos.
    rows = await backend.fetch_all(
        f"""SELECT fi.id, fi.specifier, fi.file_id, f.path, f.language
           FROM file_imports fi
           JOIN files f ON f.id = fi.file_id
           WHERE fi.resolved_file_id IS NULL
           AND f.repo_id IN ({placeholder_list})""",
        repo_ids,
    )

    resolved_count = 0
    updates: list[tuple[int, int]] = []

    for row in rows:
        candidates = _generate_candidates(row["specifier"], row["language"], row["path"])
        for candidate in candidates:
            file_id = path_to_id.get(candidate)
            if file_id is not None:
                updates.append((file_id, row["id"]))
                resolved_count += 1
                break

    if updates:
        async with backend.transaction():
            for file_id, import_id in updates:
                await backend.execute(
                    "UPDATE file_imports SET resolved_file_id = ? WHERE id = ?",
                    [file_id, import_id],
                )

    logger.info(
        "cross_repo_imports_resolved",
        repo_ids=repo_ids,
        total=len(rows),
        resolved=resolved_count,
    )
    return resolved_count


def _dedupe(candidates: list[str]) -> list[str]:
    """Remove duplicates while preserving order.

    Args:
        candidates: List of candidate paths.

    Returns:
        Deduplicated list.
    """
    seen: set[str] = set()
    result: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            result.append(c)
    return result
