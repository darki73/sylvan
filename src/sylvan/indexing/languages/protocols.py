"""Capability protocols for language plugins.

Each protocol represents an optional capability that a language can provide.
Languages implement only the protocols they support - a language with just a
tree-sitter spec needs none of these.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    import re


@runtime_checkable
class ImportExtractor(Protocol):
    """Extract import statements from source code."""

    def extract_imports(self, content: str) -> list[dict]:
        """Parse import statements and return structured results.

        Args:
            content: Source file content.

        Returns:
            List of dicts with ``specifier`` and ``names`` keys.
        """
        ...


@runtime_checkable
class ImportResolver(Protocol):
    """Generate candidate file paths for import specifiers."""

    def generate_candidates(
        self,
        specifier: str,
        source_path: str,
        context: ResolverContext,
    ) -> list[str]:
        """Convert an import specifier to candidate file paths.

        Args:
            specifier: Raw import specifier (e.g. ``App\\Models\\User``).
            source_path: Relative path of the importing file.
            context: Repo-scoped resolution state (PSR-4 mappings, tsconfig aliases, etc.).

        Returns:
            Ordered list of candidate file paths to try matching.
        """
        ...


@runtime_checkable
class ComplexityProvider(Protocol):
    """Provide language-specific complexity analysis patterns."""

    decision_pattern: re.Pattern[str]
    uses_braces: bool

    def strip_receiver(self, params_str: str) -> str:
        """Strip language-specific self/this/cls receivers from a parameter string.

        Args:
            params_str: Raw parameter string.

        Returns:
            Parameter string with receiver stripped.
        """
        ...


@dataclass
class ResolverContext:
    """Repo-scoped state passed to import resolution plugins.

    Populated by the orchestrator before resolution runs and passed through
    to each language plugin's ``generate_candidates`` method.

    Attributes:
        psr4_mappings: PHP PSR-4 namespace prefix to directory list mapping.
        tsconfig_aliases: TypeScript path alias to directory list mapping.
    """

    psr4_mappings: dict[str, list[str]] = field(default_factory=dict)
    tsconfig_aliases: dict[str, list[str]] = field(default_factory=dict)
