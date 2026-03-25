"""Tests for the heuristic summary provider."""

from __future__ import annotations

from sylvan.providers.builtin.heuristic import HeuristicSummaryProvider


class TestHeuristicSummaryProvider:
    def setup_method(self):
        self.provider = HeuristicSummaryProvider()

    # --- Properties ---

    def test_name(self):
        assert self.provider.name == "heuristic"

    def test_always_available(self):
        assert self.provider.available() is True

    # --- summarize_symbol ---

    def test_summarize_symbol_with_docstring(self):
        result = self.provider.summarize_symbol(
            signature="def foo(x: int) -> str",
            docstring="Convert an integer to string. Extra details here.",
            source="def foo(x: int) -> str:\n    return str(x)\n",
        )
        assert result == "Convert an integer to string."

    def test_summarize_symbol_docstring_first_sentence(self):
        result = self.provider.summarize_symbol(
            signature="def bar()",
            docstring="This is the summary. And more detail.",
            source="",
        )
        assert result == "This is the summary."

    def test_summarize_symbol_no_docstring_uses_signature(self):
        result = self.provider.summarize_symbol(
            signature="def compute(a: int, b: int) -> int",
            docstring=None,
            source="def compute(a, b):\n    return a + b\n",
        )
        assert result == "def compute(a: int, b: int) -> int"

    def test_summarize_symbol_empty_docstring_uses_signature(self):
        result = self.provider.summarize_symbol(
            signature="def hello()",
            docstring="",
            source="",
        )
        assert result == "def hello()"

    def test_summarize_symbol_no_docstring_no_signature(self):
        result = self.provider.summarize_symbol(
            signature="",
            docstring=None,
            source="x = 42\n",
        )
        # Falls back to _extract_summary of source
        assert "42" in result or "x" in result

    def test_summarize_symbol_all_empty(self):
        result = self.provider.summarize_symbol(
            signature="",
            docstring=None,
            source="",
        )
        assert result == ""

    def test_summarize_symbol_long_signature_truncated(self):
        sig = "def " + "x" * 200 + "()"
        result = self.provider.summarize_symbol(
            signature=sig,
            docstring=None,
            source="",
        )
        assert len(result) <= 120

    # --- summarize (batch) ---

    def test_summarize_batch(self):
        texts = [
            "def foo():\n    '''Hello world. Detail.'''\n    pass\n",
            "class Bar:\n    '''A bar class.'''\n    pass\n",
        ]
        results = self.provider.summarize(texts)
        assert len(results) == 2
        assert all(isinstance(r, str) for r in results)

    def test_summarize_batch_empty(self):
        results = self.provider.summarize([])
        assert results == []

    def test_summarize_batch_with_empty_text(self):
        results = self.provider.summarize(["", "def foo():\n    pass\n"])
        assert len(results) == 2
        assert results[0] == ""

    # --- _extract_summary / _first_sentence internals ---

    def test_first_sentence_strips_comment_markers(self):
        from sylvan.providers.builtin.heuristic import _first_sentence

        result = _first_sentence("/// Compute the hash value.")
        assert result == "Compute the hash value."

    def test_first_sentence_python_docstring_markers(self):
        from sylvan.providers.builtin.heuristic import _first_sentence

        result = _first_sentence('"""Return the count."""')
        assert result == "Return the count."

    def test_generate_summary_skips_decorators(self):
        source = "@staticmethod\ndef foo():\n    pass\n"
        result = self.provider._generate_summary(f"Source:\n{source}")
        assert "foo" in result
