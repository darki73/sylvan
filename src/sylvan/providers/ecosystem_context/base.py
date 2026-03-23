"""Ecosystem context provider framework."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

from sylvan.logging import get_logger

logger = get_logger(__name__)


@dataclass(slots=True, frozen=True)
class FileContext:
    """Context metadata for a file from an ecosystem provider.

    Attributes:
        description: Human-readable description of the file's purpose.
        tags: Tags or labels associated with the file.
        properties: Key-value metadata properties (e.g. column names).
    """

    description: str = ""
    tags: list[str] = field(default_factory=list)
    properties: dict[str, str] = field(default_factory=dict)

    def summary_context(self) -> str:
        """Build a single-line summary from all context fields.

        Returns:
            Pipe-delimited summary string.
        """
        parts = []
        if self.description:
            parts.append(self.description)
        if self.tags:
            parts.append(f"Tags: {', '.join(self.tags)}")
        if self.properties:
            props = ", ".join(f"{k}: {v}" for k, v in list(self.properties.items())[:5])
            parts.append(f"Properties: {props}")
        return " | ".join(parts)

    def search_keywords(self) -> list[str]:
        """Extract keywords suitable for FTS boosting.

        Returns:
            List of keyword strings from tags and property keys.
        """
        kw = list(self.tags)
        kw.extend(self.properties.keys())
        return kw


@runtime_checkable
class ContextProviderProtocol(Protocol):
    """Contract: what an ecosystem context provider must implement."""

    @property
    def name(self) -> str:
        """Provider name.

        Returns:
            Short identifier for this provider.
        """
        ...

    def detect(self, folder_path: Path) -> bool:
        """Check if this provider is relevant for the given folder.

        Args:
            folder_path: Root directory to inspect.

        Returns:
            ``True`` if this provider applies to the folder.
        """
        ...

    def load(self, folder_path: Path) -> None:
        """Load metadata from the folder.

        Args:
            folder_path: Root directory to load metadata from.
        """
        ...

    def get_file_context(self, file_path: str) -> FileContext | None:
        """Get context for a specific file.

        Args:
            file_path: Relative file path within the project.

        Returns:
            A :class:`FileContext` if metadata is available, else ``None``.
        """
        ...

    def stats(self) -> dict:
        """Return provider statistics.

        Returns:
            Dictionary of metric name to value.
        """
        ...


class ContextProvider:
    """Base class for ecosystem context providers.

    Subclasses implement ``name``, ``detect()``, ``load()``,
    ``get_file_context()``, and ``stats()``.  This base provides
    ``get_metadata()`` with a default empty-dict implementation.
    """

    @property
    def name(self) -> str:
        """Provider name.

        Returns:
            Short identifier for this provider.
        """
        raise NotImplementedError

    def detect(self, folder_path: Path) -> bool:
        """Check if this provider is relevant for the given folder.

        Args:
            folder_path: Root directory to inspect.

        Returns:
            ``True`` if this provider applies to the folder.
        """
        raise NotImplementedError

    def load(self, folder_path: Path) -> None:
        """Load metadata from the folder.

        Args:
            folder_path: Root directory to load metadata from.
        """
        raise NotImplementedError

    def get_file_context(self, file_path: str) -> FileContext | None:
        """Get context for a specific file.

        Args:
            file_path: Relative file path within the project.

        Returns:
            A :class:`FileContext` if metadata is available, else ``None``.
        """
        raise NotImplementedError

    def stats(self) -> dict:
        """Return provider statistics.

        Returns:
            Dictionary of metric name to value.
        """
        raise NotImplementedError

    def get_metadata(self) -> dict:
        """Return structured metadata (optional override).

        Returns:
            Dictionary of provider-specific metadata.
        """
        return {}


_PROVIDER_CLASSES: list[type[ContextProvider]] = []


def register_provider(cls: type[ContextProvider]) -> type[ContextProvider]:
    """Decorator to register a context provider class.

    Args:
        cls: The :class:`ContextProvider` subclass to register.

    Returns:
        The same class, unmodified.
    """
    _PROVIDER_CLASSES.append(cls)
    return cls


def discover_providers(folder_path: Path) -> list[ContextProvider]:
    """Discover and initialize applicable context providers for a folder.

    Args:
        folder_path: Root directory to inspect for ecosystem markers.

    Returns:
        List of loaded provider instances that apply to the folder.
    """
    providers = []
    for cls in _PROVIDER_CLASSES:
        try:
            instance = cls()
            if instance.detect(folder_path):
                instance.load(folder_path)
                providers.append(instance)
        except Exception as exc:
            logger.debug("context_provider_load_failed", error=str(exc))
    return providers


def enrich_symbols(symbols: list, providers: list[ContextProvider]) -> None:
    """Enrich symbols with ecosystem context from providers.

    Appends additional keywords to each symbol's keyword list based on
    file-level context from the providers.

    Args:
        symbols: List of symbol objects (with ``file_path`` / ``file`` and
            ``keywords`` attributes).
        providers: List of active context providers.
    """
    for sym in symbols:
        file_path = getattr(sym, "file_path", "") or getattr(sym, "file", "")
        if not file_path:
            continue

        for provider in providers:
            ctx = provider.get_file_context(file_path)
            if ctx:
                existing_kw = getattr(sym, "keywords", []) or []
                existing_kw.extend(ctx.search_keywords())
                sym.keywords = existing_kw
