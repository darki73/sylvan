"""Git-aware file discovery with security filtering.

Backed by ``sylvan-indexing`` (Rust) since v2.x. The Python entry
points, dataclasses, and public semantics are unchanged.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from sylvan._rust import discover_files as _rust_discover_files


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


def discover_files(
    root: Path,
    max_files: int = 5_000,
    max_file_size: int = 512_000,
    use_git: bool = True,
) -> DiscoveryResult:
    """Discover all indexable files in a directory.

    Uses ``git ls-files`` when ``root`` is a git work tree, falls back
    to a gitignore-aware walker otherwise. Applies security filters and
    skip patterns identical to previous Python behaviour.

    Args:
        root: Directory to discover files in.
        max_files: Maximum number of files to return.
        max_file_size: Maximum individual file size in bytes.
        use_git: Whether to attempt git-based discovery.

    Returns:
        A DiscoveryResult containing discovered files and skip diagnostics.
    """
    raw = _rust_discover_files(str(root), max_files, max_file_size, use_git)
    return DiscoveryResult(
        files=[
            DiscoveredFile(
                path=Path(entry["path"]),
                relative_path=entry["relative_path"],
                size=entry["size"],
                mtime=entry["mtime"],
            )
            for entry in raw["files"]
        ],
        skipped={reason: list(paths) for reason, paths in raw["skipped"].items()},
        git_head=raw["git_head"],
    )
