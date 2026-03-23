"""Heuristic summary provider -- free, always available, no AI needed."""

import re
from typing import override

from sylvan.providers.base import SummaryProvider, _first_sentence
from sylvan.providers.registry import register_summary_provider


@register_summary_provider("heuristic")
class HeuristicSummaryProvider(SummaryProvider):
    """Extract summaries from docstrings, signatures, and code structure.

    Default provider.  No API keys, no network, no AI models.
    """

    name = "heuristic"

    @override
    def available(self) -> bool:
        """Check provider availability.

        Returns:
            Always ``True``.
        """
        return True

    @override
    def _generate_summary(self, prompt: str) -> str:
        """Extract summary heuristically from the prompt content.

        Args:
            prompt: Formatted summary prompt containing signature, docstring,
                and source.

        Returns:
            Extracted summary string.
        """
        lines = prompt.split("\n")
        docstring = ""
        signature = ""

        for line in lines:
            if line.startswith("Docstring: "):
                docstring = line[11:].strip()
            elif line.startswith("Signature: "):
                signature = line[11:].strip()

        if docstring:
            return _first_sentence(docstring)
        if signature:
            return signature[:120]

        # Fallback: first meaningful line from source
        in_source = False
        for line in lines:
            if line.startswith("Source:"):
                in_source = True
                continue
            if in_source:
                stripped = line.strip()
                if stripped and not stripped.startswith(("#", "//", "/*", "@", "import", "from")):
                    return stripped[:120]

        return ""

    @override
    def summarize_section(self, title: str, content: str) -> str:
        """Extract a summary from section content using heuristics.

        Strips markdown formatting before extracting the first sentence.

        Args:
            title: Section heading text.
            content: Section body text.

        Returns:
            A summary string (up to 150 characters).
        """
        if not content or not content.strip():
            return title[:150]

        # Strip markdown formatting for cleaner summary
        clean = content.strip()
        # Remove code blocks
        clean = re.sub(r"```[\s\S]*?```", "", clean)
        # Remove inline code
        clean = re.sub(r"`[^`]+`", "", clean)
        # Remove markdown links, keep text
        clean = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", clean)
        # Remove heading markers
        clean = re.sub(r"^#+\s*", "", clean, flags=re.MULTILINE)
        # Remove markdown tables
        clean = re.sub(r"^\|.*\|$", "", clean, flags=re.MULTILINE)
        # Remove list markers
        clean = re.sub(r"^[\s]*[-*+]\s+", "", clean, flags=re.MULTILINE)

        return _first_sentence(clean.strip())[:150] or title[:150]
