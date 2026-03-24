"""MCP tools: configure_* -- per-editor setup to unlock the workflow gate."""

import json
from pathlib import Path

from sylvan.tools.support.response import MetaBuilder, log_tool_call, wrap_response


def _unlock_gate() -> None:
    """Mark the workflow gate as loaded."""
    from sylvan.session.tracker import get_session
    get_session()._workflow_loaded = True


def _get_workflow_rules() -> list[dict]:
    """Return the standard workflow rules for all editors."""
    return [
        {
            "rule": "ALWAYS search before reading",
            "detail": (
                "Use search_symbols or search_sections instead of Read/Grep/Glob. "
                "Sylvan returns only the exact code you need."
            ),
        },
        {
            "rule": "Use get_symbol instead of Read for source code",
            "detail": (
                "get_symbol returns exact function/class source by ID. "
                "Responses include _hints.edit with read_offset and read_limit."
            ),
        },
        {
            "rule": "Index before exploring",
            "detail": (
                "Call index_folder once per project. Re-run after code changes. "
                "Incremental reindex only processes changed files."
            ),
        },
        {
            "rule": "add_library before using third-party packages",
            "detail": (
                "Index library source code with add_library, then search_symbols "
                "to find the real API instead of guessing."
            ),
        },
        {
            "rule": "Use blast_radius before refactoring",
            "detail": (
                "Call get_blast_radius before renaming or changing signatures. "
                "Shows every file that would be affected."
            ),
        },
    ]


@log_tool_call
async def configure_claude_code(project_path: str) -> dict:
    """Configure Claude Code to use sylvan tools.

    Creates or updates .claude/settings.local.json with the mcp__sylvan__*
    permission and a SubagentStart hook that injects sylvan tool instructions
    into all subagents.

    Args:
        project_path: Absolute path to the user's project directory.

    Returns:
        Tool response with created/updated config and workflow rules.
    """
    meta = MetaBuilder()
    project_dir = Path(project_path)
    settings_path = project_dir / ".claude" / "settings.local.json"

    permission = "mcp__sylvan__*"
    subagent_hook = {
        "type": "command",
        "command": (
            "echo '{\"hookSpecificOutput\":{\"hookEventName\":\"SubagentStart\","
            "\"additionalContext\":\"CRITICAL: Always try mcp__sylvan__* tools FIRST "
            "before falling back to Read/Grep/Glob. "
            "mcp__sylvan__search_symbols to find code, "
            "mcp__sylvan__get_symbol to read source, "
            "mcp__sylvan__get_file_outline to understand files, "
            "mcp__sylvan__find_importers for dependencies, "
            "mcp__sylvan__get_blast_radius before refactoring. "
            "These return only the exact code you need and save 90%+ tokens. "
            "Only fall back to Read/Grep if the repo is not indexed or sylvan "
            "returns no results.\"}}'"
        ),
        "timeout": 5,
    }
    reindex_hook = {
        "type": "command",
        "command": (
            "echo '{\"hookSpecificOutput\":{\"hookEventName\":\"PostToolUse\","
            "\"additionalContext\":\"You just edited a file. Run "
            "mcp__sylvan__index_file to update the index so search results "
            "stay fresh. Pass the repo name and the relative file path.\"}}'"
        ),
        "timeout": 5,
    }

    settings: dict = {}
    if settings_path.exists():
        try:
            settings = json.loads(settings_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            settings = {}

    # Ensure permission
    allows = settings.setdefault("permissions", {}).setdefault("allow", [])
    if permission not in allows:
        allows.append(permission)

    hooks = settings.setdefault("hooks", {})

    # Ensure SubagentStart hook
    subagent_hooks = hooks.setdefault("SubagentStart", [])
    has_subagent = any(
        "mcp__sylvan__" in h.get("command", "")
        for entry in subagent_hooks
        for h in entry.get("hooks", [])
    )
    if not has_subagent:
        subagent_hooks.append({"matcher": "*", "hooks": [subagent_hook]})

    # Ensure PostToolUse hook for Edit/Write reindex reminders
    post_hooks = hooks.setdefault("PostToolUse", [])
    has_reindex = any(
        "index_file" in h.get("command", "")
        for entry in post_hooks
        for h in entry.get("hooks", [])
    )
    if not has_reindex:
        post_hooks.append({"matcher": "Edit|Write", "hooks": [reindex_hook]})

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")

    _unlock_gate()

    return wrap_response({
        "editor": "claude_code",
        "configured": True,
        "path": str(settings_path),
        "rules": _get_workflow_rules(),
    }, meta.build())


@log_tool_call
async def configure_cursor(project_path: str) -> dict:
    """Configure Cursor to use sylvan tools.

    Creates .cursor/rules/sylvan.md with tool usage instructions so
    Cursor's agent knows to prefer sylvan tools over file reads.

    Args:
        project_path: Absolute path to the user's project directory.

    Returns:
        Tool response with created config and workflow rules.
    """
    meta = MetaBuilder()
    project_dir = Path(project_path)
    rules_path = project_dir / ".cursor" / "rules" / "sylvan.md"

    rules_content = _build_rules_markdown()

    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(rules_content, encoding="utf-8")

    _unlock_gate()

    return wrap_response({
        "editor": "cursor",
        "configured": True,
        "path": str(rules_path),
        "rules": _get_workflow_rules(),
    }, meta.build())


@log_tool_call
async def configure_windsurf(project_path: str) -> dict:
    """Configure Windsurf to use sylvan tools.

    Creates .windsurf/rules/sylvan.md with tool usage instructions.

    Args:
        project_path: Absolute path to the user's project directory.

    Returns:
        Tool response with created config and workflow rules.
    """
    meta = MetaBuilder()
    project_dir = Path(project_path)
    rules_path = project_dir / ".windsurf" / "rules" / "sylvan.md"

    rules_content = _build_rules_markdown()

    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(rules_content, encoding="utf-8")

    _unlock_gate()

    return wrap_response({
        "editor": "windsurf",
        "configured": True,
        "path": str(rules_path),
        "rules": _get_workflow_rules(),
    }, meta.build())


@log_tool_call
async def configure_copilot(project_path: str) -> dict:
    """Configure GitHub Copilot to use sylvan tools.

    Creates .github/copilot-instructions.md with tool routing rules
    so Copilot's agent prefers sylvan tools over file reads.

    Args:
        project_path: Absolute path to the user's project directory.

    Returns:
        Tool response with created config and workflow rules.
    """
    meta = MetaBuilder()
    project_dir = Path(project_path)
    instructions_path = project_dir / ".github" / "copilot-instructions.md"

    rules_content = _build_rules_markdown()

    instructions_path.parent.mkdir(parents=True, exist_ok=True)
    instructions_path.write_text(rules_content, encoding="utf-8")

    _unlock_gate()

    return wrap_response({
        "editor": "copilot",
        "configured": True,
        "path": str(instructions_path),
        "rules": _get_workflow_rules(),
    }, meta.build())


def _build_rules_markdown() -> str:
    """Build a markdown document with sylvan tool usage rules."""
    return """\
# Sylvan - Code Intelligence MCP Tools

Always prefer sylvan MCP tools over reading files directly. Sylvan returns
only the exact code you need, saving 90%+ tokens.

## Tool Priority

| Instead of | Use |
|---|---|
| Read/cat a file | `get_symbol` (returns exact function source) |
| Grep/search | `search_symbols` (ranked, signature-level) |
| Read for structure | `get_file_outline` (all symbols with signatures) |
| Grep for imports | `find_importers` (resolved import graph) |

## Workflow

1. `index_folder` - index the project (run once, re-run after edits)
2. `search_symbols` - find code by name or keyword
3. `get_symbol` - read exact source by ID
4. `get_blast_radius` - check impact before refactoring
5. `find_importers` - find who uses a file/module

## Libraries

Before using a third-party package, index it first:
```
add_library(package="npm/htmx.org@2.0.8")
search_symbols(query="morph swap", repo="htmx.org@2.0.8")
```

## After Editing Files

IMPORTANT: After every Edit or Write operation, call `index_file` with the
repo name and relative file path to update the index. Stale indexes cause
search to miss your recent changes. This is the single most common mistake.

## Tips

- Every response includes `_hints.edit` with exact Read parameters for editing
- Every response includes `_hints.next` with follow-up tool calls
- Use `get_file_outline` before reading any file
- Use `add_library` before integrating any third-party package
- Use `get_blast_radius` before renaming or deleting anything
"""
