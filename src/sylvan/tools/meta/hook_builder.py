"""Builder for Claude Code / editor hook definitions with proper JSON serialization."""

from __future__ import annotations

import json


class Hook:
    """Builds an editor hook definition with properly escaped JSON output."""

    def __init__(self, event: str, timeout: int = 5):
        self.event = event
        self.timeout = timeout
        self._context_parts: list[str] = []

    def context(self, text: str) -> Hook:
        """Append a context fragment to the hook output."""
        self._context_parts.append(text)
        return self

    def to_dict(self) -> dict:
        """Build the hook dict using bash echo.

        Claude Code always uses bash (Git Bash on Windows), so we use
        POSIX-style commands on all platforms.
        """
        additional_context = " ".join(self._context_parts)
        payload = {
            "hookSpecificOutput": {
                "hookEventName": self.event,
                "additionalContext": additional_context,
            }
        }

        json_str = json.dumps(payload)
        escaped = json_str.replace("'", "'\\''")
        command = f"echo '{escaped}'"

        return {
            "type": "command",
            "command": command,
            "timeout": self.timeout,
        }


class TimeHook:
    """Prompt-submit hook that injects the current timestamp using native shell commands."""

    def __init__(self, event: str = "UserPromptSubmit", timeout: int = 5):
        self.event = event
        self.timeout = timeout

    def to_dict(self) -> dict:
        """Build a hook using bash date command.

        Claude Code always uses bash (Git Bash on Windows), so we use
        POSIX-style commands on all platforms.
        """
        event = self.event
        command = (
            'echo "{\\"hookSpecificOutput\\":{\\"hookEventName\\":\\"' + event + '\\",'
            '\\"additionalContext\\":\\"Current date and time: '
            "$(date '+%Y-%m-%d %H:%M:%S (%Z)')"
            '\\"}}"'
        )
        return {
            "type": "command",
            "command": command,
            "timeout": self.timeout,
        }


# Editor-specific event names for prompt submission
PROMPT_SUBMIT_EVENTS = {
    "claude_code": "UserPromptSubmit",
    "cursor": "beforeSubmitPrompt",
    "windsurf": "pre_user_prompt",
    "copilot": "UserPromptSubmit",
}


SUBAGENT_HOOK = (
    Hook("SubagentStart")
    .context("CRITICAL: Always try mcp__sylvan__* tools FIRST before falling back to Read/Grep/Glob.")
    .context("mcp__sylvan__find_code to find code,")
    .context("mcp__sylvan__read_symbol to read source,")
    .context("mcp__sylvan__whats_in_file to understand files,")
    .context("mcp__sylvan__who_depends_on_this for dependencies,")
    .context("mcp__sylvan__what_breaks_if_i_change before refactoring.")
    .context("These return only the exact code you need and save 90%+ tokens.")
    .context("Only fall back to Read/Grep if the repo is not indexed or sylvan returns no results.")
)

POST_TOOL_HOOK = (
    Hook("PostToolUse")
    .context("You just edited a file.")
    .context("Run mcp__sylvan__reindex_file to update the index so search results stay fresh.")
    .context("Pass the repo name and the relative file path.")
)


def time_hook_for(editor: str) -> TimeHook:
    """Create a TimeHook with the correct event name for the given editor."""
    event = PROMPT_SUBMIT_EVENTS.get(editor, "UserPromptSubmit")
    return TimeHook(event=event)
