"""Embedding provider -- fastembed (ONNX, no torch, 15x faster)."""

from typing import override

from sylvan.providers.base import EmbeddingProvider
from sylvan.providers.registry import register_embedding_provider

_model = None
_model_name: str | None = None


def _get_model(model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
    """Get or create the singleton fastembed TextEmbedding model.

    Args:
        model_name: Hugging Face model identifier.

    Returns:
        A :class:`fastembed.TextEmbedding` instance.
    """
    global _model, _model_name
    if _model is not None and _model_name == model_name:
        return _model
    from fastembed import TextEmbedding
    _model = TextEmbedding(model_name)
    _model_name = model_name
    return _model


@register_embedding_provider("sentence-transformers")
class SentenceTransformerEmbeddingProvider(EmbeddingProvider):
    """Generate embeddings using fastembed (ONNX, no torch).

    Default model: all-MiniLM-L6-v2 (384 dimensions).
    """

    name = "sentence-transformers"

    def __init__(self, model: str = "sentence-transformers/all-MiniLM-L6-v2") -> None:
        """Initialize with the given model name.

        Args:
            model: Hugging Face model identifier for embedding generation.
        """
        self._model_name = model
        self._dims: int | None = None

    @property
    @override
    def dimensions(self) -> int:
        """Return the dimensionality of the embedding vectors, auto-detected on first use.

        Returns:
            Number of dimensions in each embedding vector.
        """
        if self._dims is None:
            vec = self.embed_one("test")
            self._dims = len(vec)
        return self._dims

    @override
    def available(self) -> bool:
        """Check whether fastembed is importable.

        Returns:
            ``True`` if the ``fastembed`` package is installed.
        """
        try:
            from fastembed import TextEmbedding
            return True
        except ImportError:
            return False

    @override
    def _generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Generate embedding vectors using the fastembed model.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of float vectors, one per input text.
        """
        model = _get_model(self._model_name)
        return [e.tolist() for e in model.embed(texts)]
