"""Tests for the response envelope builder."""

import time

from sylvan.tools.support.response import MetaBuilder, wrap_response


class TestMetaBuilder:
    def test_timing_included(self):
        m = MetaBuilder()
        result = m.build()
        assert "timing_ms" in result
        assert isinstance(result["timing_ms"], float)

    def test_custom_fields(self):
        m = MetaBuilder()
        m.set("count", 5)
        m.set("query", "test")
        result = m.build()
        assert result["count"] == 5
        assert result["query"] == "test"

    def test_chaining(self):
        m = MetaBuilder()
        m.set("a", 1).set("b", 2)
        result = m.build()
        assert result["a"] == 1
        assert result["b"] == 2

    def test_timing_increases(self):
        m = MetaBuilder()
        time.sleep(0.05)
        result = m.build()
        assert result["timing_ms"] >= 1  # at least some time passed


class TestWrapResponse:
    def test_basic_wrap(self):
        data = {"key": "value"}
        meta = {"timing_ms": 1.0}
        result = wrap_response(data, meta)
        assert result["key"] == "value"
        assert result["_meta"]["timing_ms"] == 1.0

    def test_no_hints_by_default(self):
        result = wrap_response({"x": 1}, {"timing_ms": 0})
        assert "_hints" not in result

    def test_hints_included_when_requested(self):
        # With no session data, hints should not appear (no working files)
        result = wrap_response({"x": 1}, {"timing_ms": 0}, include_hints=True)
        # _hints only appears if session has working files
        # Fresh session = no hints
        assert "_hints" not in result
