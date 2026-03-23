"""Tests for quality metrics analysis."""

from __future__ import annotations

from sylvan.analysis.quality.quality_metrics import _estimate_complexity, _has_type_annotations


class TestHasTypeAnnotations:
    def test_python_return_annotation(self):
        assert _has_type_annotations("def foo(x) -> int") is True

    def test_python_param_annotation(self):
        assert _has_type_annotations("def foo(x: int)") is True

    def test_python_both_annotations(self):
        assert _has_type_annotations("def foo(x: int) -> str") is True

    def test_typescript_type(self):
        assert _has_type_annotations("function foo(x: number): string") is True

    def test_no_annotations(self):
        assert _has_type_annotations("def foo(x, y)") is False

    def test_empty_signature(self):
        assert _has_type_annotations("") is False

    def test_colon_in_type(self):
        assert _has_type_annotations("foo: int") is True


class TestEstimateComplexity:
    def test_simple_function(self):
        source = "def foo():\n    return 1\n"
        # Base complexity of 1, no branches
        assert _estimate_complexity(source) == 1

    def test_single_if(self):
        source = "def foo(x):\n    if x > 0:\n        return 1\n    return 0\n"
        assert _estimate_complexity(source) == 2  # 1 + 1 if

    def test_if_elif_else(self):
        source = "if x > 0:\n    pass\nelif x == 0:\n    pass\nelse:\n    pass\n"
        assert _estimate_complexity(source) == 4  # 1 + if + elif + else

    def test_for_loop(self):
        source = "for i in range(10):\n    print(i)\n"
        assert _estimate_complexity(source) == 2  # 1 + for

    def test_while_loop(self):
        source = "while True:\n    break\n"
        assert _estimate_complexity(source) == 2  # 1 + while

    def test_try_except(self):
        source = "try:\n    x()\nexcept ValueError:\n    pass\n"
        assert _estimate_complexity(source) == 2  # 1 + except

    def test_and_or_operators(self):
        source = "if a and b or c:\n    pass\n"
        # 1 + if + and + or = 4
        assert _estimate_complexity(source) == 4

    def test_nested_branches(self):
        source = "if a:\n    if b:\n        for i in c:\n            while d:\n                pass\n"
        # 1 + if + if + for + while = 5
        assert _estimate_complexity(source) == 5

    def test_empty_source(self):
        assert _estimate_complexity("") == 1  # base complexity

    def test_switch_case(self):
        source = "switch (x) {\n    case 1: break;\n    case 2: break;\n}\n"
        # 1 + switch + case + case = 4
        assert _estimate_complexity(source) == 4
