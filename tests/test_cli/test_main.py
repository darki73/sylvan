"""Tests for sylvan.__main__ entry point."""

from __future__ import annotations

from unittest.mock import patch


class TestMainModule:
    """Tests for the __main__.py entry point."""

    def test_main_module_importable(self):
        """The __main__ module can be imported without side effects."""
        import sylvan.__main__  # noqa: F401

    def test_main_module_has_main_import(self):
        """The module imports 'main' from sylvan.cli."""
        import sylvan.__main__ as m

        assert hasattr(m, "main")

    def test_main_calls_app_when_run_as_script(self):
        """Running as __main__ invokes the CLI entry point."""
        with patch("sylvan.cli.main") as mock_main:
            # exec the module body with __name__ == "__main__"
            exec(  # noqa: S102
                compile(
                    'from sylvan.cli import main\nif __name__ == "__main__":\n    main()\n',
                    "<test>",
                    "exec",
                ),
                {"__name__": "__main__"},
            )
            mock_main.assert_called_once()
