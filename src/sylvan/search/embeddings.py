"""Embedding generation, storage, and retrieval via sqlite-vec."""

import struct

from sylvan.config import get_config
from sylvan.database.orm.runtime.connection_manager import get_backend
from sylvan.logging import get_logger
from sylvan.providers.base import EmbeddingProvider


def _vec_to_blob(vec: list[float]) -> bytes:
    """Convert a float vector to a binary blob for sqlite-vec.

    Args:
        vec: List of float values.

    Returns:
        Packed binary blob.
    """
    return struct.pack(f"{len(vec)}f", *vec)


def _blob_to_vec(blob: bytes) -> list[float]:
    """Convert a sqlite-vec binary blob back to a float vector.

    Args:
        blob: Packed binary blob.

    Returns:
        List of float values.
    """
    n = len(blob) // 4  # 4 bytes per float32
    return list(struct.unpack(f"{n}f", blob))


logger = get_logger(__name__)


def get_embedding_provider() -> EmbeddingProvider | None:
    """Get the configured embedding provider.

    Default: sentence-transformers (local, always available).
    Override via config: ollama, or ``none`` to disable.

    Returns:
        An :class:`EmbeddingProvider` instance, or ``None`` if disabled.
    """
    import sylvan.providers  # noqa: F401 — trigger provider registration
    from sylvan.providers.registry import get_embedding_provider_class

    cfg = get_config()

    if cfg.embedding.provider == "none":
        return None

    provider_name = cfg.embedding.provider

    cls = get_embedding_provider_class(provider_name)
    if cls is not None and provider_name != "sentence-transformers":
        kwargs: dict = {}
        if provider_name == "ollama":
            kwargs["endpoint"] = cfg.embedding.endpoint or "http://localhost:11434"
            kwargs["model"] = cfg.embedding.model or "nomic-embed-text"
            kwargs["dims"] = cfg.embedding.dimensions
        provider = cls(**kwargs)
        if provider.available():
            return provider
        logger.debug(
            "%s not available, falling back to sentence-transformers",
            provider_name,
        )

    fallback_cls = get_embedding_provider_class("sentence-transformers")
    if fallback_cls is None:
        from sylvan.providers.builtin.sentence_transformers import SentenceTransformerEmbeddingProvider

        fallback_cls = SentenceTransformerEmbeddingProvider
    return fallback_cls(
        model=cfg.embedding.model if cfg.embedding.provider == "sentence-transformers" else "all-MiniLM-L6-v2",
    )


async def embed_and_store_symbols(
    provider: EmbeddingProvider,
    symbol_ids: list[str],
    texts: list[str],
    batch_size: int = 64,
) -> int:
    """Generate embeddings for symbols and store in sqlite-vec.

    Kept as raw SQL because vec tables are not regular tables.

    Args:
        provider: Embedding provider to use.
        symbol_ids: List of symbol ID strings.
        texts: List of text strings to embed (parallel to *symbol_ids*).
        batch_size: Number of texts per embedding batch.

    Returns:
        Number of embeddings successfully stored.
    """
    backend = get_backend()
    stored = 0

    for i in range(0, len(texts), batch_size):
        batch_ids = symbol_ids[i : i + batch_size]
        batch_texts = texts[i : i + batch_size]

        try:
            vectors = provider.embed(batch_texts)
        except Exception as e:
            logger.warning("embedding_batch_failed", offset=i, error=str(e))
            continue

        for sid, vec in zip(batch_ids, vectors):
            try:
                await backend.execute(
                    "INSERT OR REPLACE INTO symbols_vec (symbol_id, embedding) VALUES (?, ?)",
                    [sid, _vec_to_blob(vec)],
                )
                stored += 1
            except Exception as e:
                logger.debug("embedding_store_failed", symbol_id=sid, error=str(e))

    return stored


async def embed_and_store_sections(
    provider: EmbeddingProvider,
    section_ids: list[str],
    texts: list[str],
    batch_size: int = 64,
) -> int:
    """Generate embeddings for sections and store in sqlite-vec.

    Kept as raw SQL because vec tables are not regular tables.

    Args:
        provider: Embedding provider to use.
        section_ids: List of section ID strings.
        texts: List of text strings to embed (parallel to *section_ids*).
        batch_size: Number of texts per embedding batch.

    Returns:
        Number of embeddings successfully stored.
    """
    backend = get_backend()
    stored = 0

    for i in range(0, len(texts), batch_size):
        batch_ids = section_ids[i : i + batch_size]
        batch_texts = texts[i : i + batch_size]

        try:
            vectors = provider.embed(batch_texts)
        except Exception as e:
            logger.warning("section_embedding_batch_failed", offset=i, error=str(e))
            continue

        for sid, vec in zip(batch_ids, vectors):
            try:
                await backend.execute(
                    "INSERT OR REPLACE INTO sections_vec (section_id, embedding) VALUES (?, ?)",
                    [sid, _vec_to_blob(vec)],
                )
                stored += 1
            except Exception as e:
                logger.debug("section_embedding_store_failed", section_id=sid, error=str(e))

    return stored


def prepare_symbol_text(symbol: dict) -> str:
    """Prepare a text representation of a symbol for embedding.

    Args:
        symbol: Dictionary with symbol metadata (``qualified_name``,
            ``signature``, ``docstring``, ``summary``, ``name``).

    Returns:
        Concatenated text suitable for embedding.
    """
    parts = []
    if symbol.get("qualified_name"):
        parts.append(symbol["qualified_name"])
    if symbol.get("signature"):
        parts.append(symbol["signature"])
    if symbol.get("docstring"):
        parts.append(symbol["docstring"][:500])
    if symbol.get("summary"):
        parts.append(symbol["summary"])
    return " ".join(parts) or symbol.get("name", "")


def prepare_section_text(section: dict) -> str:
    """Prepare a text representation of a section for embedding.

    Args:
        section: Dictionary with section metadata (``title``, ``summary``).

    Returns:
        Concatenated text suitable for embedding.
    """
    parts = []
    if section.get("title"):
        parts.append(section["title"])
    if section.get("summary"):
        parts.append(section["summary"])
    return " ".join(parts) or ""
