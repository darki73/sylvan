"""Tests for sylvan.security.filters — path validation, symlinks, file exclusion."""

from __future__ import annotations

import pytest

from sylvan.security.filters import (
    FileExclusionResult,
    is_symlink_escape,
    should_exclude_file,
    validate_path,
)


class TestValidatePath:
    def test_child_path_is_valid(self, tmp_path):
        child = tmp_path / "subdir" / "file.py"
        child.parent.mkdir(parents=True, exist_ok=True)
        child.write_text("pass")
        assert validate_path(tmp_path, child) is True

    def test_parent_path_is_invalid(self, tmp_path):
        parent = tmp_path.parent
        assert validate_path(tmp_path, parent) is False

    def test_traversal_path_is_invalid(self, tmp_path):
        traversal = tmp_path / ".." / ".." / "etc" / "passwd"
        assert validate_path(tmp_path, traversal) is False

    def test_same_path_is_valid(self, tmp_path):
        assert validate_path(tmp_path, tmp_path) is True

    def test_deeply_nested_valid(self, tmp_path):
        deep = tmp_path / "a" / "b" / "c" / "d.py"
        deep.parent.mkdir(parents=True, exist_ok=True)
        deep.write_text("pass")
        assert validate_path(tmp_path, deep) is True


class TestIsSymlinkEscape:
    def test_regular_file_no_escape(self, tmp_path):
        f = tmp_path / "file.py"
        f.write_text("pass")
        assert is_symlink_escape(tmp_path, f) is False

    def test_symlink_inside_root_no_escape(self, tmp_path):
        target = tmp_path / "real.py"
        target.write_text("pass")
        link = tmp_path / "link.py"
        try:
            link.symlink_to(target)
        except OSError:
            pytest.skip("Symlinks not supported on this system")
        assert is_symlink_escape(tmp_path, link) is False

    def test_symlink_outside_root_escapes(self, tmp_path):
        outside = tmp_path.parent / "outside_file.txt"
        outside.write_text("secret")
        link = tmp_path / "escape_link.txt"
        try:
            link.symlink_to(outside)
        except OSError:
            pytest.skip("Symlinks not supported on this system")
        try:
            assert is_symlink_escape(tmp_path, link) is True
        finally:
            outside.unlink(missing_ok=True)


class TestShouldExcludeFile:
    def test_normal_file_not_excluded(self, tmp_path):
        f = tmp_path / "main.py"
        f.write_text("def hello(): pass\n")
        result = should_exclude_file(f, tmp_path)
        assert not result.excluded

    def test_binary_extension_excluded(self, tmp_path):
        f = tmp_path / "image.png"
        f.write_bytes(b"\x89PNG\r\n")
        result = should_exclude_file(f, tmp_path)
        assert result.excluded
        assert result.reason == "binary_extension"

    def test_secret_file_excluded(self, tmp_path):
        f = tmp_path / ".env"
        f.write_text("SECRET=abc")
        result = should_exclude_file(f, tmp_path)
        assert result.excluded
        assert result.reason == "secret_file"

    def test_skip_pattern_excluded(self, tmp_path):
        f = tmp_path / "bundle.min.js"
        f.write_text("var a=1;")
        result = should_exclude_file(f, tmp_path)
        assert result.excluded
        assert result.reason == "skip_pattern"

    def test_empty_file_excluded(self, tmp_path):
        f = tmp_path / "empty.py"
        f.write_text("")
        result = should_exclude_file(f, tmp_path)
        assert result.excluded
        assert result.reason == "empty"

    def test_too_large_file_excluded(self, tmp_path):
        f = tmp_path / "big.py"
        f.write_text("x" * 600_000)
        result = should_exclude_file(f, tmp_path, max_file_size=512_000)
        assert result.excluded
        assert "too_large" in result.reason

    def test_binary_content_excluded(self, tmp_path):
        f = tmp_path / "mystery.txt"
        f.write_bytes(b"hello\x00world")
        result = should_exclude_file(f, tmp_path)
        assert result.excluded
        assert result.reason == "binary_content"

    def test_exclusion_result_bool(self):
        assert bool(FileExclusionResult(True, "test")) is True
        assert bool(FileExclusionResult(False)) is False

    def test_check_content_disabled(self, tmp_path):
        f = tmp_path / "nullbyte.dat"
        f.write_bytes(b"data\x00here")
        should_exclude_file(f, tmp_path, check_content=False)
        # Without content check, only extension-based checks apply
        # .dat is not a binary extension, so it should pass
        # Actually .dat IS in BINARY_EXTENSIONS
        # Use a non-binary extension
        f2 = tmp_path / "nullbyte.txt"
        f2.write_bytes(b"data\x00here")
        result2 = should_exclude_file(f2, tmp_path, check_content=False)
        assert not result2.excluded
