"""Tests for sylvan.database.orm.primitives.fields — Column, JsonColumn, AutoPrimaryKey."""

from __future__ import annotations

import json

from sylvan.database.orm.primitives.fields import AutoPrimaryKey, Column, JsonColumn

# ── Column ──────────────────────────────────────────────────────


class TestColumn:
    """Tests for the base Column descriptor."""

    def test_to_db_passthrough(self):
        col = Column(str)
        assert col.to_db("hello") == "hello"
        assert col.to_db(42) == 42

    def test_to_db_none(self):
        col = Column(str)
        assert col.to_db(None) is None

    def test_from_db_str(self):
        col = Column(str)
        assert col.from_db("hello") == "hello"
        assert col.from_db(123) == "123"

    def test_from_db_int(self):
        col = Column(int)
        assert col.from_db(42) == 42
        assert col.from_db("7") == 7

    def test_from_db_float(self):
        col = Column(float)
        assert col.from_db(3.14) == 3.14
        assert col.from_db("2.5") == 2.5

    def test_from_db_bool(self):
        col = Column(bool)
        assert col.from_db(1) is True
        assert col.from_db(0) is False

    def test_from_db_none_returns_default(self):
        col = Column(str, default="fallback")
        assert col.from_db(None) == "fallback"

    def test_from_db_none_no_default(self):
        col = Column(str)
        assert col.from_db(None) is None

    def test_nullable_flag(self):
        col = Column(str, nullable=True)
        assert col.nullable is True
        col2 = Column(str, nullable=False)
        assert col2.nullable is False

    def test_primary_key_flag(self):
        col = Column(int, primary_key=True)
        assert col.primary_key is True
        col2 = Column(int)
        assert col2.primary_key is False

    def test_custom_column_name(self):
        col = Column(str, column_name="custom_col")
        col._attr_name = "my_attr"
        assert col.db_name == "custom_col"

    def test_default_column_name_from_attr(self):
        col = Column(str)
        col._attr_name = "my_attr"
        assert col.db_name == "my_attr"

    def test_repr(self):
        col = Column(str, nullable=True)
        col._attr_name = "name"
        r = repr(col)
        assert "str" in r
        assert "nullable=True" in r


# ── JsonColumn ──────────────────────────────────────────────────


class TestJsonColumn:
    """Tests for the JSON-serializing column."""

    def test_to_db_list(self):
        col = JsonColumn(list)
        assert col.to_db(["a", "b"]) == '["a", "b"]'

    def test_to_db_dict(self):
        col = JsonColumn(dict)
        val = col.to_db({"key": "value"})
        assert json.loads(val) == {"key": "value"}

    def test_to_db_empty_list_returns_json(self):
        col = JsonColumn(list)
        assert col.to_db([]) == "[]"

    def test_to_db_empty_dict_returns_json(self):
        col = JsonColumn(dict)
        assert col.to_db({}) == "{}"

    def test_to_db_none_returns_none(self):
        col = JsonColumn(list)
        assert col.to_db(None) is None

    def test_from_db_json_string_list(self):
        col = JsonColumn(list)
        assert col.from_db('["x", "y"]') == ["x", "y"]

    def test_from_db_json_string_dict(self):
        col = JsonColumn(dict)
        assert col.from_db('{"a": 1}') == {"a": 1}

    def test_from_db_none_returns_default_factory(self):
        col = JsonColumn(list)
        result = col.from_db(None)
        assert result == []
        assert isinstance(result, list)

    def test_from_db_none_dict_factory(self):
        col = JsonColumn(dict)
        result = col.from_db(None)
        assert result == {}
        assert isinstance(result, dict)

    def test_from_db_already_parsed(self):
        col = JsonColumn(list)
        assert col.from_db([1, 2, 3]) == [1, 2, 3]

    def test_roundtrip_list(self):
        col = JsonColumn(list)
        original = [1, "two", 3.0, None]
        serialized = col.to_db(original)
        deserialized = col.from_db(serialized)
        assert deserialized == original

    def test_roundtrip_dict(self):
        col = JsonColumn(dict)
        original = {"name": "test", "count": 42, "nested": {"a": 1}}
        serialized = col.to_db(original)
        deserialized = col.from_db(serialized)
        assert deserialized == original

    def test_default_factory_returns_fresh_instances(self):
        col = JsonColumn(list)
        a = col.default
        b = col.default
        assert a == b == []
        assert a is not b  # must be distinct objects

    def test_nullable_defaults_true(self):
        col = JsonColumn(list)
        assert col.nullable is True

    def test_custom_column_name(self):
        col = JsonColumn(list, column_name="json_data")
        col._attr_name = "data"
        assert col.db_name == "json_data"


# ── AutoPrimaryKey ──────────────────────────────────────────────


class TestAutoPrimaryKey:
    """Tests for the auto-increment primary key column."""

    def test_primary_key_flag(self):
        pk = AutoPrimaryKey()
        assert pk.primary_key is True

    def test_type_is_int(self):
        pk = AutoPrimaryKey()
        assert pk.type is int

    def test_nullable(self):
        pk = AutoPrimaryKey()
        assert pk.nullable is True  # allows None before insert

    def test_from_db_int(self):
        pk = AutoPrimaryKey()
        assert pk.from_db(5) == 5

    def test_to_db_passthrough(self):
        pk = AutoPrimaryKey()
        assert pk.to_db(10) == 10
        assert pk.to_db(None) is None
