"""Tests for sylvan.database.connection — sync SQLite connection factory."""

from __future__ import annotations

import os
import sqlite3

import pytest

from sylvan.config import reset_config
from sylvan.database.connection import get_connection


@pytest.fixture
def isolated_home(tmp_path):
    """Point SYLVAN_HOME to a temp dir so get_connection uses a temp DB."""
    home = tmp_path / ".sylvan"
    home.mkdir()
    os.environ["SYLVAN_HOME"] = str(home)
    reset_config()
    yield home
    os.environ.pop("SYLVAN_HOME", None)
    reset_config()


class TestGetConnection:
    def test_returns_connection(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        assert isinstance(conn, sqlite3.Connection)
        conn.close()

    def test_wal_mode(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"
        conn.close()

    def test_foreign_keys_on(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        assert fk == 1
        conn.close()

    def test_row_factory(self, tmp_path):
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        assert conn.row_factory == sqlite3.Row
        conn.close()

    def test_creates_parent_dirs(self, tmp_path):
        db_path = tmp_path / "nested" / "deep" / "test.db"
        conn = get_connection(db_path)
        assert db_path.parent.exists()
        conn.close()

    def test_sqlite_vec_loaded(self, tmp_path):
        """sqlite-vec extension should be loadable and working."""
        db_path = tmp_path / "test.db"
        conn = get_connection(db_path)
        # vec_version() is available when sqlite-vec is loaded
        row = conn.execute("SELECT vec_version()").fetchone()
        assert row is not None
        conn.close()

    def test_default_path_from_config(self, isolated_home):
        """When no db_path given, uses config default."""
        conn = get_connection()
        assert isinstance(conn, sqlite3.Connection)
        conn.close()
