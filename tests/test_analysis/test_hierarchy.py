"""Tests for class hierarchy analysis."""

from __future__ import annotations

import os

import pytest

from sylvan.analysis.structure.class_hierarchy import _extract_bases, get_class_hierarchy
from sylvan.config import reset_config
from sylvan.context import SylvanContext, reset_context, set_context
from sylvan.database.backends.sqlite import SQLiteBackend
from sylvan.database.migrations.runner import run_migrations
from sylvan.database.orm.runtime.query_cache import QueryCache
from sylvan.session.tracker import SessionTracker


class TestExtractBases:
    def test_python_single_base(self):
        sig = "class Foo(Bar)"
        assert _extract_bases(sig) == ["Bar"]

    def test_python_multiple_bases(self):
        sig = "class Foo(Bar, Baz)"
        bases = _extract_bases(sig)
        assert "Bar" in bases
        assert "Baz" in bases

    def test_python_object_filtered(self):
        sig = "class Foo(object)"
        assert _extract_bases(sig) == []

    def test_js_extends(self):
        sig = "class Child extends Parent"
        assert _extract_bases(sig) == ["Parent"]

    def test_cpp_public_base(self):
        sig = "class Derived : public Base"
        assert _extract_bases(sig) == ["Base"]

    def test_empty_signature(self):
        assert _extract_bases("") == []

    def test_no_base_class(self):
        sig = "class Standalone"
        assert _extract_bases(sig) == []

    def test_python_generics_stripped(self):
        sig = "class Foo(Generic[T], Bar)"
        bases = _extract_bases(sig)
        assert "Bar" in bases

    def test_implements_keyword(self):
        sig = "class Foo implements Serializable"
        bases = _extract_bases(sig)
        assert "Serializable" in bases


class TestGetClassHierarchy:
    @pytest.fixture(autouse=True)
    async def _setup_db(self, tmp_path):
        os.environ["SYLVAN_HOME"] = str(tmp_path)
        reset_config()

        db_path = tmp_path / "test.db"
        self.backend = SQLiteBackend(db_path)
        await self.backend.connect()
        await run_migrations(self.backend)

        context = SylvanContext(
            backend=self.backend,
            session=SessionTracker(),
            cache=QueryCache(),
        )
        self.token = set_context(context)

        # Seed data: repo, files, and a class hierarchy
        # Animal -> Dog -> GoldenRetriever
        await self.backend.execute(
            "INSERT INTO repos (id, name, source_path, indexed_at) VALUES (1, 'myrepo', '/tmp/repo', '2024-01-01')"
        )
        await self.backend.execute(
            "INSERT INTO files (id, repo_id, path, language, content_hash, byte_size) "
            "VALUES (1, 1, 'animals.py', 'python', 'hash1', 100)"
        )
        await self.backend.execute(
            "INSERT INTO symbols (file_id, symbol_id, name, qualified_name, kind, language, signature, byte_offset, byte_length) "
            "VALUES (1, 'animals.py::Animal#class', 'Animal', 'Animal', 'class', 'python', 'class Animal', 0, 50)"
        )
        await self.backend.execute(
            "INSERT INTO symbols (file_id, symbol_id, name, qualified_name, kind, language, signature, byte_offset, byte_length) "
            "VALUES (1, 'animals.py::Dog#class', 'Dog', 'Dog', 'class', 'python', 'class Dog(Animal)', 50, 50)"
        )
        await self.backend.execute(
            "INSERT INTO symbols (file_id, symbol_id, name, qualified_name, kind, language, signature, byte_offset, byte_length) "
            "VALUES (1, 'animals.py::GoldenRetriever#class', 'GoldenRetriever', 'GoldenRetriever', 'class', 'python', 'class GoldenRetriever(Dog)', 100, 50)"
        )
        await self.backend.commit()
        yield
        reset_context(self.token)
        await self.backend.disconnect()
        os.environ.pop("SYLVAN_HOME", None)
        reset_config()

    async def test_finds_target(self):
        result = await get_class_hierarchy("Dog")
        assert result["target"]["name"] == "Dog"

    async def test_finds_ancestors(self):
        result = await get_class_hierarchy("Dog")
        ancestor_names = [a["name"] for a in result["ancestors"]]
        assert "Animal" in ancestor_names

    async def test_finds_descendants(self):
        result = await get_class_hierarchy("Dog")
        desc_names = [d["name"] for d in result["descendants"]]
        assert "GoldenRetriever" in desc_names

    async def test_class_not_found(self):
        result = await get_class_hierarchy("NonExistent")
        assert result.get("error") == "class_not_found"

    async def test_root_class_no_ancestors_in_index(self):
        result = await get_class_hierarchy("Animal")
        assert result["ancestors"] == []

    async def test_leaf_class_no_descendants(self):
        result = await get_class_hierarchy("GoldenRetriever")
        assert result["descendants"] == []

    async def test_with_repo_filter(self):
        result = await get_class_hierarchy("Dog", repo_name="myrepo")
        assert result["target"]["name"] == "Dog"

    async def test_with_wrong_repo_filter(self):
        result = await get_class_hierarchy("Dog", repo_name="other_repo")
        assert result.get("error") == "class_not_found"
