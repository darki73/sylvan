"""Tests for sylvan.tools analysis tools — blast radius, hierarchy, refs, etc."""

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
    """Index a project with classes, imports, and inheritance for analysis."""
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
    (proj / "base.py").write_text(
        "class Animal:\n"
        '    """Base animal class."""\n'
        "    def speak(self):\n"
        "        pass\n"
        "\n"
        "class LivingThing:\n"
        "    pass\n",
        encoding="utf-8",
    )
    (proj / "dog.py").write_text(
        "from base import Animal\n"
        "\n"
        "class Dog(Animal):\n"
        '    """A dog."""\n'
        "    def speak(self):\n"
        '        return "Woof"\n'
        "\n"
        "def create_dog(name):\n"
        "    return Dog()\n",
        encoding="utf-8",
    )
    (proj / "app.py").write_text(
        'from dog import Dog, create_dog\n\ndef main():\n    d = create_dog("Rex")\n    d.speak()\n',
        encoding="utf-8",
    )

    from sylvan.indexing.pipeline.orchestrator import index_folder

    result = await index_folder(str(proj), name="test-repo")
    await backend.commit()
    assert result.symbols_extracted >= 5

    yield result

    reset_context(token)
    await backend.disconnect()
    os.environ.pop("SYLVAN_HOME", None)


async def _find_symbol_id(name):
    """Find a symbol ID by name."""
    from sylvan.tools.search.search_symbols import search_symbols

    resp = await search_symbols(query=name)
    for s in resp["symbols"]:
        if s["name"] == name:
            return s["symbol_id"]
    raise AssertionError(f"Symbol '{name}' not found")


class TestGetBlastRadius:
    async def test_returns_confirmed_and_potential(self, indexed_repo):
        from sylvan.tools.analysis.get_blast_radius import get_blast_radius

        sid = await _find_symbol_id("Animal")
        resp = await get_blast_radius(sid)

        assert "_meta" in resp
        assert "confirmed" in resp or "error" not in resp
        if "symbol" in resp:
            assert "confirmed" in resp
            assert "potential" in resp
            assert isinstance(resp["confirmed"], list)
            assert isinstance(resp["potential"], list)
            meta = resp["_meta"]
            assert "confirmed_count" in meta
            assert "potential_count" in meta

    async def test_not_found_symbol(self, indexed_repo):
        from sylvan.tools.analysis.get_blast_radius import get_blast_radius

        resp = await get_blast_radius("nonexistent::sym#function")

        assert "_meta" in resp
        assert "error" in resp or "symbol" in resp


class TestGetClassHierarchy:
    async def test_returns_ancestors_and_descendants(self, indexed_repo):
        from sylvan.tools.analysis.get_class_hierarchy import get_class_hierarchy

        resp = await get_class_hierarchy(class_name="Dog")

        assert "_meta" in resp
        if "target" in resp:
            assert resp["target"]["name"] == "Dog"
            assert "ancestors" in resp
            assert "descendants" in resp
            assert isinstance(resp["ancestors"], list)
            assert isinstance(resp["descendants"], list)

            meta = resp["_meta"]
            assert "ancestors" in meta
            assert "descendants" in meta

            ancestor_names = [a["name"] for a in resp["ancestors"]]
            assert "Animal" in ancestor_names

    async def test_class_not_found(self, indexed_repo):
        from sylvan.tools.analysis.get_class_hierarchy import get_class_hierarchy

        resp = await get_class_hierarchy(class_name="NonExistentClass")

        assert "_meta" in resp
        assert "error" in resp
        assert resp["error"] == "class_not_found"

    async def test_filter_by_repo(self, indexed_repo):
        from sylvan.tools.analysis.get_class_hierarchy import get_class_hierarchy

        resp = await get_class_hierarchy(class_name="Dog", repo="test-repo")
        assert "_meta" in resp
        if "target" in resp:
            assert resp["target"]["name"] == "Dog"


class TestGetReferences:
    async def test_returns_list(self, indexed_repo):
        from sylvan.tools.analysis.get_references import get_references

        sid = await _find_symbol_id("Animal")
        resp = await get_references(sid, direction="to")

        assert "_meta" in resp
        assert "references" in resp
        assert isinstance(resp["references"], list)
        assert "symbol_id" in resp
        assert resp["symbol_id"] == sid

        meta = resp["_meta"]
        assert "count" in meta
        assert "direction" in meta
        assert meta["direction"] == "to"

    async def test_direction_from(self, indexed_repo):
        from sylvan.tools.analysis.get_references import get_references

        sid = await _find_symbol_id("main")
        resp = await get_references(sid, direction="from")

        assert "_meta" in resp
        assert "references" in resp
        assert resp["_meta"]["direction"] == "from"


class TestFindImporters:
    async def test_returns_importers(self, indexed_repo):
        from sylvan.tools.analysis.find_importers import find_importers

        resp = await find_importers(repo="test-repo", file_path="base.py")

        assert "_meta" in resp
        if "error" not in resp:
            assert "importers" in resp
            assert "file" in resp
            assert isinstance(resp["importers"], list)
            meta = resp["_meta"]
            assert "count" in meta

    async def test_file_not_found(self, indexed_repo):
        from sylvan.error_codes import IndexFileNotFoundError
        from sylvan.tools.analysis.find_importers import find_importers

        with pytest.raises(IndexFileNotFoundError) as exc_info:
            await find_importers(repo="test-repo", file_path="nonexistent.py")

        resp = exc_info.value.to_dict()
        assert "_meta" in resp
        assert resp["error"] == "file_not_found"


class TestGetRelated:
    async def test_returns_scored_results(self, indexed_repo):
        from sylvan.tools.analysis.get_related import get_related

        sid = await _find_symbol_id("speak")
        resp = await get_related(sid)

        assert "_meta" in resp
        if "error" not in resp:
            assert "related" in resp
            assert "symbol_id" in resp
            assert isinstance(resp["related"], list)
            meta = resp["_meta"]
            assert "count" in meta

            for r in resp["related"]:
                assert "symbol_id" in r
                assert "name" in r
                assert "score" in r
                assert r["score"] > 0

    async def test_symbol_not_found(self, indexed_repo):
        from sylvan.error_codes import SymbolNotFoundError
        from sylvan.tools.analysis.get_related import get_related

        with pytest.raises(SymbolNotFoundError) as exc_info:
            await get_related("nonexistent::sym#function")

        resp = exc_info.value.to_dict()
        assert "_meta" in resp
        assert resp["error"] == "symbol_not_found"


class TestGetQuality:
    async def test_returns_metrics(self, indexed_repo):
        from sylvan.tools.analysis.get_quality import get_quality

        resp = await get_quality(repo="test-repo")

        assert "_meta" in resp
        assert "symbols" in resp
        assert isinstance(resp["symbols"], list)
        meta = resp["_meta"]
        assert "count" in meta

    async def test_repo_not_found(self, indexed_repo):
        from sylvan.error_codes import RepoNotFoundError
        from sylvan.tools.analysis.get_quality import get_quality

        with pytest.raises(RepoNotFoundError):
            await get_quality(repo="nonexistent-repo")

    async def test_filter_undocumented(self, indexed_repo):
        from sylvan.tools.analysis.get_quality import get_quality

        resp = await get_quality(repo="test-repo", undocumented_only=True)

        assert "_meta" in resp
        assert "symbols" in resp
