"""Tests for sylvan.database.orm.runtime.identity_map.IdentityMap."""

from __future__ import annotations

from sylvan.database.orm.runtime.identity_map import IdentityMap


class _FakeModel:
    """Dummy model class for identity map tests."""


class _OtherModel:
    """Another dummy model class."""


class TestIdentityMapGet:
    def test_get_returns_none_for_missing_key(self):
        im = IdentityMap()
        assert im.get(_FakeModel, 1) is None

    def test_get_returns_stored_instance(self):
        im = IdentityMap()
        obj = object()
        im.put(_FakeModel, 1, obj)
        assert im.get(_FakeModel, 1) is obj

    def test_get_distinguishes_classes(self):
        im = IdentityMap()
        a = object()
        b = object()
        im.put(_FakeModel, 1, a)
        im.put(_OtherModel, 1, b)
        assert im.get(_FakeModel, 1) is a
        assert im.get(_OtherModel, 1) is b

    def test_get_distinguishes_pks(self):
        im = IdentityMap()
        a = object()
        b = object()
        im.put(_FakeModel, 1, a)
        im.put(_FakeModel, 2, b)
        assert im.get(_FakeModel, 1) is a
        assert im.get(_FakeModel, 2) is b


class TestIdentityMapPut:
    def test_put_ignores_none_pk(self):
        im = IdentityMap()
        im.put(_FakeModel, None, object())
        assert len(im) == 0

    def test_put_overwrites_existing(self):
        im = IdentityMap()
        old = object()
        new = object()
        im.put(_FakeModel, 1, old)
        im.put(_FakeModel, 1, new)
        assert im.get(_FakeModel, 1) is new
        assert len(im) == 1

    def test_put_accepts_string_pk(self):
        im = IdentityMap()
        obj = object()
        im.put(_FakeModel, "abc", obj)
        assert im.get(_FakeModel, "abc") is obj


class TestIdentityMapRemove:
    def test_remove_existing_key(self):
        im = IdentityMap()
        im.put(_FakeModel, 1, object())
        im.remove(_FakeModel, 1)
        assert im.get(_FakeModel, 1) is None
        assert len(im) == 0

    def test_remove_missing_key_is_noop(self):
        im = IdentityMap()
        im.remove(_FakeModel, 999)  # should not raise
        assert len(im) == 0


class TestIdentityMapClear:
    def test_clear_empties_map(self):
        im = IdentityMap()
        im.put(_FakeModel, 1, object())
        im.put(_OtherModel, 2, object())
        assert len(im) == 2
        im.clear()
        assert len(im) == 0
        assert im.get(_FakeModel, 1) is None


class TestIdentityMapLen:
    def test_len_empty(self):
        assert len(IdentityMap()) == 0

    def test_len_after_puts(self):
        im = IdentityMap()
        im.put(_FakeModel, 1, object())
        im.put(_FakeModel, 2, object())
        assert len(im) == 2
