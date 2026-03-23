"""FTS5 + sqlite-vec search utilities for the query builder."""

import struct

_FTS5_KEYWORDS = frozenset({"AND", "OR", "NOT", "NEAR"})
"""FTS5 operator keywords that must be filtered from user queries."""


def prepare_fts_query(query: str) -> str:
    """Clean a user query for FTS5 MATCH.

    Strips special characters, filters FTS5 keywords, and joins terms with OR.

    Args:
        query: Raw user search string.

    Returns:
        A sanitized FTS5 query string with terms joined by OR.
    """
    clean = ""
    for ch in query:
        if ch.isalnum() or ch in (" ", "_", "-"):
            clean += ch
        else:
            clean += " "

    terms = [t for t in clean.split() if len(t) >= 2 and t.upper() not in _FTS5_KEYWORDS]
    if not terms:
        return ""
    return " OR ".join(terms)


def embed_text(text: str) -> list[float] | None:
    """Embed text using the configured embedding provider.

    Args:
        text: The text to embed.

    Returns:
        A float vector, or None if no provider is available or embedding fails.
    """
    try:
        from sylvan.search.embeddings import get_embedding_provider
        provider = get_embedding_provider()
        if provider is None:
            return None
        return provider.embed_one(text)
    except Exception as e:
        from sylvan.logging import get_logger
        get_logger(__name__).debug("embed_text_failed", error=str(e))
        return None


def vec_to_blob(vec: list[float]) -> bytes:
    """Convert a float vector to a binary blob for sqlite-vec.

    Args:
        vec: List of float values representing the embedding.

    Returns:
        A packed binary representation of the vector.
    """
    return struct.pack(f"{len(vec)}f", *vec)


def reciprocal_rank_fusion(
    fts_results: list[dict],
    vec_results: list[dict],
    id_key: str,
    fts_weight: float = 0.7,
    vec_weight: float = 0.3,
    k: int = 60,
) -> list[dict]:
    """Merge FTS5 and vector results using Reciprocal Rank Fusion.

    Args:
        fts_results: Results from FTS5 search (ordered by BM25 rank).
        vec_results: Results from vector search (ordered by distance).
        id_key: Column name to use as unique ID for dedup.
        fts_weight: Weight for FTS5 results (0-1).
        vec_weight: Weight for vector results (0-1).
        k: RRF constant (higher means more uniform blending).

    Returns:
        Merged results ordered by fused score, highest first.
    """
    scores: dict[str, float] = {}

    for rank, r in enumerate(fts_results):
        rid = r[id_key]
        scores[rid] = scores.get(rid, 0) + fts_weight / (k + rank + 1)

    for rank, r in enumerate(vec_results):
        rid = r[id_key]
        scores[rid] = scores.get(rid, 0) + vec_weight / (k + rank + 1)

    all_results: dict[str, dict] = {}
    for r in fts_results:
        all_results[r[id_key]] = r
    for r in vec_results:
        if r[id_key] not in all_results:
            all_results[r[id_key]] = r

    ranked = sorted(scores.items(), key=lambda x: -x[1])
    return [all_results[rid] for rid, _ in ranked if rid in all_results]
