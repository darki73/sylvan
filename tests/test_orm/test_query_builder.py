"""Tests for sylvan.database.orm.query.builder — QueryBuilder against a real async SQLite backend."""

from __future__ import annotations

import pytest

from sylvan.database.orm.exceptions import QueryError
from sylvan.database.orm.models import Repo, Symbol


async def _seed(ctx):
    """Seed the DB with repos, files, and symbols for query tests."""
    backend = ctx.backend
    await backend.execute(
        "INSERT INTO repos (id, name, indexed_at) VALUES (1, 'alpha', '2024-01-01')"
    )
    await backend.execute(
        "INSERT INTO repos (id, name, indexed_at) VALUES (2, 'beta', '2024-02-01')"
    )
    await backend.execute(
        "INSERT INTO files (id, repo_id, path, language, content_hash, byte_size) "
        "VALUES (1, 1, 'main.py', 'python', 'h1', 100)"
    )
    await backend.execute(
        "INSERT INTO files (id, repo_id, path, language, content_hash, byte_size) "
        "VALUES (2, 1, 'util.py', 'python', 'h2', 200)"
    )
    await backend.execute(
        "INSERT INTO files (id, repo_id, path, language, content_hash, byte_size) "
        "VALUES (3, 2, 'lib.go', 'go', 'h3', 300)"
    )
    # Symbols
    symbols = [
        (1, 1, "sym-1", "foo", "main.foo", "function", "python", "def foo()", None, None, None, None, None, 0, 50, None),
        (2, 1, "sym-2", "bar", "main.bar", "function", "python", "def bar()", None, None, None, None, None, 50, 40, None),
        (3, 1, "sym-3", "MyClass", "main.MyClass", "class", "python", "class MyClass", None, None, None, None, None, 90, 100, None),
        (4, 2, "sym-4", "helper", "util.helper", "function", "python", "def helper()", None, None, None, None, None, 0, 60, None),
        (5, 3, "sym-5", "GoFunc", "lib.GoFunc", "function", "go", "func GoFunc()", None, None, None, None, None, 0, 80, None),
    ]
    for s in symbols:
        await backend.execute(
            "INSERT INTO symbols (id, file_id, symbol_id, name, qualified_name, kind, language, "
            "signature, docstring, summary, decorators, keywords, parent_symbol_id, "
            "byte_offset, byte_length, content_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            list(s),
        )
    await backend.commit()


# -- Where clauses ---


class TestWhere:
    async def test_where_kwargs(self, orm_ctx):
        await _seed(orm_ctx)
        results = await Symbol.where(kind="function").get()
        assert all(s.kind == "function" for s in results)
        assert len(results) == 4

    async def test_where_positional(self, orm_ctx):
        await _seed(orm_ctx)
        results = await Symbol.where("kind", "class").get()
        assert len(results) == 1
        assert results[0].name == "MyClass"

    async def test_where_dict(self, orm_ctx):
        await _seed(orm_ctx)
        results = await Symbol.where({"kind": "class"}).get()
        assert len(results) == 1


class TestWhereIn:
    async def test_where_in(self, orm_ctx):
        await _seed(orm_ctx)
        results = await Symbol.where_in("name", ["foo", "bar"]).get()
        names = {s.name for s in results}
        assert names == {"foo", "bar"}

    async def test_where_in_empty_list(self, orm_ctx):
        await _seed(orm_ctx)
        results = await Symbol.where_in("name", []).get()
        assert results == []


class TestWhereNot:
    async def test_where_not(self, orm_ctx):
        await _seed(orm_ctx)
        results = await Symbol.where_not(kind="class").get()
        assert all(s.kind != "class" for s in results)
        assert len(results) == 4


class TestWhereLike:
    async def test_where_like(self, orm_ctx):
        await _seed(orm_ctx)
        results = await Symbol.where_like("name", "%oo%").get()
        assert len(results) == 1
        assert results[0].name == "foo"


class TestWhereNull:
    async def test_where_null(self, orm_ctx):
        await _seed(orm_ctx)
        results = await Symbol.where_null("docstring").get()
        assert len(results) == 5  # all have NULL docstring

    async def test_where_not_null(self, orm_ctx):
        await _seed(orm_ctx)
        backend = orm_ctx.backend
        await backend.execute("UPDATE symbols SET docstring = 'hello' WHERE id = 1")
        await backend.commit()
        results = await Symbol.where_not_null("docstring").get()
        assert len(results) == 1
        assert results[0].id == 1


class TestWhereRaw:
    async def test_where_raw(self, orm_ctx):
        await _seed(orm_ctx)
        results = await Symbol.query().where_raw("byte_length > ?", [50]).get()
        assert all(s.byte_length > 50 for s in results)


# -- Ordering, limiting, offset --


class TestOrderBy:
    async def test_order_by_asc(self, orm_ctx):
        await _seed(orm_ctx)
        results = await Symbol.query().order_by("name", "ASC").get()
        names = [s.name for s in results]
        assert names == sorted(names)

    async def test_order_by_desc(self, orm_ctx):
        await _seed(orm_ctx)
        results = await Symbol.query().order_by("name", "DESC").get()
        names = [s.name for s in results]
        assert names == sorted(names, reverse=True)


class TestLimit:
    async def test_limit(self, orm_ctx):
        await _seed(orm_ctx)
        results = await Symbol.query().limit(2).get()
        assert len(results) == 2


class TestOffset:
    async def test_offset(self, orm_ctx):
        await _seed(orm_ctx)
        all_results = await Symbol.query().order_by("id").get()
        offset_results = await Symbol.query().order_by("id").limit(2).offset(2).get()
        assert offset_results[0].id == all_results[2].id


# -- Group by --


class TestGroupBy:
    async def test_group_by_count(self, orm_ctx):
        await _seed(orm_ctx)
        counts = await Symbol.query().group_by("kind").count()
        assert isinstance(counts, dict)
        assert counts["function"] == 4
        assert counts["class"] == 1

    async def test_group_by_multi(self, orm_ctx):
        await _seed(orm_ctx)
        counts = await Symbol.query().group_by("kind", "language").count()
        assert isinstance(counts, dict)
        assert counts[("function", "python")] == 3
        assert counts[("function", "go")] == 1


# -- Join --


class TestJoin:
    async def test_join(self, orm_ctx):
        await _seed(orm_ctx)
        results = await (
            Symbol.query()
            .join("files", "files.id = symbols.file_id")
            .where("files.language", "go")
            .get()
        )
        assert len(results) == 1
        assert results[0].name == "GoFunc"

    async def test_duplicate_join_ignored(self, orm_ctx):
        await _seed(orm_ctx)
        qb = Symbol.query()
        qb.join("files", "files.id = symbols.file_id")
        qb.join("files", "files.id = symbols.file_id")
        assert len(qb._joins) == 1


# -- Terminal methods --


class TestGet:
    async def test_get_returns_list_of_models(self, orm_ctx):
        await _seed(orm_ctx)
        results = await Symbol.query().get()
        assert len(results) == 5
        assert all(isinstance(s, Symbol) for s in results)


class TestFirst:
    async def test_first_returns_instance(self, orm_ctx):
        await _seed(orm_ctx)
        s = await Symbol.where(name="foo").first()
        assert s is not None
        assert s.name == "foo"

    async def test_first_returns_none_when_empty(self, orm_ctx):
        await _seed(orm_ctx)
        s = await Symbol.where(name="nonexistent").first()
        assert s is None


class TestCount:
    async def test_count(self, orm_ctx):
        await _seed(orm_ctx)
        assert await Symbol.query().count() == 5

    async def test_count_with_where(self, orm_ctx):
        await _seed(orm_ctx)
        assert await Symbol.where(kind="function").count() == 4


class TestExists:
    async def test_exists_true(self, orm_ctx):
        await _seed(orm_ctx)
        assert await Symbol.where(name="foo").exists() is True

    async def test_exists_false(self, orm_ctx):
        await _seed(orm_ctx)
        assert await Symbol.where(name="nope").exists() is False


class TestPluck:
    async def test_pluck(self, orm_ctx):
        await _seed(orm_ctx)
        names = await Symbol.query().order_by("name").pluck("name")
        assert names == sorted(["foo", "bar", "MyClass", "helper", "GoFunc"])


class TestBulkDelete:
    async def test_delete_with_where(self, orm_ctx):
        await _seed(orm_ctx)
        deleted = await Symbol.where(kind="class").delete()
        assert deleted == 1
        assert await Symbol.query().count() == 4

    async def test_delete_all(self, orm_ctx):
        await _seed(orm_ctx)
        deleted = await Symbol.query().delete()
        assert deleted == 5


class TestBulkUpdate:
    async def test_update_with_where(self, orm_ctx):
        await _seed(orm_ctx)
        updated = await Symbol.where(kind="function").update(summary="updated")
        assert updated == 4
        results = await Symbol.where(summary="updated").get()
        assert len(results) == 4


# -- FTS5 search --


class TestSearch:
    async def test_search_by_name(self, orm_ctx):
        await _seed(orm_ctx)
        results = await Symbol.search("foo").get()
        assert len(results) >= 1
        names = [s.name for s in results]
        assert "foo" in names

    async def test_search_combined_with_where(self, orm_ctx):
        await _seed(orm_ctx)
        results = await Symbol.search("foo bar").where(language="python").get()
        assert all(s.language == "python" for s in results)

    async def test_search_no_fts_table_raises(self, orm_ctx):
        with pytest.raises(QueryError, match="has no FTS5"):
            Repo.search("test")


# -- Scope chaining via __getattr__ --


class TestScopeChaining:
    async def test_scope_on_query_builder(self, orm_ctx):
        await _seed(orm_ctx)
        results = await Symbol.functions().get()
        assert all(s.kind == "function" for s in results)

    async def test_scope_chain_on_builder(self, orm_ctx):
        await _seed(orm_ctx)
        results = await Symbol.functions().in_repo("alpha").get()
        assert all(s.kind == "function" for s in results)
        # alpha repo has sym-1, sym-2, sym-4 (file 1 and 2 belong to repo 1)
        names = {s.name for s in results}
        assert "GoFunc" not in names

    async def test_unknown_attr_raises(self, orm_ctx):
        with pytest.raises(AttributeError):
            Symbol.query().nonexistent_scope()


# -- Raw query --


class TestRaw:
    async def test_raw_returns_model_instances(self, orm_ctx):
        await _seed(orm_ctx)
        results = await Symbol.raw("SELECT * FROM symbols WHERE kind = ?", ["function"])
        assert len(results) == 4
        assert all(isinstance(s, Symbol) for s in results)
