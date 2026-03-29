"""Tests for sylvan.services.section - SectionService fluent builder."""

from __future__ import annotations

import hashlib

import pytest

from sylvan.database.orm import FileRecord, Repo, Section
from sylvan.database.orm.models.blob import Blob
from sylvan.error_codes import ContentNotAvailableError, SectionNotFoundError
from sylvan.services.section import SectionResult, SectionService


async def _seed_repo(ctx, name="test-repo"):
    """Create a repo."""
    backend = ctx.backend
    await backend.execute(
        "INSERT INTO repos (name, source_path, indexed_at, repo_type) "
        f"VALUES ('{name}', '/tmp/{name}', '2024-01-01', 'local')"
    )
    await backend.commit()
    return await Repo.where(name=name).first()


async def _seed_file_with_blob(ctx, repo_id, path="docs/README.md", content=b"# Hello\n\nWorld\n"):
    """Create a file record with a stored blob."""
    content_hash = hashlib.sha256(content).hexdigest()
    backend = ctx.backend
    await backend.execute(
        "INSERT INTO files (repo_id, path, language, content_hash, byte_size) "
        f"VALUES ({repo_id}, '{path}', 'markdown', '{content_hash}', {len(content)})"
    )
    await Blob.store(content_hash, content)
    await backend.commit()
    return await FileRecord.where(path=path).first()


async def _seed_section(
    ctx,
    file_id,
    title="Hello",
    level=1,
    byte_start=0,
    byte_end=7,
    parent_section_id=None,
    path="docs/README.md",
):
    """Create a section."""
    slug = title.lower().replace(" ", "-")
    sec_id = f"test-repo::{path}::{slug}#section"
    ps_val = f"'{parent_section_id}'" if parent_section_id else "NULL"
    backend = ctx.backend
    await backend.execute(
        "INSERT INTO sections (file_id, section_id, title, level, byte_start, byte_end, "
        "parent_section_id, summary) "
        f"VALUES ({file_id}, '{sec_id}', '{title}', {level}, {byte_start}, {byte_end}, "
        f"{ps_val}, 'Summary of {title}')"
    )
    await backend.commit()
    return await Section.where(section_id=sec_id).first()


class TestSectionServiceFind:
    async def test_find_section(self, ctx):
        repo = await _seed_repo(ctx)
        file_rec = await _seed_file_with_blob(ctx, repo.id)
        sec = await _seed_section(ctx, file_rec.id)

        result = await SectionService().find(sec.section_id)
        assert result is not None
        assert isinstance(result, SectionResult)
        assert result.title == "Hello"

    async def test_find_missing(self, ctx):
        with pytest.raises(SectionNotFoundError):
            await SectionService().find("nonexistent::ghost#section")


class TestSectionServiceEnrichment:
    async def test_with_content(self, ctx):
        content = b"# Intro\n\nSome text here.\n"
        repo = await _seed_repo(ctx)
        file_rec = await _seed_file_with_blob(ctx, repo.id, content=content)
        sec = await _seed_section(
            ctx,
            file_rec.id,
            title="Intro",
            byte_start=0,
            byte_end=len(content),
        )

        result = await SectionService().with_content().find(sec.section_id)
        assert result.content is not None
        assert "# Intro" in result.content
        assert "Some text here." in result.content

    async def test_with_content_missing_blob(self, ctx):
        """Section exists but blob does not - raises ContentNotAvailableError."""
        await _seed_repo(ctx)
        backend = ctx.backend
        # Create file without storing blob
        await backend.execute(
            "INSERT INTO files (repo_id, path, language, content_hash, byte_size) "
            "VALUES (1, 'orphan.md', 'markdown', 'missing_hash', 100)"
        )
        await backend.commit()
        file_rec = await FileRecord.where(path="orphan.md").first()
        sec = await _seed_section(
            ctx,
            file_rec.id,
            title="Orphan",
            path="orphan.md",
        )

        with pytest.raises(ContentNotAvailableError):
            await SectionService().with_content().find(sec.section_id)


class TestSectionServiceBatch:
    async def test_find_many(self, ctx):
        content = b"# A\n\n# B\n"
        repo = await _seed_repo(ctx)
        file_rec = await _seed_file_with_blob(ctx, repo.id, content=content)
        sec_a = await _seed_section(ctx, file_rec.id, title="A", byte_start=0, byte_end=4)
        sec_b = await _seed_section(ctx, file_rec.id, title="B", byte_start=5, byte_end=9)

        results = await SectionService().with_content().find_many([sec_a.section_id, sec_b.section_id])
        assert len(results) == 2
        titles = {r.title for r in results}
        assert titles == {"A", "B"}

    async def test_find_many_skips_missing(self, ctx):
        content = b"# Only\n"
        repo = await _seed_repo(ctx)
        file_rec = await _seed_file_with_blob(ctx, repo.id, content=content)
        sec = await _seed_section(ctx, file_rec.id, title="Only", byte_start=0, byte_end=7)

        results = await SectionService().find_many([sec.section_id, "missing::nope#section"])
        assert len(results) == 1


class TestSectionServiceToc:
    async def test_toc(self, ctx):
        content = b"# Root\n\n## Child\n"
        repo = await _seed_repo(ctx)
        file_rec = await _seed_file_with_blob(ctx, repo.id, content=content)
        root = await _seed_section(ctx, file_rec.id, title="Root", level=1, byte_start=0, byte_end=7)
        await _seed_section(
            ctx,
            file_rec.id,
            title="Child",
            level=2,
            byte_start=8,
            byte_end=17,
            parent_section_id=root.section_id,
        )

        toc = await SectionService().toc("test-repo")
        assert toc["section_count"] == 2
        assert toc["repo_name"] == "test-repo"
        titles = [entry["title"] for entry in toc["toc"]]
        assert "Root" in titles
        assert "Child" in titles


class TestSectionResult:
    async def test_repr(self, ctx):
        repo = await _seed_repo(ctx)
        file_rec = await _seed_file_with_blob(ctx, repo.id)
        sec = await _seed_section(ctx, file_rec.id)
        result = SectionResult(sec)
        assert "section" in repr(result)

    async def test_proxies_model_fields(self, ctx):
        repo = await _seed_repo(ctx)
        file_rec = await _seed_file_with_blob(ctx, repo.id)
        sec = await _seed_section(ctx, file_rec.id, title="Proxied", level=2)
        result = SectionResult(sec)
        assert result.title == "Proxied"
        assert result.level == 2
