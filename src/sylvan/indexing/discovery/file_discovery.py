"""Git-aware file discovery with security filtering."""

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path

import pathspec

from sylvan.git import run_git
from sylvan.security.filters import should_exclude_file
from sylvan.security.patterns import should_skip_dir


def _load_gitignore(root: Path) -> pathspec.PathSpec | None:
    """Load .gitignore patterns from root.

    Args:
        root: Repository root directory.

    Returns:
        Parsed PathSpec if .gitignore exists, None otherwise.
    """
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        return None
    try:
        with gitignore.open(encoding="utf-8", errors="ignore") as f:
            return pathspec.PathSpec.from_lines("gitwildmatch", f)
    except Exception:
        return None


def _is_git_repo(root: Path) -> bool:
    """Fast check: is this directory inside a git work tree?

    Args:
        root: Directory to check.

    Returns:
        True if a .git directory is found in any ancestor.
    """
    p = root
    for _ in range(50):
        if (p / ".git").exists():
            return True
        parent = p.parent
        if parent == p:
            break
        p = parent
    return False


def _git_ls_files(root: Path) -> list[str] | None:
    """Use git ls-files to get tracked files (fastest method for git repos).

    Args:
        root: Repository root directory.

    Returns:
        List of relative file paths, or None if git is unavailable.
    """
    if not _is_git_repo(root):
        return None
    output = run_git(root, ["ls-files", "--cached", "--others", "--exclude-standard"], timeout=30)
    if output is not None:
        return [f for f in output.split("\n") if f]
    return None


def _get_git_head(root: Path) -> str | None:
    """Get the current HEAD commit hash.

    Args:
        root: Repository root directory.

    Returns:
        The HEAD commit hash, or None if not a git repo.
    """
    if not _is_git_repo(root):
        return None
    return run_git(root, ["rev-parse", "HEAD"], timeout=10)


def hash_content(content: bytes) -> str:
    """SHA-256 hash of file content.

    Args:
        content: Raw file bytes.

    Returns:
        Hex-encoded SHA-256 digest.
    """
    return hashlib.sha256(content).hexdigest()


@dataclass(slots=True, frozen=True)
class DiscoveredFile:
    """A file discovered for indexing.

    Attributes:
        path: Absolute path to the file.
        relative_path: Path relative to the repository root.
        size: File size in bytes.
        mtime: File modification time as a Unix timestamp.
    """

    path: Path
    relative_path: str
    size: int
    mtime: float


@dataclass
class DiscoveryResult:
    """Result of file discovery, including diagnostics.

    Attributes:
        files: Files accepted for indexing.
        skipped: Mapping of skip reasons to lists of skipped file paths.
        git_head: Git HEAD commit hash at the time of discovery.
    """

    files: list[DiscoveredFile] = field(default_factory=list)
    skipped: dict[str, list[str]] = field(default_factory=dict)
    git_head: str | None = None

    @property
    def total_found(self) -> int:
        """Return the number of accepted files.

        Returns:
            Count of discovered files.
        """
        return len(self.files)

    @property
    def total_skipped(self) -> int:
        """Return the total count of skipped files across all reasons.

        Returns:
            Sum of all skipped file counts.
        """
        return sum(len(v) for v in self.skipped.values())

    def add_skipped(self, path: str, reason: str) -> None:
        """Record a skipped file under the given reason category.

        Args:
            path: Relative path of the skipped file.
            reason: Category describing why the file was skipped.
        """
        self.skipped.setdefault(reason, []).append(path)


def _has_skippable_directory(rel_path: str) -> bool:
    """Return True if any directory component in the path should be skipped.

    Args:
        rel_path: Relative file path to check.

    Returns:
        True if a directory component matches skip patterns.
    """
    parts = Path(rel_path).parts
    return any(should_skip_dir(part) for part in parts[:-1])


def _discover_via_git(
    root: Path, git_files: list[str], max_files: int, max_file_size: int, result: DiscoveryResult
) -> None:
    """Populate discovery result using git ls-files output.

    Args:
        root: Repository root directory.
        git_files: List of relative file paths from git ls-files.
        max_files: Maximum number of files to discover.
        max_file_size: Maximum file size in bytes.
        result: Discovery result accumulator to populate.
    """
    for rel_path in git_files:
        if len(result.files) >= max_files:
            result.add_skipped(rel_path, "max_files_reached")
            continue

        full_path = root / rel_path

        if _has_skippable_directory(rel_path):
            result.add_skipped(rel_path, "skip_dir")
            continue

        exclusion = should_exclude_file(full_path, root, max_file_size)
        if exclusion:
            result.add_skipped(rel_path, exclusion.reason)
            continue

        try:
            stat = full_path.stat()
            result.files.append(
                DiscoveredFile(
                    path=full_path,
                    relative_path=rel_path.replace("\\", "/"),
                    size=stat.st_size,
                    mtime=stat.st_mtime,
                )
            )
        except OSError:
            result.add_skipped(rel_path, "stat_error")


def _discover_via_walk(root: Path, max_files: int, max_file_size: int, result: DiscoveryResult) -> None:
    """Populate discovery result using os.walk with gitignore filtering.

    Args:
        root: Repository root directory.
        max_files: Maximum number of files to discover.
        max_file_size: Maximum file size in bytes.
        result: Discovery result accumulator to populate.
    """
    gitignore_spec = _load_gitignore(root)

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if not should_skip_dir(d)]

        for filename in filenames:
            full_path = Path(dirpath) / filename
            rel_path = str(full_path.relative_to(root)).replace("\\", "/")

            if len(result.files) >= max_files:
                result.add_skipped(rel_path, "max_files_reached")
                continue

            if gitignore_spec and gitignore_spec.match_file(rel_path):
                result.add_skipped(rel_path, "gitignore")
                continue

            exclusion = should_exclude_file(full_path, root, max_file_size)
            if exclusion:
                result.add_skipped(rel_path, exclusion.reason)
                continue

            try:
                stat = full_path.stat()
                result.files.append(
                    DiscoveredFile(
                        path=full_path,
                        relative_path=rel_path,
                        size=stat.st_size,
                        mtime=stat.st_mtime,
                    )
                )
            except OSError:
                result.add_skipped(rel_path, "stat_error")


def discover_files(
    root: Path,
    max_files: int = 5_000,
    max_file_size: int = 512_000,
    use_git: bool = True,
) -> DiscoveryResult:
    """Discover all indexable files in a directory.

    Tries git ls-files first for speed, falls back to os.walk.
    Applies security filters and skip patterns.

    Args:
        root: Directory to discover files in.
        max_files: Maximum number of files to return.
        max_file_size: Maximum individual file size in bytes.
        use_git: Whether to attempt git-based discovery.

    Returns:
        A DiscoveryResult containing discovered files and skip diagnostics.
    """
    result = DiscoveryResult()
    root = root.resolve()

    if use_git:
        result.git_head = _get_git_head(root)

    git_files = _git_ls_files(root) if use_git else None

    if git_files is not None:
        _discover_via_git(root, git_files, max_files, max_file_size, result)
    else:
        _discover_via_walk(root, max_files, max_file_size, result)

    return result
