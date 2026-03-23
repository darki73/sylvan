"""Tests for sylvan.tools.meta.scaffold — the MCP scaffold tool wrapper."""

from __future__ import annotations

import os

import pytest

from sylvan.config import reset_config
from sylvan.context import SylvanContext, reset_context, set_context
from sylvan.database.backends.sqlite import SQLiteBackend
from sylvan.database.migrations.runner import run_migrations
from sylvan.database.orm.runtime.query_cache import QueryCache
from sylvan.session.tracker import SessionTracker, reset_session


@pytest.fixture
async def scaffold_tool_ctx(tmp_path):
    """Set up a context with an indexed repo for scaffold tool tests."""
    os.environ["SYLVAN_HOME"] = str(tmp_path)
    reset_config()
    reset_session()

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

    proj = tmp_path / "toolproject"
    proj.mkdir()
    (proj / "app.py").write_text(
        'def serve():\n'
        '    """Start the server."""\n'
        '    pass\n',
        encoding="utf-8",
    )

    from sylvan.indexing.pipeline.orchestrator import index_folder
    await index_folder(str(proj), name="toolproject")
    await backend.commit()

    yield {"project_root": proj, "tmp_path": tmp_path}

    reset_context(token)
    await backend.disconnect()
    os.environ.pop("SYLVAN_HOME", None)


class TestScaffoldTool:
    async def test_scaffold_tool_returns_response_envelope(self, scaffold_tool_ctx):
        from sylvan.tools.meta.scaffold import scaffold

        root = scaffold_tool_ctx["project_root"]
        result = await scaffold(repo="toolproject", root=str(root))

        assert "_meta" in result
        assert "_version" in result
        assert "status" in result

    async def test_scaffold_tool_creates_files(self, scaffold_tool_ctx):
        from sylvan.tools.meta.scaffold import scaffold

        root = scaffold_tool_ctx["project_root"]
        result = await scaffold(repo="toolproject", root=str(root))

        assert result.get("status") == "generated"
        assert result["files_created"] > 0
        assert (root / "sylvan").is_dir()
        assert (root / "CLAUDE.md").exists()

    async def test_scaffold_tool_meta_has_status(self, scaffold_tool_ctx):
        from sylvan.tools.meta.scaffold import scaffold

        root = scaffold_tool_ctx["project_root"]
        result = await scaffold(repo="toolproject", root=str(root))

        meta = result["_meta"]
        assert "status" in meta
        assert "files_created" in meta
        assert "timing_ms" in meta

    async def test_scaffold_tool_with_cursor_agent(self, scaffold_tool_ctx):
        from sylvan.tools.meta.scaffold import scaffold

        root = scaffold_tool_ctx["project_root"]
        result = await scaffold(repo="toolproject", agent="cursor", root=str(root))

        assert result.get("config_file") == ".cursorrules"
        assert (root / ".cursorrules").exists()

    async def test_scaffold_tool_repo_not_found(self, scaffold_tool_ctx):
        from sylvan.tools.meta.scaffold import scaffold

        result = await scaffold(repo="nonexistent")
        assert "error" in result
