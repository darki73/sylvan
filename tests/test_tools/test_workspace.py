"""Tests for sylvan.database.workspace — workspace management."""

from __future__ import annotations

import os

import pytest

from sylvan.config import reset_config
from sylvan.context import SylvanContext, reset_context, set_context
from sylvan.database.backends.sqlite import SQLiteBackend
from sylvan.database.migrations.runner import run_migrations
from sylvan.database.orm.runtime.query_cache import QueryCache
from sylvan.database.workspace import (
    async_add_repo_to_workspace,
    async_create_workspace,
    async_delete_workspace,
    async_get_workspace,
    async_get_workspace_repo_ids,
    async_list_workspaces,
)
from sylvan.indexing.pipeline.orchestrator import index_folder
from sylvan.session.tracker import SessionTracker, reset_session


@pytest.fixture
async def async_ctx(tmp_path):
    """Create an async backend + context for workspace tests."""
    sylvan_home = tmp_path / "sylvan_home"
    sylvan_home.mkdir(parents=True, exist_ok=True)
    os.environ["SYLVAN_HOME"] = str(sylvan_home)
    reset_config()
    reset_session()

    db_path = sylvan_home / "test.db"
    backend = SQLiteBackend(db_path)
    await backend.connect()
    await run_migrations(backend)

    ctx = SylvanContext(
        backend=backend,
        session=SessionTracker(),
        cache=QueryCache(),
    )
    token = set_context(ctx)

    yield tmp_path, backend

    reset_context(token)
    await backend.disconnect()
    os.environ.pop("SYLVAN_HOME", None)


async def _upsert_repo(backend, name, source_path):
    """Helper to insert a repo and return its id."""
    from datetime import UTC, datetime

    now = datetime.now(UTC).isoformat()
    await backend.execute(
        "INSERT OR REPLACE INTO repos (name, source_path, indexed_at) VALUES (?, ?, ?)",
        [name, source_path, now],
    )
    await backend.commit()
    row = await backend.fetch_one("SELECT id FROM repos WHERE source_path = ?", [source_path])
    return row["id"]


class TestCreateWorkspace:
    async def test_create_returns_id(self, async_ctx):
        _, backend = async_ctx
        ws_id = await async_create_workspace(backend, "my-workspace", "A test workspace")
        assert isinstance(ws_id, int)
        assert ws_id > 0

    async def test_create_idempotent(self, async_ctx):
        _, backend = async_ctx
        id1 = await async_create_workspace(backend, "ws")
        id2 = await async_create_workspace(backend, "ws")
        assert id1 == id2

    async def test_different_names_get_different_ids(self, async_ctx):
        _, backend = async_ctx
        id1 = await async_create_workspace(backend, "ws-a")
        id2 = await async_create_workspace(backend, "ws-b")
        assert id1 != id2


class TestAddRepoToWorkspace:
    async def test_add_repo(self, async_ctx):
        _, backend = async_ctx
        ws_id = await async_create_workspace(backend, "ws")
        repo_id = await _upsert_repo(backend, name="repo1", source_path="/test/repo1")
        await async_add_repo_to_workspace(backend, ws_id, repo_id)
        repo_ids = await async_get_workspace_repo_ids(backend, "ws")
        assert repo_id in repo_ids

    async def test_add_multiple_repos(self, async_ctx):
        _, backend = async_ctx
        ws_id = await async_create_workspace(backend, "ws")
        r1 = await _upsert_repo(backend, name="repo1", source_path="/test/r1")
        r2 = await _upsert_repo(backend, name="repo2", source_path="/test/r2")
        await async_add_repo_to_workspace(backend, ws_id, r1)
        await async_add_repo_to_workspace(backend, ws_id, r2)
        repo_ids = await async_get_workspace_repo_ids(backend, "ws")
        assert r1 in repo_ids
        assert r2 in repo_ids

    async def test_add_same_repo_twice_idempotent(self, async_ctx):
        _, backend = async_ctx
        ws_id = await async_create_workspace(backend, "ws")
        repo_id = await _upsert_repo(backend, name="repo", source_path="/test/repo")
        await async_add_repo_to_workspace(backend, ws_id, repo_id)
        await async_add_repo_to_workspace(backend, ws_id, repo_id)  # should not raise
        repo_ids = await async_get_workspace_repo_ids(backend, "ws")
        assert repo_ids.count(repo_id) == 1


class TestGetWorkspace:
    async def test_returns_workspace_with_repos(self, async_ctx):
        _, backend = async_ctx
        ws_id = await async_create_workspace(backend, "ws", "desc")
        repo_id = await _upsert_repo(backend, name="repo", source_path="/test/repo")
        await async_add_repo_to_workspace(backend, ws_id, repo_id)
        ws = await async_get_workspace(backend, "ws")
        assert ws is not None
        assert ws["name"] == "ws"
        assert ws["description"] == "desc"
        assert len(ws["repos"]) == 1
        assert ws["repos"][0]["name"] == "repo"

    async def test_returns_none_for_missing(self, async_ctx):
        _, backend = async_ctx
        ws = await async_get_workspace(backend, "nonexistent")
        assert ws is None


class TestListWorkspaces:
    async def test_lists_all_workspaces(self, async_ctx):
        _, backend = async_ctx
        await async_create_workspace(backend, "ws-a")
        await async_create_workspace(backend, "ws-b")
        workspaces = await async_list_workspaces(backend)
        names = [w["name"] for w in workspaces]
        assert "ws-a" in names
        assert "ws-b" in names

    async def test_includes_repo_count(self, async_ctx):
        _, backend = async_ctx
        ws_id = await async_create_workspace(backend, "ws")
        r1 = await _upsert_repo(backend, name="r1", source_path="/test/r1")
        r2 = await _upsert_repo(backend, name="r2", source_path="/test/r2")
        await async_add_repo_to_workspace(backend, ws_id, r1)
        await async_add_repo_to_workspace(backend, ws_id, r2)
        workspaces = await async_list_workspaces(backend)
        ws = next(w for w in workspaces if w["name"] == "ws")
        assert ws["repo_count"] == 2

    async def test_empty_returns_empty(self, async_ctx):
        _, backend = async_ctx
        workspaces = await async_list_workspaces(backend)
        assert workspaces == []


class TestDeleteWorkspace:
    async def test_delete_existing(self, async_ctx):
        _, backend = async_ctx
        await async_create_workspace(backend, "ws")
        assert await async_delete_workspace(backend, "ws") is True
        assert await async_get_workspace(backend, "ws") is None

    async def test_delete_nonexistent(self, async_ctx):
        _, backend = async_ctx
        assert await async_delete_workspace(backend, "nonexistent") is False


class TestIndexWorkspaceIntegration:
    """Integration test: index two projects and add them to a workspace."""

    async def test_index_two_projects_into_workspace(self, async_ctx):
        tmp_path, backend = async_ctx

        proj_a = tmp_path / "project_a"
        proj_a.mkdir()
        (proj_a / "main.py").write_text("def alpha(): pass\n")

        proj_b = tmp_path / "project_b"
        proj_b.mkdir()
        (proj_b / "main.go").write_text("package main\n\nfunc Beta() {}\n")

        r1 = await index_folder(str(proj_a), name="proj-a")
        r2 = await index_folder(str(proj_b), name="proj-b")

        assert r1.files_indexed >= 1
        assert r2.files_indexed >= 1

        ws_id = await async_create_workspace(backend, "multi-project")
        await async_add_repo_to_workspace(backend, ws_id, r1.repo_id)
        await async_add_repo_to_workspace(backend, ws_id, r2.repo_id)

        repo_ids = await async_get_workspace_repo_ids(backend, "multi-project")
        assert r1.repo_id in repo_ids
        assert r2.repo_id in repo_ids

        ws = await async_get_workspace(backend, "multi-project")
        assert len(ws["repos"]) == 2
        repo_names = {r["name"] for r in ws["repos"]}
        assert "proj-a" in repo_names
        assert "proj-b" in repo_names


class TestIndexWorkspaceTool:
    """Tests for the MCP tool version of index_workspace."""

    async def test_index_workspace_creates_workspace_and_indexes(self, async_ctx):
        tmp_path, _ = async_ctx

        proj_a = tmp_path / "proj_a"
        proj_a.mkdir()
        (proj_a / "alpha.py").write_text("def alpha(): pass\n")

        proj_b = tmp_path / "proj_b"
        proj_b.mkdir()
        (proj_b / "beta.py").write_text("def beta(): pass\n")

        from sylvan.tools.workspace import index_workspace

        resp = await index_workspace(
            workspace="my-ws",
            paths=[str(proj_a), str(proj_b)],
            description="Test workspace",
        )

        assert "workspace" in resp
        assert resp["workspace"] == "my-ws"
        assert "repos" in resp
        assert "_meta" in resp
        assert isinstance(resp["repos"], list)
        assert len(resp["repos"]) == 2

        meta = resp["_meta"]
        assert "repos_indexed" in meta
        assert meta["repos_indexed"] == 2
        assert "total_files" in meta
        assert meta["total_files"] >= 2
        assert "total_symbols" in meta
        assert meta["total_symbols"] >= 2


class TestWorkspaceSearchTool:
    """Tests for the MCP tool workspace_search."""

    async def test_workspace_search_returns_results(self, async_ctx):
        tmp_path, _ = async_ctx

        proj_a = tmp_path / "proj_a"
        proj_a.mkdir()
        (proj_a / "search_me.py").write_text("def find_alpha(): pass\ndef find_beta(): pass\n")

        from sylvan.tools.workspace import index_workspace, workspace_search

        await index_workspace(
            workspace="search-ws",
            paths=[str(proj_a)],
        )

        resp = await workspace_search(workspace="search-ws", query="find_alpha")

        assert "symbols" in resp
        assert "_meta" in resp
        assert "results_count" in resp["_meta"]
        assert "repos_searched" in resp["_meta"]
        assert len(resp["symbols"]) >= 1

    async def test_workspace_search_empty_workspace(self, async_ctx):
        from sylvan.error_codes import WorkspaceNotFoundError
        from sylvan.tools.workspace import workspace_search

        with pytest.raises(WorkspaceNotFoundError):
            await workspace_search(workspace="nonexistent-ws", query="anything")


class TestWorkspaceBlastRadiusTool:
    """Tests for the MCP tool workspace_blast_radius."""

    async def test_workspace_blast_radius_returns_structure(self, async_ctx):
        tmp_path, _ = async_ctx

        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "core.py").write_text("class Engine:\n    def start(self): pass\n")
        (proj / "app.py").write_text("from core import Engine\n\ndef run():\n    e = Engine()\n    e.start()\n")

        from sylvan.tools.workspace import index_workspace, workspace_blast_radius

        await index_workspace(workspace="br-ws", paths=[str(proj)])

        from sylvan.tools.search.search_symbols import search_symbols

        resp = await search_symbols(query="Engine")
        engine_syms = [s for s in resp["symbols"] if s["name"] == "Engine"]
        assert len(engine_syms) >= 1
        sid = engine_syms[0]["symbol_id"]

        br_resp = await workspace_blast_radius(workspace="br-ws", symbol_id=sid)

        assert "_meta" in br_resp
        if "error" not in br_resp:
            assert "confirmed" in br_resp or "symbol" in br_resp
            meta = br_resp["_meta"]
            assert "confirmed_count" in meta

    async def test_workspace_blast_radius_empty_workspace(self, async_ctx):
        from sylvan.error_codes import WorkspaceNotFoundError
        from sylvan.tools.workspace import workspace_blast_radius

        with pytest.raises(WorkspaceNotFoundError):
            await workspace_blast_radius(
                workspace="nonexistent-ws",
                symbol_id="fake::sym#function",
            )
