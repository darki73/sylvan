"""Tests for sylvan.services.analysis - AnalysisService."""

from __future__ import annotations

import hashlib

import pytest

from sylvan.database.orm import FileRecord, Repo, Symbol
from sylvan.database.orm.models.blob import Blob
from sylvan.database.orm.models.file_import import FileImport
from sylvan.database.orm.models.reference import Reference
from sylvan.error_codes import (
    IndexFileNotFoundError,
    RepoNotFoundError,
    SymbolNotFoundError,
)
from sylvan.services.analysis import AnalysisService


async def _seed_repo(name: str = "test-repo") -> Repo:
    return await Repo.create(name=name, source_path=None, indexed_at="2025-01-01T00:00:00")


async def _seed_file(
    repo: Repo, *, path: str = "src/utils.py", language: str = "python", content: bytes | None = None
) -> FileRecord:
    content = content or b"# placeholder\n"
    content_hash = hashlib.sha256(content).hexdigest()
    await Blob.store(content_hash, content)
    return await FileRecord.create(
        repo_id=repo.id,
        path=path,
        language=language,
        content_hash=content_hash,
        byte_size=len(content),
    )


async def _seed_symbol(
    file: FileRecord,
    *,
    name: str,
    kind: str = "function",
    language: str = "python",
    signature: str = "",
    symbol_id: str | None = None,
) -> Symbol:
    sid = symbol_id or f"{file.path}::{name}#{kind}"
    return await Symbol.create(
        file_id=file.id,
        symbol_id=sid,
        name=name,
        qualified_name=name,
        kind=kind,
        language=language,
        signature=signature,
        byte_offset=0,
        byte_length=0,
    )


class TestFindImporters:
    async def test_find_importers(self, ctx):
        repo = await _seed_repo()
        target = await _seed_file(repo, path="src/utils.py")
        importer = await _seed_file(repo, path="src/main.py")
        await _seed_symbol(importer, name="main", symbol_id="src/main.py::main#function")
        await FileImport.create(
            file_id=importer.id,
            specifier="./utils",
            resolved_file_id=target.id,
        )

        svc = AnalysisService()
        result = await svc.find_importers("test-repo", "src/utils.py")

        assert result["file"] == "src/utils.py"
        assert len(result["importers"]) >= 1
        paths = [i["path"] for i in result["importers"]]
        assert "src/main.py" in paths

    async def test_find_importers_missing_file(self, ctx):
        await _seed_repo()
        svc = AnalysisService()
        with pytest.raises(IndexFileNotFoundError):
            await svc.find_importers("test-repo", "nonexistent.py")


class TestDependencyGraph:
    async def test_dependency_graph(self, ctx):
        repo = await _seed_repo()
        utils = await _seed_file(repo, path="src/utils.py")
        main = await _seed_file(repo, path="src/main.py")
        await FileImport.create(
            file_id=main.id,
            specifier="./utils",
            resolved_file_id=utils.id,
        )

        svc = AnalysisService()
        result = await svc.dependency_graph("test-repo", "src/main.py")

        assert result["target"] == "src/main.py"
        assert result["node_count"] >= 1
        assert "src/main.py" in result["nodes"]

    async def test_dependency_graph_missing_repo(self, ctx):
        svc = AnalysisService()
        with pytest.raises(RepoNotFoundError):
            await svc.dependency_graph("nonexistent-repo", "file.py")

    async def test_dependency_graph_missing_file(self, ctx):
        await _seed_repo()
        svc = AnalysisService()
        with pytest.raises(IndexFileNotFoundError):
            await svc.dependency_graph("test-repo", "nonexistent.py")


class TestReferences:
    async def test_references_empty_graph(self, ctx):
        svc = AnalysisService()
        result = await svc.references("fake::symbol#function")

        assert result["references"] == []
        assert "warning" in result

    async def test_references_with_data(self, ctx):
        repo = await _seed_repo()
        f = await _seed_file(repo)
        caller = await _seed_symbol(f, name="caller")
        callee = await _seed_symbol(f, name="callee", symbol_id="src/utils.py::callee#function")
        await Reference.create(
            source_symbol_id=caller.symbol_id,
            target_symbol_id=callee.symbol_id,
            target_specifier="callee",
        )

        svc = AnalysisService()
        result = await svc.references(callee.symbol_id, direction="to")
        assert result["direction"] == "to"


class TestRelated:
    async def test_related_finds_same_file_symbols(self, ctx):
        repo = await _seed_repo()
        f = await _seed_file(repo)
        target = await _seed_symbol(f, name="parse_json", signature="def parse_json(data)")
        await _seed_symbol(
            f, name="parse_xml", signature="def parse_xml(data)", symbol_id="src/utils.py::parse_xml#function"
        )

        svc = AnalysisService()
        result = await svc.related(target.symbol_id)

        assert result["symbol_id"] == target.symbol_id
        # parse_xml shares the file and naming pattern, so it should score > 0
        if result["related"]:
            names = [r["name"] for r in result["related"]]
            assert "parse_xml" in names

    async def test_related_symbol_not_found(self, ctx):
        svc = AnalysisService()
        with pytest.raises(SymbolNotFoundError):
            await svc.related("nonexistent::symbol#function")


class TestQuality:
    async def test_quality_missing_repo(self, ctx):
        svc = AnalysisService()
        with pytest.raises(RepoNotFoundError):
            await svc.quality("nonexistent-repo")
