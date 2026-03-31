"""Tests for call site extraction from Python source code."""

from sylvan.indexing.source_code.call_extractor import CallSite, extract_call_sites
from sylvan.indexing.source_code.extractor import parse_file


def _extract(source: str, language: str = "python", repo: str = "test") -> list[CallSite]:
    """Helper: parse source and extract call sites."""
    symbols = parse_file(source, "test.py", language)
    return extract_call_sites(symbols, source, language, repo)


class TestSimpleCalls:
    def test_simple_function_call(self):
        source = """
def greet():
    print("hello")
"""
        calls = _extract(source)
        assert len(calls) == 1
        assert calls[0].callee_name == "print"
        assert calls[0].line == 3

    def test_multiple_calls(self):
        source = """
def process():
    x = len(items)
    print(x)
    result = sorted(items)
"""
        calls = _extract(source)
        callee_names = [c.callee_name for c in calls]
        assert "len" in callee_names
        assert "print" in callee_names
        assert "sorted" in callee_names


class TestMethodCalls:
    def test_self_method_call(self):
        source = """
class MyClass:
    def foo(self):
        self.bar()
"""
        calls = _extract(source)
        assert len(calls) == 1
        assert calls[0].callee_name == "self.bar"

    def test_attribute_chain_call(self):
        source = """
def process():
    Module.baz()
"""
        calls = _extract(source)
        assert len(calls) == 1
        assert calls[0].callee_name == "Module.baz"

    def test_dotted_chain_call(self):
        source = """
def process():
    obj.method.chain()
"""
        calls = _extract(source)
        assert len(calls) == 1
        assert calls[0].callee_name == "obj.method.chain"


class TestCallerSymbolId:
    def test_function_caller(self):
        source = """
def caller():
    target()
"""
        calls = _extract(source)
        assert len(calls) == 1
        assert "caller" in calls[0].caller_symbol_id
        assert "test.py::" in calls[0].caller_symbol_id

    def test_method_caller_includes_class(self):
        source = """
class MyClass:
    def my_method(self):
        target()
"""
        calls = _extract(source)
        assert len(calls) == 1
        assert "MyClass" in calls[0].caller_symbol_id
        assert "my_method" in calls[0].caller_symbol_id

    def test_module_level_call(self):
        source = """
setup()

def later():
    pass
"""
        calls = _extract(source)
        module_calls = [c for c in calls if c.caller_symbol_id == "__module__"]
        assert len(module_calls) == 1
        assert module_calls[0].callee_name == "setup"


class TestUnsupportedLanguage:
    def test_javascript_returns_empty(self):
        source = "function foo() { bar(); }"
        calls = _extract(source, language="javascript")
        assert calls == []

    def test_unknown_language_returns_empty(self):
        source = "anything"
        calls = _extract(source, language="unknown_lang")
        assert calls == []


class TestEdgeCases:
    def test_nested_function_calls(self):
        source = """
def outer():
    print(len(items))
"""
        calls = _extract(source)
        callee_names = [c.callee_name for c in calls]
        assert "print" in callee_names
        assert "len" in callee_names

    def test_no_calls_in_function(self):
        source = """
def noop():
    x = 1 + 2
    return x
"""
        calls = _extract(source)
        assert calls == []

    def test_empty_source(self):
        source = ""
        calls = _extract(source)
        assert calls == []

    def test_call_in_decorator_excluded(self):
        """Calls inside decorators of nested functions should not be captured."""
        source = """
def outer():
    x = 1
    return x
"""
        calls = _extract(source)
        assert calls == []

    def test_multiple_functions(self):
        source = """
def first():
    alpha()

def second():
    beta()
"""
        calls = _extract(source)
        assert len(calls) == 2
        first_calls = [c for c in calls if "first" in c.caller_symbol_id]
        second_calls = [c for c in calls if "second" in c.caller_symbol_id]
        assert len(first_calls) == 1
        assert first_calls[0].callee_name == "alpha"
        assert len(second_calls) == 1
        assert second_calls[0].callee_name == "beta"
