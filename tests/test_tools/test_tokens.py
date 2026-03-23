"""Tests for sylvan.tools.support.token_counting — token counting and savings estimation."""

from __future__ import annotations

from sylvan.tools.support.token_counting import count_tokens, estimate_savings


class TestCountTokens:
    def test_returns_int_for_text(self):
        result = count_tokens("Hello, world!")
        # tiktoken should be available
        assert isinstance(result, int)
        assert result > 0

    def test_empty_string_returns_zero(self):
        result = count_tokens("")
        assert result == 0

    def test_longer_text_more_tokens(self):
        short = count_tokens("hi")
        long = count_tokens("This is a much longer sentence with many words in it.")
        assert long > short

    def test_code_tokenized(self):
        code = "def hello_world():\n    return 'hello'\n"
        result = count_tokens(code)
        assert result > 0


class TestEstimateSavings:
    def test_byte_ratio_path(self):
        result = estimate_savings(
            returned_bytes=100,
            total_file_bytes=1000,
        )
        assert result["returned_bytes"] == 100
        assert result["total_file_bytes"] == 1000
        assert result["bytes_avoided"] == 900
        assert result["file_percent_returned"] == 10.0
        assert result["method"] == "byte_ratio"

    def test_tiktoken_path(self):
        returned_text = "def foo(): pass"
        total_text = "def foo(): pass\ndef bar(): pass\ndef baz(): pass\n"
        result = estimate_savings(
            returned_bytes=len(returned_text.encode()),
            total_file_bytes=len(total_text.encode()),
            returned_text=returned_text,
            total_file_text=total_text,
        )
        assert result["method"] == "tiktoken_cl100k"
        assert "returned_tokens" in result
        assert "total_file_tokens" in result
        assert "tokens_avoided" in result
        assert result["tokens_avoided"] >= 0

    def test_zero_total_bytes(self):
        result = estimate_savings(returned_bytes=0, total_file_bytes=0)
        assert result["file_percent_returned"] == 0
        assert result["bytes_avoided"] == 0

    def test_returned_equals_total(self):
        result = estimate_savings(returned_bytes=500, total_file_bytes=500)
        assert result["bytes_avoided"] == 0
        assert result["file_percent_returned"] == 100.0

    def test_returned_larger_than_total_no_negative(self):
        result = estimate_savings(returned_bytes=200, total_file_bytes=100)
        assert result["bytes_avoided"] == 0  # max(0, ...) ensures no negative
