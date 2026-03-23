"""Tests for configuration loading."""

import os

from sylvan.config import Config, load_config, reset_config


class TestConfig:
    def test_defaults(self, tmp_path):
        """Default config has sensible values when no file exists."""
        os.environ["SYLVAN_HOME"] = str(tmp_path)
        reset_config()
        try:
            config = load_config()
            assert config.summary.provider == "heuristic"
            assert config.embedding.provider == "sentence-transformers"
            assert config.indexing.max_file_size == 512_000
            assert config.indexing.max_files_local == 5_000
            assert config.server.max_concurrent_tools == 8
            assert config.logging.level == "INFO"
            assert config.security.validate_paths is True
        finally:
            os.environ.pop("SYLVAN_HOME", None)
            reset_config()

    def test_loads_yaml(self, tmp_path):
        """Loads all sections from a YAML config file."""
        os.environ["SYLVAN_HOME"] = str(tmp_path)
        reset_config()
        try:
            config_path = tmp_path / "config.yaml"
            config_path.write_text(
                "summary:\n"
                "  provider: ollama\n"
                "  endpoint: http://myhost:11434\n"
                "  model: qwen3\n"
                "embedding:\n"
                "  provider: ollama\n"
                "  dimensions: 768\n",
                encoding="utf-8",
            )
            config = load_config()
            assert config.summary.provider == "ollama"
            assert config.summary.endpoint == "http://myhost:11434"
            assert config.summary.model == "qwen3"
            assert config.embedding.provider == "ollama"
            assert config.embedding.dimensions == 768
        finally:
            os.environ.pop("SYLVAN_HOME", None)
            reset_config()

    def test_invalid_yaml_falls_back(self, tmp_path):
        """Invalid YAML falls back to defaults."""
        os.environ["SYLVAN_HOME"] = str(tmp_path)
        reset_config()
        try:
            config_path = tmp_path / "config.yaml"
            config_path.write_text("this is not valid yaml: {{{{", encoding="utf-8")
            config = load_config()
            assert config.summary.provider == "heuristic"
        finally:
            os.environ.pop("SYLVAN_HOME", None)
            reset_config()

    def test_partial_config(self, tmp_path):
        """Partial YAML fills in defaults for missing sections."""
        os.environ["SYLVAN_HOME"] = str(tmp_path)
        reset_config()
        try:
            config_path = tmp_path / "config.yaml"
            config_path.write_text(
                "summary:\n  provider: claude-code\n",
                encoding="utf-8",
            )
            config = load_config()
            assert config.summary.provider == "claude-code"
            assert config.embedding.provider == "sentence-transformers"
        finally:
            os.environ.pop("SYLVAN_HOME", None)
            reset_config()

    def test_indexing_override(self, tmp_path):
        """Indexing section overrides defaults."""
        os.environ["SYLVAN_HOME"] = str(tmp_path)
        reset_config()
        try:
            config_path = tmp_path / "config.yaml"
            config_path.write_text(
                "indexing:\n  max_file_size: 2000000\n",
                encoding="utf-8",
            )
            config = load_config()
            assert config.indexing.max_file_size == 2_000_000
            assert config.max_file_size == 2_000_000
        finally:
            os.environ.pop("SYLVAN_HOME", None)
            reset_config()

    def test_to_yaml_and_save(self, tmp_path):
        """Config serializes to YAML and round-trips correctly."""
        os.environ["SYLVAN_HOME"] = str(tmp_path)
        reset_config()
        try:
            config = Config()
            config.summary.provider = "ollama"
            config.summary.endpoint = "http://localhost:11434"
            config.libraries.overrides = {"pip/foo": "https://github.com/foo/foo"}
            config.save()

            loaded = load_config()
            assert loaded.summary.provider == "ollama"
            assert loaded.summary.endpoint == "http://localhost:11434"
            assert loaded.libraries.overrides == {"pip/foo": "https://github.com/foo/foo"}
        finally:
            os.environ.pop("SYLVAN_HOME", None)
            reset_config()
