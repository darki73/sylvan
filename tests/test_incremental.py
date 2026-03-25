"""Tests for incremental indexing."""

import os

from sylvan.config import reset_config
from sylvan.context import SylvanContext, reset_context, set_context
from sylvan.database.backends.sqlite import SQLiteBackend
from sylvan.database.migrations.runner import run_migrations
from sylvan.database.orm.runtime.query_cache import QueryCache
from sylvan.session.tracker import SessionTracker


class TestIncremental:
    async def test_mtime_comparison(self, tmp_path):
        os.environ["SYLVAN_HOME"] = str(tmp_path)
        reset_config()
        try:
            from sylvan.indexing.discovery.incremental import get_files_to_reindex

            db_path = tmp_path / "test.db"
            backend = SQLiteBackend(db_path)
            await backend.connect()
            await run_migrations(backend)

            context = SylvanContext(
                backend=backend,
                session=SessionTracker(),
                cache=QueryCache(),
            )
            token = set_context(context)

            try:
                await backend.execute(
                    "INSERT INTO repos (name, source_path, indexed_at) VALUES (?, ?, datetime('now'))",
                    ["test", str(tmp_path)],
                )
                await backend.commit()
                row = await backend.fetch_one("SELECT id FROM repos WHERE name = 'test'")
                repo_id = row["id"]

                f = tmp_path / "test.py"
                f.write_text("x = 1\n")
                mtime = f.stat().st_mtime

                await backend.execute(
                    "INSERT INTO files (repo_id, path, content_hash, byte_size, mtime, language) VALUES (?, ?, ?, ?, ?, ?)",
                    [repo_id, "test.py", "abc", 6, mtime, "python"],
                )
                await backend.commit()

                changed = await get_files_to_reindex(repo_id, tmp_path)
                assert changed == []

                await backend.execute(
                    "UPDATE files SET mtime = ? WHERE repo_id = ? AND path = ?",
                    [mtime - 10, repo_id, "test.py"],
                )
                await backend.commit()
                changed = await get_files_to_reindex(repo_id, tmp_path)
                assert "test.py" in changed
            finally:
                reset_context(token)
                await backend.disconnect()
        finally:
            os.environ.pop("SYLVAN_HOME", None)
            reset_config()

    async def test_no_stored_files(self, tmp_path):
        os.environ["SYLVAN_HOME"] = str(tmp_path)
        reset_config()
        try:
            from sylvan.indexing.discovery.incremental import get_files_to_reindex

            db_path = tmp_path / "test.db"
            backend = SQLiteBackend(db_path)
            await backend.connect()
            await run_migrations(backend)

            context = SylvanContext(
                backend=backend,
                session=SessionTracker(),
                cache=QueryCache(),
            )
            token = set_context(context)

            try:
                await backend.execute(
                    "INSERT INTO repos (name, source_path, indexed_at) VALUES (?, ?, datetime('now'))",
                    ["empty", str(tmp_path)],
                )
                await backend.commit()
                row = await backend.fetch_one("SELECT id FROM repos WHERE name = 'empty'")
                repo_id = row["id"]

                changed = await get_files_to_reindex(repo_id, tmp_path)
                assert changed is None
            finally:
                reset_context(token)
                await backend.disconnect()
        finally:
            os.environ.pop("SYLVAN_HOME", None)
            reset_config()

    async def test_deleted_file(self, tmp_path):
        os.environ["SYLVAN_HOME"] = str(tmp_path)
        reset_config()
        try:
            from sylvan.indexing.discovery.incremental import get_files_to_reindex

            db_path = tmp_path / "test.db"
            backend = SQLiteBackend(db_path)
            await backend.connect()
            await run_migrations(backend)

            context = SylvanContext(
                backend=backend,
                session=SessionTracker(),
                cache=QueryCache(),
            )
            token = set_context(context)

            try:
                await backend.execute(
                    "INSERT INTO repos (name, source_path, indexed_at) VALUES (?, ?, datetime('now'))",
                    ["test2", str(tmp_path)],
                )
                await backend.commit()
                row = await backend.fetch_one("SELECT id FROM repos WHERE name = 'test2'")
                repo_id = row["id"]

                await backend.execute(
                    "INSERT INTO files (repo_id, path, content_hash, byte_size, mtime) VALUES (?, ?, ?, ?, ?)",
                    [repo_id, "deleted.py", "abc", 10, 1000.0],
                )
                await backend.commit()

                changed = await get_files_to_reindex(repo_id, tmp_path)
                assert "deleted.py" in changed
            finally:
                reset_context(token)
                await backend.disconnect()
        finally:
            os.environ.pop("SYLVAN_HOME", None)
            reset_config()
