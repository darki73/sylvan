"""Tests for index_folder tool wrapper."""

import os

import pytest

from sylvan.config import reset_config
from sylvan.context import SylvanContext, reset_context, set_context
from sylvan.database.backends.sqlite import SQLiteBackend
from sylvan.database.migrations.runner import run_migrations
from sylvan.database.orm.runtime.query_cache import QueryCache
from sylvan.session.tracker import SessionTracker


@pytest.fixture
async def backend_ctx(tmp_path):
    """Create backend + context for tool tests."""
    os.environ["SYLVAN_HOME"] = str(tmp_path)
    reset_config()

    db_path = tmp_path / "test.db"
    backend = SQLiteBackend(db_path)
    await backend.connect()
    await run_migrations(backend)

    ctx = SylvanContext(
        backend=backend,
        session=SessionTracker(),
        cache=QueryCache(),
    )
    token = set_context(ctx)

    yield tmp_path

    reset_context(token)
    await backend.disconnect()
    os.environ.pop("SYLVAN_HOME", None)
    reset_config()


class TestIndexFolder:
    async def test_indexes_project(self, backend_ctx):
        tmp_path = backend_ctx
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "main.py").write_text("def hello(): pass\n")
        (proj / "README.md").write_text("# Hello\nWorld\n")

        from sylvan.tools.indexing.index_folder import index_folder
        result = await index_folder(str(proj))

        assert "files_indexed" in result
        assert result["files_indexed"] >= 1
        assert result["symbols_extracted"] >= 1
        assert "_meta" in result

    async def test_invalid_path(self, backend_ctx):
        tmp_path = backend_ctx
        from sylvan.error_codes import IndexNotADirectoryError
        from sylvan.tools.indexing.index_folder import index_folder
        with pytest.raises(IndexNotADirectoryError):
            await index_folder(str(tmp_path / "nonexistent"))

    async def test_custom_name(self, backend_ctx):
        tmp_path = backend_ctx
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "app.py").write_text("x = 1\n")

        from sylvan.tools.indexing.index_folder import index_folder
        result = await index_folder(str(proj), name="my-project")
        assert result["repo_name"] == "my-project"
