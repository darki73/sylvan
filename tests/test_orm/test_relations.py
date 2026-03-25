"""Tests for sylvan.database.orm.primitives.relations — BelongsTo, HasMany, HasOne."""

from __future__ import annotations

from sylvan.database.orm.models import FileRecord, Quality, Repo, Symbol


async def _seed_relations(ctx):
    """Seed DB with data for relation tests."""
    backend = ctx.backend
    await backend.execute("INSERT INTO repos (id, name, indexed_at) VALUES (1, 'test-repo', '2024-01-01')")
    await backend.execute(
        "INSERT INTO files (id, repo_id, path, language, content_hash, byte_size) "
        "VALUES (1, 1, 'main.py', 'python', 'h1', 100)"
    )
    await backend.execute(
        "INSERT INTO files (id, repo_id, path, language, content_hash, byte_size) "
        "VALUES (2, 1, 'util.py', 'python', 'h2', 200)"
    )
    await backend.execute(
        "INSERT INTO symbols (id, file_id, symbol_id, name, qualified_name, kind, "
        "language, byte_offset, byte_length) "
        "VALUES (1, 1, 'sym-1', 'foo', 'main.foo', 'function', 'python', 0, 50)"
    )
    await backend.execute(
        "INSERT INTO symbols (id, file_id, symbol_id, name, qualified_name, kind, "
        "language, byte_offset, byte_length, parent_symbol_id) "
        "VALUES (2, 1, 'sym-2', 'bar', 'main.bar', 'method', 'python', 50, 40, 'sym-1')"
    )
    await backend.execute(
        "INSERT INTO symbols (id, file_id, symbol_id, name, qualified_name, kind, "
        "language, byte_offset, byte_length) "
        "VALUES (3, 2, 'sym-3', 'helper', 'util.helper', 'function', 'python', 0, 60)"
    )
    await backend.execute("INSERT INTO quality (symbol_id, has_tests, has_docs) VALUES ('sym-1', 1, 1)")
    await backend.commit()


class TestBelongsTo:
    async def test_lazy_loads_related_model(self, orm_ctx):
        await _seed_relations(orm_ctx)
        sym = await Symbol.query().with_("file").where(id=1).first()
        file = sym.file
        assert isinstance(file, FileRecord)
        assert file.id == 1
        assert file.path == "main.py"

    async def test_returns_none_when_fk_null(self, orm_ctx):
        await _seed_relations(orm_ctx)
        sym = await Symbol.query().with_("parent_symbol").where(id=1).first()
        # parent_symbol_id is NULL for top-level symbols
        result = sym.parent_symbol
        assert result is None

    async def test_caches_result(self, orm_ctx):
        await _seed_relations(orm_ctx)
        sym = await Symbol.query().with_("file").where(id=1).first()
        file1 = sym.file
        file2 = sym.file
        assert file1 is file2  # same cached object

    async def test_class_level_access_returns_descriptor(self, orm_ctx):
        from sylvan.database.orm.primitives.relations import BelongsTo

        assert isinstance(Symbol.file, BelongsTo)


class TestHasMany:
    async def test_returns_list_of_related_models(self, orm_ctx):
        await _seed_relations(orm_ctx)
        file_rec = await FileRecord.query().with_("symbols").where(id=1).first()
        syms = file_rec.symbols
        assert isinstance(syms, list)
        assert len(syms) == 2  # sym-1 and sym-2
        assert all(isinstance(s, Symbol) for s in syms)

    async def test_returns_empty_list_when_none(self, orm_ctx):
        await _seed_relations(orm_ctx)
        backend = orm_ctx.backend
        await backend.execute(
            "INSERT INTO files (id, repo_id, path, language, content_hash, byte_size) "
            "VALUES (99, 1, 'empty.py', 'python', 'h99', 0)"
        )
        await backend.commit()
        file_rec = await FileRecord.query().with_("symbols").where(id=99).first()
        assert file_rec.symbols == []

    async def test_repo_has_many_files(self, orm_ctx):
        await _seed_relations(orm_ctx)
        repo = await Repo.query().with_("files").where(id=1).first()
        files = repo.files
        assert len(files) == 2
        paths = {f.path for f in files}
        assert paths == {"main.py", "util.py"}

    async def test_symbol_has_many_children(self, orm_ctx):
        await _seed_relations(orm_ctx)
        parent = await Symbol.query().with_("children").where(id=1).first()
        children = parent.children
        assert len(children) == 1
        assert children[0].name == "bar"


class TestHasOne:
    async def test_returns_single_related_model(self, orm_ctx):
        await _seed_relations(orm_ctx)
        sym = await Symbol.query().with_("quality_info").where(id=1).first()
        q = sym.quality_info
        assert isinstance(q, Quality)
        assert q.has_tests is True
        assert q.has_docs is True

    async def test_returns_none_when_no_related(self, orm_ctx):
        await _seed_relations(orm_ctx)
        sym = await Symbol.query().with_("quality_info").where(id=3).first()
        assert sym.quality_info is None


class TestEagerLoading:
    async def test_with_belongs_to(self, orm_ctx):
        await _seed_relations(orm_ctx)
        symbols = await Symbol.query().with_("file").get()
        for sym in symbols:
            # Eager-loaded, so _rel_file is set
            cached = getattr(sym, "_rel_file", None)
            assert cached is not None or sym.file_id == 9999

    async def test_with_has_many(self, orm_ctx):
        await _seed_relations(orm_ctx)
        files = await FileRecord.query().with_("symbols").get()
        for f in files:
            cached = getattr(f, "_rel_symbols", None)
            assert cached is not None
            assert isinstance(cached, list)

    async def test_with_has_one(self, orm_ctx):
        await _seed_relations(orm_ctx)
        symbols = await Symbol.query().with_("quality_info").get()
        sym1 = next(s for s in symbols if s.symbol_id == "sym-1")
        assert getattr(sym1, "_rel_quality_info", None) is not None
