"""Embedding provider backed by the Rust sylvan-providers crate.

Every call to the ``sentence-transformers`` provider routes through
``sylvan._rust.EmbeddingModel`` (raw ``ort-sys`` FFI with RAII safety).
The ONNX Runtime shared library is downloaded on first use from
Microsoft's GitHub releases into ``~/.sylvan/runtime/``; no Python
``onnxruntime`` package dependency is required.

Set ``ORT_DLL_PATH`` to bypass the download and point at an existing
ORT installation (useful for air-gapped setups or custom builds).

The provider key and file name are historical artefacts from the
fastembed era; see the canopy memory for the rename plan deferred to
v3.0.
"""

from __future__ import annotations

from functools import lru_cache
from typing import override

from sylvan._rust import EmbeddingModel as _RustEmbeddingModel
from sylvan.providers.base import EmbeddingProvider
from sylvan.providers.registry import register_embedding_provider

# Cache loaded models keyed on (model_name, cache_path). Loading is
# expensive (filesystem read + tokenizer init + ORT session compile)
# so repeated provider instantiations with the same config reuse the
# same underlying handle.
_model_cache: dict[tuple[str, str], _RustEmbeddingModel] = {}


@lru_cache(maxsize=1)
def _default_cache_path() -> str:
    """Return the configured model cache directory.

    Reads :class:`sylvan.config.EmbeddingConfig.model_cache_path` so
    any override in ``~/.sylvan/config.yaml`` is respected; falls back
    to the default ``~/.sylvan/models`` otherwise.
    """
    from sylvan.config import load_config

    return load_config().embedding.model_cache_path


def _get_model(model_name: str, cache_path: str | None = None) -> _RustEmbeddingModel:
    """Get or create the cached Rust embedding model for this config."""
    resolved_cache = cache_path or _default_cache_path()
    key = (model_name, resolved_cache)
    cached = _model_cache.get(key)
    if cached is not None:
        return cached
    # ort_library_path omitted → Rust downloads + caches the platform
    # binary under `$SYLVAN_HOME/runtime/` on first call.
    model = _RustEmbeddingModel(
        model_name=model_name,
        cache_dir=resolved_cache,
    )
    _model_cache[key] = model
    return model


@register_embedding_provider("sentence-transformers")
class SentenceTransformerEmbeddingProvider(EmbeddingProvider):
    """Generate embeddings through the Rust ONNX Runtime pipeline.

    Default model: ``all-MiniLM-L6-v2`` (384 dimensions).
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
        """Return the embedding dimension, auto-detected on first use."""
        if self._dims is None:
            vec = self.embed_one("test")
            self._dims = len(vec)
        return self._dims

    @override
    def available(self) -> bool:
        """Rust backend is always present once the sylvan wheel loads."""
        return True

    @override
    def _generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Embed *texts* through the Rust backend."""
        return _get_model(self._model_name).embed(texts)
