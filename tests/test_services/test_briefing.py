"""Tests for sylvan.services.briefing - BriefingService."""

from __future__ import annotations

import json

import pytest

from sylvan.database.orm import FileRecord, Repo, Symbol
from sylvan.error_codes import RepoNotFoundError
from sylvan.services.briefing import (
    BriefingService,
    _build_directory_tree,
    _read_manifests,
)


class TestBuildDirectoryTree:
    def test_flat_files(self):
        paths = ["README.md", "main.py", "setup.py"]
        tree = _build_directory_tree(paths)
        assert tree == {".": 3}

    def test_nested_directories(self):
        paths = [
            "src/main.py",
            "src/utils.py",
            "src/db/models.py",
            "src/db/migrations.py",
            "tests/test_main.py",
        ]
        tree = _build_directory_tree(paths)
        assert tree["src"] == 2
        assert tree["src/db"] == 2
        assert tree["tests"] == 1

    def test_mixed_root_and_nested(self):
        paths = ["README.md", "src/app.py"]
        tree = _build_directory_tree(paths)
        assert tree["."] == 1
        assert tree["src"] == 1

    def test_empty_paths(self):
        tree = _build_directory_tree([])
        assert tree == {}

    def test_windows_backslashes_normalized(self):
        paths = ["src\\db\\models.py", "src\\utils.py"]
        tree = _build_directory_tree(paths)
        assert tree["src/db"] == 1
        assert tree["src"] == 1

    def test_sorted_output(self):
        paths = ["z/a.py", "a/b.py", "m/c.py"]
        tree = _build_directory_tree(paths)
        keys = list(tree.keys())
        assert keys == sorted(keys)


class TestReadManifests:
    def test_reads_pyproject(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "test"\n')
        result = _read_manifests(tmp_path)
        assert "pyproject.toml" in result
        assert "test" in result["pyproject.toml"]

    def test_reads_package_json(self, tmp_path):
        (tmp_path / "package.json").write_text('{"name": "test"}')
        result = _read_manifests(tmp_path)
        assert "package.json" in result

    def test_skips_missing(self, tmp_path):
        result = _read_manifests(tmp_path)
        assert result == {}

    def test_reads_multiple(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("[project]")
        (tmp_path / "package.json").write_text("{}")
        result = _read_manifests(tmp_path)
        assert len(result) == 2

    def test_truncates_large_files(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text("x" * 10000)
        result = _read_manifests(tmp_path)
        assert "truncated" in result["pyproject.toml"]
        assert len(result["pyproject.toml"]) < 6000

    def test_ignores_directories(self, tmp_path):
        (tmp_path / "package.json").mkdir()
        result = _read_manifests(tmp_path)
        assert result == {}


class TestBriefingServiceGenerate:
    async def test_generates_briefing(self, ctx):
        repo = await Repo.create(name="test", source_path=None, indexed_at="2025-01-01T00:00:00")
        f = await FileRecord.create(
            repo_id=repo.id, path="src/main.py", language="python", byte_size=100, content_hash="abc123"
        )
        await Symbol.create(
            file_id=f.id,
            symbol_id="src/main.py::main#function",
            name="main",
            qualified_name="main",
            kind="function",
            language="python",
            signature="def main()",
            byte_offset=0,
            byte_length=20,
            content_hash="sym123",
        )

        await BriefingService().generate("test")

        repo = await Repo.where(name="test").first()
        assert repo.briefing is not None
        data = json.loads(repo.briefing)
        assert data["stats"]["files"] == 1
        assert data["stats"]["symbols"] == 1
        assert data["languages"]["python"] == 1
        assert "src" in data["directory_tree"]

    async def test_not_found_raises(self, ctx):
        with pytest.raises(RepoNotFoundError):
            await BriefingService().generate("nonexistent")


class TestBriefingServiceGet:
    async def test_get_returns_stored(self, ctx):
        repo = await Repo.create(name="test", source_path=None, indexed_at="2025-01-01T00:00:00")
        await FileRecord.create(repo_id=repo.id, path="main.py", language="python", byte_size=50, content_hash="def456")

        await BriefingService().generate("test")
        result = await BriefingService().get("test")

        assert result["repo"] == "test"
        assert result["stats"]["files"] == 1
        assert "repo_id" in result  # present in service response, tool handler pops it

    async def test_get_generates_on_first_access(self, ctx):
        repo = await Repo.create(name="test", source_path=None, indexed_at="2025-01-01T00:00:00")
        await FileRecord.create(repo_id=repo.id, path="main.py", language="go", byte_size=50, content_hash="ghi789")

        result = await BriefingService().get("test")
        assert result["stats"]["files"] == 1
        assert result["languages"]["go"] == 1

    async def test_get_not_found_raises(self, ctx):
        with pytest.raises(RepoNotFoundError):
            await BriefingService().get("nonexistent")

    async def test_manifests_from_disk(self, ctx, tmp_path):
        (tmp_path / "go.mod").write_text("module example.com/test\n\ngo 1.21\n")
        repo = await Repo.create(name="test", source_path=str(tmp_path), indexed_at="2025-01-01T00:00:00")
        await FileRecord.create(repo_id=repo.id, path="main.go", language="go", byte_size=50, content_hash="jkl012")

        result = await BriefingService().get("test")
        assert "go.mod" in result["manifests"]
        assert "example.com/test" in result["manifests"]["go.mod"]

    async def test_no_manifests_when_no_source_path(self, ctx):
        repo = await Repo.create(name="test", source_path=None, indexed_at="2025-01-01T00:00:00")
        await FileRecord.create(repo_id=repo.id, path="main.py", language="python", byte_size=50, content_hash="def456")

        result = await BriefingService().get("test")
        assert result["manifests"] == {}


class TestSearchQueryCoercion:
    """Verify that numeric queries don't crash search methods."""

    async def test_symbols_accepts_int_query(self, ctx):
        await Repo.create(name="test", source_path=None, indexed_at="2025-01-01T00:00:00")
        result = await SearchService().symbols(query=123, repo="test")
        assert result["query"] == "123"

    async def test_sections_accepts_int_query(self, ctx):
        await Repo.create(name="test", source_path=None, indexed_at="2025-01-01T00:00:00")
        result = await SearchService().sections(query=42, repo="test")
        assert result["query"] == "42"


# Import here to avoid circular at module level
from sylvan.services.search import SearchService
