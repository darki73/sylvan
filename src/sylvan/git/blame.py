"""Symbol-level git blame -- who last touched each symbol."""

import contextlib
import sqlite3
from pathlib import Path

from sylvan.git import run_git


def blame_symbol(
    root: Path,
    file_path: str,
    line_start: int,
    line_end: int,
) -> dict:
    """Get git blame for a line range (symbol-level).

    Returns the most recent commit that touched any line in the range.

    Args:
        root: Repository root directory.
        file_path: Relative path to the file.
        line_start: First line of the range (1-based).
        line_end: Last line of the range (1-based).

    Returns:
        Dictionary with ``hash``, ``author``, ``timestamp``, and ``message``
        for the most recent commit, or empty dict on failure.
    """
    output = run_git(
        root,
        [
            "blame",
            "--porcelain",
            f"-L{line_start},{line_end}",
            "--",
            file_path,
        ],
    )

    if not output:
        return {}

    commits: dict[str, dict] = {}
    current_hash = None

    for line in output.split("\n"):
        if line and len(line) >= 40 and line[:40].isalnum() and " " in line:
            parts = line.split()
            current_hash = parts[0]
            if current_hash not in commits:
                commits[current_hash] = {"hash": current_hash}
        elif current_hash and line.startswith("author "):
            commits[current_hash]["author"] = line[7:]
        elif current_hash and line.startswith("author-time "):
            commits[current_hash]["timestamp"] = int(line[12:])
        elif current_hash and line.startswith("summary "):
            commits[current_hash]["message"] = line[8:]

    if not commits:
        return {}

    most_recent = max(
        commits.values(),
        key=lambda entry: entry.get("timestamp", 0),
    )
    return most_recent


def blame_file_symbols(
    conn: sqlite3.Connection,
    root: Path,
    file_path: str,
) -> list[dict]:
    """Get blame info for all symbols in a file.

    Args:
        conn: Active SQLite connection with indexed data.
        root: Repository root directory.
        file_path: Relative path to the file.

    Returns:
        List of dicts combining symbol metadata with blame information.
    """
    symbols = conn.execute(
        """SELECT s.symbol_id, s.name, s.kind, s.line_start, s.line_end
           FROM symbols s
           JOIN files f ON f.id = s.file_id
           WHERE f.path = ?
           ORDER BY s.line_start""",
        (file_path,),
    ).fetchall()

    results = []
    for row in symbols:
        record = dict(row)
        blame = blame_symbol(root, file_path, record["line_start"], record["line_end"] or record["line_start"])
        results.append(
            {
                **record,
                "last_author": blame.get("author", ""),
                "last_commit": blame.get("hash", ""),
                "last_message": blame.get("message", ""),
            }
        )

    return results


def get_change_frequency(
    root: Path,
    file_path: str,
    max_count: int = 100,
) -> int:
    """Count how many commits have touched a file.

    Args:
        root: Repository root directory.
        file_path: Relative path to the file.
        max_count: Maximum number of commits to count.

    Returns:
        Number of commits that touched the file.
    """
    output = run_git(root, ["rev-list", "--count", f"--max-count={max_count}", "HEAD", "--", file_path], timeout=10)
    if output:
        with contextlib.suppress(ValueError):
            return int(output)
    return 0
