"""Tests for per-symbol complexity metrics."""

from __future__ import annotations

from sylvan.indexing.source_code.complexity import compute_complexity


class TestCyclomaticComplexity:
    def test_simple_function(self):
        source = "def hello():\n    return 1\n"
        result = compute_complexity(source, "python")
        assert result["cyclomatic"] == 1

    def test_branches_increase_complexity(self):
        source = """def process(x):
    if x > 0:
        for i in range(x):
            if i % 2 == 0:
                pass
            else:
                pass
    while x > 0:
        x -= 1
"""
        result = compute_complexity(source, "python")
        assert result["cyclomatic"] >= 5

    def test_boolean_operators(self):
        source = "def check(a, b):\n    if a and b or not a:\n        pass\n"
        result = compute_complexity(source, "python")
        assert result["cyclomatic"] >= 3

    def test_try_except(self):
        source = """def risky():
    try:
        do_something()
    except ValueError:
        handle()
    except TypeError:
        other()
"""
        result = compute_complexity(source, "python")
        assert result["cyclomatic"] >= 3

    def test_javascript_complexity(self):
        source = """function process(x) {
    if (x > 0) {
        for (let i = 0; i < x; i++) {
            switch (i) {
                case 0: break;
                case 1: break;
            }
        }
    }
}"""
        result = compute_complexity(source, "javascript")
        assert result["cyclomatic"] >= 4

    def test_empty_source(self):
        result = compute_complexity("", "python")
        assert result["cyclomatic"] == 1

    def test_unknown_language(self):
        result = compute_complexity("if x then y", "brainfuck")
        assert result["cyclomatic"] >= 1


class TestMaxNesting:
    def test_flat_function(self):
        source = "def hello():\n    return 1\n"
        result = compute_complexity(source, "python")
        assert result["max_nesting"] <= 1

    def test_nested_python(self):
        source = """def deep():
    if True:
        for x in range(10):
            if x > 5:
                while True:
                    break
"""
        result = compute_complexity(source, "python")
        assert result["max_nesting"] >= 3

    def test_brace_nesting(self):
        source = """function deep() {
    if (true) {
        for (let i = 0; i < 10; i++) {
            if (i > 5) {
                console.log(i);
            }
        }
    }
}"""
        result = compute_complexity(source, "javascript")
        assert result["max_nesting"] >= 3

    def test_empty_source(self):
        result = compute_complexity("", "python")
        assert result["max_nesting"] == 0


class TestParamCount:
    def test_no_params(self):
        source = "def hello():\n    pass\n"
        result = compute_complexity(source, "python")
        assert result["param_count"] == 0

    def test_self_excluded(self):
        source = "def method(self, x, y):\n    pass\n"
        result = compute_complexity(source, "python")
        assert result["param_count"] == 2

    def test_cls_excluded(self):
        source = "def method(cls, x):\n    pass\n"
        result = compute_complexity(source, "python")
        assert result["param_count"] == 1

    def test_multiple_params(self):
        source = "def func(a, b, c, d, e):\n    pass\n"
        result = compute_complexity(source, "python")
        assert result["param_count"] == 5

    def test_typed_params(self):
        source = "def func(a: int, b: str = 'hello') -> bool:\n    pass\n"
        result = compute_complexity(source, "python")
        assert result["param_count"] == 2

    def test_js_params(self):
        source = "function process(a, b, c) {\n    return a + b + c;\n}\n"
        result = compute_complexity(source, "javascript")
        assert result["param_count"] == 3

    def test_no_parens(self):
        source = "MAX_RETRIES = 3\n"
        result = compute_complexity(source, "python")
        assert result["param_count"] == 0

    def test_complex_generic_params(self):
        source = "def func(items: list[dict[str, Any]], callback: Callable[[int], bool]):\n    pass\n"
        result = compute_complexity(source, "python")
        assert result["param_count"] == 2
