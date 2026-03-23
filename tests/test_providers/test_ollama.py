"""Tests for Ollama provider using real captured responses.

Fixture data captured from a real Ollama server (qwen3:4b for summaries,
embeddinggemma:300m for embeddings). Mocks the ollama.Client to return
real responses without needing a live server.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def ollama_fixtures():
    fixture_path = Path(__file__).parent.parent / "fixtures" / "ollama_responses.json"
    with fixture_path.open() as f:
        return json.load(f)


def _mock_client(generate_response=None, embed_response=None, list_response=None):
    """Create a mock ollama.Client."""
    client = MagicMock()

    if generate_response is not None:
        resp = MagicMock()
        resp.response = generate_response
        client.generate.return_value = resp

    if embed_response is not None:
        resp = MagicMock()
        resp.embeddings = embed_response
        client.embed.return_value = resp

    if list_response is not None:
        resp = MagicMock()
        models = []
        for name in list_response:
            m = MagicMock()
            m.model = name
            models.append(m)
        resp.models = models
        client.list.return_value = resp
    else:
        client.list.return_value = MagicMock(models=[])

    return client


class TestOllamaSummaryProvider:
    def test_summarize_with_docstring(self, ollama_fixtures):
        from sylvan.providers.external.ollama.provider import OllamaSummaryProvider
        real = ollama_fixtures["summary_responses"][0]
        tc = ollama_fixtures["summary_test_cases"][0]

        mock = _mock_client(generate_response=real)
        with patch("sylvan.providers.external.ollama.provider._get_client", return_value=mock):
            p = OllamaSummaryProvider(model="qwen3:4b")
            result = p.summarize_symbol(tc["signature"], tc["docstring"], tc["source"])
            assert result == real[:120]
            assert len(result) > 5

    def test_summarize_without_docstring(self, ollama_fixtures):
        from sylvan.providers.external.ollama.provider import OllamaSummaryProvider
        real = ollama_fixtures["summary_responses"][1]
        tc = ollama_fixtures["summary_test_cases"][1]

        mock = _mock_client(generate_response=real)
        with patch("sylvan.providers.external.ollama.provider._get_client", return_value=mock):
            p = OllamaSummaryProvider(model="qwen3:4b")
            result = p.summarize_symbol(tc["signature"], None, tc["source"])
            assert len(result) > 5

    def test_summarize_class(self, ollama_fixtures):
        from sylvan.providers.external.ollama.provider import OllamaSummaryProvider
        real = ollama_fixtures["summary_responses"][2]
        tc = ollama_fixtures["summary_test_cases"][2]

        mock = _mock_client(generate_response=real)
        with patch("sylvan.providers.external.ollama.provider._get_client", return_value=mock):
            p = OllamaSummaryProvider(model="qwen3:4b")
            result = p.summarize_symbol(tc["signature"], tc["docstring"], tc["source"])
            assert len(result) > 5

    def test_summarize_batch(self, ollama_fixtures):
        from sylvan.providers.external.ollama.provider import OllamaSummaryProvider
        responses = ollama_fixtures["summary_responses"]
        idx = [0]

        def fake_generate(**kwargs):
            i = min(idx[0], len(responses) - 1)
            idx[0] += 1
            resp = MagicMock()
            resp.response = responses[i]
            return resp

        mock = _mock_client()
        mock.generate.side_effect = fake_generate
        with patch("sylvan.providers.external.ollama.provider._get_client", return_value=mock):
            p = OllamaSummaryProvider()
            results = p.summarize(["code1", "code2", "code3"])
            assert len(results) == 3
            assert all(isinstance(r, str) for r in results)

    def test_available_when_server_up(self):
        from sylvan.providers.external.ollama.provider import OllamaSummaryProvider
        mock = _mock_client(list_response=["qwen3:4b"])
        with patch("sylvan.providers.external.ollama.provider._get_client", return_value=mock):
            assert OllamaSummaryProvider().available() is True

    def test_unavailable_when_server_down(self):
        from sylvan.providers.external.ollama.provider import OllamaSummaryProvider
        with patch("sylvan.providers.external.ollama.provider._get_client", side_effect=Exception("refused")):
            assert OllamaSummaryProvider().available() is False

    def test_fallback_on_timeout(self):
        from sylvan.providers.external.ollama.provider import OllamaSummaryProvider
        mock = _mock_client()
        mock.generate.side_effect = Exception("timeout")
        with patch("sylvan.providers.external.ollama.provider._get_client", return_value=mock):
            p = OllamaSummaryProvider()
            result = p.summarize_symbol("def foo(x: int)", None, "def foo(x): pass")
            assert "def foo(x: int)" in result

    def test_name(self):
        from sylvan.providers.external.ollama.provider import OllamaSummaryProvider
        assert OllamaSummaryProvider().name == "ollama"


class TestOllamaEmbeddingProvider:
    def test_embed_returns_real_vectors(self, ollama_fixtures):
        from sylvan.providers.external.ollama.provider import OllamaEmbeddingProvider
        real = ollama_fixtures["embeddings"]

        mock = _mock_client(embed_response=real)
        with patch("sylvan.providers.external.ollama.provider._get_client", return_value=mock):
            p = OllamaEmbeddingProvider(
                model="embeddinggemma:300m",
                dims=ollama_fixtures["embedding_dimensions"],
            )
            results = p.embed(ollama_fixtures["embedding_texts"])
            assert len(results) == len(real)
            assert len(results[0]) == ollama_fixtures["embedding_dimensions"]
            assert results[0][:5] == [float(x) for x in real[0][:5]]

    def test_embed_one(self, ollama_fixtures):
        from sylvan.providers.external.ollama.provider import OllamaEmbeddingProvider
        real = ollama_fixtures["embeddings"]

        mock = _mock_client(embed_response=[real[0]])
        with patch("sylvan.providers.external.ollama.provider._get_client", return_value=mock):
            p = OllamaEmbeddingProvider(dims=ollama_fixtures["embedding_dimensions"])
            result = p.embed_one("test")
            assert len(result) == ollama_fixtures["embedding_dimensions"]

    def test_semantic_similarity_real_data(self, ollama_fixtures):
        """Real embeddings should show correct similarity patterns."""
        embeddings = ollama_fixtures["embeddings"]

        def cosine_sim(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a))
            nb = math.sqrt(sum(x * x for x in b))
            return dot / (na * nb) if na and nb else 0

        # get_connection should be more similar to "database connection"
        # than to "authentication login"
        sim_db = cosine_sim(embeddings[0], embeddings[1])
        sim_auth = cosine_sim(embeddings[0], embeddings[2])
        assert sim_db > sim_auth

    def test_available_with_model(self):
        from sylvan.providers.external.ollama.provider import OllamaEmbeddingProvider
        mock = _mock_client(list_response=["embeddinggemma:300m"])
        with patch("sylvan.providers.external.ollama.provider._get_client", return_value=mock):
            p = OllamaEmbeddingProvider(model="embeddinggemma:300m")
            assert p.available() is True

    def test_unavailable_without_model(self):
        from sylvan.providers.external.ollama.provider import OllamaEmbeddingProvider
        mock = _mock_client(list_response=["qwen3:4b"])
        with patch("sylvan.providers.external.ollama.provider._get_client", return_value=mock):
            p = OllamaEmbeddingProvider(model="embeddinggemma:300m")
            assert p.available() is False

    def test_fallback_zero_vector(self):
        from sylvan.providers.external.ollama.provider import OllamaEmbeddingProvider
        mock = _mock_client()
        mock.embed.side_effect = Exception("timeout")
        with patch("sylvan.providers.external.ollama.provider._get_client", return_value=mock):
            p = OllamaEmbeddingProvider(dims=384)
            results = p.embed(["test"])
            assert len(results) == 1
            assert len(results[0]) == 384
            assert all(v == 0.0 for v in results[0])

    def test_dimensions_property(self):
        from sylvan.providers.external.ollama.provider import OllamaEmbeddingProvider
        assert OllamaEmbeddingProvider(dims=768).dimensions == 768

    def test_name(self):
        from sylvan.providers.external.ollama.provider import OllamaEmbeddingProvider
        assert OllamaEmbeddingProvider().name == "ollama"
