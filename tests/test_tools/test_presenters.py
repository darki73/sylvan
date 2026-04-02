"""Tests for model presenters."""

from types import SimpleNamespace

from sylvan.tools.base.presenters import (
    FilePresenter,
    ImportPresenter,
    ReferencePresenter,
    SectionPresenter,
    SymbolPresenter,
)


def _make_symbol(**overrides):
    defaults = {
        "symbol_id": "repo::src/main.py::foo#function",
        "name": "foo",
        "qualified_name": "foo",
        "kind": "function",
        "language": "python",
        "signature": "def foo(x: int) -> str",
        "docstring": "Does foo things.",
        "decorators": ["@log"],
        "summary": "A foo function.",
        "line_start": 10,
        "line_end": 25,
        "parent_symbol_id": None,
        "_file_path": "src/main.py",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_file(**overrides):
    defaults = {"path": "src/main.py", "language": "python"}
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_import(**overrides):
    defaults = {"specifier": "sylvan.database.orm", "names": ["Symbol", "FileRecord"]}
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_section(**overrides):
    defaults = {
        "section_id": "repo::docs/guide.md::installation",
        "title": "Installation",
        "level": 2,
        "summary": "How to install.",
        "tags": ["setup"],
        "_doc_path": "docs/guide.md",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class TestSymbolPresenter:
    def test_brief(self):
        sym = _make_symbol()
        d = SymbolPresenter.brief(sym)
        assert d["symbol_id"] == "repo::src/main.py::foo#function"
        assert d["name"] == "foo"
        assert d["kind"] == "function"
        assert d["file"] == "src/main.py"
        assert d["line_start"] == 10
        assert "signature" not in d
        assert "source" not in d

    def test_standard(self):
        sym = _make_symbol()
        d = SymbolPresenter.standard(sym)
        assert d["signature"] == "def foo(x: int) -> str"
        assert d["language"] == "python"
        assert d["summary"] == "A foo function."
        assert d["qualified_name"] == "foo"
        assert "source" not in d
        assert "docstring" not in d

    def test_standard_file_path_override(self):
        sym = _make_symbol()
        d = SymbolPresenter.standard(sym, file_path="override.py")
        assert d["file"] == "override.py"

    def test_full(self):
        sym = _make_symbol()
        d = SymbolPresenter.full(sym, source="def foo(): pass")
        assert d["source"] == "def foo(): pass"
        assert d["docstring"] == "Does foo things."
        assert d["decorators"] == ["@log"]
        assert d["line_end"] == 25

    def test_sibling(self):
        sym = _make_symbol()
        d = SymbolPresenter.sibling(sym)
        assert set(d.keys()) == {"symbol_id", "name", "kind", "signature", "line_start"}

    def test_outline(self):
        sym = _make_symbol()
        d = SymbolPresenter.outline(sym)
        assert "parent_symbol_id" in d
        assert "line_end" in d
        assert "source" not in d

    def test_empty_optional_fields(self):
        sym = _make_symbol(signature="", docstring="", decorators=[], summary="")
        d = SymbolPresenter.full(sym)
        assert d["signature"] == ""
        assert d["docstring"] == ""
        assert d["decorators"] == []


class TestFilePresenter:
    def test_brief(self):
        f = _make_file()
        d = FilePresenter.brief(f)
        assert d == {"path": "src/main.py", "language": "python"}

    def test_with_counts(self):
        f = _make_file()
        d = FilePresenter.with_counts(f, symbol_count=42)
        assert d["symbol_count"] == 42
        assert d["path"] == "src/main.py"


class TestImportPresenter:
    def test_standard(self):
        imp = _make_import()
        d = ImportPresenter.standard(imp)
        assert d["specifier"] == "sylvan.database.orm"
        assert d["names"] == ["Symbol", "FileRecord"]

    def test_empty_names(self):
        imp = _make_import(names=None)
        d = ImportPresenter.standard(imp)
        assert d["names"] == []


class TestSectionPresenter:
    def test_brief(self):
        s = _make_section()
        d = SectionPresenter.brief(s)
        assert d["section_id"] == "repo::docs/guide.md::installation"
        assert d["title"] == "Installation"
        assert "summary" not in d

    def test_standard(self):
        s = _make_section()
        d = SectionPresenter.standard(s)
        assert d["summary"] == "How to install."
        assert d["tags"] == ["setup"]

    def test_full(self):
        s = _make_section()
        d = SectionPresenter.full(s, content="# Installation\nRun pip install.")
        assert d["content"] == "# Installation\nRun pip install."

    def test_doc_path_override(self):
        s = _make_section()
        d = SectionPresenter.standard(s, doc_path="other.md")
        assert d["doc_path"] == "other.md"


class TestReferencePresenter:
    def test_caller(self):
        ref = {
            "source_symbol_id": "repo::a.py::bar#function",
            "name": "bar",
            "kind": "function",
            "file_path": "src/a.py",
            "signature": "def bar()",
            "line": 42,
        }
        d = ReferencePresenter.caller(ref)
        assert d["symbol_id"] == "repo::a.py::bar#function"
        assert d["line"] == 42

    def test_callee(self):
        ref = {
            "target_symbol_id": "repo::b.py::baz#function",
            "name": "baz",
            "kind": "function",
            "file_path": "src/b.py",
            "signature": "def baz()",
            "line": 10,
        }
        d = ReferencePresenter.callee(ref)
        assert d["symbol_id"] == "repo::b.py::baz#function"

    def test_missing_fields_default(self):
        d = ReferencePresenter.caller({})
        assert d["symbol_id"] == ""
        assert d["name"] == ""
        assert d["line"] is None


class TestPresenterFieldConsistency:
    """Verify that field names are consistent across detail levels."""

    def test_symbol_brief_subset_of_standard(self):
        sym = _make_symbol()
        brief_keys = set(SymbolPresenter.brief(sym).keys())
        standard_keys = set(SymbolPresenter.standard(sym).keys())
        assert brief_keys.issubset(standard_keys)

    def test_symbol_standard_subset_of_full(self):
        sym = _make_symbol()
        standard_keys = set(SymbolPresenter.standard(sym).keys())
        full_keys = set(SymbolPresenter.full(sym).keys())
        assert standard_keys.issubset(full_keys)

    def test_section_brief_subset_of_standard(self):
        s = _make_section()
        brief_keys = set(SectionPresenter.brief(s).keys())
        standard_keys = set(SectionPresenter.standard(s).keys())
        assert brief_keys.issubset(standard_keys)

    def test_section_standard_subset_of_full(self):
        s = _make_section()
        standard_keys = set(SectionPresenter.standard(s).keys())
        full_keys = set(SectionPresenter.full(s, content="x").keys())
        assert standard_keys.issubset(full_keys)

    def test_caller_callee_same_shape(self):
        ref = {
            "source_symbol_id": "a",
            "target_symbol_id": "b",
            "name": "x",
            "kind": "f",
            "file_path": "f.py",
            "signature": "s",
            "line": 1,
        }
        caller_keys = set(ReferencePresenter.caller(ref).keys())
        callee_keys = set(ReferencePresenter.callee(ref).keys())
        assert caller_keys == callee_keys
