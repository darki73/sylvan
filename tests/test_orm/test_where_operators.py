"""Tests for operator where support, OR variants, multi-column, and dirty tracking."""

import pytest

from sylvan.database.orm import Repo
from sylvan.database.orm.query.where import _check_operator


class TestOperatorWhere:
    async def test_three_arg_less_than(self, ctx):
        """where(col, '<', val) should generate correct SQL."""
        builder = Repo.where("id", "<", 5)
        sql, params = builder.to_sql()
        assert "id < ?" in sql
        assert 5 in params

    async def test_three_arg_greater_equal(self, ctx):
        """where(col, '>=', val) should generate correct SQL."""
        builder = Repo.where("id", ">=", 10)
        sql, _params = builder.to_sql()
        assert "id >= ?" in sql

    async def test_three_arg_not_equal(self, ctx):
        """where(col, '!=', val) should generate correct SQL."""
        builder = Repo.where("name", "!=", "test")
        sql, _params = builder.to_sql()
        assert "name != ?" in sql

    async def test_three_arg_like(self, ctx):
        """where(col, 'like', pattern) should generate correct SQL."""
        builder = Repo.where("name", "like", "%foo%")
        sql, _params = builder.to_sql()
        assert "name like ?" in sql

    async def test_invalid_operator_raises(self, ctx):
        """Invalid operators should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid operator"):
            _check_operator("DROP TABLE")

    async def test_two_arg_still_works(self, ctx):
        """Two-arg where should still generate equality."""
        builder = Repo.where("name", "test")
        sql, _params = builder.to_sql()
        assert "name = ?" in sql

    async def test_kwargs_still_works(self, ctx):
        """Kwargs where should still generate equality."""
        builder = Repo.where(name="test")
        sql, _params = builder.to_sql()
        assert "name = ?" in sql


class TestWhereNone:
    async def test_where_col_none_becomes_is_null(self, ctx):
        """where(col, None) should generate IS NULL."""
        builder = Repo.where("name", None)
        sql, _params = builder.to_sql()
        assert "name IS NULL" in sql

    async def test_where_kwargs_none_becomes_is_null(self, ctx):
        """where(col=None) should generate IS NULL."""
        builder = Repo.where(name=None)
        sql, _params = builder.to_sql()
        assert "name IS NULL" in sql

    async def test_operator_eq_none_becomes_is_null(self, ctx):
        """where(col, '=', None) should generate IS NULL."""
        builder = Repo.where("name", "=", None)
        sql, _params = builder.to_sql()
        assert "name IS NULL" in sql

    async def test_operator_neq_none_becomes_is_not_null(self, ctx):
        """where(col, '!=', None) should generate IS NOT NULL."""
        builder = Repo.where("name", "!=", None)
        sql, _params = builder.to_sql()
        assert "name IS NOT NULL" in sql


class TestOrWhereVariants:
    async def test_or_where_null(self, ctx):
        builder = Repo.where(name="x").or_where_null("source_path")
        sql, _ = builder.to_sql()
        assert "OR source_path IS NULL" in sql

    async def test_or_where_not_null(self, ctx):
        builder = Repo.where(name="x").or_where_not_null("source_path")
        sql, _ = builder.to_sql()
        assert "OR source_path IS NOT NULL" in sql

    async def test_or_where_in(self, ctx):
        builder = Repo.where(name="x").or_where_in("id", [1, 2, 3])
        sql, params = builder.to_sql()
        assert "OR id IN" in sql
        assert 1 in params

    async def test_or_where_between(self, ctx):
        builder = Repo.where(name="x").or_where_between("id", 1, 10)
        sql, _params = builder.to_sql()
        assert "OR id BETWEEN" in sql


class TestWhereMultiColumn:
    async def test_where_any(self, ctx):
        """where_any should create an OR group."""
        builder = Repo.query().where_any(["name", "source_path"], "like", "%test%")
        sql, params = builder.to_sql()
        assert "name like ?" in sql
        assert "OR" in sql
        assert len(params) == 2

    async def test_where_all(self, ctx):
        """where_all should create an AND group."""
        builder = Repo.query().where_all(["name", "source_path"], "!=", None)
        sql, _ = builder.to_sql()
        assert "IS NOT NULL" in sql

    async def test_where_none(self, ctx):
        """where_none should create a NOT(...) group."""
        builder = Repo.query().where_none(["name", "source_path"], "like", "%spam%")
        sql, _ = builder.to_sql()
        assert "NOT (" in sql

    async def test_where_column(self, ctx):
        """where_column should compare two columns."""
        builder = Repo.query().where_column("name", "=", "source_path")
        sql, _ = builder.to_sql()
        assert "name = source_path" in sql


class TestDirtyTracking:
    async def test_new_instance_is_dirty(self, ctx):
        """A freshly created (unsaved) instance should be dirty."""
        repo = Repo(name="test", indexed_at="2024-01-01")
        assert repo.is_dirty() is True

    async def test_loaded_instance_is_clean(self, ctx):
        """A loaded instance should not be dirty."""
        await Repo.create(name="clean", indexed_at="2024-01-01")
        await ctx.backend.commit()
        loaded = await Repo.where(name="clean").first()
        assert loaded.is_dirty() is False

    async def test_modified_instance_is_dirty(self, ctx):
        """Changing an attribute should make it dirty."""
        await Repo.create(name="original", indexed_at="2024-01-01")
        await ctx.backend.commit()
        loaded = await Repo.where(name="original").first()
        loaded.name = "changed"
        assert loaded.is_dirty() is True
        assert loaded.is_dirty("name") is True

    async def test_get_dirty_returns_changed(self, ctx):
        """get_dirty should return only changed fields."""
        await Repo.create(name="original", indexed_at="2024-01-01")
        await ctx.backend.commit()
        loaded = await Repo.where(name="original").first()
        loaded.name = "changed"
        dirty = loaded.get_dirty()
        assert "name" in dirty
        assert dirty["name"] == "changed"

    async def test_get_original_returns_old_value(self, ctx):
        """get_original should return the value from when it was loaded."""
        await Repo.create(name="original", indexed_at="2024-01-01")
        await ctx.backend.commit()
        loaded = await Repo.where(name="original").first()
        loaded.name = "changed"
        assert loaded.get_original("name") == "original"

    async def test_save_snapshots_original(self, ctx):
        """After save, original should be updated."""
        await Repo.create(name="v1", indexed_at="2024-01-01")
        await ctx.backend.commit()
        loaded = await Repo.where(name="v1").first()
        loaded.name = "v2"
        await loaded.save()
        await ctx.backend.commit()
        assert loaded.is_dirty() is False
        assert loaded.get_original("name") == "v2"
