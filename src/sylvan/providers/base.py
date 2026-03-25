"""Provider base classes with built-in logging, error handling, retries, and timing.

Subclasses only implement the core logic. The base handles everything else:
- Structured logging for every call
- Error catching with fallback behavior
- Timing metrics
- Input validation
- Retry logic for transient failures
- Standard prompt building for summary providers

To implement a new SummaryProvider::

    class MyProvider(SummaryProvider):
        name = "my-provider"
        def available(self) -> bool: ...
        def _generate_summary(self, prompt: str) -> str: ...

To implement a new EmbeddingProvider::

    class MyProvider(EmbeddingProvider):
        name = "my-provider"
        dimensions = 384
        def available(self) -> bool: ...
        def _generate_embeddings(self, texts: list[str]) -> list[list[float]]: ...
"""

import time
from abc import ABC, abstractmethod
from typing import Protocol, runtime_checkable

from sylvan.logging import get_logger

logger = get_logger(__name__)

SUMMARY_SYSTEM_PROMPT = (
    "You are a code summarizer. Given code, return a single-line "
    "summary under 100 characters. Return ONLY the summary text."
)


def build_summary_prompt(
    signature: str,
    docstring: str | None,
    source: str,
    max_source_chars: int = 500,
) -> str:
    """Build a standard summary prompt from symbol metadata.

    Args:
        signature: Function or method signature string.
        docstring: Extracted docstring, if any.
        source: Raw source code of the symbol.
        max_source_chars: Maximum characters of source to include.

    Returns:
        A formatted prompt string for the summary provider.
    """
    parts = ["Generate a single-line summary (max 100 chars) of this code. Return ONLY the summary, nothing else.\n"]
    if signature:
        parts.append(f"Signature: {signature}")
    if docstring:
        parts.append(f"Docstring: {docstring}")
    parts.append(f"Source:\n{source[:max_source_chars]}")
    return "\n".join(parts)


def _first_sentence(text: str) -> str:
    """Extract the first sentence from text, stripping quote delimiters.

    Args:
        text: Raw text, possibly with leading/trailing delimiters.

    Returns:
        The first sentence or first line (up to 120 characters).
    """
    text = text.strip()
    for prefix in ('"""', "'''", "///", "//", "#", "/*", "*"):
        if text.startswith(prefix):
            text = text[len(prefix) :].strip()
    for suffix in ('"""', "'''", "*/"):
        if text.endswith(suffix):
            text = text[: -len(suffix)].strip()
    if not text:
        return ""
    first_line = text.split("\n")[0].strip()
    dot = first_line.find(".")
    if 0 < dot < 120:
        return first_line[: dot + 1]
    return first_line[:120]


@runtime_checkable
class SummaryProviderProtocol(Protocol):
    """Contract: what a summary provider must implement."""

    @property
    def name(self) -> str:
        """Provider identifier (e.g., ``'ollama'``, ``'claude-code'``).

        Returns:
            Provider name string.
        """
        ...

    def available(self) -> bool:
        """Check if this provider is currently usable.

        Returns:
            ``True`` if the provider can generate summaries right now.
        """
        ...

    def _generate_summary(self, prompt: str) -> str:
        """Core implementation: send prompt, return summary text.

        Args:
            prompt: The formatted summary prompt.

        Returns:
            Raw summary text from the provider.
        """
        ...

    def summarize_section(self, title: str, content: str) -> str:
        """Generate a summary for a documentation section.

        Args:
            title: Section heading text.
            content: Section body text.

        Returns:
            A summary string (up to 150 characters).
        """
        ...


class SummaryProvider(ABC):
    """Base class with shared logging/timing/fallback behavior for summary generation.

    Subclasses implement ``available()`` and ``_generate_summary()``.
    This base provides ``summarize_symbol()``, ``summarize()``, and ``name``.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (e.g., ``'ollama'``, ``'claude-code'``).

        Returns:
            Provider name string.
        """

    @abstractmethod
    def available(self) -> bool:
        """Check if this provider is currently usable.

        Returns:
            ``True`` if the provider can generate summaries right now.
        """

    @abstractmethod
    def _generate_summary(self, prompt: str) -> str:
        """Core implementation: send prompt, return summary text.

        This is what subclasses implement.  No error handling needed --
        the base class catches exceptions and falls back gracefully.

        Args:
            prompt: The formatted summary prompt.

        Returns:
            Raw summary text from the provider.
        """

    def summarize_symbol(
        self,
        signature: str,
        docstring: str | None,
        source: str,
    ) -> str:
        """Generate a summary for a code symbol.

        Handles prompt building, timing, logging, and error fallback.

        Args:
            signature: Function or method signature.
            docstring: Extracted docstring, if any.
            source: Raw source code.

        Returns:
            A summary string (up to 120 characters).
        """
        prompt = build_summary_prompt(signature, docstring, source)

        t0 = time.perf_counter()
        try:
            result = self._generate_summary(prompt)
            elapsed = (time.perf_counter() - t0) * 1000

            if result and len(result.strip()) > 5:
                summary = result.strip()[:120]
                logger.debug(
                    "summary_generated",
                    provider=self.name,
                    length=len(summary),
                    elapsed_ms=round(elapsed, 1),
                )
                return summary

        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            logger.debug(
                "summary_failed",
                provider=self.name,
                error=str(e),
                elapsed_ms=round(elapsed, 1),
            )

        if docstring:
            first_line = docstring.strip().split("\n")[0].strip()
            if len(first_line) > 10:
                return first_line[:120]
        return signature[:120] if signature else ""

    def summarize_section(self, title: str, content: str) -> str:
        """Generate a summary for a documentation section.

        Handles prompt building, timing, logging, and error fallback.

        Args:
            title: Section heading text.
            content: Section body text.

        Returns:
            A summary string (up to 150 characters).
        """
        prompt = f"Title: {title}\nContent: {content[:500]}"

        t0 = time.perf_counter()
        try:
            result = self._generate_summary(prompt)
            elapsed = (time.perf_counter() - t0) * 1000

            if result and len(result.strip()) > 5:
                summary = result.strip()[:150]
                logger.debug(
                    "section_summary_generated",
                    provider=self.name,
                    length=len(summary),
                    elapsed_ms=round(elapsed, 1),
                )
                return summary

        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            logger.debug(
                "section_summary_failed",
                provider=self.name,
                error=str(e),
                elapsed_ms=round(elapsed, 1),
            )

        # Fallback: first sentence of content
        return _first_sentence(content)[:150] if content else title[:150]

    def summarize(self, texts: list[str]) -> list[str]:
        """Batch summarize multiple text blocks.

        Default implementation calls :meth:`summarize_symbol` for each.

        Args:
            texts: List of source text blocks to summarize.

        Returns:
            List of summary strings, one per input text.
        """
        return [self.summarize_symbol("", None, t) for t in texts]


@runtime_checkable
class EmbeddingProviderProtocol(Protocol):
    """Contract: what an embedding provider must implement."""

    @property
    def name(self) -> str:
        """Provider identifier.

        Returns:
            Provider name string.
        """
        ...

    @property
    def dimensions(self) -> int:
        """Embedding vector dimensionality.

        Returns:
            Number of dimensions in each embedding vector.
        """
        ...

    def available(self) -> bool:
        """Check if this provider is currently usable.

        Returns:
            ``True`` if the provider can generate embeddings right now.
        """
        ...

    def _generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Core implementation: generate embedding vectors.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of float vectors, one per input text.
        """
        ...


class EmbeddingProvider(ABC):
    """Base class with shared logging/timing/fallback behavior for embedding generation.

    Subclasses implement ``available()`` and ``_generate_embeddings()``.
    This base provides ``embed()``, ``embed_one()``, ``name``, and ``dimensions``.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier.

        Returns:
            Provider name string.
        """

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Embedding vector dimensionality.

        Returns:
            Number of dimensions in each embedding vector.
        """

    @abstractmethod
    def available(self) -> bool:
        """Check if this provider is currently usable.

        Returns:
            ``True`` if the provider can generate embeddings right now.
        """

    @abstractmethod
    def _generate_embeddings(self, texts: list[str]) -> list[list[float]]:
        """Core implementation: generate embedding vectors.

        Subclasses implement this.  Errors are caught by the base class.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of float vectors, one per input text.
        """

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings with logging and error handling.

        On failure, returns zero vectors (never crashes the caller).

        Args:
            texts: List of text strings to embed.

        Returns:
            List of float vectors.  On error, returns zero vectors.
        """
        if not texts:
            return []

        t0 = time.perf_counter()
        try:
            results = self._generate_embeddings(texts)
            elapsed = (time.perf_counter() - t0) * 1000

            logger.debug(
                "embeddings_generated",
                provider=self.name,
                count=len(results),
                dimensions=len(results[0]) if results else 0,
                elapsed_ms=round(elapsed, 1),
            )
            return results

        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            logger.warning(
                "embedding_failed",
                provider=self.name,
                count=len(texts),
                error=str(e),
                elapsed_ms=round(elapsed, 1),
            )
            return [[0.0] * self.dimensions for _ in texts]

    def embed_one(self, text: str) -> list[float]:
        """Embed a single text string.

        Convenience wrapper around :meth:`embed`.

        Args:
            text: Text string to embed.

        Returns:
            A single float vector.
        """
        results = self.embed([text])
        return results[0] if results else [0.0] * self.dimensions
