"""Claude Code provider -- uses Claude Agent SDK for summaries."""

import asyncio
from typing import override

from sylvan.providers.base import SUMMARY_SYSTEM_PROMPT, SummaryProvider
from sylvan.providers.registry import register_summary_provider


@register_summary_provider("claude-code")
class ClaudeCodeSummaryProvider(SummaryProvider):
    """Generate summaries using the Claude Agent SDK.

    Uses claude-haiku for speed/cost.  Sessions are ephemeral
    (``--no-session-persistence``) -- won't clutter user's history.
    """

    name = "claude-code"

    def __init__(self, model: str = "claude-haiku-4-5-20251001") -> None:
        """Initialize with the target model identifier.

        Args:
            model: Claude model ID to use for summary generation.
        """
        self._model = model

    @override
    def available(self) -> bool:
        """Check whether the Claude Agent SDK is importable.

        Returns:
            ``True`` if ``claude_agent_sdk`` is installed.
        """
        try:
            from claude_agent_sdk import ClaudeAgentOptions, query
            return True
        except ImportError:
            return False

    @override
    def _generate_summary(self, prompt: str) -> str:
        """Run summary generation via the Agent SDK (async internally).

        Args:
            prompt: Formatted summary prompt.

        Returns:
            Summary text (up to 120 characters).
        """
        try:
            return asyncio.run(self._async_generate(prompt))
        except RuntimeError:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, self._async_generate(prompt)).result(timeout=30)

    async def _async_generate(self, prompt: str) -> str:
        """Async implementation of summary generation.

        Args:
            prompt: Formatted summary prompt.

        Returns:
            Summary text (up to 120 characters).
        """
        from claude_agent_sdk import ClaudeAgentOptions, query

        response_text = ""
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                allowed_tools=[],
                model=self._model,
                max_turns=1,
                system_prompt=SUMMARY_SYSTEM_PROMPT,
                extra_args={"no-session-persistence": None},
            ),
        ):
            if hasattr(message, "result") and message.result:
                response_text = message.result.strip()
            elif hasattr(message, "content"):
                for block in getattr(message, "content", []):
                    if hasattr(block, "text"):
                        response_text = block.text.strip()

        return response_text[:120]
