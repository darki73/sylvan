"""Tests for sylvan.services.repository - RepositoryService fluent builder."""

from __future__ import annotations

import pytest

from sylvan.database.orm import FileRecord, Repo, Section, Symbol
from sylvan.error_codes import RepoNotFoundError
from sylvan.services.repository import (
    RepoResult,
    RepositoryService,
    load_languages,
    load_stats,
)


async def _seed_repo(ctx, name="test-repo", repo_type="local", source_path=None):
    """Create a repo via raw SQL for deterministic IDs."""
    if source_path is None:
        source_path = f"/test/{name}"
    backend = ctx.backend
    await backend.execute(
        "INSERT INTO repos (name, source_path, indexed_at, repo_type) "
        f"VALUES ('{name}', '{source_path}', '2024-01-01', '{repo_type}')"
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


async def _seed_symbol(ctx, file_id, name="main", kind="function"):
    """Create a symbol."""
    sid = f"src/main.py::{name}#{kind}"
    backend = ctx.backend
    await backend.execute(
        "INSERT INTO symbols (file_id, symbol_id, name, qualified_name, kind, "
        "language, byte_offset, byte_length) "
        f"VALUES ({file_id}, '{sid}', '{name}', '{name}', '{kind}', 'python', 0, 50)"
    )
    await backend.commit()
    return await Symbol.where(symbol_id=sid).first()


async def _seed_section(ctx, file_id, title="Introduction", level=1):
    """Create a section."""
    sec_id = f"test-repo::README.md::{title.lower()}#section"
    backend = ctx.backend
    await backend.execute(
        "INSERT INTO sections (file_id, section_id, title, level, byte_start, byte_end) "
        f"VALUES ({file_id}, '{sec_id}', '{title}', {level}, 0, 100)"
    )
    await backend.commit()
    return await Section.where(section_id=sec_id).first()


class TestRepositoryServiceGet:
    async def test_get_returns_all_repos(self, ctx):
        await _seed_repo(ctx, name="alpha")
        await _seed_repo(ctx, name="beta")

        results = await RepositoryService().get()
        assert len(results) == 2
        names = [r.name for r in results]
        assert "alpha" in names
        assert "beta" in names

    async def test_exclude_libraries(self, ctx):
        await _seed_repo(ctx, name="my-project", repo_type="local")
        await _seed_repo(ctx, name="numpy@1.26", repo_type="library")

        results = await RepositoryService().exclude_libraries().get()
        assert len(results) == 1
        assert results[0].name == "my-project"


class TestRepositoryServiceStats:
    async def test_with_stats(self, ctx):
        repo = await _seed_repo(ctx, name="stats-repo")
        file_rec = await _seed_file(ctx, repo.id)
        await _seed_symbol(ctx, file_rec.id, name="func_a")
        await _seed_symbol(ctx, file_rec.id, name="func_b", kind="class")
        # Add a doc file with a section
        doc = await _seed_file(ctx, repo.id, path="README.md", language="markdown")
        await _seed_section(ctx, doc.id)

        result = await RepositoryService().with_stats().find("stats-repo")
        assert result is not None
        assert result.stats is not None
        assert result.stats["files"] == 2
        assert result.stats["symbols"] == 2
        assert result.stats["sections"] == 1

    async def test_with_languages(self, ctx):
        repo = await _seed_repo(ctx, name="lang-repo")
        await _seed_file(ctx, repo.id, path="a.py", language="python")
        await _seed_file(ctx, repo.id, path="b.py", language="python")
        await _seed_file(ctx, repo.id, path="c.ts", language="typescript")

        result = await RepositoryService().with_languages().find("lang-repo")
        assert result is not None
        assert result.languages is not None
        assert result.languages["python"] == 2
        assert result.languages["typescript"] == 1
        # Sorted descending by count
        keys = list(result.languages.keys())
        assert keys[0] == "python"


class TestRepositoryServiceFind:
    async def test_find_existing(self, ctx):
        await _seed_repo(ctx, name="findme")
        result = await RepositoryService().find("findme")
        assert result is not None
        assert isinstance(result, RepoResult)
        assert result.name == "findme"

    async def test_find_missing(self, ctx):
        result = await RepositoryService().find("nonexistent")
        assert result is None


class TestRepositoryServiceRemove:
    async def test_remove(self, ctx):
        repo = await _seed_repo(ctx, name="doomed")
        file_rec = await _seed_file(ctx, repo.id)
        await _seed_symbol(ctx, file_rec.id)

        info = await RepositoryService().remove("doomed")
        assert info["repo"] == "doomed"
        assert info["repo_id"] == repo.id

        # Verify cascaded
        assert await Repo.where(name="doomed").first() is None

    async def test_remove_missing(self, ctx):
        with pytest.raises(RepoNotFoundError):
            await RepositoryService().remove("ghost")


class TestRepoResult:
    async def test_result_proxies_model_fields(self, ctx):
        repo = await _seed_repo(ctx, name="proxy-test", source_path="/srv/code")
        result = RepoResult(repo)
        assert result.name == "proxy-test"
        assert result.source_path == "/srv/code"
        assert repr(result) == "<RepoResult proxy-test>"


class TestBuildingBlocks:
    async def test_load_stats(self, ctx):
        repo = await _seed_repo(ctx, name="bb-repo")
        file_rec = await _seed_file(ctx, repo.id)
        await _seed_symbol(ctx, file_rec.id)

        stats = await load_stats(repo.id)
        assert stats["files"] == 1
        assert stats["symbols"] == 1
        assert stats["sections"] == 0

    async def test_load_languages(self, ctx):
        repo = await _seed_repo(ctx, name="bb-lang")
        await _seed_file(ctx, repo.id, path="x.go", language="go")
        await _seed_file(ctx, repo.id, path="y.go", language="go")
        await _seed_file(ctx, repo.id, path="z.rs", language="rust")

        langs = await load_languages(repo.id)
        assert langs["go"] == 2
        assert langs["rust"] == 1

    async def test_load_languages_empty(self, ctx):
        repo = await _seed_repo(ctx, name="bb-empty")
        langs = await load_languages(repo.id)
        assert langs == {}
