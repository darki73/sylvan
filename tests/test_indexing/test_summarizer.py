"""Tests for sylvan.indexing.post_processing.summarizer — summary generation helpers."""

from __future__ import annotations

from sylvan.indexing.post_processing.summarizer import _is_heuristic_provider, _source_in_bounds


class FakeProvider:
    """A mock summary provider."""

    def __init__(self, name: str = "claude"):
        self.name = name

    def summarize_symbol(self, signature: str, docstring: str | None, source: str) -> str:
        return f"Summary of {signature}"


class FakeSymbol:
    """A minimal symbol-like object for testing."""

    def __init__(self, byte_offset: int, byte_length: int):
        self.byte_offset = byte_offset
        self.byte_length = byte_length


class TestIsHeuristicProvider:
    def test_heuristic(self):
        provider = FakeProvider(name="heuristic")
        assert _is_heuristic_provider(provider) is True

    def test_non_heuristic(self):
        provider = FakeProvider(name="claude")
        assert _is_heuristic_provider(provider) is False

    def test_other_provider(self):
        provider = FakeProvider(name="ollama")
        assert _is_heuristic_provider(provider) is False


class TestSourceInBounds:
    def test_within_bounds(self):
        sym = FakeSymbol(byte_offset=0, byte_length=10)
        content = b"0123456789"  # exactly 10 bytes
        assert _source_in_bounds(sym, content) is True

    def test_at_boundary(self):
        sym = FakeSymbol(byte_offset=5, byte_length=5)
        content = b"0123456789"
        assert _source_in_bounds(sym, content) is True

    def test_out_of_bounds(self):
        sym = FakeSymbol(byte_offset=5, byte_length=10)
        content = b"0123456789"  # only 10 bytes, but offset+length=15
        assert _source_in_bounds(sym, content) is False

    def test_zero_length(self):
        sym = FakeSymbol(byte_offset=0, byte_length=0)
        content = b"anything"
        assert _source_in_bounds(sym, content) is True

    def test_empty_content(self):
        sym = FakeSymbol(byte_offset=0, byte_length=1)
        content = b""
        assert _source_in_bounds(sym, content) is False

    def test_large_offset(self):
        sym = FakeSymbol(byte_offset=1000, byte_length=1)
        content = b"short"
        assert _source_in_bounds(sym, content) is False
