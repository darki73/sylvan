"""Tests for sylvan.git.diff — changed files, branch diff, commit log."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sylvan.git.diff import get_branch_diff, get_changed_files, get_commit_log


class TestGetChangedFiles:
    def test_since_commit(self):
        output = "src/foo.py\nsrc/bar.py\n"
        with patch("sylvan.git.diff.run_git", return_value=output) as mock:
            result = get_changed_files(Path("/repo"), since_commit="abc123")

        assert result == ["src/foo.py", "src/bar.py"]
        args = mock.call_args[0][1]
        assert "abc123" in args
        assert "HEAD" in args

    def test_uncommitted_changes(self):
        output = "file1.py\nfile2.py\n"
        with patch("sylvan.git.diff.run_git", return_value=output) as mock:
            result = get_changed_files(Path("/repo"))

        assert result == ["file1.py", "file2.py"]
        args = mock.call_args[0][1]
        assert "HEAD" in args

    def test_returns_empty_on_none(self):
        with patch("sylvan.git.diff.run_git", return_value=None):
            result = get_changed_files(Path("/repo"))

        assert result == []

    def test_returns_empty_on_empty(self):
        with patch("sylvan.git.diff.run_git", return_value=""):
            result = get_changed_files(Path("/repo"))

        assert result == []

    def test_filters_directory_traversal(self):
        output = "good.py\n../etc/passwd\nnormal/file.py\n"
        with patch("sylvan.git.diff.run_git", return_value=output):
            result = get_changed_files(Path("/repo"))

        assert "good.py" in result
        assert "normal/file.py" in result
        assert "../etc/passwd" not in result

    def test_filters_empty_lines(self):
        output = "file1.py\n\nfile2.py\n\n"
        with patch("sylvan.git.diff.run_git", return_value=output):
            result = get_changed_files(Path("/repo"))

        assert result == ["file1.py", "file2.py"]


class TestGetBranchDiff:
    def test_default_head(self):
        output = "changed.py\n"
        with patch("sylvan.git.diff.run_git", return_value=output) as mock:
            result = get_branch_diff(Path("/repo"), base_branch="main")

        assert result == ["changed.py"]
        args = mock.call_args[0][1]
        assert "main...HEAD" in args

    def test_explicit_head_branch(self):
        output = "a.py\nb.py\n"
        with patch("sylvan.git.diff.run_git", return_value=output) as mock:
            result = get_branch_diff(Path("/repo"), base_branch="main", head_branch="feature")

        assert result == ["a.py", "b.py"]
        args = mock.call_args[0][1]
        assert "main...feature" in args

    def test_returns_empty_on_none(self):
        with patch("sylvan.git.diff.run_git", return_value=None):
            result = get_branch_diff(Path("/repo"))

        assert result == []

    def test_filters_traversal(self):
        output = "ok.py\n../../bad.py\n"
        with patch("sylvan.git.diff.run_git", return_value=output):
            result = get_branch_diff(Path("/repo"))

        assert "ok.py" in result
        assert len(result) == 1


class TestGetCommitLog:
    def test_parses_log_output(self):
        output = (
            "abc123|Alice|2024-01-15T10:30:00+00:00|Fix bug in parser\n"
            "def456|Bob|2024-01-14T09:00:00+00:00|Add new feature\n"
        )
        with patch("sylvan.git.diff.run_git", return_value=output):
            result = get_commit_log(Path("/repo"))

        assert len(result) == 2
        assert result[0]["hash"] == "abc123"
        assert result[0]["author"] == "Alice"
        assert result[0]["date"] == "2024-01-15T10:30:00+00:00"
        assert result[0]["message"] == "Fix bug in parser"
        assert result[1]["hash"] == "def456"

    def test_returns_empty_on_none(self):
        with patch("sylvan.git.diff.run_git", return_value=None):
            result = get_commit_log(Path("/repo"))

        assert result == []

    def test_skips_malformed_lines(self):
        output = "abc123|Alice|2024-01-15T10:30:00+00:00|Good line\nmalformed line\n"
        with patch("sylvan.git.diff.run_git", return_value=output):
            result = get_commit_log(Path("/repo"))

        assert len(result) == 1
        assert result[0]["hash"] == "abc123"

    def test_skips_lines_without_pipe(self):
        output = "no pipes here\n"
        with patch("sylvan.git.diff.run_git", return_value=output):
            result = get_commit_log(Path("/repo"))

        assert result == []

    def test_file_path_filter(self):
        output = "abc123|Alice|2024-01-15|Fix\n"
        with patch("sylvan.git.diff.run_git", return_value=output) as mock:
            get_commit_log(Path("/repo"), file_path="src/main.py")

        args = mock.call_args[0][1]
        assert "--" in args
        assert "src/main.py" in args

    def test_max_count(self):
        output = "abc123|Alice|2024-01-15|Fix\n"
        with patch("sylvan.git.diff.run_git", return_value=output) as mock:
            get_commit_log(Path("/repo"), max_count=5)

        args = mock.call_args[0][1]
        assert "--max-count=5" in args

    def test_message_with_pipes(self):
        """Pipe chars in the commit message should be preserved (split max 3)."""
        output = "abc123|Alice|2024-01-15|Fix: use a|b pattern\n"
        with patch("sylvan.git.diff.run_git", return_value=output):
            result = get_commit_log(Path("/repo"))

        assert len(result) == 1
        assert result[0]["message"] == "Fix: use a|b pattern"
