"""Tests for library source fetcher.

Covers:
- sylvan.libraries.source_fetcher (_validate_tag, get_library_path,
  remove_library_source, fetch_source, _download_github_tarball)
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from sylvan.libraries.source_fetcher import (
    _validate_tag,
    get_library_path,
    remove_library_source,
)

# ---------------------------------------------------------------------------
# _validate_tag
# ---------------------------------------------------------------------------

class TestValidateTag:
    def test_simple_version(self):
        assert _validate_tag("v1.2.3") == "v1.2.3"

    def test_version_without_v(self):
        assert _validate_tag("1.2.3") == "1.2.3"

    def test_tag_with_slash(self):
        assert _validate_tag("release/1.0") == "release/1.0"

    def test_tag_with_dots_and_dashes(self):
        assert _validate_tag("v1.0.0-rc1") == "v1.0.0-rc1"

    def test_tag_with_underscore(self):
        assert _validate_tag("v1_0_0") == "v1_0_0"

    def test_leading_dash_raises(self):
        with pytest.raises(ValueError, match="Invalid git tag"):
            _validate_tag("-v1.0.0")

    def test_special_chars_raises(self):
        with pytest.raises(ValueError, match="Invalid git tag"):
            _validate_tag("v1.0.0; rm -rf /")

    def test_spaces_raises(self):
        with pytest.raises(ValueError, match="Invalid git tag"):
            _validate_tag("v1 0 0")

    def test_backtick_raises(self):
        with pytest.raises(ValueError, match="Invalid git tag"):
            _validate_tag("`whoami`")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="Invalid git tag"):
            _validate_tag("")


# ---------------------------------------------------------------------------
# get_library_path
# ---------------------------------------------------------------------------

class TestGetLibraryPath:
    def test_basic_path(self, tmp_path):
        os.environ["SYLVAN_HOME"] = str(tmp_path)
        from sylvan.config import reset_config
        reset_config()

        try:
            path = get_library_path("pip", "django", "4.2")
            assert path.parts[-3:] == ("pip", "django", "4.2")
        finally:
            os.environ.pop("SYLVAN_HOME", None)
            reset_config()

    def test_scoped_npm_package(self, tmp_path):
        os.environ["SYLVAN_HOME"] = str(tmp_path)
        from sylvan.config import reset_config
        reset_config()

        try:
            path = get_library_path("npm", "@org/package", "1.0.0")
            # Slashes in name get replaced with --
            assert "@org--package" in str(path)
        finally:
            os.environ.pop("SYLVAN_HOME", None)
            reset_config()


# ---------------------------------------------------------------------------
# remove_library_source
# ---------------------------------------------------------------------------

class TestRemoveLibrarySource:
    def test_removes_existing_directory(self, tmp_path):
        os.environ["SYLVAN_HOME"] = str(tmp_path)
        from sylvan.config import reset_config
        reset_config()

        try:
            path = get_library_path("pip", "django", "4.2")
            path.mkdir(parents=True)
            (path / "setup.py").write_text("# setup", encoding="utf-8")

            result = remove_library_source("pip", "django", "4.2")
            assert result is True
            assert not path.exists()
        finally:
            os.environ.pop("SYLVAN_HOME", None)
            reset_config()

    def test_returns_false_for_nonexistent(self, tmp_path):
        os.environ["SYLVAN_HOME"] = str(tmp_path)
        from sylvan.config import reset_config
        reset_config()

        try:
            result = remove_library_source("pip", "nonexistent", "9.9.9")
            assert result is False
        finally:
            os.environ.pop("SYLVAN_HOME", None)
            reset_config()


# ---------------------------------------------------------------------------
# fetch_source (mock git / httpx)
# ---------------------------------------------------------------------------

class TestFetchSource:
    def test_success_on_first_clone(self, tmp_path):
        from sylvan.libraries.source_fetcher import fetch_source

        dest = tmp_path / "src"
        dest.mkdir()

        with patch("sylvan.libraries.source_fetcher._git_clone", return_value=True) as mock_clone:
            result = fetch_source("https://github.com/org/repo", "v1.0.0", dest)

        assert result == dest
        mock_clone.assert_called_once_with(
            "https://github.com/org/repo", "v1.0.0", dest, 120
        )

    def test_fallback_to_alt_tag(self, tmp_path):
        from sylvan.libraries.source_fetcher import fetch_source

        dest = tmp_path / "src"
        dest.mkdir()

        call_count = 0

        def mock_clone(url, tag, d, timeout):
            nonlocal call_count
            call_count += 1
            # First call with "v1.0.0" fails, second with "1.0.0" succeeds
            return call_count == 2

        with patch("sylvan.libraries.source_fetcher._git_clone", side_effect=mock_clone):
            result = fetch_source("https://github.com/org/repo", "v1.0.0", dest)

        assert result == dest

    def test_fallback_to_tarball(self, tmp_path):
        from sylvan.libraries.source_fetcher import fetch_source

        dest = tmp_path / "src"
        dest.mkdir()

        with (
            patch("sylvan.libraries.source_fetcher._git_clone", return_value=False),
            patch("sylvan.libraries.source_fetcher._download_github_tarball", return_value=True) as mock_tb,
        ):
            result = fetch_source("https://github.com/org/repo", "v1.0.0", dest)

        assert result == dest
        assert mock_tb.call_count >= 1

    def test_fallback_to_default_branch(self, tmp_path):
        from sylvan.libraries.source_fetcher import fetch_source

        dest = tmp_path / "src"
        dest.mkdir()

        with (
            patch("sylvan.libraries.source_fetcher._git_clone", return_value=False),
            patch("sylvan.libraries.source_fetcher._download_github_tarball", return_value=False),
            patch("sylvan.libraries.source_fetcher._git_clone_default", return_value=True) as mock_default,
        ):
            result = fetch_source("https://github.com/org/repo", "v1.0.0", dest)

        assert result == dest
        mock_default.assert_called_once()

    def test_all_strategies_fail_raises(self, tmp_path):
        from sylvan.libraries.source_fetcher import fetch_source

        dest = tmp_path / "src"
        dest.mkdir()

        with (
            patch("sylvan.libraries.source_fetcher._git_clone", return_value=False),
            patch("sylvan.libraries.source_fetcher._download_github_tarball", return_value=False),
            patch("sylvan.libraries.source_fetcher._git_clone_default", return_value=False),
            pytest.raises(RuntimeError, match="Failed to fetch source"),
        ):
            fetch_source("https://github.com/org/repo", "v1.0.0", dest)

    def test_non_github_skips_tarball(self, tmp_path):
        from sylvan.libraries.source_fetcher import fetch_source

        dest = tmp_path / "src"
        dest.mkdir()

        with (
            patch("sylvan.libraries.source_fetcher._git_clone", return_value=False),
            patch("sylvan.libraries.source_fetcher._download_github_tarball") as mock_tb,
            patch("sylvan.libraries.source_fetcher._git_clone_default", return_value=True),
        ):
            fetch_source("https://gitlab.com/org/repo", "v1.0.0", dest)

        mock_tb.assert_not_called()


# ---------------------------------------------------------------------------
# _download_github_tarball
# ---------------------------------------------------------------------------

class TestDownloadGithubTarball:
    def test_non_github_url_returns_false(self, tmp_path):
        from sylvan.libraries.source_fetcher import _download_github_tarball

        result = _download_github_tarball("https://gitlab.com/org/repo", "v1.0", tmp_path, 30)
        assert result is False

    def test_http_error_returns_false(self, tmp_path):
        from sylvan.libraries.source_fetcher import _download_github_tarball

        mock_stream_response = MagicMock()
        mock_stream_response.status_code = 404
        mock_stream_response.__enter__ = MagicMock(return_value=mock_stream_response)
        mock_stream_response.__exit__ = MagicMock(return_value=False)

        with patch("sylvan.libraries.source_fetcher.httpx.stream", return_value=mock_stream_response):
            result = _download_github_tarball(
                "https://github.com/org/repo", "v1.0", tmp_path, 30
            )
        assert result is False

    def test_exception_returns_false(self, tmp_path):
        from sylvan.libraries.source_fetcher import _download_github_tarball

        with patch("sylvan.libraries.source_fetcher.httpx.stream", side_effect=Exception("network")):
            result = _download_github_tarball(
                "https://github.com/org/repo", "v1.0", tmp_path, 30
            )
        assert result is False


# ---------------------------------------------------------------------------
# _git_clone
# ---------------------------------------------------------------------------

class TestGitClone:
    def test_invalid_tag_returns_false(self, tmp_path):
        from sylvan.libraries.source_fetcher import _git_clone

        dest = tmp_path / "out"
        dest.mkdir()
        result = _git_clone("https://github.com/org/repo", "; rm -rf /", dest, 30)
        assert result is False

    def test_git_not_found_returns_false(self, tmp_path):
        from sylvan.libraries.source_fetcher import _git_clone

        dest = tmp_path / "out"
        dest.mkdir()

        with patch("sylvan.libraries.source_fetcher.subprocess.Popen", side_effect=FileNotFoundError):
            result = _git_clone("https://github.com/org/repo", "v1.0.0", dest, 30)

        assert result is False
