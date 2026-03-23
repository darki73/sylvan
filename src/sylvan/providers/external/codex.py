"""Codex CLI provider -- uses OpenAI's CLI for summaries."""

import shutil
import subprocess
from typing import override

from sylvan.providers.base import SummaryProvider
from sylvan.providers.registry import register_summary_provider


@register_summary_provider("codex")
class CodexSummaryProvider(SummaryProvider):
    """Generate summaries using OpenAI's Codex CLI.

    Uses the user's existing ChatGPT subscription -- no extra cost.
    """

    name = "codex"

    @override
    def available(self) -> bool:
        """Check whether the ``codex`` CLI is on ``PATH``.

        Returns:
            ``True`` if ``codex`` is found.
        """
        return shutil.which("codex") is not None

    @override
    def _generate_summary(self, prompt: str) -> str:
        """Generate a summary by invoking the Codex CLI.

        Args:
            prompt: Formatted summary prompt (truncated to 800 chars).

        Returns:
            Summary text (up to 120 characters), or empty string on failure.
        """
        result = subprocess.run(
            ["codex", "--quiet", "--approval-mode", "full-auto", prompt[:800]],
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()[:120]
        return ""
