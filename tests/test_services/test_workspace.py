"""Tests for sylvan.services.workspace - WorkspaceService fluent builder."""

from __future__ import annotations

from sylvan.database.orm import FileRecord, Repo
from sylvan.database.orm.models.workspace import Workspace
from sylvan.services.workspace import WorkspaceResult, WorkspaceService


async def _seed_repo(ctx, name="test-repo", repo_type="local"):
    """Create a repo."""
    backend = ctx.backend
    await backend.execute(
        "INSERT INTO repos (name, source_path, indexed_at, repo_type) "
        f"VALUES ('{name}', '/tmp/{name}', '2024-01-01', '{repo_type}')"
    )
    await backend.commit()
    return await Repo.where(name=name).first()


async def _seed_file(ctx, repo_id, path="src/main.py", language="python"):
    """Create a file record."""
    backend = ctx.backend
    await backend.execute(
        "INSERT INTO files (repo_id, path, language, content_hash, byte_size) "
        f"VALUES ({repo_id}, '{path}', '{language}', 'hash_{path}', 100)"
    )
    await backend.commit()
    return await FileRecord.where(path=path).first()


async def _seed_symbol(ctx, file_id, name="main"):
    """Create a symbol."""
    sid = f"src/main.py::{name}#function"
    backend = ctx.backend
    await backend.execute(
        "INSERT INTO symbols (file_id, symbol_id, name, qualified_name, kind, "
        "language, byte_offset, byte_length) "
        f"VALUES ({file_id}, '{sid}', '{name}', '{name}', 'function', 'python', 0, 50)"
    )
    await backend.commit()


class TestWorkspaceCreate:
    async def test_create_workspace(self, ctx):
        result = await WorkspaceService().create("my-ws", description="Test workspace")
        assert isinstance(result, WorkspaceResult)
        assert result.name == "my-ws"
        assert result.description == "Test workspace"

    async def test_create_existing_returns_existing(self, ctx):
        first = await WorkspaceService().create("idempotent")
        second = await WorkspaceService().create("idempotent")
        assert first.id == second.id


class TestWorkspaceFind:
    async def test_find_workspace(self, ctx):
        await WorkspaceService().create("lookup-ws")
        result = await WorkspaceService().find("lookup-ws")
        assert result is not None
        assert result.name == "lookup-ws"

    async def test_find_missing(self, ctx):
        result = await WorkspaceService().find("ghost")
        assert result is None


class TestWorkspaceGet:
    async def test_get_all(self, ctx):
        await WorkspaceService().create("alpha")
        await WorkspaceService().create("beta")

        results = await WorkspaceService().get()
        assert len(results) == 2
        names = [r.name for r in results]
        assert "alpha" in names
        assert "beta" in names


class TestWorkspaceEnrichment:
    async def test_with_repos(self, ctx):
        repo = await _seed_repo(ctx, name="repo-a")
        file_rec = await _seed_file(ctx, repo.id)
        await _seed_symbol(ctx, file_rec.id)

        await WorkspaceService().create("enriched-ws")
        ws = await Workspace.where(name="enriched-ws").first()
        await ws.attach("repos", repo.id)

        result = await WorkspaceService().with_repos().find("enriched-ws")
        assert result is not None
        assert result.repos_data is not None
        assert len(result.repos_data) == 1
        assert result.repos_data[0]["name"] == "repo-a"
        assert result.repos_data[0]["files"] == 1
        assert result.repos_data[0]["symbols"] == 1

    async def test_with_stats(self, ctx):
        repo = await _seed_repo(ctx, name="stats-repo")
        file_rec = await _seed_file(ctx, repo.id)
        await _seed_symbol(ctx, file_rec.id, name="fn_a")
        await _seed_symbol(ctx, file_rec.id, name="fn_b")

        await WorkspaceService().create("stats-ws")
        ws = await Workspace.where(name="stats-ws").first()
        await ws.attach("repos", repo.id)

        result = await WorkspaceService().with_repos().with_stats().find("stats-ws")
        assert result is not None
        assert result.stats is not None
        assert result.stats["total_files"] == 1
        assert result.stats["total_symbols"] == 2
        assert result.stats["total_sections"] == 0

    async def test_with_available_repos(self, ctx):
        repo_in = await _seed_repo(ctx, name="included")
        await _seed_repo(ctx, name="available")

        await WorkspaceService().create("avail-ws")
        ws = await Workspace.where(name="avail-ws").first()
        await ws.attach("repos", repo_in.id)

        # Need repos data first (available_repos uses ws_repo_ids)
        await _seed_file(ctx, repo_in.id)
        result = await WorkspaceService().with_repos().with_available_repos().find("avail-ws")
        assert result is not None
        assert result.available_repos is not None
        avail_names = [r["name"] for r in result.available_repos]
        assert "available" in avail_names
        assert "included" not in avail_names


class TestWorkspaceUpdate:
    async def test_update_name(self, ctx):
        await WorkspaceService().create("old-name")
        result = await WorkspaceService().update("old-name", new_name="new-name")
        assert result is not None
        assert result.name == "new-name"

    async def test_update_description(self, ctx):
        await WorkspaceService().create("desc-ws")
        result = await WorkspaceService().update("desc-ws", description="Updated")
        assert result is not None
        assert result.description == "Updated"

    async def test_update_missing(self, ctx):
        result = await WorkspaceService().update("nope", new_name="x")
        assert result is None


class TestWorkspaceDelete:
    async def test_delete(self, ctx):
        repo = await _seed_repo(ctx, name="kept-repo")
        await WorkspaceService().create("doomed-ws")
        ws = await Workspace.where(name="doomed-ws").first()
        await ws.attach("repos", repo.id)

        deleted = await WorkspaceService().delete("doomed-ws")
        assert deleted is True
        assert await Workspace.where(name="doomed-ws").first() is None
        # Repo still exists
        assert await Repo.where(name="kept-repo").first() is not None

    async def test_delete_missing(self, ctx):
        deleted = await WorkspaceService().delete("ghost")
        assert deleted is False


class TestWorkspaceRepoManagement:
    async def test_add_repo(self, ctx):
        await _seed_repo(ctx, name="add-target")
        await WorkspaceService().create("add-ws")

        info = await WorkspaceService().add_repo("add-ws", "add-target")
        assert info is not None
        assert "cross_repo_imports_resolved" in info

    async def test_add_repo_by_id(self, ctx):
        repo = await _seed_repo(ctx, name="id-target")
        await WorkspaceService().create("id-ws")

        ok = await WorkspaceService().add_repo_by_id("id-ws", repo.id)
        assert ok is True

        ids = await WorkspaceService().get_repo_ids("id-ws")
        assert repo.id in ids

    async def test_remove_repo_by_id(self, ctx):
        repo = await _seed_repo(ctx, name="removable")
        await WorkspaceService().create("rm-ws")
        ws = await Workspace.where(name="rm-ws").first()
        await ws.attach("repos", repo.id)

        ok = await WorkspaceService().remove_repo_by_id("rm-ws", repo.id)
        assert ok is True

        ids = await WorkspaceService().get_repo_ids("rm-ws")
        assert repo.id not in ids

    async def test_get_repo_ids(self, ctx):
        repo_a = await _seed_repo(ctx, name="id-a")
        repo_b = await _seed_repo(ctx, name="id-b")
        await WorkspaceService().create("ids-ws")
        ws = await Workspace.where(name="ids-ws").first()
        await ws.attach("repos", repo_a.id)
        await ws.attach("repos", repo_b.id)

        ids = await WorkspaceService().get_repo_ids("ids-ws")
        assert set(ids) == {repo_a.id, repo_b.id}

    async def test_get_repo_ids_missing_ws(self, ctx):
        ids = await WorkspaceService().get_repo_ids("nonexistent")
        assert ids == []


class TestWorkspaceResult:
    async def test_repr(self, ctx):
        ws = await WorkspaceService().create("repr-ws")
        assert repr(ws) == "<WorkspaceResult repr-ws>"

    async def test_proxies_model_fields(self, ctx):
        ws = await WorkspaceService().create("proxy-ws", description="Desc")
        assert ws.name == "proxy-ws"
        assert ws.description == "Desc"
