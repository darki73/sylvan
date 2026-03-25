"""Token estimation -- tiktoken if available, byte ratio fallback."""

import functools


@functools.cache
def _get_tokenizer() -> object | None:
    """Lazy-load tiktoken encoder, caching the result via :func:`functools.cache`.

    Returns:
        A tiktoken ``Encoding`` instance, or ``None`` if tiktoken is unavailable.
    """
    try:
        import tiktoken

        return tiktoken.get_encoding("cl100k_base")
    except (ImportError, Exception):
        return None


def count_tokens(text: str) -> int | None:
    """Count tokens using tiktoken if available.

    Args:
        text: Text string to tokenize.

    Returns:
        Token count, or ``None`` if tiktoken is not installed.
    """
    enc = _get_tokenizer()
    if enc is None:
        return None
    return len(enc.encode(text))


def estimate_savings(
    returned_bytes: int,
    total_file_bytes: int,
    returned_text: str | None = None,
    total_file_text: str | None = None,
) -> dict:
    """Estimate how much was saved by returning a subset of a file.

    Args:
        returned_bytes: Byte count of the returned content.
        total_file_bytes: Byte count of the full file.
        returned_text: Optional text of the returned content (for token counting).
        total_file_text: Optional text of the full file (for token counting).

    Returns:
        Dictionary with byte-level stats always, plus token-level stats
        if tiktoken is available and text arguments are provided.
    """
    result = {
        "returned_bytes": returned_bytes,
        "total_file_bytes": total_file_bytes,
        "bytes_avoided": max(0, total_file_bytes - returned_bytes),
        "file_percent_returned": round((returned_bytes / total_file_bytes * 100) if total_file_bytes > 0 else 0, 1),
    }

    enc = _get_tokenizer()
    if enc is not None and returned_text is not None and total_file_text is not None:
        returned_tokens = len(enc.encode(returned_text))
        total_tokens = len(enc.encode(total_file_text))
        result["returned_tokens"] = returned_tokens
        result["total_file_tokens"] = total_tokens
        result["tokens_avoided"] = max(0, total_tokens - returned_tokens)
        result["method"] = "tiktoken_cl100k"
    else:
        result["method"] = "byte_ratio"

    return result
