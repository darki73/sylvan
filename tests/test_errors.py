"""Tests for the errors module — exception hierarchy and legacy constructors."""

from __future__ import annotations

import pytest

from sylvan.error_codes import (
    SylvanError,
    ContentNotAvailableError,
    EmptyQueryError,
    IndexFileNotFoundError,
    IndexNotADirectoryError,
    NoFilesFoundError,
    ParseError,
    PathTooBroadError,
    RepoNotFoundError,
    SectionNotFoundError,
    SourceNotAvailableError,
    SymbolNotFoundError,
    WorkspaceNotFoundError,
    _LegacyError,
    content_not_available,
    empty_query,
    no_files_found,
    not_a_directory,
    parse_error,
    repo_not_found,
    section_not_found,
    source_not_available,
    symbol_not_found,
    workspace_not_found,
)

# ---------------------------------------------------------------------------
# New exception hierarchy tests
# ---------------------------------------------------------------------------


class TestSylvanErrorException:
    def test_is_exception(self):
        err = SylvanError("something broke")
        assert isinstance(err, Exception)

    def test_to_dict_basic(self):
        err = SylvanError("something broke")
        d = err.to_dict()
        assert d["error"] == "internal_error"
        assert d["detail"] == "something broke"

    def test_to_dict_no_detail(self):
        err = SylvanError()
        d = err.to_dict()
        assert d == {"error": "internal_error"}

    def test_to_dict_with_context(self):
        err = SylvanError("oops", symbol_id="abc")
        d = err.to_dict()
        assert d["symbol_id"] == "abc"
        assert d["error"] == "internal_error"
        assert d["detail"] == "oops"

    def test_to_dict_with_meta(self):
        meta = {"timing_ms": 1.2}
        err = SylvanError("oops", _meta=meta)
        d = err.to_dict()
        assert d["_meta"] == meta

    def test_to_dict_without_meta(self):
        err = SylvanError("oops")
        d = err.to_dict()
        assert "_meta" not in d

    def test_str(self):
        err = SylvanError("something broke")
        assert str(err) == "something broke"

    def test_context_stored(self):
        err = SylvanError("x", key="val")
        assert err.context == {"key": "val"}


class TestSymbolNotFoundExc:
    def test_code(self):
        err = SymbolNotFoundError(symbol_id="sym1")
        assert err.code == "symbol_not_found"

    def test_is_sylvan_error(self):
        assert issubclass(SymbolNotFoundError, SylvanError)

    def test_to_dict(self):
        err = SymbolNotFoundError(symbol_id="abc")
        d = err.to_dict()
        assert d["error"] == "symbol_not_found"
        assert d["symbol_id"] == "abc"

    def test_to_dict_with_meta(self):
        err = SymbolNotFoundError(symbol_id="abc", _meta={"timing_ms": 0.5})
        d = err.to_dict()
        assert d["_meta"]["timing_ms"] == 0.5

    def test_raise_and_catch(self):
        with pytest.raises(SylvanError) as exc_info:
            raise SymbolNotFoundError("missing", symbol_id="x")
        assert exc_info.value.code == "symbol_not_found"
        assert "x" in exc_info.value.to_dict()["symbol_id"]


class TestSectionNotFoundExc:
    def test_code(self):
        err = SectionNotFoundError(section_id="sec1")
        assert err.code == "section_not_found"

    def test_to_dict(self):
        d = SectionNotFoundError(section_id="sec1").to_dict()
        assert d["error"] == "section_not_found"
        assert d["section_id"] == "sec1"


class TestRepoNotFoundExc:
    def test_code(self):
        assert RepoNotFoundError(repo="r").code == "repo_not_found"


class TestFileNotFoundExc:
    def test_code(self):
        assert IndexFileNotFoundError(file_path="f.py").code == "file_not_found"

    def test_to_dict(self):
        d = IndexFileNotFoundError(file_path="f.py").to_dict()
        assert d["file_path"] == "f.py"


class TestWorkspaceNotFoundExc:
    def test_code(self):
        assert WorkspaceNotFoundError(workspace="ws").code == "workspace_not_found"


class TestSourceNotAvailableExc:
    def test_code(self):
        assert SourceNotAvailableError(symbol_id="s").code == "source_not_available"


class TestContentNotAvailableExc:
    def test_code(self):
        assert ContentNotAvailableError(section_id="s").code == "content_not_available"


class TestEmptyQueryExc:
    def test_code(self):
        assert EmptyQueryError().code == "empty_query"


class TestPathTooBroadExc:
    def test_code(self):
        assert PathTooBroadError(path="/").code == "path_too_broad"


class TestNotADirectoryExc:
    def test_code(self):
        assert IndexNotADirectoryError(path="/x").code == "not_a_directory"


class TestNoFilesFoundExc:
    def test_code(self):
        assert NoFilesFoundError(path="/d").code == "no_files_found"


class TestParseErrorExc:
    def test_code(self):
        assert ParseError(path="/f.py", detail="bad").code == "parse_error"


# ---------------------------------------------------------------------------
# Legacy shim tests (backward-compatible constructors)
# ---------------------------------------------------------------------------


class TestLegacySylvanError:
    def test_to_dict_basic(self):
        err = _LegacyError("TEST", "test message")
        d = err.to_dict()
        assert d["error_code"] == "TEST"
        assert d["error"] == "test message"
        assert "details" not in d

    def test_to_dict_with_details(self):
        err = _LegacyError("TEST", "msg", {"key": "val"})
        d = err.to_dict()
        assert d["details"] == {"key": "val"}

    def test_defaults_details_to_empty_dict(self):
        err = _LegacyError("X", "Y")
        assert err.details == {}


class TestSymbolNotFound:
    def test_error_code(self):
        d = symbol_not_found("sym1")
        assert d["error_code"] == "SYMBOL_NOT_FOUND"

    def test_message_contains_id(self):
        d = symbol_not_found("my_sym")
        assert "my_sym" in d["error"]

    def test_details(self):
        d = symbol_not_found("abc")
        assert d["details"]["symbol_id"] == "abc"


class TestSectionNotFound:
    def test_error_code(self):
        d = section_not_found("sec1")
        assert d["error_code"] == "SECTION_NOT_FOUND"

    def test_message_contains_id(self):
        d = section_not_found("sec1")
        assert "sec1" in d["error"]


class TestRepoNotFound:
    def test_error_code(self):
        d = repo_not_found("myrepo")
        assert d["error_code"] == "REPO_NOT_FOUND"

    def test_message_contains_repo(self):
        d = repo_not_found("myrepo")
        assert "myrepo" in d["error"]


class TestWorkspaceNotFound:
    def test_error_code(self):
        d = workspace_not_found("ws1")
        assert d["error_code"] == "WORKSPACE_NOT_FOUND"

    def test_message_contains_workspace(self):
        d = workspace_not_found("ws1")
        assert "ws1" in d["error"]


class TestNotADirectory:
    def test_error_code(self):
        d = not_a_directory("/test/missing")
        assert d["error_code"] == "NOT_A_DIRECTORY"

    def test_details(self):
        d = not_a_directory("/some/path")
        assert d["details"]["path"] == "/some/path"


class TestSourceNotAvailable:
    def test_error_code(self):
        d = source_not_available("sym_x")
        assert d["error_code"] == "SOURCE_NOT_AVAILABLE"

    def test_message_contains_id(self):
        d = source_not_available("sym_x")
        assert "sym_x" in d["error"]


class TestContentNotAvailable:
    def test_error_code(self):
        d = content_not_available("sec_y")
        assert d["error_code"] == "CONTENT_NOT_AVAILABLE"

    def test_message_contains_id(self):
        d = content_not_available("sec_y")
        assert "sec_y" in d["error"]


class TestEmptyQuery:
    def test_error_code(self):
        d = empty_query()
        assert d["error_code"] == "EMPTY_QUERY"

    def test_no_details(self):
        d = empty_query()
        assert "details" not in d


class TestParseError:
    def test_error_code(self):
        d = parse_error("/file.py", "syntax error")
        assert d["error_code"] == "PARSE_ERROR"

    def test_details(self):
        d = parse_error("/file.py", "syntax error")
        assert d["details"]["path"] == "/file.py"
        assert d["details"]["detail"] == "syntax error"


class TestNoFilesFound:
    def test_error_code(self):
        d = no_files_found("/empty/dir")
        assert d["error_code"] == "NO_FILES_FOUND"

    def test_details(self):
        d = no_files_found("/empty/dir")
        assert d["details"]["path"] == "/empty/dir"
