"""Tests for sylvan.providers.external.ollama.setup — interactive Ollama config."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestListOllamaModels:
    """Tests for list_ollama_models()."""

    def test_separates_llm_and_embedding_models(self):
        """LLM and embedding models are separated based on name."""
        from sylvan.providers.external.ollama.setup import list_ollama_models

        mock_models = []
        for name in ["llama3:8b", "nomic-embed-text:latest", "qwen3:4b"]:
            m = MagicMock()
            m.model = name
            m.details.parameter_size = "4B"
            mock_models.append(m)

        mock_client = MagicMock()
        mock_client.list.return_value = MagicMock(models=mock_models)

        with patch("ollama.Client", return_value=mock_client):
            llms, embeds = list_ollama_models("http://localhost:11434")

        assert len(llms) == 2
        assert len(embeds) == 1
        assert embeds[0][0] == "nomic-embed-text:latest"

    def test_excludes_vision_models(self):
        """Models with 'vl' or 'llava' in name are excluded from LLMs."""
        from sylvan.providers.external.ollama.setup import list_ollama_models

        mock_models = []
        for name in ["llama3:8b", "llava:7b", "qwen-vl:4b"]:
            m = MagicMock()
            m.model = name
            m.details.parameter_size = "4B"
            mock_models.append(m)

        mock_client = MagicMock()
        mock_client.list.return_value = MagicMock(models=mock_models)

        with patch("ollama.Client", return_value=mock_client):
            llms, _embeds = list_ollama_models("http://localhost:11434")

        assert len(llms) == 1
        assert llms[0][0] == "llama3:8b"

    def test_returns_empty_on_connection_error(self):
        """Returns empty lists when Ollama is unreachable."""
        from sylvan.providers.external.ollama.setup import list_ollama_models

        with patch("ollama.Client", side_effect=ConnectionError("refused")):
            llms, embeds = list_ollama_models("http://localhost:11434")

        assert llms == []
        assert embeds == []

    def test_handles_missing_details(self):
        """Models with details=None show '?' as size."""
        from sylvan.providers.external.ollama.setup import list_ollama_models

        m = MagicMock()
        m.model = "llama3:8b"
        m.details = None

        mock_client = MagicMock()
        mock_client.list.return_value = MagicMock(models=[m])

        with patch("ollama.Client", return_value=mock_client):
            llms, _embeds = list_ollama_models("http://localhost:11434")

        assert len(llms) == 1
        assert llms[0][1] == "?"


class TestDetectEmbeddingDims:
    """Tests for detect_embedding_dims()."""

    def test_returns_detected_dimensions(self):
        """Returns the length of the first embedding vector."""
        from sylvan.providers.external.ollama.setup import detect_embedding_dims

        mock_client = MagicMock()
        mock_client.embed.return_value = MagicMock(
            embeddings=[[0.1] * 384],
        )

        with patch("ollama.Client", return_value=mock_client):
            dims = detect_embedding_dims("http://localhost:11434", "nomic-embed-text")

        assert dims == 384

    def test_returns_768_on_empty_embeddings(self):
        """Returns fallback 768 when response has no embeddings."""
        from sylvan.providers.external.ollama.setup import detect_embedding_dims

        mock_client = MagicMock()
        mock_client.embed.return_value = MagicMock(embeddings=[])

        with patch("ollama.Client", return_value=mock_client):
            dims = detect_embedding_dims("http://localhost:11434", "nomic-embed-text")

        assert dims == 768

    def test_returns_768_on_error(self):
        """Returns fallback 768 when embed call fails."""
        from sylvan.providers.external.ollama.setup import detect_embedding_dims

        with patch("ollama.Client", side_effect=Exception("failed")):
            dims = detect_embedding_dims("http://localhost:11434", "nomic-embed-text")

        assert dims == 768


class TestConfigureOllama:
    """Tests for configure_ollama()."""

    def test_exits_when_no_models_found(self):
        """Raises typer.Exit when no models are available."""
        import typer

        from sylvan.providers.external.ollama.setup import configure_ollama

        config = MagicMock()

        with patch("typer.prompt", return_value="http://localhost:11434"), \
             patch(
                 "sylvan.providers.external.ollama.setup.list_ollama_models",
                 return_value=([], []),
             ), \
             pytest.raises(typer.Exit):
            configure_ollama(config)

    def test_configures_summary_provider(self):
        """Sets config.summary with ollama provider when LLM model selected."""
        from sylvan.providers.external.ollama.setup import configure_ollama

        config = MagicMock()
        llms = [("llama3:8b", "8B"), ("qwen3:4b", "4B")]
        embeds: list = []

        with patch("typer.prompt", side_effect=["http://localhost:11434", "1"]), \
             patch("typer.echo"), \
             patch(
                 "sylvan.providers.external.ollama.setup.list_ollama_models",
                 return_value=(llms, embeds),
             ):
            configure_ollama(config)

        assert config.summary is not None
        # The SummaryConfig was assigned
        assert config.summary.provider == "ollama"
        assert config.summary.model == "llama3:8b"

    def test_invalid_pick_defaults_to_first(self):
        """Invalid model selection falls back to first model."""
        from sylvan.providers.external.ollama.setup import configure_ollama

        config = MagicMock()
        llms = [("llama3:8b", "8B")]
        embeds: list = []

        with patch("typer.prompt", side_effect=["http://localhost:11434", "not_a_number"]), \
             patch("typer.echo"), \
             patch(
                 "sylvan.providers.external.ollama.setup.list_ollama_models",
                 return_value=(llms, embeds),
             ):
            configure_ollama(config)

        assert config.summary.model == "llama3:8b"
