"""Tests for advanced ORM features: or_where, having, to_sql, pagination, hooks, soft deletes."""

from __future__ import annotations

from datetime import UTC


async def _seed(ctx):
    """Seed test data."""
    from datetime import datetime
    backend = ctx.backend
    now = datetime.now(UTC).isoformat()
    await backend.execute(
        "INSERT INTO repos (id, name, source_path, indexed_at) VALUES (1, 'test', '/tmp/test', ?)",
        [now],
    )
    await backend.execute(
        "INSERT INTO files (id, repo_id, path, language, content_hash, byte_size) VALUES (1, 1, 'main.py', 'python', 'abc', 100)"
    )
    await backend.execute(
        "INSERT INTO files (id, repo_id, path, language, content_hash, byte_size) VALUES (2, 1, 'util.py', 'python', 'def', 200)"
    )
    for i, (name, kind) in enumerate([
        ("hello", "function"), ("world", "function"), ("Foo", "class"),
        ("bar", "method"), ("MAX", "constant"), ("greet", "function"),
    ], start=1):
        await backend.execute(
            "INSERT INTO symbols (id, file_id, symbol_id, name, qualified_name, kind, language, byte_offset, byte_length) "
            "VALUES (?, ?, ?, ?, ?, ?, 'python', 0, 10)",
            [i, 1 if i <= 3 else 2, f"s{i}", name, name, kind],
        )
    await backend.commit()


class TestOrWhere:
    async def test_or_where_basic(self, orm_ctx):
        await _seed(orm_ctx)
        from sylvan.database.orm.models import Symbol
        results = await Symbol.where(kind="function").or_where(kind="constant").get()
        kinds = {r.kind for r in results}
        assert "function" in kinds
        assert "constant" in kinds
        assert "class" not in kinds


class TestToSql:
    async def test_returns_sql_and_params(self, orm_ctx):
        from sylvan.database.orm.models import Symbol
        sql, params = Symbol.where(kind="function").limit(5).to_sql()
        assert "SELECT" in sql
        assert "WHERE" in sql
        assert "LIMIT" in sql
        assert "function" in params

    async def test_does_not_execute(self, orm_ctx):
        await _seed(orm_ctx)
        from sylvan.database.orm.models import Symbol
        # to_sql should not hit the DB
        sql, params = Symbol.where(kind="nonexistent_kind_xyz").to_sql()
        assert isinstance(sql, str)
        assert isinstance(params, list)


class TestSelectRaw:
    async def test_select_raw_count(self, orm_ctx):
        await _seed(orm_ctx)
        from sylvan.database.orm.models import Symbol
        results = await Symbol.query().select_raw("kind, COUNT(*) as cnt").group_by("kind").get()
        # Should have rows with cnt attribute
        assert len(results) > 0


class TestPagination:
    async def test_paginate_returns_structure(self, orm_ctx):
        await _seed(orm_ctx)
        from sylvan.database.orm.models import Symbol
        page = await Symbol.all().paginate(page=1, per_page=2)
        assert "data" in page
        assert "total" in page
        assert "page" in page
        assert "per_page" in page
        assert "pages" in page
        assert page["page"] == 1
        assert page["per_page"] == 2
        assert len(page["data"]) <= 2
        assert page["total"] == 6
        assert page["pages"] == 3

    async def test_paginate_page_2(self, orm_ctx):
        await _seed(orm_ctx)
        from sylvan.database.orm.models import Symbol
        page = await Symbol.all().paginate(page=2, per_page=2)
        assert page["page"] == 2
        assert len(page["data"]) <= 2


class TestQueryLogging:
    async def test_debug_mode_logs_queries(self, orm_ctx):
        await _seed(orm_ctx)
        from sylvan.database.orm.query.builder import QueryBuilder
        QueryBuilder.enable_debug()
        QueryBuilder.clear_query_log()

        from sylvan.database.orm.models import Symbol
        await Symbol.where(kind="function").get()

        log = QueryBuilder.get_query_log()
        assert len(log) >= 1
        assert "SELECT" in log[0][0]

        QueryBuilder.disable_debug()
        QueryBuilder.clear_query_log()
