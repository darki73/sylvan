"""Ollama provider -- local LLM for summaries and embeddings via official SDK."""

from typing import override

from sylvan.providers.base import EmbeddingProvider, SummaryProvider
from sylvan.providers.registry import register_embedding_provider, register_summary_provider


def _get_client(endpoint: str):
    """Create an Ollama client connected to the given endpoint.

    Args:
        endpoint: Ollama server URL (e.g. ``http://localhost:11434``).

    Returns:
        An ``ollama.Client`` instance.
    """
    from ollama import Client

    return Client(host=endpoint)


@register_summary_provider("ollama")
class OllamaSummaryProvider(SummaryProvider):
    """Generate summaries using a local Ollama instance."""

    name = "ollama"

    def __init__(self, endpoint: str = "http://localhost:11434", model: str = "qwen3:4b") -> None:
        """Initialize with the Ollama endpoint and model name.

        Args:
            endpoint: Ollama server URL.
            model: Model identifier to use for generation.
        """
        self._endpoint = endpoint
        self._model = model

    @override
    def available(self) -> bool:
        """Check if Ollama is reachable and has models.

        Returns:
            ``True`` if the server responds to a model list request.
        """
        try:
            _get_client(self._endpoint).list()
            return True
        except Exception:
            return False

    @override
    def _generate_summary(self, prompt: str) -> str:
        """Generate a summary via the Ollama generate API.

        Args:
            prompt: Formatted summary prompt.

        Returns:
            Summary text (up to 120 characters).
        """
        client = _get_client(self._endpoint)
        response = client.generate(model=self._model, prompt=prompt, stream=False)
        return response.response.strip()[:120]


@register_embedding_provider("ollama")
class OllamaEmbeddingProvider(EmbeddingProvider):
    """Generate embeddings using a local Ollama instance."""

    name = "ollama"

    def __init__(
        self,
        endpoint: str = "http://localhost:11434",
        model: str = "embeddinggemma:300m",
        dims: int = 768,
    ) -> None:
        """Initialize with the Ollama endpoint, model, and dimension count.

        Args:
            endpoint: Ollama server URL.
            model: Model identifier for embedding generation.
            dims: Expected dimensionality of the embedding vectors.
        """
        self._endpoint = endpoint
        self._model = model
        self._dims = dims

    @property
    @override
    def dimensions(self) -> int:
        """Return the embedding vector dimensionality.

        Returns:
            Number of dimensions per vector.
        """
        return self._dims

    @override
    def available(self) -> bool:
        """Check if Ollama has the configured embedding model.

        Returns:
            ``True`` if the model is listed on the server.
        """
        try:
            client = _get_client(self._endpoint)
            models = client.list()
            return any(m.model.startswith(self._model) for m in models.models)
        except Exception:
            return False

    @override
    def _generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Generate embedding vectors via the Ollama embed API.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of float vectors, one per input text.
        """
        client = _get_client(self._endpoint)
        response = client.embed(model=self._model, input=texts)
        return [list(e) for e in response.embeddings]
