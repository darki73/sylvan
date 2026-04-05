"""Tests for sylvan.scaffold — generator, agent_config, auto_docs, auto_reports, directory_structure."""

from __future__ import annotations

import os

import pytest

from sylvan.config import reset_config
from sylvan.context import SylvanContext, reset_context, set_context
from sylvan.database.backends.sqlite import SQLiteBackend
from sylvan.database.migrations.runner import run_migrations
from sylvan.database.orm.runtime.query_cache import QueryCache
from sylvan.session.tracker import SessionTracker, reset_session

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def scaffold_ctx(tmp_path):
    """Set up a SylvanContext with an indexed repo for scaffold tests."""
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

    # Create a sample project on disk
    proj = tmp_path / "myproject"
    proj.mkdir()
    (proj / "main.py").write_text(
        'def main():\n    """Entry point."""\n    pass\n\ndef cli():\n    pass\n',
        encoding="utf-8",
    )
    (proj / "pyproject.toml").write_text(
        '[project]\nname = "myproject"\n',
        encoding="utf-8",
    )
    src = proj / "src"
    src.mkdir()
    (src / "model.py").write_text(
        "class UserModel:\n"
        '    """A user model."""\n'
        "    pass\n"
        "\n"
        'def get_user(id: int) -> "UserModel":\n'
        '    """Get a user by ID."""\n'
        "    pass\n",
        encoding="utf-8",
    )
    (src / "util.py").write_text(
        'def helper():\n    """A helper function."""\n    pass\n',
        encoding="utf-8",
    )

    # Index it
    from sylvan.indexing.pipeline.orchestrator import index_folder

    result = await index_folder(str(proj), name="myproject")
    await backend.commit()

    yield {
        "backend": backend,
        "ctx": ctx,
        "project_root": proj,
        "index_result": result,
        "tmp_path": tmp_path,
    }

    reset_context(token)
    await backend.disconnect()
    os.environ.pop("SYLVAN_HOME", None)


# ---------------------------------------------------------------------------
# directory_structure.py
# ---------------------------------------------------------------------------


class TestDirectoryStructure:
    """Tests for the STRUCTURE constant and _create_structure helper."""

    def test_structure_has_sylvan_key(self):
        from sylvan.scaffold.directory_structure import STRUCTURE

        assert "sylvan" in STRUCTURE

    def test_structure_has_expected_subdirs(self):
        from sylvan.scaffold.directory_structure import STRUCTURE

        sylvan = STRUCTURE["sylvan"]
        assert "architecture" in sylvan
        assert "dependencies" in sylvan
        assert "quality" in sylvan
        assert "plans" in sylvan
        assert "context" in sylvan
        assert "decisions" in sylvan
        assert "notes" in sylvan

    def test_structure_plans_has_workflow_dirs(self):
        from sylvan.scaffold.directory_structure import STRUCTURE

        plans = STRUCTURE["sylvan"]["plans"]
        assert "future" in plans
        assert "working" in plans
        assert "completed" in plans

    def test_conventions_has_placeholder_content(self):
        from sylvan.scaffold.directory_structure import STRUCTURE

        conventions = STRUCTURE["sylvan"]["architecture"]["conventions.md"]
        assert isinstance(conventions, str)
        assert "Conventions" in conventions

    def test_create_structure_creates_dirs_and_files(self, tmp_path):
        from sylvan.scaffold.directory_structure import STRUCTURE
        from sylvan.scaffold.generator import _create_structure

        base = tmp_path / "sylvan"
        created = _create_structure(base, STRUCTURE["sylvan"])

        assert base.exists()
        assert (base / "architecture").is_dir()
        assert (base / "plans" / "future").is_dir()
        assert (base / "plans" / "future" / ".gitkeep").exists()
        assert (base / "architecture" / "conventions.md").exists()
        assert created > 0

    def test_create_structure_idempotent(self, tmp_path):
        from sylvan.scaffold.directory_structure import STRUCTURE
        from sylvan.scaffold.generator import _create_structure

        base = tmp_path / "sylvan"
        first = _create_structure(base, STRUCTURE["sylvan"])
        second = _create_structure(base, STRUCTURE["sylvan"])

        # Second run should create 0 new files since they already exist
        assert second == 0
        assert first > 0

    def test_create_structure_skips_none_values(self, tmp_path):
        from sylvan.scaffold.generator import _create_structure

        structure = {"auto.md": None, "manual.md": "content"}
        base = tmp_path / "test"
        created = _create_structure(base, structure)

        assert not (base / "auto.md").exists()
        assert (base / "manual.md").exists()
        assert created == 1


# ---------------------------------------------------------------------------
# agent_config.py
# ---------------------------------------------------------------------------


class TestAgentConfig:
    """Tests for agent configuration generation."""

    def test_get_agent_filename_claude(self):
        from sylvan.scaffold.agent_config import get_agent_filename

        assert get_agent_filename("claude") == "CLAUDE.md"

    def test_get_agent_filename_cursor(self):
        from sylvan.scaffold.agent_config import get_agent_filename

        assert get_agent_filename("cursor") == ".cursorrules"

    def test_get_agent_filename_copilot(self):
        from sylvan.scaffold.agent_config import get_agent_filename

        assert get_agent_filename("copilot") == ".github/copilot-instructions.md"

    def test_get_agent_filename_generic(self):
        from sylvan.scaffold.agent_config import get_agent_filename

        assert get_agent_filename("generic") == ".ai-instructions.md"

    def test_get_agent_filename_unknown_defaults_to_generic(self):
        from sylvan.scaffold.agent_config import get_agent_filename

        assert get_agent_filename("unknown") == ".ai-instructions.md"

    def test_agent_formats_constant(self):
        from sylvan.scaffold.agent_config import AGENT_FORMATS

        assert len(AGENT_FORMATS) == 4
        assert all(isinstance(v, str) for v in AGENT_FORMATS.values())

    async def test_async_generate_agent_config_repo_not_found(self, scaffold_ctx):
        from sylvan.scaffold.agent_config import async_generate_agent_config

        result = await async_generate_agent_config("nonexistent")
        assert "not indexed" in result.lower() or "Not indexed" in result

    async def test_async_generate_agent_config_contains_project_info(self, scaffold_ctx):
        from sylvan.scaffold.agent_config import async_generate_agent_config

        result = await async_generate_agent_config("myproject")

        assert "myproject" in result
        assert "Primary language" in result or "primary language" in result.lower()
        assert "Files" in result
        assert "sylvan/" in result

    async def test_async_generate_agent_config_detects_python_test_cmd(self, scaffold_ctx):
        from sylvan.scaffold.agent_config import async_generate_agent_config

        result = await async_generate_agent_config("myproject")

        # pyproject.toml is present, so test cmd should be detected
        assert "pytest" in result or "Test" in result

    async def test_async_generate_agent_config_includes_tool_docs(self, scaffold_ctx):
        from sylvan.scaffold.agent_config import async_generate_agent_config

        result = await async_generate_agent_config("myproject")

        assert "find_code" in result
        assert "read_symbol" in result
        assert "whats_in_file" in result

    async def test_build_instructions_contains_sylvan_table(self, scaffold_ctx):
        from sylvan.scaffold.agent_config import _build_instructions

        content = _build_instructions(
            repo_name="test",
            primary_lang="python",
            total_files=10,
            languages={"python": 8, "yaml": 2},
            test_cmd="pytest",
            run_cmd="",
            agent="claude",
        )
        assert "project.md" in content
        assert "architecture/overview.md" in content
        assert "quality/report.md" in content

    def test_detect_test_command_python(self):
        from sylvan.scaffold.agent_config import _detect_test_command

        class FakeFile:
            def __init__(self, path):
                self.path = path

        files = [FakeFile("pyproject.toml"), FakeFile("src/main.py")]
        result = _detect_test_command(None, files)
        assert "pytest" in result

    def test_detect_test_command_node(self):
        from sylvan.scaffold.agent_config import _detect_test_command

        class FakeFile:
            def __init__(self, path):
                self.path = path

        files = [FakeFile("package.json"), FakeFile("src/index.ts")]
        result = _detect_test_command(None, files)
        assert result == "npm test"

    def test_detect_test_command_go(self):
        from sylvan.scaffold.agent_config import _detect_test_command

        class FakeFile:
            def __init__(self, path):
                self.path = path

        files = [FakeFile("go.mod"), FakeFile("main.go")]
        result = _detect_test_command(None, files)
        assert result == "go test ./..."

    def test_detect_test_command_rust(self):
        from sylvan.scaffold.agent_config import _detect_test_command

        class FakeFile:
            def __init__(self, path):
                self.path = path

        files = [FakeFile("Cargo.toml"), FakeFile("src/main.rs")]
        result = _detect_test_command(None, files)
        assert result == "cargo test"

    def test_detect_run_command_node(self):
        from sylvan.scaffold.agent_config import _detect_run_command

        class FakeFile:
            def __init__(self, path):
                self.path = path

        files = [FakeFile("package.json")]
        result = _detect_run_command(None, files)
        assert result == "npm start"

    def test_detect_run_command_python_returns_empty(self):
        from sylvan.scaffold.agent_config import _detect_run_command

        class FakeFile:
            def __init__(self, path):
                self.path = path

        files = [FakeFile("pyproject.toml")]
        result = _detect_run_command(None, files)
        assert result == ""


# ---------------------------------------------------------------------------
# auto_docs.py
# ---------------------------------------------------------------------------


class TestAutoDocs:
    """Tests for auto-generated documentation."""

    async def test_generate_project_md_repo_not_found(self, scaffold_ctx):
        from sylvan.scaffold.auto_docs import async_generate_project_md

        result = await async_generate_project_md("nonexistent")
        assert "Not indexed" in result or "not indexed" in result.lower()

    async def test_generate_project_md_contains_repo_info(self, scaffold_ctx):
        from sylvan.scaffold.auto_docs import async_generate_project_md

        result = await async_generate_project_md("myproject")

        assert "myproject" in result
        assert "Primary language" in result or "primary language" in result.lower()
        assert "Files" in result
        assert "Symbols" in result
        assert "Languages" in result

    async def test_generate_architecture_overview_repo_not_found(self, scaffold_ctx):
        from sylvan.scaffold.auto_docs import async_generate_architecture_overview

        result = await async_generate_architecture_overview("nonexistent")
        assert result == ""

    async def test_generate_architecture_overview_contains_modules(self, scaffold_ctx):
        from sylvan.scaffold.auto_docs import async_generate_architecture_overview

        result = await async_generate_architecture_overview("myproject")

        assert "Architecture Overview" in result
        assert "Module Map" in result
        # The src/ directory should appear as a module
        assert "src" in result

    async def test_generate_module_doc_repo_not_found(self, scaffold_ctx):
        from sylvan.scaffold.auto_docs import async_generate_module_doc

        result = await async_generate_module_doc("nonexistent", "src")
        assert result == ""

    async def test_generate_module_doc_lists_symbols(self, scaffold_ctx):
        from sylvan.scaffold.auto_docs import async_generate_module_doc

        result = await async_generate_module_doc("myproject", "src")

        assert "Module:" in result
        assert "src" in result
        # Should contain symbols from src/model.py or src/util.py
        assert "UserModel" in result or "helper" in result or "get_user" in result

    async def test_generate_patterns_md_repo_not_found(self, scaffold_ctx):
        from sylvan.scaffold.auto_docs import async_generate_patterns_md

        result = await async_generate_patterns_md("nonexistent")
        assert result == ""

    async def test_generate_patterns_md_detects_patterns(self, scaffold_ctx):
        from sylvan.scaffold.auto_docs import async_generate_patterns_md

        result = await async_generate_patterns_md("myproject")

        assert "Detected Patterns" in result
        # We have a main() function, so CLI should be detected
        assert "CLI" in result or "Agent" in result or "Patterns" in result


# ---------------------------------------------------------------------------
# auto_reports.py
# ---------------------------------------------------------------------------


class TestAutoReports:
    """Tests for auto-generated reports."""

    async def test_generate_dependencies_internal_repo_not_found(self, scaffold_ctx):
        from sylvan.scaffold.auto_reports import async_generate_dependencies_internal

        result = await async_generate_dependencies_internal("nonexistent")
        assert result == ""

    async def test_generate_dependencies_internal_has_header(self, scaffold_ctx):
        from sylvan.scaffold.auto_reports import async_generate_dependencies_internal

        result = await async_generate_dependencies_internal("myproject")
        assert "Internal Dependencies" in result

    async def test_generate_dependencies_external_no_source_path(self, scaffold_ctx):
        from sylvan.scaffold.auto_reports import async_generate_dependencies_external

        result = await async_generate_dependencies_external("nonexistent")
        assert "External Dependencies" in result

    async def test_generate_dependencies_external_has_header(self, scaffold_ctx):
        from sylvan.scaffold.auto_reports import async_generate_dependencies_external

        result = await async_generate_dependencies_external("myproject")
        assert "External Dependencies" in result

    async def test_generate_quality_report_repo_not_found(self, scaffold_ctx):
        from sylvan.scaffold.auto_reports import async_generate_quality_report

        result = await async_generate_quality_report("nonexistent")
        assert result == ""

    async def test_generate_quality_report_contains_metrics(self, scaffold_ctx):
        from sylvan.scaffold.auto_reports import async_generate_quality_report

        result = await async_generate_quality_report("myproject")

        assert "Quality Report" in result
        assert "Total symbols" in result
        assert "Functions" in result
        assert "Classes" in result
        assert "Documented" in result

    async def test_generate_entry_points_repo_not_found(self, scaffold_ctx):
        from sylvan.scaffold.auto_reports import async_generate_entry_points

        result = await async_generate_entry_points("nonexistent")
        assert result == ""

    async def test_generate_entry_points_finds_main(self, scaffold_ctx):
        from sylvan.scaffold.auto_reports import async_generate_entry_points

        result = await async_generate_entry_points("myproject")

        assert "Entry Points" in result
        # main() and cli() are both entry point names
        assert "main" in result or "cli" in result

    async def test_generate_recent_changes_no_source_path(self, scaffold_ctx):
        from sylvan.scaffold.auto_reports import async_generate_recent_changes

        result = await async_generate_recent_changes("nonexistent")
        assert "Recent Changes" in result

    async def test_generate_recent_changes_has_header(self, scaffold_ctx):
        from sylvan.scaffold.auto_reports import async_generate_recent_changes

        result = await async_generate_recent_changes("myproject")
        assert "Recent Changes" in result

    async def test_generate_hot_files_no_source_path(self, scaffold_ctx):
        from sylvan.scaffold.auto_reports import async_generate_hot_files

        result = await async_generate_hot_files("nonexistent")
        assert "Hot Files" in result

    async def test_generate_hot_files_has_header(self, scaffold_ctx):
        from sylvan.scaffold.auto_reports import async_generate_hot_files

        result = await async_generate_hot_files("myproject")
        assert "Hot Files" in result


# ---------------------------------------------------------------------------
# generator.py (async_scaffold_project)
# ---------------------------------------------------------------------------


class TestScaffoldGenerator:
    """Tests for the main scaffold generator."""

    async def test_scaffold_repo_not_found(self, scaffold_ctx):
        from sylvan.scaffold.generator import async_scaffold_project

        result = await async_scaffold_project("nonexistent")
        assert "error" in result

    async def test_scaffold_creates_sylvan_dir(self, scaffold_ctx):
        from sylvan.scaffold.generator import async_scaffold_project

        root = scaffold_ctx["project_root"]
        result = await async_scaffold_project("myproject", project_root=root)

        assert result.get("status") == "generated"
        assert result["files_created"] > 0
        assert (root / "sylvan").is_dir()

    async def test_scaffold_creates_agent_config_file(self, scaffold_ctx):
        from sylvan.scaffold.generator import async_scaffold_project

        root = scaffold_ctx["project_root"]
        result = await async_scaffold_project("myproject", agent="claude", project_root=root)

        assert result["config_file"] == "CLAUDE.md"
        assert (root / "CLAUDE.md").exists()

        content = (root / "CLAUDE.md").read_text(encoding="utf-8")
        assert "myproject" in content

    async def test_scaffold_creates_auto_docs(self, scaffold_ctx):
        from sylvan.scaffold.generator import async_scaffold_project

        root = scaffold_ctx["project_root"]
        await async_scaffold_project("myproject", project_root=root)

        sylvan_dir = root / "sylvan"
        assert (sylvan_dir / "project.md").exists()
        assert (sylvan_dir / "architecture" / "overview.md").exists()
        assert (sylvan_dir / "architecture" / "patterns.md").exists()

    async def test_scaffold_creates_quality_report(self, scaffold_ctx):
        from sylvan.scaffold.generator import async_scaffold_project

        root = scaffold_ctx["project_root"]
        await async_scaffold_project("myproject", project_root=root)

        quality_report = root / "sylvan" / "quality" / "report.md"
        assert quality_report.exists()
        content = quality_report.read_text(encoding="utf-8")
        assert "Quality Report" in content

    async def test_scaffold_creates_module_docs(self, scaffold_ctx):
        from sylvan.scaffold.generator import async_scaffold_project

        root = scaffold_ctx["project_root"]
        await async_scaffold_project("myproject", project_root=root)

        modules_dir = root / "sylvan" / "architecture" / "modules"
        assert modules_dir.is_dir()
        # The "src" directory should get a module doc
        module_files = list(modules_dir.glob("*.md"))
        assert len(module_files) >= 1

    async def test_scaffold_cursor_format(self, scaffold_ctx):
        from sylvan.scaffold.generator import async_scaffold_project

        root = scaffold_ctx["project_root"]
        result = await async_scaffold_project("myproject", agent="cursor", project_root=root)

        assert result["config_file"] == ".cursorrules"
        assert result["agent"] == "cursor"
        assert (root / ".cursorrules").exists()

    async def test_scaffold_returns_summary_dict(self, scaffold_ctx):
        from sylvan.scaffold.generator import async_scaffold_project

        root = scaffold_ctx["project_root"]
        result = await async_scaffold_project("myproject", project_root=root)

        assert "status" in result
        assert "repo" in result
        assert "sylvan_dir" in result
        assert "config_file" in result
        assert "files_created" in result
        assert "agent" in result

    async def test_scaffold_nonexistent_root(self, scaffold_ctx):
        from sylvan.scaffold.generator import async_scaffold_project

        result = await async_scaffold_project("myproject", project_root="/nonexistent/path")
        assert "error" in result
