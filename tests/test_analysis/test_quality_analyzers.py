"""Tests for quality analysis modules: code_smells, duplication, security_scanner, test_coverage, quality_metrics."""

from __future__ import annotations

import hashlib
import os

import pytest

from sylvan.analysis.quality.code_smells import CodeSmell, _count_parameters, detect_code_smells
from sylvan.analysis.quality.duplication import DuplicateGroup, _normalize_body, detect_duplicates
from sylvan.analysis.quality.quality_metrics import (
    compute_quality_metrics,
    get_low_quality_symbols,
    get_quality,
)
from sylvan.analysis.quality.security_scanner import SECURITY_RULES, SecurityFinding, scan_security
from sylvan.analysis.quality.test_coverage import analyze_test_coverage
from sylvan.config import reset_config
from sylvan.context import SylvanContext, reset_context, set_context
from sylvan.database.backends.sqlite import SQLiteBackend
from sylvan.database.migrations.runner import run_migrations
from sylvan.database.orm.models.blob import Blob
from sylvan.database.orm.runtime.query_cache import QueryCache
from sylvan.session.tracker import SessionTracker

# ---------------------------------------------------------------------------
# Shared fixture: sets up backend, context, and seeds a repo with files/symbols
# ---------------------------------------------------------------------------


@pytest.fixture
async def analysis_ctx(tmp_path):
    """Create an in-memory DB with schema and seed data for analysis tests."""
    os.environ["SYLVAN_HOME"] = str(tmp_path)
    reset_config()

    db_path = tmp_path / "test.db"
    backend = SQLiteBackend(db_path)
    await backend.connect()
    await run_migrations(backend)

    context = SylvanContext(
        backend=backend,
        session=SessionTracker(),
        cache=QueryCache(),
    )
    token = set_context(context)

    # Seed repo
    await backend.execute(
        "INSERT INTO repos (id, name, source_path, indexed_at) VALUES (1, 'myrepo', '/tmp/repo', '2024-01-01')"
    )

    yield backend

    reset_context(token)
    await backend.disconnect()
    os.environ.pop("SYLVAN_HOME", None)
    reset_config()


async def _insert_file(backend, *, file_id, path, language="python", content_hash="hash1", repo_id=1):
    """Insert a file record."""
    await backend.execute(
        "INSERT INTO files (id, repo_id, path, language, content_hash, byte_size) "
        f"VALUES ({file_id}, {repo_id}, '{path}', '{language}', '{content_hash}', 1000)"
    )


async def _insert_symbol(
    backend,
    *,
    file_id,
    symbol_id,
    name,
    kind,
    signature="",
    docstring=None,
    line_start=None,
    line_end=None,
    byte_offset=0,
    byte_length=0,
    parent_symbol_id=None,
    language="python",
    content_hash=None,
):
    """Insert a symbol record."""
    doc_val = f"'{docstring}'" if docstring else "NULL"
    parent_val = f"'{parent_symbol_id}'" if parent_symbol_id else "NULL"
    ls = line_start if line_start is not None else "NULL"
    le = line_end if line_end is not None else "NULL"
    ch_val = f"'{content_hash}'" if content_hash else "NULL"
    await backend.execute(
        "INSERT INTO symbols (file_id, symbol_id, name, qualified_name, kind, language, "
        "signature, docstring, byte_offset, byte_length, line_start, line_end, parent_symbol_id, content_hash) "
        f"VALUES ({file_id}, '{symbol_id}', '{name}', '{name}', '{kind}', '{language}', "
        f"'{signature}', {doc_val}, {byte_offset}, {byte_length}, {ls}, {le}, {parent_val}, {ch_val})"
    )


async def _store_blob(backend, content_hash: str, raw: bytes):
    """Store a blob via the Blob model."""
    await Blob.store(content_hash, raw)
    await backend.commit()


# ===========================================================================
# 1. code_smells.py
# ===========================================================================


class TestCountParameters:
    """Unit tests for _count_parameters."""

    def test_no_params(self):
        assert _count_parameters("def foo()") == 0

    def test_one_param(self):
        assert _count_parameters("def foo(x)") == 1

    def test_self_excluded(self):
        assert _count_parameters("def foo(self, x, y)") == 2

    def test_cls_excluded(self):
        assert _count_parameters("def foo(cls, x)") == 1

    def test_many_params(self):
        params = ", ".join(f"p{i}" for i in range(10))
        assert _count_parameters(f"def foo({params})") == 10

    def test_no_parens(self):
        assert _count_parameters("foo") == 0

    def test_empty_parens(self):
        assert _count_parameters("def foo(  )") == 0

    def test_with_defaults(self):
        assert _count_parameters("def foo(a, b=1, c=2)") == 3

    def test_with_type_annotations(self):
        assert _count_parameters("def foo(a: int, b: str) -> None") == 2


class TestDetectCodeSmells:
    """Integration tests for detect_code_smells."""

    async def test_too_many_parameters(self, analysis_ctx):
        backend = analysis_ctx
        await _insert_file(backend, file_id=1, path="src/utils.py", content_hash="h1")
        params = ", ".join(f"p{i}" for i in range(10))
        await _insert_symbol(
            backend,
            file_id=1,
            symbol_id="utils.py::big_func#function",
            name="big_func",
            kind="function",
            signature=f"def big_func({params})",
            docstring="A well-documented function with lots of params.",
            line_start=1,
            line_end=10,
        )
        await backend.commit()

        smells = await detect_code_smells(repo_id=1)
        types = [s.smell_type for s in smells]
        assert "too_many_parameters" in types

    async def test_too_long_medium(self, analysis_ctx):
        backend = analysis_ctx
        await _insert_file(backend, file_id=1, path="src/long.py", content_hash="h1")
        await _insert_symbol(
            backend,
            file_id=1,
            symbol_id="long.py::long_func#function",
            name="long_func",
            kind="function",
            signature="def long_func() -> None",
            docstring="This is a valid docstring for testing.",
            line_start=1,
            line_end=250,
        )
        await backend.commit()

        smells = await detect_code_smells(repo_id=1)
        long_smells = [s for s in smells if s.smell_type == "too_long"]
        assert len(long_smells) == 1
        assert long_smells[0].severity == "medium"

    async def test_too_long_high(self, analysis_ctx):
        backend = analysis_ctx
        await _insert_file(backend, file_id=1, path="src/huge.py", content_hash="h1")
        await _insert_symbol(
            backend,
            file_id=1,
            symbol_id="huge.py::huge_func#function",
            name="huge_func",
            kind="function",
            signature="def huge_func() -> None",
            docstring="This is a valid docstring for testing.",
            line_start=1,
            line_end=500,
        )
        await backend.commit()

        smells = await detect_code_smells(repo_id=1)
        long_smells = [s for s in smells if s.smell_type == "too_long"]
        assert len(long_smells) == 1
        assert long_smells[0].severity == "high"

    async def test_missing_docstring(self, analysis_ctx):
        backend = analysis_ctx
        await _insert_file(backend, file_id=1, path="src/nodoc.py", content_hash="h1")
        await _insert_symbol(
            backend,
            file_id=1,
            symbol_id="nodoc.py::no_doc_func#function",
            name="no_doc_func",
            kind="function",
            signature="def no_doc_func() -> None",
            line_start=1,
            line_end=5,
        )
        await backend.commit()

        smells = await detect_code_smells(repo_id=1)
        types = [s.smell_type for s in smells]
        assert "missing_docstring" in types

    async def test_private_symbol_no_docstring_smell(self, analysis_ctx):
        """Private symbols (starting with _) should NOT get missing_docstring smell."""
        backend = analysis_ctx
        await _insert_file(backend, file_id=1, path="src/priv.py", content_hash="h1")
        await _insert_symbol(
            backend,
            file_id=1,
            symbol_id="priv.py::_helper#function",
            name="_helper",
            kind="function",
            signature="def _helper() -> None",
            line_start=1,
            line_end=5,
        )
        await backend.commit()

        smells = await detect_code_smells(repo_id=1)
        doc_smells = [s for s in smells if s.smell_type == "missing_docstring"]
        assert len(doc_smells) == 0

    async def test_missing_types(self, analysis_ctx):
        backend = analysis_ctx
        await _insert_file(backend, file_id=1, path="src/notype.py", content_hash="h1")
        await _insert_symbol(
            backend,
            file_id=1,
            symbol_id="notype.py::untyped#function",
            name="untyped",
            kind="function",
            signature="def untyped(x, y)",
            docstring="This is a valid docstring for testing purposes.",
            line_start=1,
            line_end=5,
        )
        await backend.commit()

        smells = await detect_code_smells(repo_id=1)
        types = [s.smell_type for s in smells]
        assert "missing_types" in types

    async def test_typed_function_no_missing_types(self, analysis_ctx):
        backend = analysis_ctx
        await _insert_file(backend, file_id=1, path="src/typed.py", content_hash="h1")
        await _insert_symbol(
            backend,
            file_id=1,
            symbol_id="typed.py::typed_func#function",
            name="typed_func",
            kind="function",
            signature="def typed_func(x: int) -> str",
            docstring="This is a valid docstring for testing purposes.",
            line_start=1,
            line_end=5,
        )
        await backend.commit()

        smells = await detect_code_smells(repo_id=1)
        type_smells = [s for s in smells if s.smell_type == "missing_types"]
        assert len(type_smells) == 0

    async def test_too_many_methods(self, analysis_ctx):
        backend = analysis_ctx
        await _insert_file(backend, file_id=1, path="src/bigclass.py", content_hash="h1")
        await _insert_symbol(
            backend,
            file_id=1,
            symbol_id="bigclass.py::BigClass#class",
            name="BigClass",
            kind="class",
            signature="class BigClass",
            docstring="This is a class with too many methods for real.",
            line_start=1,
            line_end=500,
        )
        # Insert 22 methods
        for i in range(22):
            await _insert_symbol(
                backend,
                file_id=1,
                symbol_id=f"bigclass.py::BigClass.method_{i}#method",
                name=f"method_{i}",
                kind="method",
                signature=f"def method_{i}(self) -> None",
                docstring="Method docstring is valid and long enough.",
                parent_symbol_id="bigclass.py::BigClass#class",
                line_start=10 + i * 10,
                line_end=15 + i * 10,
            )
        await backend.commit()

        smells = await detect_code_smells(repo_id=1)
        method_smells = [s for s in smells if s.smell_type == "too_many_methods"]
        assert len(method_smells) == 1
        assert "22" in method_smells[0].message

    async def test_excludes_test_files(self, analysis_ctx):
        """Symbols in test files should be excluded from smell detection."""
        backend = analysis_ctx
        await _insert_file(backend, file_id=1, path="tests/test_foo.py", content_hash="h1")
        await _insert_symbol(
            backend,
            file_id=1,
            symbol_id="test_foo.py::test_something#function",
            name="test_something",
            kind="function",
            signature="def test_something()",
            line_start=1,
            line_end=5,
        )
        await backend.commit()

        smells = await detect_code_smells(repo_id=1)
        assert len(smells) == 0

    async def test_no_symbols_returns_empty(self, analysis_ctx):
        smells = await detect_code_smells(repo_id=1)
        assert smells == []

    async def test_smell_has_correct_fields(self, analysis_ctx):
        backend = analysis_ctx
        await _insert_file(backend, file_id=1, path="src/fields.py", content_hash="h1")
        await _insert_symbol(
            backend,
            file_id=1,
            symbol_id="fields.py::bare#function",
            name="bare",
            kind="function",
            signature="def bare(x, y)",
            line_start=10,
            line_end=15,
        )
        await backend.commit()

        smells = await detect_code_smells(repo_id=1)
        assert len(smells) > 0
        smell = smells[0]
        assert isinstance(smell, CodeSmell)
        assert smell.symbol_id == "fields.py::bare#function"
        assert smell.name == "bare"
        assert smell.file == "src/fields.py"
        assert smell.line == 10


# ===========================================================================
# 2. duplication.py
# ===========================================================================


class TestNormalizeBody:
    """Unit tests for _normalize_body."""

    def test_removes_comments(self):
        source = "x = 1  # comment\ny = 2  # another"
        result = _normalize_body(source)
        assert "#" not in result

    def test_removes_docstrings_double(self):
        source = '"""This is a docstring."""\nx = 1'
        result = _normalize_body(source)
        assert "docstring" not in result

    def test_removes_docstrings_single(self):
        source = "'''Another docstring.'''\nx = 1"
        result = _normalize_body(source)
        assert "docstring" not in result

    def test_normalizes_whitespace(self):
        source = "x  =  1\n\n\ny  =  2"
        result = _normalize_body(source)
        assert "\n" not in result
        assert "  " not in result

    def test_replaces_string_contents(self):
        source = 'x = "hello world"\ny = "goodbye"'
        result = _normalize_body(source)
        assert "hello" not in result
        assert "goodbye" not in result

    def test_structurally_identical_code_matches(self):
        src1 = 'def foo():\n    x = "hello"\n    return x\n'
        src2 = 'def foo():\n    x = "world"\n    return x\n'
        assert _normalize_body(src1) == _normalize_body(src2)

    def test_different_structure_does_not_match(self):
        src1 = "def foo():\n    return 1\n"
        src2 = "def foo():\n    x = 1\n    return x\n"
        assert _normalize_body(src1) != _normalize_body(src2)


class TestDetectDuplicates:
    """Integration tests for detect_duplicates."""

    async def test_finds_duplicate_functions(self, analysis_ctx):
        backend = analysis_ctx
        body = "def func():\n    x = 1\n    y = 2\n    z = x + y\n    return z\n    # padding\n    # more\n"
        content_hash = hashlib.sha256(body.encode()).hexdigest()

        await _insert_file(backend, file_id=1, path="src/a.py", content_hash=content_hash)
        await _insert_file(backend, file_id=2, path="src/b.py", content_hash=content_hash)
        await _store_blob(backend, content_hash, body.encode())

        await _insert_symbol(
            backend,
            file_id=1,
            symbol_id="a.py::func#function",
            name="func",
            kind="function",
            line_start=1,
            line_end=8,
            byte_offset=0,
            byte_length=len(body.encode()),
            content_hash=content_hash,
        )
        await _insert_symbol(
            backend,
            file_id=2,
            symbol_id="b.py::func#function",
            name="func",
            kind="function",
            line_start=1,
            line_end=8,
            byte_offset=0,
            byte_length=len(body.encode()),
            content_hash=content_hash,
        )
        await backend.commit()

        groups = await detect_duplicates(repo_id=1)
        assert len(groups) == 1
        assert len(groups[0].symbols) == 2
        assert isinstance(groups[0], DuplicateGroup)

    async def test_skips_short_functions(self, analysis_ctx):
        backend = analysis_ctx
        body = "def f():\n    return 1\n"
        content_hash = hashlib.sha256(body.encode()).hexdigest()

        await _insert_file(backend, file_id=1, path="src/short_a.py", content_hash=content_hash)
        await _insert_file(backend, file_id=2, path="src/short_b.py", content_hash=content_hash)
        await _store_blob(backend, content_hash, body.encode())

        await _insert_symbol(
            backend,
            file_id=1,
            symbol_id="short_a.py::f#function",
            name="f",
            kind="function",
            line_start=1,
            line_end=2,  # Only 1 line, below min_lines=5
            byte_offset=0,
            byte_length=len(body.encode()),
        )
        await _insert_symbol(
            backend,
            file_id=2,
            symbol_id="short_b.py::f#function",
            name="f",
            kind="function",
            line_start=1,
            line_end=2,
            byte_offset=0,
            byte_length=len(body.encode()),
        )
        await backend.commit()

        groups = await detect_duplicates(repo_id=1)
        assert len(groups) == 0

    async def test_no_duplicates_different_bodies(self, analysis_ctx):
        backend = analysis_ctx
        body1 = "def func1():\n    a = 1\n    b = 2\n    c = 3\n    d = 4\n    return a + b + c + d\n"
        body2 = "def func2():\n    x = 10\n    return x * x * x * x * x * x\n    # padding\n    # more\n    # more\n"
        hash1 = hashlib.sha256(body1.encode()).hexdigest()
        hash2 = hashlib.sha256(body2.encode()).hexdigest()

        await _insert_file(backend, file_id=1, path="src/diff_a.py", content_hash=hash1)
        await _insert_file(backend, file_id=2, path="src/diff_b.py", content_hash=hash2)
        await _store_blob(backend, hash1, body1.encode())
        await _store_blob(backend, hash2, body2.encode())

        await _insert_symbol(
            backend,
            file_id=1,
            symbol_id="diff_a.py::func1#function",
            name="func1",
            kind="function",
            line_start=1,
            line_end=7,
            byte_offset=0,
            byte_length=len(body1.encode()),
        )
        await _insert_symbol(
            backend,
            file_id=2,
            symbol_id="diff_b.py::func2#function",
            name="func2",
            kind="function",
            line_start=1,
            line_end=7,
            byte_offset=0,
            byte_length=len(body2.encode()),
        )
        await backend.commit()

        groups = await detect_duplicates(repo_id=1)
        assert len(groups) == 0

    async def test_empty_repo_returns_empty(self, analysis_ctx):
        groups = await detect_duplicates(repo_id=1)
        assert groups == []

    async def test_groups_sorted_by_line_count_desc(self, analysis_ctx):
        backend = analysis_ctx

        # Create two pairs of duplicates with different lengths
        short_body = "def s():\n    a = 1\n    b = 2\n    c = 3\n    d = 4\n    return a\n"
        long_body = "def l():\n" + "".join(f"    line{i} = {i}\n" for i in range(15)) + "    return 0\n"

        short_hash = hashlib.sha256(short_body.encode()).hexdigest()
        long_hash = hashlib.sha256(long_body.encode()).hexdigest()

        await _insert_file(backend, file_id=1, path="src/s1.py", content_hash=short_hash)
        await _insert_file(backend, file_id=2, path="src/s2.py", content_hash=short_hash)
        await _insert_file(backend, file_id=3, path="src/l1.py", content_hash=long_hash)
        await _insert_file(backend, file_id=4, path="src/l2.py", content_hash=long_hash)
        await _store_blob(backend, short_hash, short_body.encode())
        await _store_blob(backend, long_hash, long_body.encode())

        await _insert_symbol(
            backend, file_id=1, symbol_id="s1.py::s#function", name="s", kind="function",
            line_start=1, line_end=7, byte_offset=0, byte_length=len(short_body.encode()),
            content_hash=short_hash,
        )
        await _insert_symbol(
            backend, file_id=2, symbol_id="s2.py::s#function", name="s", kind="function",
            line_start=1, line_end=7, byte_offset=0, byte_length=len(short_body.encode()),
            content_hash=short_hash,
        )
        await _insert_symbol(
            backend, file_id=3, symbol_id="l1.py::l#function", name="l", kind="function",
            line_start=1, line_end=17, byte_offset=0, byte_length=len(long_body.encode()),
            content_hash=long_hash,
        )
        await _insert_symbol(
            backend, file_id=4, symbol_id="l2.py::l#function", name="l", kind="function",
            line_start=1, line_end=17, byte_offset=0, byte_length=len(long_body.encode()),
            content_hash=long_hash,
        )
        await backend.commit()

        groups = await detect_duplicates(repo_id=1)
        assert len(groups) == 2
        assert groups[0].line_count >= groups[1].line_count


# ===========================================================================
# 3. security_scanner.py
# ===========================================================================


class TestSecurityRules:
    """Verify the regex rules in SECURITY_RULES are well-formed."""

    def test_rules_count(self):
        assert len(SECURITY_RULES) == 10

    def test_all_rules_have_four_fields(self):
        for rule in SECURITY_RULES:
            assert len(rule) == 4


class TestScanSecurity:
    """Integration tests for scan_security."""

    async def _setup_file_with_blob(self, backend, file_id, path, content, language="python"):
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        await _insert_file(
            backend, file_id=file_id, path=path, content_hash=content_hash, language=language
        )
        await _store_blob(backend, content_hash, content.encode())
        await backend.commit()

    async def test_detects_eval(self, analysis_ctx):
        backend = analysis_ctx
        code = "result = eval(user_input)\n"
        await self._setup_file_with_blob(backend, 1, "src/danger.py", code)

        findings = await scan_security(repo_id=1)
        rules = [f.rule for f in findings]
        assert "eval_usage" in rules

    async def test_detects_exec(self, analysis_ctx):
        backend = analysis_ctx
        code = "exec(code_string)\n"
        await self._setup_file_with_blob(backend, 1, "src/danger.py", code)

        findings = await scan_security(repo_id=1)
        rules = [f.rule for f in findings]
        assert "exec_usage" in rules

    async def test_detects_shell_injection(self, analysis_ctx):
        backend = analysis_ctx
        code = 'subprocess.run(cmd, shell=True)\n'
        await self._setup_file_with_blob(backend, 1, "src/danger.py", code)

        findings = await scan_security(repo_id=1)
        rules = [f.rule for f in findings]
        assert "shell_injection" in rules

    async def test_detects_pickle_load(self, analysis_ctx):
        backend = analysis_ctx
        code = "data = pickle.load(f)\n"
        await self._setup_file_with_blob(backend, 1, "src/danger.py", code)

        findings = await scan_security(repo_id=1)
        rules = [f.rule for f in findings]
        assert "pickle_load" in rules

    async def test_detects_hardcoded_password(self, analysis_ctx):
        backend = analysis_ctx
        code = 'password = "supersecret123"\n'
        await self._setup_file_with_blob(backend, 1, "src/danger.py", code)

        findings = await scan_security(repo_id=1)
        rules = [f.rule for f in findings]
        assert "hardcoded_password" in rules

    async def test_detects_md5(self, analysis_ctx):
        backend = analysis_ctx
        code = "h = md5(data)\n"
        await self._setup_file_with_blob(backend, 1, "src/danger.py", code)

        findings = await scan_security(repo_id=1)
        rules = [f.rule for f in findings]
        assert "md5_usage" in rules

    async def test_detects_broad_except(self, analysis_ctx):
        backend = analysis_ctx
        code = "try:\n    risky()\nexcept:\n    pass\n"
        await self._setup_file_with_blob(backend, 1, "src/danger.py", code)

        findings = await scan_security(repo_id=1)
        rules = [f.rule for f in findings]
        assert "broad_except" in rules

    async def test_detects_assert(self, analysis_ctx):
        backend = analysis_ctx
        code = "assert user.is_admin\n"
        await self._setup_file_with_blob(backend, 1, "src/danger.py", code)

        findings = await scan_security(repo_id=1)
        rules = [f.rule for f in findings]
        assert "assert_in_production" in rules

    async def test_excludes_test_files(self, analysis_ctx):
        """Test files should be skipped by the scanner."""
        backend = analysis_ctx
        code = "result = eval(user_input)\n"
        await self._setup_file_with_blob(backend, 1, "tests/test_eval.py", code)

        findings = await scan_security(repo_id=1)
        assert len(findings) == 0

    async def test_excludes_non_code_files(self, analysis_ctx):
        """Files without a language should be skipped."""
        backend = analysis_ctx
        content_hash = hashlib.sha256(b"eval(x)").hexdigest()
        await analysis_ctx.execute(
            f"INSERT INTO files (id, repo_id, path, language, content_hash, byte_size) "
            f"VALUES (1, 1, 'README.md', '', '{content_hash}', 100)"
        )
        await _store_blob(backend, content_hash, b"eval(x)")

        findings = await scan_security(repo_id=1)
        assert len(findings) == 0

    async def test_finding_has_correct_fields(self, analysis_ctx):
        backend = analysis_ctx
        code = "result = eval(user_input)\n"
        await self._setup_file_with_blob(backend, 1, "src/vuln.py", code)

        findings = await scan_security(repo_id=1)
        f = next(f for f in findings if f.rule == "eval_usage")
        assert isinstance(f, SecurityFinding)
        assert f.file == "src/vuln.py"
        assert f.line == 1
        assert f.severity == "critical"
        assert len(f.snippet) > 0

    async def test_multiple_findings_same_file(self, analysis_ctx):
        backend = analysis_ctx
        code = "eval(x)\nexec(y)\n"
        await self._setup_file_with_blob(backend, 1, "src/multi.py", code)

        findings = await scan_security(repo_id=1)
        rules = {f.rule for f in findings}
        assert "eval_usage" in rules
        assert "exec_usage" in rules

    async def test_empty_repo_returns_empty(self, analysis_ctx):
        findings = await scan_security(repo_id=1)
        assert findings == []

    async def test_correct_line_numbers(self, analysis_ctx):
        backend = analysis_ctx
        code = "import os\nimport sys\nresult = eval(user_input)\n"
        await self._setup_file_with_blob(backend, 1, "src/lines.py", code)

        findings = await scan_security(repo_id=1)
        eval_finding = next(f for f in findings if f.rule == "eval_usage")
        assert eval_finding.line == 3


# ===========================================================================
# 4. test_coverage.py (the module, not our test file)
# ===========================================================================


class TestAnalyzeTestCoverage:
    """Integration tests for analyze_test_coverage."""

    async def test_covered_symbol(self, analysis_ctx):
        """A symbol is covered when a test file imports its module AND calls its name."""
        backend = analysis_ctx

        # Source file with a function
        await _insert_file(backend, file_id=1, path="src/utils.py", content_hash="src_hash")
        await _insert_symbol(
            backend,
            file_id=1,
            symbol_id="utils.py::compute#function",
            name="compute",
            kind="function",
            line_start=1,
            line_end=10,
        )

        # Test file that imports and calls compute
        test_code = "from src.utils import compute\n\ndef test_compute():\n    compute(1, 2)\n"
        test_hash = hashlib.sha256(test_code.encode()).hexdigest()
        await _insert_file(backend, file_id=2, path="tests/test_utils.py", content_hash=test_hash)
        await _store_blob(backend, test_hash, test_code.encode())

        # Insert import record for the test file
        await backend.execute(
            "INSERT INTO file_imports (file_id, specifier, names) "
            "VALUES (2, 'src.utils', '[\"compute\"]')"
        )
        await backend.commit()

        result = await analyze_test_coverage(repo_id=1)
        assert "utils.py::compute#function" in result["covered"]
        assert result["coverage_percent"] > 0

    async def test_uncovered_symbol(self, analysis_ctx):
        """A symbol with no test importing or calling it should be uncovered."""
        backend = analysis_ctx
        await _insert_file(backend, file_id=1, path="src/orphan.py", content_hash="orphan_hash")
        await _insert_symbol(
            backend,
            file_id=1,
            symbol_id="orphan.py::lonely#function",
            name="lonely",
            kind="function",
            line_start=1,
            line_end=10,
        )
        await backend.commit()

        result = await analyze_test_coverage(repo_id=1)
        assert "orphan.py::lonely#function" in result["uncovered"]
        assert result["coverage_percent"] == 0.0

    async def test_no_symbols_returns_empty(self, analysis_ctx):
        result = await analyze_test_coverage(repo_id=1)
        assert result["covered"] == []
        assert result["uncovered"] == []
        assert result["coverage_percent"] == 0.0

    async def test_no_test_files_all_uncovered(self, analysis_ctx):
        backend = analysis_ctx
        await _insert_file(backend, file_id=1, path="src/module.py", content_hash="mod_hash")
        await _insert_symbol(
            backend,
            file_id=1,
            symbol_id="module.py::func#function",
            name="func",
            kind="function",
            line_start=1,
            line_end=5,
        )
        await backend.commit()

        result = await analyze_test_coverage(repo_id=1)
        assert len(result["uncovered"]) == 1
        assert result["coverage_percent"] == 0.0

    async def test_called_but_not_imported_is_uncovered(self, analysis_ctx):
        """If name is called but module is not imported, still uncovered."""
        backend = analysis_ctx
        await _insert_file(backend, file_id=1, path="src/utils.py", content_hash="src_h")
        await _insert_symbol(
            backend,
            file_id=1,
            symbol_id="utils.py::helper#function",
            name="helper",
            kind="function",
            line_start=1,
            line_end=10,
        )

        # Test file calls helper but imports something unrelated
        test_code = "import something_else\n\ndef test_it():\n    helper()\n"
        test_hash = hashlib.sha256(test_code.encode()).hexdigest()
        await _insert_file(backend, file_id=2, path="tests/test_utils.py", content_hash=test_hash)
        await _store_blob(backend, test_hash, test_code.encode())

        await backend.execute(
            "INSERT INTO file_imports (file_id, specifier, names) "
            "VALUES (2, 'something_else', '[]')"
        )
        await backend.commit()

        result = await analyze_test_coverage(repo_id=1)
        assert "utils.py::helper#function" in result["uncovered"]

    async def test_coverage_percent_calculation(self, analysis_ctx):
        backend = analysis_ctx

        # Two source functions
        await _insert_file(backend, file_id=1, path="src/mod.py", content_hash="mh")
        await _insert_symbol(
            backend, file_id=1, symbol_id="mod.py::alpha#function", name="alpha", kind="function",
            line_start=1, line_end=5,
        )
        await _insert_symbol(
            backend, file_id=1, symbol_id="mod.py::beta#function", name="beta", kind="function",
            line_start=6, line_end=10,
        )

        # Test file imports mod and calls alpha (but not beta)
        test_code = "from src.mod import alpha\n\ndef test_alpha():\n    alpha()\n"
        test_hash = hashlib.sha256(test_code.encode()).hexdigest()
        await _insert_file(backend, file_id=2, path="tests/test_mod.py", content_hash=test_hash)
        await _store_blob(backend, test_hash, test_code.encode())

        await backend.execute(
            "INSERT INTO file_imports (file_id, specifier, names) "
            "VALUES (2, 'src.mod', '[\"alpha\"]')"
        )
        await backend.commit()

        result = await analyze_test_coverage(repo_id=1)
        assert result["coverage_percent"] == 50.0


# ===========================================================================
# 5. quality_metrics.py — compute, get, get_low_quality_symbols
# ===========================================================================


class TestComputeQualityMetrics:
    """Integration tests for compute_quality_metrics."""

    async def test_scores_symbols(self, analysis_ctx):
        backend = analysis_ctx
        body = "def foo(x: int) -> int:\n    if x > 0:\n        return x\n    return 0\n"
        content_hash = hashlib.sha256(body.encode()).hexdigest()

        await _insert_file(backend, file_id=1, path="src/foo.py", content_hash=content_hash)
        await _store_blob(backend, content_hash, body.encode())
        await _insert_symbol(
            backend,
            file_id=1,
            symbol_id="foo.py::foo#function",
            name="foo",
            kind="function",
            signature="def foo(x: int) -> int",
            docstring="Compute a value based on x being positive.",
            byte_offset=0,
            byte_length=len(body.encode()),
        )
        await backend.commit()

        scored = await compute_quality_metrics(repo_id=1)
        assert scored == 1

    async def test_get_quality_returns_scored(self, analysis_ctx):
        backend = analysis_ctx
        body = "def bar():\n    return 1\n"
        content_hash = hashlib.sha256(body.encode()).hexdigest()

        await _insert_file(backend, file_id=1, path="src/bar.py", content_hash=content_hash)
        await _store_blob(backend, content_hash, body.encode())
        await _insert_symbol(
            backend,
            file_id=1,
            symbol_id="bar.py::bar#function",
            name="bar",
            kind="function",
            signature="def bar()",
            byte_offset=0,
            byte_length=len(body.encode()),
        )
        await backend.commit()

        await compute_quality_metrics(repo_id=1)
        q = await get_quality("bar.py::bar#function")
        assert q is not None
        assert q["symbol_id"] == "bar.py::bar#function"
        assert isinstance(q["has_tests"], (bool, int))
        assert isinstance(q["complexity"], int)

    async def test_get_quality_not_scored(self, analysis_ctx):
        q = await get_quality("nonexistent::sym#function")
        assert q is None

    async def test_has_tests_detected(self, analysis_ctx):
        """A symbol whose name appears in a test file blob should get has_tests=True."""
        backend = analysis_ctx
        body = "def compute():\n    return 42\n"
        content_hash = hashlib.sha256(body.encode()).hexdigest()
        await _insert_file(backend, file_id=1, path="src/compute.py", content_hash=content_hash)
        await _store_blob(backend, content_hash, body.encode())
        await _insert_symbol(
            backend,
            file_id=1,
            symbol_id="compute.py::compute#function",
            name="compute",
            kind="function",
            signature="def compute()",
            byte_offset=0,
            byte_length=len(body.encode()),
        )

        # Test file that mentions "compute"
        test_body = "from compute import compute\ndef test_compute():\n    assert compute() == 42\n"
        test_hash = hashlib.sha256(test_body.encode()).hexdigest()
        await _insert_file(backend, file_id=2, path="tests/test_compute.py", content_hash=test_hash)
        await _store_blob(backend, test_hash, test_body.encode())
        await backend.commit()

        await compute_quality_metrics(repo_id=1)
        q = await get_quality("compute.py::compute#function")
        assert q is not None
        assert q["has_tests"] is True or q["has_tests"] == 1

    async def test_has_docs_detection(self, analysis_ctx):
        backend = analysis_ctx
        body = "def documented():\n    return 1\n"
        content_hash = hashlib.sha256(body.encode()).hexdigest()
        await _insert_file(backend, file_id=1, path="src/doc.py", content_hash=content_hash)
        await _store_blob(backend, content_hash, body.encode())
        await _insert_symbol(
            backend,
            file_id=1,
            symbol_id="doc.py::documented#function",
            name="documented",
            kind="function",
            signature="def documented()",
            docstring="This is a sufficiently long docstring for the test.",
            byte_offset=0,
            byte_length=len(body.encode()),
        )
        await backend.commit()

        await compute_quality_metrics(repo_id=1)
        q = await get_quality("doc.py::documented#function")
        assert q["has_docs"] is True or q["has_docs"] == 1

    async def test_has_types_detection(self, analysis_ctx):
        backend = analysis_ctx
        body = "def typed(x: int) -> str:\n    return str(x)\n"
        content_hash = hashlib.sha256(body.encode()).hexdigest()
        await _insert_file(backend, file_id=1, path="src/typed.py", content_hash=content_hash)
        await _store_blob(backend, content_hash, body.encode())
        await _insert_symbol(
            backend,
            file_id=1,
            symbol_id="typed.py::typed#function",
            name="typed",
            kind="function",
            signature="def typed(x: int) -> str",
            byte_offset=0,
            byte_length=len(body.encode()),
        )
        await backend.commit()

        await compute_quality_metrics(repo_id=1)
        q = await get_quality("typed.py::typed#function")
        assert q["has_types"] is True or q["has_types"] == 1

    async def test_complexity_computed(self, analysis_ctx):
        backend = analysis_ctx
        body = "def complex():\n    if a:\n        if b:\n            for i in c:\n                while d:\n                    pass\n"
        content_hash = hashlib.sha256(body.encode()).hexdigest()
        await _insert_file(backend, file_id=1, path="src/cx.py", content_hash=content_hash)
        await _store_blob(backend, content_hash, body.encode())
        await _insert_symbol(
            backend,
            file_id=1,
            symbol_id="cx.py::complex#function",
            name="complex",
            kind="function",
            signature="def complex()",
            byte_offset=0,
            byte_length=len(body.encode()),
        )
        await backend.commit()

        await compute_quality_metrics(repo_id=1)
        q = await get_quality("cx.py::complex#function")
        assert q["complexity"] >= 5  # 1 + if + if + for + while

    async def test_empty_repo(self, analysis_ctx):
        scored = await compute_quality_metrics(repo_id=1)
        assert scored == 0


class TestGetLowQualitySymbols:
    """Integration tests for get_low_quality_symbols."""

    async def test_returns_high_complexity(self, analysis_ctx):
        backend = analysis_ctx
        body = "def hard():\n    if a:\n        for b in c:\n            while d:\n                if e and f:\n                    pass\n"
        content_hash = hashlib.sha256(body.encode()).hexdigest()
        await _insert_file(backend, file_id=1, path="src/hard.py", content_hash=content_hash)
        await _store_blob(backend, content_hash, body.encode())
        await _insert_symbol(
            backend,
            file_id=1,
            symbol_id="hard.py::hard#function",
            name="hard",
            kind="function",
            language="python",
            signature="def hard()",
            byte_offset=0,
            byte_length=len(body.encode()),
        )
        await backend.commit()

        await compute_quality_metrics(repo_id=1)
        results = await get_low_quality_symbols("myrepo", min_complexity=3)
        assert len(results) >= 1
        assert results[0]["name"] == "hard"

    async def test_untested_only_filter(self, analysis_ctx):
        backend = analysis_ctx
        body = "def lonely():\n    if a:\n        for b in c:\n            pass\n"
        content_hash = hashlib.sha256(body.encode()).hexdigest()
        await _insert_file(backend, file_id=1, path="src/lonely.py", content_hash=content_hash)
        await _store_blob(backend, content_hash, body.encode())
        await _insert_symbol(
            backend,
            file_id=1,
            symbol_id="lonely.py::lonely#function",
            name="lonely",
            kind="function",
            language="python",
            signature="def lonely()",
            byte_offset=0,
            byte_length=len(body.encode()),
        )
        await backend.commit()

        await compute_quality_metrics(repo_id=1)
        results = await get_low_quality_symbols("myrepo", min_complexity=0, untested_only=True)
        names = [r["name"] for r in results]
        assert "lonely" in names

    async def test_undocumented_only_filter(self, analysis_ctx):
        backend = analysis_ctx
        body = "def nodoc():\n    return 1\n"
        content_hash = hashlib.sha256(body.encode()).hexdigest()
        await _insert_file(backend, file_id=1, path="src/nodoc.py", content_hash=content_hash)
        await _store_blob(backend, content_hash, body.encode())
        await _insert_symbol(
            backend,
            file_id=1,
            symbol_id="nodoc.py::nodoc#function",
            name="nodoc",
            kind="function",
            language="python",
            signature="def nodoc()",
            byte_offset=0,
            byte_length=len(body.encode()),
        )
        await backend.commit()

        await compute_quality_metrics(repo_id=1)
        results = await get_low_quality_symbols("myrepo", min_complexity=0, undocumented_only=True)
        names = [r["name"] for r in results]
        assert "nodoc" in names

    async def test_wrong_repo_returns_empty(self, analysis_ctx):
        results = await get_low_quality_symbols("nonexistent")
        assert results == []

    async def test_result_has_expected_keys(self, analysis_ctx):
        backend = analysis_ctx
        body = "def keyed():\n    if x:\n        for y in z:\n            while w:\n                if a and b:\n                    pass\n"
        content_hash = hashlib.sha256(body.encode()).hexdigest()
        await _insert_file(backend, file_id=1, path="src/keyed.py", content_hash=content_hash)
        await _store_blob(backend, content_hash, body.encode())
        await _insert_symbol(
            backend,
            file_id=1,
            symbol_id="keyed.py::keyed#function",
            name="keyed",
            kind="function",
            language="python",
            signature="def keyed()",
            byte_offset=0,
            byte_length=len(body.encode()),
        )
        await backend.commit()

        await compute_quality_metrics(repo_id=1)
        results = await get_low_quality_symbols("myrepo", min_complexity=3)
        assert len(results) >= 1
        r = results[0]
        expected_keys = {
            "symbol_id", "has_tests", "has_docs", "has_types", "complexity",
            "change_frequency", "last_changed", "name", "qualified_name",
            "kind", "language", "signature", "file_path",
        }
        assert expected_keys.issubset(r.keys())
