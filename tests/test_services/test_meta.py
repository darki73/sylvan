"""Tests for sylvan.services.meta - suggest_queries, get_logs, scaffold."""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, patch

import pytest

from sylvan.database.orm import FileRecord, Repo, Symbol
from sylvan.database.orm.models.blob import Blob
from sylvan.error_codes import RepoNotFoundError
from sylvan.services.meta import get_logs, scaffold, suggest_queries


async def _seed_repo(name: str = "test-repo") -> Repo:
    return await Repo.create(name=name, source_path=None, indexed_at="2025-01-01T00:00:00")


async def _seed_file(repo: Repo, *, path: str = "src/main.py") -> FileRecord:
    content = b"# main\n"
    content_hash = hashlib.sha256(content).hexdigest()
    await Blob.store(content_hash, content)
    return await FileRecord.create(
        repo_id=repo.id,
        path=path,
        language="python",
        content_hash=content_hash,
        byte_size=len(content),
    )


class TestSuggestQueries:
    async def test_suggest_queries_repo_not_found(self, ctx):
        with pytest.raises(RepoNotFoundError):
            await suggest_queries("nonexistent-repo")

    async def test_suggest_queries_basic(self, ctx):
        repo = await _seed_repo()
        f = await _seed_file(repo)
        await Symbol.create(
            file_id=f.id,
            symbol_id="src/main.py::main#function",
            name="main",
            qualified_name="main",
            kind="function",
            language="python",
            signature="def main()",
            byte_offset=0,
            byte_length=0,
        )

        result = await suggest_queries("test-repo")
        assert "suggestions" in result
        assert isinstance(result["suggestions"], list)


class TestGetLogs:
    async def test_get_logs_no_file(self, ctx, tmp_sylvan_home):
        result = await get_logs()
        assert result["entries"] == []
        assert "No log file found" in result.get("message", "")

    async def test_get_logs_with_file(self, ctx, tmp_sylvan_home):
        log_dir = tmp_sylvan_home / "logs"
        log_dir.mkdir()
        log_file = log_dir / "sylvan.log"
        log_file.write_text("line1\nline2\nline3\n", encoding="utf-8")

        with patch("sylvan.logging._get_log_dir", return_value=log_dir):
            result = await get_logs(lines=2)

        assert result["returned_lines"] == 2


class TestScaffold:
    async def test_scaffold_delegates(self, ctx):
        mock_result = {"status": "ok", "files_created": 3}
        with patch(
            "sylvan.scaffold.generator.async_scaffold_project",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_scaffold:
            result = await scaffold("test-repo", agent="claude")
            mock_scaffold.assert_called_once()
            assert result["status"] == "ok"
