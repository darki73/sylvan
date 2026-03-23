"""Security filters: path traversal, file exclusion, symlink protection."""

from pathlib import Path

from sylvan.security.patterns import (
    is_binary_content,
    is_binary_extension,
    is_secret_file,
    should_skip_file,
)


def validate_path(root: Path, target: Path) -> bool:
    """Ensure target is within root (prevents path traversal).

    Args:
        root: Trusted root directory.
        target: Path to validate.

    Returns:
        ``True`` if *target* resolves to a location under *root*.
    """
    try:
        root_resolved = root.resolve()
        target_resolved = target.resolve()
        return str(target_resolved).startswith(str(root_resolved))
    except (OSError, ValueError):
        return False


def is_symlink_escape(root: Path, path: Path) -> bool:
    """Detect if a path resolves outside the root directory (symlink-safe).

    Args:
        root: Trusted root directory.
        path: Path to check.

    Returns:
        ``True`` if the path escapes the root via a symlink.
    """
    try:
        resolved = path.resolve(strict=True)
        root_resolved = root.resolve()
        return not str(resolved).startswith(str(root_resolved))
    except (OSError, ValueError):
        return True


class FileExclusionResult:
    """Result of checking whether a file should be excluded from indexing."""

    __slots__ = ("excluded", "reason")

    def __init__(self, excluded: bool, reason: str = "") -> None:
        """Create a file exclusion result.

        Args:
            excluded: Whether the file should be excluded.
            reason: Machine-readable reason string.
        """
        self.excluded = excluded
        self.reason = reason

    def __bool__(self) -> bool:
        """Return ``True`` if the file is excluded.

        Returns:
            The exclusion verdict.
        """
        return self.excluded


def should_exclude_file(
    file_path: Path,
    root: Path,
    max_file_size: int = 512_000,
    check_content: bool = True,
) -> FileExclusionResult:
    """Check all exclusion criteria for a file.

    Args:
        file_path: Absolute path to the file to check.
        root: Trusted root directory.
        max_file_size: Maximum allowed file size in bytes.
        check_content: Whether to read file content for binary detection.

    Returns:
        A :class:`FileExclusionResult` with the verdict and reason.
    """
    if not validate_path(root, file_path):
        return FileExclusionResult(True, "path_traversal")

    if is_symlink_escape(root, file_path):
        return FileExclusionResult(True, "symlink_escape")

    name = file_path.name

    if should_skip_file(name):
        return FileExclusionResult(True, "skip_pattern")

    if is_secret_file(name):
        return FileExclusionResult(True, "secret_file")

    if is_binary_extension(name):
        return FileExclusionResult(True, "binary_extension")

    try:
        size = file_path.stat().st_size
        if size > max_file_size:
            return FileExclusionResult(True, f"too_large:{size}")
        if size == 0:
            return FileExclusionResult(True, "empty")
    except OSError:
        return FileExclusionResult(True, "stat_error")

    if check_content:
        try:
            with file_path.open("rb") as f:
                head = f.read(8192)
            if is_binary_content(head):
                return FileExclusionResult(True, "binary_content")
        except OSError:
            return FileExclusionResult(True, "read_error")

    return FileExclusionResult(False)
