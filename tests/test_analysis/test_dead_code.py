"""Tests for dead code detection."""

from __future__ import annotations

import os

import pytest

from sylvan.analysis.quality.dead_code import _is_entry_point, find_dead_code
from sylvan.config import reset_config
from sylvan.context import SylvanContext, reset_context, set_context
from sylvan.database.backends.sqlite import SQLiteBackend
from sylvan.database.migrations.runner import run_migrations
from sylvan.database.orm.runtime.query_cache import QueryCache
from sylvan.session.tracker import SessionTracker


class TestIsEntryPoint:
    def test_main(self):
        assert _is_entry_point("main", "app.py") is True

    def test_init(self):
        assert _is_entry_point("__init__", "module.py") is True

    def test_dunder_main(self):
        assert _is_entry_point("__main__", "run.py") is True

    def test_setup(self):
        assert _is_entry_point("setup", "setup.py") is True

    def test_teardown(self):
        assert _is_entry_point("teardown", "test_file.py") is True

    def test_test_prefix(self):
        assert _is_entry_point("test_something", "test_module.py") is True

    def test_test_class_prefix(self):
        assert _is_entry_point("TestFoo", "test_module.py") is True

    def test_cli_file(self):
        assert _is_entry_point("run", "cli.py") is True

    def test_server_file(self):
        assert _is_entry_point("start", "server.py") is True

    def test_app_file(self):
        assert _is_entry_point("create", "app.py") is True

    def test_main_py_file(self):
        assert _is_entry_point("run", "__main__.py") is True

    def test_private_single_underscore(self):
        assert _is_entry_point("_helper", "utils.py") is True

    def test_dunder_not_private(self):
        assert _is_entry_point("__init__", "module.py") is True

    def test_regular_function_not_entry(self):
        assert _is_entry_point("calculate", "math_utils.py") is False

    def test_regular_name_regular_file(self):
        assert _is_entry_point("process_data", "processor.py") is False


class TestFindDeadCode:
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

        # Seed: repo, file, symbols, references
        await self.backend.execute(
            "INSERT INTO repos (id, name, source_path, indexed_at) VALUES (1, 'myrepo', '/tmp/repo', '2024-01-01')"
        )
        await self.backend.execute(
            "INSERT INTO files (id, repo_id, path, language, content_hash, byte_size) "
            "VALUES (1, 1, 'utils.py', 'python', 'hash1', 200)"
        )

        await self.backend.execute(
            "INSERT INTO symbols (file_id, symbol_id, name, qualified_name, kind, language, signature, byte_offset, byte_length) "
            "VALUES (1, 'utils.py::used_func#function', 'used_func', 'used_func', 'function', 'python', 'def used_func()', 0, 50)"
        )
        await self.backend.execute(
            "INSERT INTO symbols (file_id, symbol_id, name, qualified_name, kind, language, signature, byte_offset, byte_length) "
            "VALUES (1, 'utils.py::dead_func#function', 'dead_func', 'dead_func', 'function', 'python', 'def dead_func()', 50, 50)"
        )
        await self.backend.execute(
            "INSERT INTO symbols (file_id, symbol_id, name, qualified_name, kind, language, signature, byte_offset, byte_length) "
            "VALUES (1, 'utils.py::main#function', 'main', 'main', 'function', 'python', 'def main()', 100, 50)"
        )
        await self.backend.execute(
            "INSERT INTO symbols (file_id, symbol_id, name, qualified_name, kind, language, signature, byte_offset, byte_length) "
            "VALUES (1, 'utils.py::test_foo#function', 'test_foo', 'test_foo', 'function', 'python', 'def test_foo()', 150, 50)"
        )

        await self.backend.execute(
            "INSERT INTO \"references\" (source_symbol_id, target_symbol_id, target_specifier) "
            "VALUES ('utils.py::caller#function', 'utils.py::used_func#function', 'used_func')"
        )

        await self.backend.commit()
        yield
        reset_context(self.token)
        await self.backend.disconnect()
        os.environ.pop("SYLVAN_HOME", None)
        reset_config()

    async def test_finds_unreferenced_symbols(self):
        dead = await find_dead_code("myrepo")
        dead_names = [d["name"] for d in dead]
        assert "dead_func" in dead_names

    async def test_excludes_referenced_symbols(self):
        dead = await find_dead_code("myrepo")
        dead_names = [d["name"] for d in dead]
        assert "used_func" not in dead_names

    async def test_excludes_main_entry_point(self):
        dead = await find_dead_code("myrepo")
        dead_names = [d["name"] for d in dead]
        assert "main" not in dead_names

    async def test_excludes_test_functions(self):
        dead = await find_dead_code("myrepo")
        dead_names = [d["name"] for d in dead]
        assert "test_foo" not in dead_names

    async def test_default_kinds_function_method(self):
        dead = await find_dead_code("myrepo")
        for d in dead:
            assert d["kind"] in ("function", "method")

    async def test_wrong_repo_returns_empty(self):
        dead = await find_dead_code("nonexistent")
        assert dead == []
