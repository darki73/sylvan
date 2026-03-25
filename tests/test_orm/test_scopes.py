"""Tests for sylvan.database.orm.primitives.scopes — scope decorator and ScopeDescriptor."""

from __future__ import annotations

from sylvan.database.orm.model.base import Model
from sylvan.database.orm.primitives.fields import AutoPrimaryKey, Column
from sylvan.database.orm.primitives.scopes import ScopeDescriptor, scope
from sylvan.database.orm.query.builder import QueryBuilder


# Define a test model with scopes (outside any test to trigger ModelMeta)
class ScopedWidget(Model):
    __table__ = "scoped_widgets"

    id = AutoPrimaryKey()
    name = Column(str)
    color = Column(str, nullable=True)
    active = Column(bool, default=False)

    @scope
    def red(query):
        return query.where(color="red")

    @scope
    def active_only(query):
        return query.where(active=1)

    @scope
    def named(query, name):
        return query.where(name=name)


class TestScopeDecorator:
    def test_creates_scope_descriptor(self):
        assert isinstance(ScopedWidget.__dict__["red"], ScopeDescriptor)
        assert isinstance(ScopedWidget.__dict__["active_only"], ScopeDescriptor)

    def test_descriptor_has_func(self):
        desc = ScopedWidget.__dict__["red"]
        assert callable(desc.func)

    def test_descriptor_name(self):
        desc = ScopedWidget.__dict__["red"]
        assert desc.name == "red"


class TestScopeCallable:
    async def test_scope_returns_query_builder(self, orm_ctx):
        result = ScopedWidget.red()
        assert isinstance(result, QueryBuilder)

    async def test_scope_applies_filter(self, orm_ctx):
        qb = ScopedWidget.red()
        assert len(qb._wheres) == 1
        clause, params = qb._wheres[0][0], qb._wheres[0][1]
        assert "color" in clause
        assert params == ["red"]

    async def test_scope_with_args(self, orm_ctx):
        qb = ScopedWidget.named("widget-1")
        _clause, params = qb._wheres[0][0], qb._wheres[0][1]
        assert params == ["widget-1"]


class TestScopeChaining:
    async def test_chain_scopes_on_query_builder(self, orm_ctx):
        """Scopes should be chainable via QueryBuilder.__getattr__."""
        qb = ScopedWidget.red().active_only()
        assert isinstance(qb, QueryBuilder)
        assert len(qb._wheres) == 2

    async def test_chain_with_regular_methods(self, orm_ctx):
        qb = ScopedWidget.red().order_by("name").limit(5)
        assert isinstance(qb, QueryBuilder)
        assert len(qb._wheres) == 1
        assert qb._limit_val == 5

    async def test_real_model_scope_chaining(self, orm_ctx):
        """Test scopes on the real Symbol model."""
        from sylvan.database.orm.models import Symbol

        backend = orm_ctx.backend
        await backend.execute("INSERT INTO repos (id, name, indexed_at) VALUES (1, 'myrepo', '2024-01-01')")
        await backend.execute(
            "INSERT INTO files (id, repo_id, path, language, content_hash, byte_size) "
            "VALUES (1, 1, 'main.py', 'python', 'h1', 100)"
        )
        await backend.execute(
            "INSERT INTO symbols (id, file_id, symbol_id, name, qualified_name, kind, "
            "language, byte_offset, byte_length) "
            "VALUES (1, 1, 'sym-1', 'foo', 'main.foo', 'function', 'python', 0, 50)"
        )
        await backend.commit()

        results = await Symbol.functions().in_repo("myrepo").get()
        assert len(results) == 1
        assert results[0].name == "foo"
