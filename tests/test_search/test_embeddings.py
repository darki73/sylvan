"""Tests for sylvan.search.embeddings — vec conversion, text preparation, store functions."""

from __future__ import annotations

import struct

import pytest

from sylvan.context import SylvanContext, reset_context, set_context
from sylvan.database.backends.sqlite import SQLiteBackend
from sylvan.database.migrations.runner import run_migrations
from sylvan.database.orm.runtime.query_cache import QueryCache
from sylvan.search.embeddings import (
    _blob_to_vec,
    _vec_to_blob,
    embed_and_store_sections,
    embed_and_store_symbols,
    prepare_section_text,
    prepare_symbol_text,
)
from sylvan.session.tracker import SessionTracker


class TestVecToBlob:
    def test_roundtrip(self):
        original = [1.0, 2.5, -3.7, 0.0]
        blob = _vec_to_blob(original)
        restored = _blob_to_vec(blob)
        assert len(restored) == len(original)
        for a, b in zip(original, restored):
            assert abs(a - b) < 1e-6

    def test_empty_vector(self):
        blob = _vec_to_blob([])
        assert blob == b""
        assert _blob_to_vec(b"") == []

    def test_single_element(self):
        blob = _vec_to_blob([42.0])
        assert len(blob) == 4  # one float32
        restored = _blob_to_vec(blob)
        assert abs(restored[0] - 42.0) < 1e-6

    def test_blob_format(self):
        vec = [1.0, 2.0]
        blob = _vec_to_blob(vec)
        expected = struct.pack("2f", 1.0, 2.0)
        assert blob == expected


class TestPrepareSymbolText:
    def test_all_fields(self):
        sym = {
            "qualified_name": "module.MyClass",
            "signature": "class MyClass(Base):",
            "docstring": "A cool class.",
            "summary": "Represents a thing.",
            "name": "MyClass",
        }
        text = prepare_symbol_text(sym)
        assert "module.MyClass" in text
        assert "class MyClass(Base):" in text
        assert "A cool class." in text
        assert "Represents a thing." in text

    def test_minimal_fields(self):
        sym = {"name": "foo"}
        text = prepare_symbol_text(sym)
        assert text == "foo"

    def test_empty_dict(self):
        text = prepare_symbol_text({})
        assert text == ""

    def test_docstring_truncated(self):
        sym = {"docstring": "x" * 1000}
        text = prepare_symbol_text(sym)
        assert len(text) <= 500

    def test_no_name_fallback(self):
        sym = {"qualified_name": "a.b.c"}
        text = prepare_symbol_text(sym)
        assert text == "a.b.c"


class TestPrepareSectionText:
    def test_both_fields(self):
        sec = {"title": "Introduction", "summary": "Overview of the project."}
        text = prepare_section_text(sec)
        assert "Introduction" in text
        assert "Overview" in text

    def test_title_only(self):
        sec = {"title": "Chapter 1"}
        text = prepare_section_text(sec)
        assert text == "Chapter 1"

    def test_empty_dict(self):
        text = prepare_section_text({})
        assert text == ""


@pytest.fixture
async def embed_ctx(tmp_path):
    """Backend + context for embedding store tests."""
    db_path = tmp_path / "embed_test.db"
    backend = SQLiteBackend(db_path)
    await backend.connect()
    await run_migrations(backend)
    # Recreate vec tables with 4 dimensions to match FakeEmbeddingProvider
    try:
        await backend.execute("DROP TABLE IF EXISTS symbols_vec")
        await backend.execute("DROP TABLE IF EXISTS sections_vec")
        await backend.execute(
            "CREATE VIRTUAL TABLE symbols_vec USING vec0(symbol_id TEXT PRIMARY KEY, embedding float[4])",
            [],
        )
        await backend.execute(
            "CREATE VIRTUAL TABLE sections_vec USING vec0(section_id TEXT PRIMARY KEY, embedding float[4])",
            [],
        )
    except Exception:
        pytest.skip("sqlite-vec not available for vec table creation")

    ctx = SylvanContext(
        backend=backend,
        session=SessionTracker(),
        cache=QueryCache(),
    )
    token = set_context(ctx)
    yield ctx
    reset_context(token)
    await backend.disconnect()


class FakeEmbeddingProvider:
    """A mock embedding provider that returns fixed-size vectors."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

    def embed_one(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3, 0.4]


class FailingEmbeddingProvider:
    """A mock provider that always raises."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("Embedding failed")


class TestEmbedAndStoreSymbols:
    async def test_stores_embeddings(self, embed_ctx):
        provider = FakeEmbeddingProvider()
        stored = await embed_and_store_symbols(
            provider,
            symbol_ids=["sym1", "sym2", "sym3"],
            texts=["hello", "world", "test"],
            batch_size=2,
        )
        assert stored == 3

    async def test_handles_provider_failure(self, embed_ctx):
        provider = FailingEmbeddingProvider()
        stored = await embed_and_store_symbols(
            provider,
            symbol_ids=["sym1"],
            texts=["hello"],
        )
        assert stored == 0

    async def test_empty_input(self, embed_ctx):
        provider = FakeEmbeddingProvider()
        stored = await embed_and_store_symbols(provider, [], [])
        assert stored == 0


class TestEmbedAndStoreSections:
    async def test_stores_embeddings(self, embed_ctx):
        provider = FakeEmbeddingProvider()
        stored = await embed_and_store_sections(
            provider,
            section_ids=["sec1", "sec2"],
            texts=["intro", "body"],
        )
        assert stored == 2

    async def test_handles_provider_failure(self, embed_ctx):
        provider = FailingEmbeddingProvider()
        stored = await embed_and_store_sections(
            provider,
            section_ids=["sec1"],
            texts=["intro"],
        )
        assert stored == 0
