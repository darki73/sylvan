"""Tests for symbol extraction from source code."""

from sylvan.indexing.source_code.extractor import parse_file


class TestPythonExtraction:
    def test_extracts_functions(self):
        code = '''
def hello(name: str) -> str:
    """Say hello."""
    return f"Hello, {name}"
'''
        symbols = parse_file(code, "test.py", "python")
        funcs = [s for s in symbols if s.kind == "function"]
        assert len(funcs) == 1
        assert funcs[0].name == "hello"
        assert "name: str" in funcs[0].signature

    def test_extracts_classes_and_methods(self):
        code = '''
class MyClass:
    """A test class."""

    def method_one(self, x: int) -> int:
        """First method."""
        return x + 1

    def method_two(self):
        pass
'''
        symbols = parse_file(code, "test.py", "python")
        classes = [s for s in symbols if s.kind == "class"]
        methods = [s for s in symbols if s.kind == "method"]

        assert len(classes) == 1
        assert classes[0].name == "MyClass"
        assert len(methods) == 2
        assert methods[0].parent_symbol_id is not None

    def test_extracts_constants(self):
        code = """
MAX_RETRIES = 3
DEFAULT_TIMEOUT = 30
regular_var = "not a constant"
"""
        symbols = parse_file(code, "test.py", "python")
        constants = [s for s in symbols if s.kind == "constant"]
        assert len(constants) == 2
        names = {c.name for c in constants}
        assert "MAX_RETRIES" in names
        assert "DEFAULT_TIMEOUT" in names

    def test_extracts_docstrings(self):
        code = '''
def documented():
    """This is the docstring."""
    pass
'''
        symbols = parse_file(code, "test.py", "python")
        assert len(symbols) == 1
        assert "This is the docstring" in (symbols[0].docstring or "")

    def test_extracts_decorators(self):
        code = """
@property
def my_prop(self):
    return self._val

@staticmethod
def static_method():
    pass
"""
        symbols = parse_file(code, "test.py", "python")
        assert any("@property" in (s.decorators or []) for s in symbols if s.name == "my_prop")

    def test_byte_offsets_are_correct(self):
        code = """def first():
    pass

def second():
    pass
"""
        symbols = parse_file(code, "test.py", "python")
        source_bytes = code.encode("utf-8")
        for sym in symbols:
            extracted = source_bytes[sym.byte_offset : sym.byte_offset + sym.byte_length]
            text = extracted.decode("utf-8")
            assert sym.name in text

    def test_empty_file(self):
        symbols = parse_file("", "empty.py", "python")
        assert symbols == []

    def test_syntax_error_graceful(self):
        code = "def broken(:\n    pass"
        symbols = parse_file(code, "bad.py", "python")
        # Should not crash, may extract partial results
        assert isinstance(symbols, list)


class TestTypeScriptExtraction:
    def test_extracts_functions(self):
        code = """
function greet(name: string): string {
    return `Hello, ${name}`;
}
"""
        symbols = parse_file(code, "test.ts", "typescript")
        funcs = [s for s in symbols if s.kind == "function"]
        assert len(funcs) == 1
        assert funcs[0].name == "greet"

    def test_extracts_interfaces(self):
        code = """
interface Config {
    apiUrl: string;
    timeout: number;
}
"""
        symbols = parse_file(code, "test.ts", "typescript")
        types = [s for s in symbols if s.kind == "type"]
        assert len(types) == 1
        assert types[0].name == "Config"

    def test_extracts_classes_and_methods(self):
        code = """
class ApiClient {
    constructor(private url: string) {}

    async fetch(path: string): Promise<Response> {
        return fetch(this.url + path);
    }
}
"""
        symbols = parse_file(code, "test.ts", "typescript")
        classes = [s for s in symbols if s.kind == "class"]
        methods = [s for s in symbols if s.kind == "method"]
        assert len(classes) == 1
        assert len(methods) >= 1

    def test_extracts_enums(self):
        code = """
enum Color {
    Red = "RED",
    Green = "GREEN",
    Blue = "BLUE",
}
"""
        symbols = parse_file(code, "test.ts", "typescript")
        types = [s for s in symbols if s.kind == "type"]
        assert any(t.name == "Color" for t in types)


class TestGoExtraction:
    def test_extracts_functions(self):
        code = """package main

func Hello(name string) string {
    return "Hello, " + name
}
"""
        symbols = parse_file(code, "test.go", "go")
        funcs = [s for s in symbols if s.kind == "function"]
        assert len(funcs) == 1
        assert funcs[0].name == "Hello"

    def test_extracts_types(self):
        code = """package main

type Server struct {
    port int
    host string
}

type Handler interface {
    Handle(r Request) Response
}
"""
        symbols = parse_file(code, "test.go", "go")
        types = [s for s in symbols if s.kind == "type"]
        assert len(types) >= 2

    def test_extracts_methods(self):
        code = """package main

type Server struct {
    port int
}

func (s *Server) Start() error {
    return nil
}
"""
        symbols = parse_file(code, "test.go", "go")
        methods = [s for s in symbols if s.kind == "method"]
        assert len(methods) == 1
        assert methods[0].name == "Start"

    def test_extracts_preceding_comments(self):
        code = """package main

// Hello greets someone.
func Hello(name string) string {
    return "Hello, " + name
}
"""
        symbols = parse_file(code, "test.go", "go")
        assert len(symbols) >= 1
        assert symbols[0].docstring and "greets" in symbols[0].docstring


class TestCssExtraction:
    def test_extracts_rule_sets(self):
        code = ".foo { color: red; }\n#bar { margin: 0; }\n"
        symbols = parse_file(code, "test.css", "css")
        names = {s.name for s in symbols if s.kind == "type"}
        assert ".foo" in names
        assert "#bar" in names

    def test_extracts_keyframes(self):
        code = "@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }\n"
        symbols = parse_file(code, "test.css", "css")
        funcs = [s for s in symbols if s.kind == "function"]
        assert any(s.name == "fadeIn" for s in funcs)

    def test_extracts_plain_import(self):
        code = '@import "reset.css";\n'
        symbols = parse_file(code, "test.css", "css")
        imports = [s for s in symbols if s.kind == "constant"]
        assert len(imports) == 1
        assert "reset.css" in imports[0].name

    def test_extracts_url_import(self):
        code = '@import url("theme.css");\n'
        symbols = parse_file(code, "test.css", "css")
        imports = [s for s in symbols if s.kind == "constant"]
        assert len(imports) == 1
        assert "theme.css" in imports[0].name
