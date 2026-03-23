"""Git diff integration -- changed files, branch comparison."""

from pathlib import Path

from sylvan.git import run_git


def get_changed_files(
    root: Path,
    since_commit: str | None = None,
) -> list[str]:
    """Get list of files changed since a commit (or since last index).

    If *since_commit* is ``None``, returns uncommitted changes
    (staged + unstaged).

    Args:
        root: Repository root directory.
        since_commit: Commit hash to diff against, or ``None`` for
            uncommitted changes.

    Returns:
        List of relative file paths that changed.
    """
    if since_commit:
        output = run_git(root, ["diff", "--name-only", since_commit, "HEAD"])
    else:
        output = run_git(root, ["diff", "--name-only", "HEAD"])

    if output:
        return [f for f in output.split("\n") if f and ".." not in f.split("/")]
    return []


def get_branch_diff(
    root: Path,
    base_branch: str = "main",
    head_branch: str | None = None,
) -> list[str]:
    """Get files changed between two branches.

    Args:
        root: Repository root directory.
        base_branch: Branch to compare against.
        head_branch: Branch to compare from (defaults to ``HEAD``).

    Returns:
        List of relative file paths that differ.
    """
    ref = f"{base_branch}...{head_branch}" if head_branch else f"{base_branch}...HEAD"
    output = run_git(root, ["diff", "--name-only", ref])
    if output:
        return [f for f in output.split("\n") if f and ".." not in f.split("/")]
    return []


def get_commit_log(
    root: Path,
    file_path: str | None = None,
    max_count: int = 20,
) -> list[dict]:
    """Get recent commit log, optionally filtered to a file.

    Args:
        root: Repository root directory.
        file_path: Optional file path to filter commits by.
        max_count: Maximum number of commits to return.

    Returns:
        List of dicts with ``hash``, ``author``, ``date``, and ``message``.
    """
    cmd = ["log", f"--max-count={max_count}", "--format=%H|%an|%aI|%s"]
    if file_path:
        cmd.extend(["--", file_path])

    output = run_git(root, cmd)
    if not output:
        return []

    commits = []
    for line in output.split("\n"):
        if "|" not in line:
            continue
        parts = line.split("|", 3)
        if len(parts) == 4:
            commits.append({
                "hash": parts[0],
                "author": parts[1],
                "date": parts[2],
                "message": parts[3],
            })
    return commits
