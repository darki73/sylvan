"""Tests for the Sylvan CLI (cli.py)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from sylvan.cli import app

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()


def _fake_config(tmp_path: Path) -> MagicMock:
    """Build a minimal fake Config pointing at *tmp_path* for the DB."""
    cfg = MagicMock()
    cfg.db_path = tmp_path / "sylvan.db"
    cfg.database.resolved_path = cfg.db_path
    cfg.summary.provider = "heuristic"
    cfg.embedding.provider = "sentence-transformers"
    cfg.embedding.dimensions = 384
    return cfg


def _closing_run(return_value=None):
    """Return a side_effect for asyncio.run that closes the coroutine."""

    def _side_effect(coro):
        coro.close()
        return return_value

    return _side_effect


class TestStatus:
    def test_status_no_repos_mocked(self, tmp_path):
        _fake_config(tmp_path)
        with patch("sylvan.cli.asyncio.run", side_effect=_closing_run()):
            result = runner.invoke(app, ["status"])
            assert result.exit_code == 0

    def test_status_with_repos(self, tmp_path):
        _fake_config(tmp_path)
        with patch("sylvan.cli.asyncio.run", side_effect=_closing_run()):
            result = runner.invoke(app, ["status"])
            assert result.exit_code == 0


class TestDoctor:
    def test_doctor_runs(self):
        with patch("sylvan.cli.asyncio.run", side_effect=_closing_run()):
            result = runner.invoke(app, ["doctor"])
            assert result.exit_code == 0

    def test_doctor_help(self):
        result = runner.invoke(app, ["doctor", "--help"])
        assert result.exit_code == 0
        assert "Diagnose" in result.output or "health" in result.output


class TestServe:
    def test_serve_help(self):
        result = runner.invoke(app, ["serve", "--help"])
        assert result.exit_code == 0
        assert "transport" in result.output.lower()

    def test_serve_invokes_startup(self):
        with patch("sylvan.server.startup.main") as mock_main:
            result = runner.invoke(app, ["serve", "--transport", "stdio", "--port", "9999"])
            assert result.exit_code == 0
            mock_main.assert_called_once_with(transport="stdio", host="127.0.0.1", port=9999)

    def test_serve_sse_transport(self):
        with patch("sylvan.server.startup.main") as mock_main:
            result = runner.invoke(app, ["serve", "-t", "sse", "--host", "0.0.0.0"])  # noqa: S104
            assert result.exit_code == 0
            mock_main.assert_called_once_with(transport="sse", host="0.0.0.0", port=8420)  # noqa: S104


class TestIndex:
    def test_index_invokes_async(self, tmp_path):
        fake_result = {"repo": "test-repo", "files_indexed": 5, "symbols_extracted": 20}
        with patch("sylvan.cli.asyncio.run", side_effect=_closing_run(fake_result)):
            result = runner.invoke(app, ["index", str(tmp_path)])
            assert result.exit_code == 0
            assert "Indexing" in result.output
            assert "test-repo" in result.output

    def test_index_with_name(self, tmp_path):
        fake_result = {"repo": "custom-name", "files_indexed": 3}
        with patch("sylvan.cli.asyncio.run", side_effect=_closing_run(fake_result)):
            result = runner.invoke(app, ["index", str(tmp_path), "-n", "custom-name"])
            assert result.exit_code == 0
            assert "Indexing" in result.output

    def test_index_help(self):
        result = runner.invoke(app, ["index", "--help"])
        assert result.exit_code == 0
        assert "PATH" in result.output or "path" in result.output.lower()


class TestLibraryAdd:
    def test_library_add_indexed(self):
        mock_result = {
            "status": "indexed",
            "name": "django@4.2",
            "files_indexed": 100,
            "symbols_extracted": 500,
            "sections_extracted": 50,
        }
        with patch("sylvan.libraries.manager.add_library", return_value=mock_result):
            result = runner.invoke(app, ["library", "add", "pip/django@4.2"])
            assert result.exit_code == 0
            assert "Adding library: pip/django@4.2" in result.output
            assert "500 symbols" in result.output

    def test_library_add_already_indexed(self):
        mock_result = {"status": "already_indexed", "message": "django@4.2 is already indexed."}
        with patch("sylvan.libraries.manager.add_library", return_value=mock_result):
            result = runner.invoke(app, ["library", "add", "pip/django@4.2"])
            assert result.exit_code == 0
            assert "already indexed" in result.output

    def test_library_add_with_timeout(self):
        mock_result = {
            "status": "indexed",
            "name": "flask",
            "files_indexed": 10,
            "symbols_extracted": 30,
            "sections_extracted": 5,
        }
        with patch("sylvan.libraries.manager.add_library", return_value=mock_result) as mock_add:
            result = runner.invoke(app, ["library", "add", "pip/flask", "--timeout", "60"])
            assert result.exit_code == 0
            mock_add.assert_called_once_with("pip/flask", timeout=60)


class TestLibraryList:
    def test_library_list_empty(self):
        with patch("sylvan.libraries.manager.list_libraries", return_value=[]):
            result = runner.invoke(app, ["library", "list"])
            assert result.exit_code == 0
            assert "No libraries indexed" in result.output

    def test_library_list_with_entries(self):
        libs = [
            {"name": "django@4.2", "files": 100, "symbols": 500, "manager": "pip"},
            {"name": "flask@3.0", "files": 50, "symbols": 200, "manager": "pip"},
        ]
        with patch("sylvan.libraries.manager.list_libraries", return_value=libs):
            result = runner.invoke(app, ["library", "list"])
            assert result.exit_code == 0
            assert "django@4.2" in result.output
            assert "flask@3.0" in result.output


class TestLibraryRemove:
    def test_library_remove_success(self):
        mock_result = {"status": "removed", "name": "django@4.2"}
        with patch("sylvan.libraries.manager.remove_library", return_value=mock_result):
            result = runner.invoke(app, ["library", "remove", "django@4.2"])
            assert result.exit_code == 0
            assert "Removed: django@4.2" in result.output

    def test_library_remove_not_found(self):
        mock_result = {"status": "not_found", "message": "Library not found."}
        with patch("sylvan.libraries.manager.remove_library", return_value=mock_result):
            result = runner.invoke(app, ["library", "remove", "nonexistent"])
            assert result.exit_code == 0
            assert "Library not found" in result.output


class TestLibraryUpdate:
    def test_library_update_success(self):
        mock_result = {"status": "indexed", "name": "django@5.0", "symbols_extracted": 600}
        with patch("sylvan.libraries.manager.update_library", return_value=mock_result):
            result = runner.invoke(app, ["library", "update", "django@4.2"])
            assert result.exit_code == 0
            assert "django@5.0" in result.output
            assert "600 symbols" in result.output


class TestLibraryMap:
    def test_library_map(self):
        with patch("sylvan.libraries.resolution.package_registry.save_override") as mock_save:
            result = runner.invoke(
                app,
                [
                    "library",
                    "map",
                    "pip/tiktoken",
                    "https://github.com/openai/tiktoken",
                ],
            )
            assert result.exit_code == 0
            assert "Mapped pip/tiktoken" in result.output
            mock_save.assert_called_once_with("pip/tiktoken", "https://github.com/openai/tiktoken")


class TestLibraryUnmap:
    def test_library_unmap_success(self):
        with patch("sylvan.libraries.resolution.package_registry.remove_override", return_value=True):
            result = runner.invoke(app, ["library", "unmap", "pip/tiktoken"])
            assert result.exit_code == 0
            assert "Removed mapping" in result.output

    def test_library_unmap_not_found(self):
        with patch("sylvan.libraries.resolution.package_registry.remove_override", return_value=False):
            result = runner.invoke(app, ["library", "unmap", "pip/nonexistent"])
            assert result.exit_code == 0
            assert "No mapping found" in result.output


class TestLibraryMappings:
    def test_mappings_empty(self):
        with patch("sylvan.libraries.resolution.package_registry.list_overrides", return_value={}):
            result = runner.invoke(app, ["library", "mappings"])
            assert result.exit_code == 0
            assert "No mappings configured" in result.output

    def test_mappings_with_entries(self):
        overrides = {"pip/tiktoken": "https://github.com/openai/tiktoken"}
        with patch("sylvan.libraries.resolution.package_registry.list_overrides", return_value=overrides):
            result = runner.invoke(app, ["library", "mappings"])
            assert result.exit_code == 0
            assert "pip/tiktoken" in result.output


class TestScaffold:
    def test_scaffold_success(self, tmp_path):
        mock_result = {
            "files_created": 5,
            "sylvan_dir": str(tmp_path / "sylvan"),
            "config_file": str(tmp_path / "CLAUDE.md"),
            "agent": "claude",
        }
        with patch("sylvan.scaffold.scaffold_project", return_value=mock_result):
            result = runner.invoke(app, ["scaffold", "my-repo"])
            assert result.exit_code == 0
            assert "Generated 5 files" in result.output

    def test_scaffold_with_agent(self, tmp_path):
        mock_result = {
            "files_created": 3,
            "sylvan_dir": str(tmp_path / "sylvan"),
            "config_file": str(tmp_path / ".cursorrules"),
            "agent": "cursor",
        }
        with patch("sylvan.scaffold.scaffold_project", return_value=mock_result) as mock_scaffold:
            result = runner.invoke(app, ["scaffold", "my-repo", "--agent", "cursor"])
            assert result.exit_code == 0
            mock_scaffold.assert_called_once_with("my-repo", agent="cursor", project_root=None)

    def test_scaffold_with_root(self, tmp_path):
        mock_result = {
            "files_created": 2,
            "sylvan_dir": str(tmp_path / "sylvan"),
            "config_file": str(tmp_path / "CLAUDE.md"),
            "agent": "claude",
        }
        with patch("sylvan.scaffold.scaffold_project", return_value=mock_result) as mock_scaffold:
            result = runner.invoke(app, ["scaffold", "my-repo", "--root", str(tmp_path)])
            assert result.exit_code == 0
            mock_scaffold.assert_called_once_with("my-repo", agent="claude", project_root=tmp_path)

    def test_scaffold_error(self):
        mock_result = {"error": "Repository 'bogus' not found."}
        with patch("sylvan.scaffold.scaffold_project", return_value=mock_result):
            result = runner.invoke(app, ["scaffold", "bogus"])
            assert result.exit_code == 1
            assert "not found" in result.output

    def test_scaffold_help(self):
        result = runner.invoke(app, ["scaffold", "--help"])
        assert result.exit_code == 0
        assert "repo" in result.output.lower()


class TestMigrate:
    def test_migrate_runs(self):
        with patch("sylvan.cli.asyncio.run", side_effect=_closing_run()):
            result = runner.invoke(app, ["migrate"])
            assert result.exit_code == 0

    def test_migrate_dry_run(self):
        with patch("sylvan.cli.asyncio.run", side_effect=_closing_run()):
            result = runner.invoke(app, ["migrate", "--dry-run"])
            assert result.exit_code == 0

    def test_migrate_create(self, tmp_path):
        fake_path = tmp_path / "migrations" / "003_add_column.py"
        with patch("sylvan.database.migrations.runner.create_migration", return_value=fake_path):
            result = runner.invoke(app, ["migrate", "create", "add column"])
            assert result.exit_code == 0
            assert "Created:" in result.output

    def test_migrate_help(self):
        result = runner.invoke(app, ["migrate", "--help"])
        assert result.exit_code == 0
        assert "create" in result.output

    def test_migrate_rollback_runs(self):
        with patch("sylvan.cli.asyncio.run", side_effect=_closing_run()):
            result = runner.invoke(app, ["migrate", "rollback"])
            assert result.exit_code == 0


class TestExport:
    def test_export_runs(self):
        with patch("sylvan.cli.asyncio.run", side_effect=_closing_run()):
            result = runner.invoke(app, ["export", "my-repo"])
            assert result.exit_code == 0

    def test_export_help(self):
        result = runner.invoke(app, ["export", "--help"])
        assert result.exit_code == 0
        assert "output" in result.output.lower()


class TestInit:
    def test_init_heuristic_default(self):
        result = runner.invoke(app, ["init"], input="1\n")
        assert result.exit_code == 0

    def test_init_claude_code(self, tmp_path):
        fake_config = MagicMock()
        fake_config.save.return_value = tmp_path / "config.yaml"
        with (
            patch("sylvan.config.Config", return_value=fake_config),
            patch("sylvan.config.SummaryConfig"),
        ):
            result = runner.invoke(app, ["init"], input="3\n")
            assert result.exit_code == 0
            fake_config.save.assert_called_once()

    def test_init_help(self):
        result = runner.invoke(app, ["init", "--help"])
        assert result.exit_code == 0

    def test_init_displays_provider_options(self):
        result = runner.invoke(app, ["init"], input="\n")
        assert result.exit_code == 0
        assert "Heuristic" in result.output
        assert "Ollama" in result.output


class TestDefaultCallback:
    def test_help_flag(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "serve" in result.output
        assert "index" in result.output


class TestMainEntrypoint:
    def test_main_no_args_calls_serve(self):
        with (
            patch("sys.argv", ["sylvan"]),
            patch("sylvan.server.startup.main") as mock_serve,
        ):
            from sylvan.cli import main

            main()
            mock_serve.assert_called_once_with()

    def test_main_with_args_calls_app(self):
        with (
            patch("sys.argv", ["sylvan", "status"]),
            patch("sylvan.cli.app") as mock_app,
        ):
            from sylvan.cli import main

            main()
            mock_app.assert_called_once()
