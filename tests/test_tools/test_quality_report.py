"""Tests for sylvan.tools.analysis.get_quality_report."""

from __future__ import annotations

import os

import pytest

from sylvan.config import reset_config
from sylvan.context import SylvanContext, reset_context, set_context
from sylvan.database.backends.sqlite import SQLiteBackend
from sylvan.database.migrations.runner import run_migrations
from sylvan.database.orm.runtime.query_cache import QueryCache
from sylvan.session.tracker import SessionTracker, reset_session


@pytest.fixture
async def indexed_project(tmp_path):
    """Index a sample project so quality report has data to analyze."""
    os.environ["SYLVAN_HOME"] = str(tmp_path)
    reset_config()
    reset_session()

    db_path = tmp_path / "test.db"
    backend = SQLiteBackend(db_path)
    await backend.connect()
    await run_migrations(backend)

    ctx = SylvanContext(
        backend=backend,
        session=SessionTracker(),
        cache=QueryCache(),
    )
    token = set_context(ctx)

    proj = tmp_path / "project"
    proj.mkdir()
    (proj / "main.py").write_text(
        "def greet(name: str) -> str:\n"
        '    """Greet someone."""\n'
        '    return f"Hello {name}"\n'
        "\n"
        "def farewell(name):\n"
        '    return f"Goodbye {name}"\n'
        "\n"
        "class Calculator:\n"
        '    """A calculator class."""\n'
        "    def add(self, a: int, b: int) -> int:\n"
        '        """Add two numbers."""\n'
        "        return a + b\n",
        encoding="utf-8",
    )
    (proj / "test_main.py").write_text(
        "from main import greet, Calculator\n"
        "\n"
        "def test_greet():\n"
        '    assert greet("world") == "Hello world"\n'
        "\n"
        "def test_calculator():\n"
        "    calc = Calculator()\n"
        "    assert calc.add(1, 2) == 3\n",
        encoding="utf-8",
    )

    from sylvan.indexing.pipeline.orchestrator import index_folder

    result = await index_folder(str(proj), name="quality-repo")
    await backend.commit()
    assert result.symbols_extracted >= 3

    yield backend

    reset_context(token)
    await backend.disconnect()
    os.environ.pop("SYLVAN_HOME", None)


class TestGetQualityReport:
    async def test_repo_not_found(self, indexed_project):
        from sylvan.error_codes import RepoNotFoundError
        from sylvan.tools.analysis.get_quality_report import GetQualityReport

        with pytest.raises(RepoNotFoundError):
            await GetQualityReport().execute({"repo": "nonexistent"})

    async def test_report_structure(self, indexed_project):
        from sylvan.tools.analysis.get_quality_report import GetQualityReport

        resp = await GetQualityReport().execute({"repo": "quality-repo"})

        assert "_meta" in resp
        assert resp["repository"] == "quality-repo"

        # Quality gate section
        assert "quality_gate" in resp
        gate = resp["quality_gate"]
        assert "passed" in gate
        assert isinstance(gate["passed"], bool)
        assert "failures" in gate

        # Coverage section
        assert "coverage" in resp
        cov = resp["coverage"]
        assert "test_coverage_percent" in cov
        assert isinstance(cov["test_coverage_percent"], (int, float))
        assert "uncovered_count" in cov
        assert "covered_count" in cov

        # Documentation section
        assert "documentation" in resp
        doc = resp["documentation"]
        assert "doc_coverage_percent" in doc
        assert "type_coverage_percent" in doc
        assert "total_symbols" in doc

        # Code smells section
        assert "code_smells" in resp
        smells = resp["code_smells"]
        assert "total" in smells
        assert "by_severity" in smells
        assert "items" in smells

        # Security section
        assert "security" in resp
        sec = resp["security"]
        assert "total" in sec
        assert "by_severity" in sec
        assert "findings" in sec

        # Duplication section
        assert "duplication" in resp
        dup = resp["duplication"]
        assert "duplicate_groups" in dup
        assert "groups" in dup

    async def test_meta_fields(self, indexed_project):
        from sylvan.tools.analysis.get_quality_report import GetQualityReport

        resp = await GetQualityReport().execute({"repo": "quality-repo"})
        meta = resp["_meta"]

        assert "gate_passed" in meta
        assert "test_coverage" in meta
        assert "doc_coverage" in meta
        assert "smells_count" in meta
        assert "security_count" in meta
        assert "duplicate_groups" in meta

    async def test_coverage_values_are_percentages(self, indexed_project):
        from sylvan.tools.analysis.get_quality_report import GetQualityReport

        resp = await GetQualityReport().execute({"repo": "quality-repo"})

        test_cov = resp["coverage"]["test_coverage_percent"]
        doc_cov = resp["documentation"]["doc_coverage_percent"]
        type_cov = resp["documentation"]["type_coverage_percent"]

        assert 0 <= test_cov <= 100
        assert 0 <= doc_cov <= 100
        assert 0 <= type_cov <= 100
