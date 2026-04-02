"""Tests for sylvan.tools section tools — search_sections, get_section, get_toc."""

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
async def indexed_repo(tmp_path):
    """Create backend + context and index a project with documentation files."""
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

    proj = tmp_path / "project"
    proj.mkdir()
    (proj / "main.py").write_text(
        "def hello(): pass\n",
        encoding="utf-8",
    )
    (proj / "README.md").write_text(
        "# My Project\n\nA great project.\n\n"
        "## Installation\n\nRun pip install.\n\n"
        "## Usage\n\nImport and use the library.\n\n"
        "### Advanced Usage\n\nFor power users.\n",
        encoding="utf-8",
    )
    (proj / "docs.md").write_text(
        "# API Reference\n\nAPI docs here.\n\n## Endpoints\n\nList of endpoints.\n",
        encoding="utf-8",
    )

    from sylvan.indexing.pipeline.orchestrator import index_folder

    result = await index_folder(str(proj), name="test-repo")
    await backend.commit()
    assert result.sections_extracted >= 3

    yield result

    reset_context(token)
    await backend.disconnect()
    os.environ.pop("SYLVAN_HOME", None)


async def _get_section_ids():
    """Helper: get available section IDs via get_toc."""
    from sylvan.tools.browsing.get_toc import GetToc

    resp = await GetToc().execute({"repo": "test-repo"})
    return [entry["section_id"] for entry in resp["toc"]]


class TestSearchSections:
    async def test_returns_results(self, indexed_repo):
        from sylvan.tools.search.search_sections import search_sections

        resp = await search_sections(query="Installation")

        assert "sections" in resp
        assert "_meta" in resp
        assert len(resp["sections"]) >= 1

        sec = resp["sections"][0]
        assert "section_id" in sec
        assert "title" in sec
        assert "level" in sec
        assert "doc_path" in sec
        assert "repo" in sec

    async def test_empty_query_returns_error(self, indexed_repo):
        from sylvan.error_codes import EmptyQueryError
        from sylvan.tools.search.search_sections import search_sections

        with pytest.raises(EmptyQueryError) as exc_info:
            await search_sections(query="")

        resp = exc_info.value.to_dict()
        assert resp["error"] == "empty_query"

    async def test_meta_has_results_count(self, indexed_repo):
        from sylvan.tools.search.search_sections import search_sections

        resp = await search_sections(query="Usage")
        meta = resp["_meta"]
        assert "results_count" in meta
        assert "query" in meta


class TestGetSection:
    async def test_returns_content_with_savings(self, indexed_repo):
        section_ids = await _get_section_ids()
        assert len(section_ids) >= 1

        from sylvan.tools.browsing.get_section import GetSection

        resp = await GetSection().execute({"section_id": section_ids[0]})

        assert "content" in resp
        assert "title" in resp
        assert "level" in resp
        assert "doc_path" in resp
        assert "repo" in resp
        assert "section_id" in resp
        assert "_meta" in resp

        meta = resp["_meta"]
        assert "timing_ms" in meta
        if "savings" in meta:
            assert "returned_bytes" in meta["savings"]
            assert "total_file_bytes" in meta["savings"]

    async def test_section_not_found(self, indexed_repo):
        from sylvan.error_codes import SectionNotFoundError
        from sylvan.tools.browsing.get_section import GetSection

        with pytest.raises(SectionNotFoundError) as exc_info:
            await GetSection().execute({"section_id": "nonexistent-section-id"})

        resp = exc_info.value.to_dict()
        assert resp["error"] == "section_not_found"


class TestGetSectionsBatch:
    async def test_batch_returns_multiple(self, indexed_repo):
        section_ids = await _get_section_ids()
        assert len(section_ids) >= 2

        from sylvan.tools.browsing.get_section import GetSections

        resp = await GetSections().execute({"section_ids": section_ids[:2]})

        assert "sections" in resp
        assert "not_found" in resp
        assert "_meta" in resp
        assert len(resp["sections"]) == 2
        assert resp["_meta"]["found"] == 2

        for s in resp["sections"]:
            assert "section_id" in s
            assert "title" in s
            assert "content" in s

    async def test_batch_with_not_found(self, indexed_repo):
        section_ids = await _get_section_ids()
        fake_id = "fake-section-abc"

        from sylvan.tools.browsing.get_section import GetSections

        resp = await GetSections().execute({"section_ids": [section_ids[0], fake_id]})

        assert resp["_meta"]["found"] == 1
        assert resp["_meta"]["not_found_count"] == 1
        assert fake_id in resp["not_found"]


class TestGetToc:
    async def test_returns_hierarchy(self, indexed_repo):
        from sylvan.tools.browsing.get_toc import GetToc

        resp = await GetToc().execute({"repo": "test-repo"})

        assert "toc" in resp
        assert "_meta" in resp
        assert len(resp["toc"]) >= 3

        entry = resp["toc"][0]
        assert "section_id" in entry
        assert "title" in entry
        assert "level" in entry
        assert "doc_path" in entry
        assert "summary" in entry

        meta = resp["_meta"]
        assert "section_count" in meta
        assert meta["section_count"] >= 3

    async def test_toc_with_doc_path_filter(self, indexed_repo):
        from sylvan.tools.browsing.get_toc import GetToc

        resp = await GetToc().execute({"repo": "test-repo", "doc_path": "README.md"})

        assert "toc" in resp
        for entry in resp["toc"]:
            assert entry["doc_path"] == "README.md"


class TestGetTocTree:
    async def test_returns_nested_structure(self, indexed_repo):
        from sylvan.tools.browsing.get_toc import GetTocTree

        resp = await GetTocTree().execute({"repo": "test-repo"})

        assert "tree" in resp
        assert "_meta" in resp
        assert len(resp["tree"]) >= 1

        meta = resp["_meta"]
        assert "document_count" in meta
        assert "section_count" in meta

        doc = resp["tree"][0]
        assert "doc_path" in doc
        assert "sections" in doc
        assert isinstance(doc["sections"], list)
        assert len(doc["sections"]) >= 1

        section = doc["sections"][0]
        assert "section_id" in section
        assert "title" in section
        assert "level" in section
        assert "children" in section
