"""Tests for sylvan.git.blame — blame parsing and change frequency."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sylvan.git.blame import blame_symbol, get_change_frequency

SAMPLE_PORCELAIN = """\
abc123def456abc123def456abc123def456abc12345 10 10 1
author Alice
author-mail <alice@example.com>
author-time 1700000000
author-tz +0000
committer Alice
committer-mail <alice@example.com>
committer-time 1700000000
committer-tz +0000
summary Fix the widget
filename src/widget.py
\tdef widget():
def456abc123def456abc123def456abc123def45678 11 11 1
author Bob
author-mail <bob@example.com>
author-time 1700000100
author-tz +0000
committer Bob
committer-mail <bob@example.com>
committer-time 1700000100
committer-tz +0000
summary Refactor widget internals
filename src/widget.py
\t    pass
"""


class TestBlameSymbol:
    def test_parses_most_recent_commit(self):
        with patch("sylvan.git.blame.run_git", return_value=SAMPLE_PORCELAIN):
            result = blame_symbol(Path("/repo"), "src/widget.py", 10, 11)

        assert result["author"] == "Bob"
        assert result["message"] == "Refactor widget internals"
        assert result["timestamp"] == 1700000100

    def test_returns_empty_on_none_output(self):
        with patch("sylvan.git.blame.run_git", return_value=None):
            result = blame_symbol(Path("/repo"), "src/widget.py", 1, 5)

        assert result == {}

    def test_returns_empty_on_empty_output(self):
        with patch("sylvan.git.blame.run_git", return_value=""):
            result = blame_symbol(Path("/repo"), "src/widget.py", 1, 5)

        assert result == {}

    def test_single_commit(self):
        single = (
            "aabbccdd00112233445566778899aabbccddeeff 1 1 1\n"
            "author Carol\n"
            "author-time 1600000000\n"
            "summary Initial commit\n"
            "filename foo.py\n"
            "\tprint('hello')\n"
        )
        with patch("sylvan.git.blame.run_git", return_value=single):
            result = blame_symbol(Path("/repo"), "foo.py", 1, 1)

        assert result["author"] == "Carol"
        assert result["hash"] == "aabbccdd00112233445566778899aabbccddeeff"
        assert result["message"] == "Initial commit"

    def test_no_parseable_lines(self):
        """If output has no valid commit lines, return empty dict."""
        with patch("sylvan.git.blame.run_git", return_value="not a blame line\ngarbage"):
            result = blame_symbol(Path("/repo"), "file.py", 1, 1)

        assert result == {}


class TestGetChangeFrequency:
    def test_returns_count(self):
        with patch("sylvan.git.blame.run_git", return_value="42"):
            result = get_change_frequency(Path("/repo"), "src/file.py")

        assert result == 42

    def test_returns_zero_on_none(self):
        with patch("sylvan.git.blame.run_git", return_value=None):
            result = get_change_frequency(Path("/repo"), "src/file.py")

        assert result == 0

    def test_returns_zero_on_non_numeric(self):
        with patch("sylvan.git.blame.run_git", return_value="not-a-number"):
            result = get_change_frequency(Path("/repo"), "src/file.py")

        assert result == 0

    def test_returns_zero_on_empty_string(self):
        with patch("sylvan.git.blame.run_git", return_value=""):
            result = get_change_frequency(Path("/repo"), "src/file.py")

        assert result == 0
