"""Tests for sylvan.indexing.pipeline.orchestrator — end-to-end indexing."""

import pytest

from sylvan.error_codes import IndexNotADirectoryError
from sylvan.indexing.pipeline.orchestrator import index_folder


class TestIndexFolder:
    async def test_indexes_sample_project(self, ctx, sample_project):
        result = await index_folder(str(sample_project), name="sample")
        assert result.repo_id > 0
        assert result.files_indexed > 0
        assert result.symbols_extracted > 0

    async def test_creates_symbols_in_db(self, ctx, sample_project):
        await index_folder(str(sample_project), name="sample")
        rows = await ctx.backend.fetch_all("SELECT * FROM symbols")
        assert len(rows) > 0

    async def test_stores_blobs(self, ctx, sample_project):
        await index_folder(str(sample_project), name="sample")
        row = await ctx.backend.fetch_value("SELECT COUNT(*) FROM blobs")
        assert row > 0

    async def test_repo_name_defaults_to_folder_name(self, ctx, sample_project):
        result = await index_folder(str(sample_project))
        assert result.repo_name == sample_project.name

    async def test_invalid_directory_returns_error(self, ctx, tmp_path):
        with pytest.raises(IndexNotADirectoryError):
            await index_folder(str(tmp_path / "nonexistent"))

    async def test_reindex_same_folder_idempotent(self, ctx, sample_project):
        await index_folder(str(sample_project), name="sample")
        result = await index_folder(str(sample_project), name="sample")
        assert result.files_indexed == 0

    async def test_extracts_imports(self, ctx, sample_project):
        result = await index_folder(str(sample_project), name="sample")
        assert result.imports_extracted > 0

    async def test_result_to_dict(self, ctx, sample_project):
        result = await index_folder(str(sample_project), name="sample")
        result_dict = result.to_dict()
        assert isinstance(result_dict, dict)
        assert "repo_id" in result_dict
        assert "files_indexed" in result_dict
        assert "duration_ms" in result_dict
