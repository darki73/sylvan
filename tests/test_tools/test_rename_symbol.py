"""Tests for sylvan.tools.analysis.rename_symbol — MCP tool wrapper."""

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
    """Index a project with cross-file references for rename testing."""
    os.environ["SYLVAN_HOME"] = str(tmp_path)
    config_path = tmp_path / "config.toml"
    config_path.write_text('[embedding]\nprovider = "none"\n', encoding="utf-8")
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
    (proj / "models.py").write_text(
        'class UserAccount:\n'
        '    """A user account."""\n'
        '    def get_name(self):\n'
        '        return self.name\n',
        encoding="utf-8",
    )
    (proj / "views.py").write_text(
        'from models import UserAccount\n'
        '\n'
        'def show_user():\n'
        '    account = UserAccount()\n'
        '    return account.get_name()\n',
        encoding="utf-8",
    )

    from sylvan.indexing.pipeline.orchestrator import index_folder
    result = await index_folder(str(proj), name="test-repo")
    await backend.commit()
    assert result.symbols_extracted >= 3

    yield result

    reset_context(token)
    await backend.disconnect()
    os.environ.pop("SYLVAN_HOME", None)


async def _find_symbol_id(name: str) -> str:
    """Find a symbol ID by name."""
    from sylvan.tools.search.search_symbols import search_symbols
    resp = await search_symbols(query=name)
    for s in resp["symbols"]:
        if s["name"] == name:
            return s["symbol_id"]
    raise AssertionError(f"Symbol '{name}' not found")


class TestRenameSymbolBasic:
    async def test_returns_edits_for_target_file(self, indexed_repo):
        from sylvan.tools.analysis.rename_symbol import rename_symbol
        sid = await _find_symbol_id("UserAccount")
        resp = await rename_symbol(symbol_id=sid, new_name="CustomerAccount")

        assert "_meta" in resp
        assert "edits" in resp
        assert "symbol" in resp
        assert isinstance(resp["edits"], list)
        assert len(resp["edits"]) >= 1

        meta = resp["_meta"]
        assert "affected_files" in meta
        assert "total_edits" in meta
        assert meta["old_name"] == "UserAccount"
        assert meta["new_name"] == "CustomerAccount"

        # Verify edit structure
        edit = resp["edits"][0]
        assert "file" in edit
        assert "line" in edit
        assert "old_text" in edit
        assert "new_text" in edit
        assert "UserAccount" in edit["old_text"]
        assert "CustomerAccount" in edit["new_text"]

    async def test_rename_finds_edits_in_defining_file(self, indexed_repo):
        from sylvan.tools.analysis.rename_symbol import rename_symbol
        sid = await _find_symbol_id("UserAccount")
        resp = await rename_symbol(symbol_id=sid, new_name="CustomerAccount")

        assert "_meta" in resp
        assert "edits" in resp

        # At minimum, the defining file should have edits
        meta = resp["_meta"]
        assert meta["affected_files"] >= 1
        assert meta["total_edits"] >= 1

        # All edits should replace old name with new name
        for edit in resp["edits"]:
            assert "UserAccount" not in edit["new_text"] or "CustomerAccount" in edit["new_text"]

    async def test_symbol_info_in_response(self, indexed_repo):
        from sylvan.tools.analysis.rename_symbol import rename_symbol
        sid = await _find_symbol_id("UserAccount")
        resp = await rename_symbol(symbol_id=sid, new_name="CustomerAccount")

        sym = resp["symbol"]
        assert sym["symbol_id"] == sid
        assert sym["name"] == "UserAccount"
        assert "kind" in sym
        assert "file" in sym
        assert "line_start" in sym
        assert "line_end" in sym


class TestRenameSymbolErrors:
    async def test_symbol_not_found(self, indexed_repo):
        from sylvan.tools.analysis.rename_symbol import rename_symbol
        resp = await rename_symbol(
            symbol_id="nonexistent::sym#function",
            new_name="new_name",
        )

        assert "_meta" in resp
        assert resp["error"] == "symbol_not_found"

    async def test_same_name_returns_error(self, indexed_repo):
        from sylvan.tools.analysis.rename_symbol import rename_symbol
        sid = await _find_symbol_id("UserAccount")
        resp = await rename_symbol(symbol_id=sid, new_name="UserAccount")

        assert "_meta" in resp
        assert resp["error"] == "same_name"

    async def test_invalid_identifier_returns_error(self, indexed_repo):
        from sylvan.tools.analysis.rename_symbol import rename_symbol
        sid = await _find_symbol_id("UserAccount")
        resp = await rename_symbol(symbol_id=sid, new_name="123bad")

        assert "_meta" in resp
        assert resp["error"] == "invalid_name"

    async def test_empty_name_returns_error(self, indexed_repo):
        from sylvan.tools.analysis.rename_symbol import rename_symbol
        sid = await _find_symbol_id("UserAccount")
        resp = await rename_symbol(symbol_id=sid, new_name="")

        assert "_meta" in resp
        assert resp["error"] == "invalid_name"
