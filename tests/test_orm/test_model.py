"""Tests for sylvan.database.orm.model.base — Model CRUD operations."""

from __future__ import annotations

import pytest

from sylvan.database.orm.exceptions import ModelNotFoundError
from sylvan.database.orm.models import FileRecord, Repo


async def _make_repo(ctx, name="test-repo"):
    """Insert a repo via ORM and return its id."""
    repo = await Repo.create(name=name, indexed_at="2024-01-01")
    return repo.id


async def _make_file(ctx, repo_id, path="main.py"):
    """Insert a file via ORM and return its id."""
    f = await FileRecord.create(
        repo_id=repo_id,
        path=path,
        language="python",
        content_hash="abc123",
        byte_size=100,
    )
    return f.id


class TestCreate:
    async def test_create_returns_instance_with_pk(self, orm_ctx):
        repo = await Repo.create(name="my-repo", indexed_at="2024-01-01")
        assert repo.id is not None
        assert repo.id > 0
        assert repo.name == "my-repo"

    async def test_create_persists_to_db(self, orm_ctx):
        repo = await Repo.create(name="persisted", indexed_at="2024-01-01")
        found = await Repo.find(repo.id)
        assert found.name == "persisted"


class TestSave:
    async def test_save_new_instance_inserts(self, orm_ctx):
        repo = Repo(name="new-repo", indexed_at="2024-01-01")
        assert repo._persisted is False
        await repo.save()
        assert repo._persisted is True
        assert repo.id is not None

    async def test_save_persisted_instance_updates(self, orm_ctx):
        repo = await Repo.create(name="original", indexed_at="2024-01-01")
        repo.name = "updated"
        await repo.save()
        found = await Repo.find(repo.id)
        assert found.name == "updated"


class TestUpdate:
    async def test_update_specific_fields(self, orm_ctx):
        repo = await Repo.create(name="before", indexed_at="2024-01-01")
        await repo.update(name="after")
        assert repo.name == "after"
        found = await Repo.find(repo.id)
        assert found.name == "after"


class TestDelete:
    async def test_delete_removes_from_db(self, orm_ctx):
        repo = await Repo.create(name="to-delete", indexed_at="2024-01-01")
        rid = repo.id
        await repo.delete()
        assert repo._persisted is False
        found = await Repo.find(rid)
        assert found is None


class TestFind:
    async def test_find_by_pk(self, orm_ctx):
        repo = await Repo.create(name="findme", indexed_at="2024-01-01")
        found = await Repo.find(repo.id)
        assert found is not None
        assert found.name == "findme"

    async def test_find_returns_none_for_missing(self, orm_ctx):
        assert await Repo.find(99999) is None


class TestFindOrFail:
    async def test_find_or_fail_returns_instance(self, orm_ctx):
        repo = await Repo.create(name="exists", indexed_at="2024-01-01")
        found = await Repo.find_or_fail(repo.id)
        assert found.name == "exists"

    async def test_find_or_fail_raises_model_not_found(self, orm_ctx):
        with pytest.raises(ModelNotFoundError, match="Repo not found"):
            await Repo.find_or_fail(99999)


class TestUpsert:
    async def test_upsert_inserts_new_row(self, orm_ctx):
        repo_id = await _make_repo(orm_ctx)
        f = await FileRecord.upsert(
            conflict_columns=["repo_id", "path"],
            repo_id=repo_id,
            path="new.py",
            language="python",
            content_hash="hash1",
            byte_size=50,
        )
        assert f.id is not None
        assert f._persisted is True

    async def test_upsert_updates_on_conflict(self, orm_ctx):
        repo_id = await _make_repo(orm_ctx)
        await FileRecord.upsert(
            conflict_columns=["repo_id", "path"],
            repo_id=repo_id,
            path="same.py",
            language="python",
            content_hash="hash1",
            byte_size=50,
        )
        f2 = await FileRecord.upsert(
            conflict_columns=["repo_id", "path"],
            update_columns=["content_hash", "byte_size"],
            repo_id=repo_id,
            path="same.py",
            language="python",
            content_hash="hash2",
            byte_size=200,
        )
        found = await FileRecord.where(repo_id=repo_id, path="same.py").first()
        assert found.content_hash == "hash2"
        assert found.byte_size == 200
        assert f2.id is not None


class TestInsertOrIgnore:
    async def test_insert_or_ignore_inserts_new(self, orm_ctx):
        repo = await Repo.insert_or_ignore(name="new-repo", indexed_at="2024-01-01", source_path="/unique/path")
        assert repo.id is not None

    async def test_insert_or_ignore_ignores_duplicate(self, orm_ctx):
        await Repo.create(name="dup-repo", indexed_at="2024-01-01", source_path="/dup/path")
        count_before = await Repo.query().count()
        await Repo.insert_or_ignore(name="dup-repo-2", indexed_at="2024-02-01", source_path="/dup/path")
        count_after = await Repo.query().count()
        assert count_after == count_before


class TestInsertOrReplace:
    async def test_insert_or_replace_inserts_new(self, orm_ctx):
        repo = await Repo.insert_or_replace(name="brand-new", indexed_at="2024-01-01")
        assert repo.id is not None
        assert repo._persisted is True

    async def test_insert_or_replace_replaces_existing(self, orm_ctx):
        await Repo.create(name="orig", indexed_at="2024-01-01", source_path="/replace/path")
        await Repo.insert_or_replace(
            name="replaced",
            indexed_at="2024-02-01",
            source_path="/replace/path",
        )
        found = await Repo.where(source_path="/replace/path").first()
        assert found.name == "replaced"


class TestFromRow:
    async def test_from_row_creates_instance(self, orm_ctx):
        repo = Repo._from_row(
            {
                "id": 42,
                "name": "from-row",
                "indexed_at": "2024-01-01",
                "source_path": None,
                "github_url": None,
                "git_head": None,
            }
        )
        assert repo.id == 42
        assert repo.name == "from-row"
        assert repo._persisted is True


class TestToDict:
    async def test_to_dict_serializes_fields(self, orm_ctx):
        repo = Repo(name="dictme", indexed_at="2024-01-01")
        d = repo._to_dict()
        assert d["name"] == "dictme"
        assert d["indexed_at"] == "2024-01-01"
        assert "id" in d


class TestRefresh:
    async def test_refresh_reloads_from_db(self, orm_ctx):
        repo = await Repo.create(name="before-refresh", indexed_at="2024-01-01")
        # Directly update via backend
        backend = orm_ctx.backend
        await backend.execute(
            "UPDATE repos SET name = 'after-refresh' WHERE id = ?",
            [repo.id],
        )
        await backend.commit()
        await repo.refresh()
        assert repo.name == "after-refresh"

    async def test_refresh_raises_if_deleted(self, orm_ctx):
        repo = await Repo.create(name="doomed", indexed_at="2024-01-01")
        backend = orm_ctx.backend
        await backend.execute("DELETE FROM repos WHERE id = ?", [repo.id])
        await backend.commit()
        with pytest.raises(ModelNotFoundError):
            await repo.refresh()
