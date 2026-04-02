"""Git churn metrics - commit frequency, unique authors, change velocity."""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

from sylvan.git import run_git


def get_file_churn(repo_path: str, file_path: str, days: int = 90) -> dict:
    """Get git churn metrics for a file.

    Args:
        repo_path: Absolute path to the git repository root.
        file_path: Relative file path within the repo.
        days: Number of days to look back.

    Returns:
        Dict with commit_count, unique_authors, first_seen, last_modified,
        churn_per_week, and assessment.
    """
    root = Path(repo_path)
    output = run_git(
        root,
        [
            "log",
            "--follow",
            "--format=%H|%ai|%an",
            f"--since={days} days ago",
            "--",
            file_path,
        ],
        timeout=30,
    )

    if not output:
        return {
            "commit_count": 0,
            "unique_authors": 0,
            "first_seen": None,
            "last_modified": None,
            "churn_per_week": 0.0,
            "assessment": "stable",
        }

    commits = []
    authors: set[str] = set()
    for line in output.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        _hash, date_str, author = parts
        authors.add(author.strip())
        try:
            dt = datetime.fromisoformat(date_str.strip())
            commits.append(dt)
        except ValueError:
            continue

    if not commits:
        return {
            "commit_count": 0,
            "unique_authors": 0,
            "first_seen": None,
            "last_modified": None,
            "churn_per_week": 0.0,
            "assessment": "stable",
        }

    commits.sort()
    last_modified = commits[-1].isoformat()

    # Get actual file creation date (may be beyond the lookback window)
    first_output = run_git(
        root,
        ["log", "--follow", "--diff-filter=A", "--format=%ai", "--", file_path],
        timeout=15,
    )
    if first_output and first_output.strip():
        lines = first_output.strip().split("\n")
        try:
            first_seen = datetime.fromisoformat(lines[-1].strip()).isoformat()
        except ValueError:
            first_seen = commits[0].isoformat()
    else:
        first_seen = commits[0].isoformat()

    weeks = max(1, days / 7)
    churn_per_week = round(len(commits) / weeks, 2)

    if churn_per_week <= 1:
        assessment = "stable"
    elif churn_per_week <= 3:
        assessment = "active"
    else:
        assessment = "volatile"

    return {
        "commit_count": len(commits),
        "unique_authors": len(authors),
        "first_seen": first_seen,
        "last_modified": last_modified,
        "churn_per_week": churn_per_week,
        "assessment": assessment,
    }


def hotspot_score(cyclomatic: int, commit_count: int) -> float:
    """Compute hotspot score using Adam Tornhill's methodology.

    Args:
        cyclomatic: Cyclomatic complexity of the symbol.
        commit_count: Number of commits touching the file.

    Returns:
        Hotspot score: cyclomatic * log(1 + commits).
    """
    return round(cyclomatic * math.log(1 + commit_count), 2)
