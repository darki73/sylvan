"""Tests for sylvan.tools.analysis.search_columns."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from sylvan.config import reset_config
from sylvan.context import SylvanContext, reset_context, set_context
from sylvan.database.backends.sqlite import SQLiteBackend
from sylvan.database.migrations.runner import run_migrations
from sylvan.database.orm.runtime.query_cache import QueryCache
from sylvan.session.tracker import SessionTracker, reset_session


@pytest.fixture
async def indexed_repo(tmp_path):
    """Index a minimal project for column search tests."""
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
    (proj / "model.py").write_text("x = 1\n", encoding="utf-8")

    from sylvan.indexing.pipeline.orchestrator import index_folder

    await index_folder(str(proj), name="col-repo")
    await backend.commit()

    yield proj

    reset_context(token)
    await backend.disconnect()
    os.environ.pop("SYLVAN_HOME", None)


class _FakeProvider:
    """Fake ecosystem context provider for testing."""

    @property
    def name(self) -> str:
        return "fake"

    def get_metadata(self) -> dict:
        return {
            "dbt_columns": {
                "orders": {
                    "order_id": "Primary key for orders",
                    "customer_id": "FK to customers",
                    "amount": "Order total amount",
                },
                "customers": {
                    "customer_id": "Primary key",
                    "email": "Customer email address",
                },
            },
        }


class TestSearchColumns:
    async def test_repo_not_found(self, indexed_repo):
        from sylvan.error_codes import RepoNotFoundError
        from sylvan.tools.analysis.search_columns import SearchColumns

        with pytest.raises(RepoNotFoundError):
            await SearchColumns().execute({"repo": "nonexistent", "query": "id"})

    async def test_no_providers(self, indexed_repo):
        from sylvan.tools.analysis.search_columns import SearchColumns

        with patch("sylvan.providers.ecosystem_context.base.discover_providers", return_value=[]):
            resp = await SearchColumns().execute({"repo": "col-repo", "query": "id"})

        assert "_meta" in resp
        assert resp["columns"] == []
        assert "No ecosystem context providers" in resp.get("message", "")

    async def test_finds_matching_columns(self, indexed_repo):
        from sylvan.tools.analysis.search_columns import SearchColumns

        fake = _FakeProvider()
        with patch("sylvan.providers.ecosystem_context.base.discover_providers", return_value=[fake]):
            resp = await SearchColumns().execute({"repo": "col-repo", "query": "customer_id"})

        assert "_meta" in resp
        assert len(resp["columns"]) >= 1
        col_names = [c["column"] for c in resp["columns"]]
        assert "customer_id" in col_names

    async def test_model_pattern_filter(self, indexed_repo):
        from sylvan.tools.analysis.search_columns import SearchColumns

        fake = _FakeProvider()
        with patch("sylvan.providers.ecosystem_context.base.discover_providers", return_value=[fake]):
            resp = await SearchColumns().execute({"repo": "col-repo", "query": "id", "model_pattern": "orders"})

        assert "_meta" in resp
        for col in resp["columns"]:
            assert col["model"] == "orders"

    async def test_max_results_respected(self, indexed_repo):
        from sylvan.tools.analysis.search_columns import SearchColumns

        fake = _FakeProvider()
        with patch("sylvan.providers.ecosystem_context.base.discover_providers", return_value=[fake]):
            resp = await SearchColumns().execute({"repo": "col-repo", "query": "id", "max_results": 1})

        assert len(resp["columns"]) <= 1

    async def test_meta_includes_provider_info(self, indexed_repo):
        from sylvan.tools.analysis.search_columns import SearchColumns

        fake = _FakeProvider()
        with patch("sylvan.providers.ecosystem_context.base.discover_providers", return_value=[fake]):
            resp = await SearchColumns().execute({"repo": "col-repo", "query": "email"})

        meta = resp["_meta"]
        assert "results_count" in meta
        assert "providers_found" in meta
        assert meta["providers_found"] == 1
        assert "fake" in meta["providers"]


class TestMatchScore:
    def test_exact_match(self):
        from sylvan.services.analysis import _match_score

        assert _match_score("foo", "foo") == 1.0

    def test_substring_match(self):
        from sylvan.services.analysis import _match_score

        score = _match_score("cust", "customer_id")
        assert score == 0.8

    def test_no_match(self):
        from sylvan.services.analysis import _match_score

        score = _match_score("zzz", "abc")
        assert score == 0.0

    def test_partial_word_match(self):
        from sylvan.services.analysis import _match_score

        score = _match_score("customer email", "Customer email address")
        assert score > 0.0
