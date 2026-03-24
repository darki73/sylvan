"""MCP tools: configure_* -- per-editor setup to unlock the workflow gate."""

import json
from pathlib import Path

from sylvan.tools.support.response import MetaBuilder, log_tool_call, wrap_response


def _unlock_gate() -> None:
    """Mark the workflow gate as loaded."""
    from sylvan.session.tracker import get_session
    get_session()._workflow_loaded = True


def _auto_configure_enabled() -> bool:
    """Check if auto_configure is enabled in server config."""
    from sylvan.config import get_config
    return get_config().server.auto_configure


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
        {
            "rule": "Reindex after edits",
            "detail": (
                "After editing files, call index_file with the repo name and "
                "relative file path. Stale indexes miss recent changes."
            ),
        },
    ]


def _claude_code_settings_content() -> dict:
    """Build the full settings.local.json content for Claude Code."""
    return {
        "permissions": {"allow": ["mcp__sylvan__*"]},
        "hooks": {
            "SubagentStart": [{
                "matcher": "*",
                "hooks": [{
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
                }],
            }],
            "PostToolUse": [{
                "matcher": "Edit|Write",
                "hooks": [{
                    "type": "command",
                    "command": (
                        "echo '{\"hookSpecificOutput\":{\"hookEventName\":\"PostToolUse\","
                        "\"additionalContext\":\"You just edited a file. Run "
                        "mcp__sylvan__index_file to update the index so search results "
                        "stay fresh. Pass the repo name and the relative file path.\"}}'"
                    ),
                    "timeout": 5,
                }],
            }],
        },
    }


@log_tool_call
async def configure_claude_code(project_path: str) -> dict:
    """Configure Claude Code to use sylvan tools.

    When auto_configure is enabled in config, directly writes
    .claude/settings.local.json. Otherwise returns instructions
    for the agent to apply the changes.

    Args:
        project_path: Absolute path to the user's project directory.

    Returns:
        Tool response with config content and workflow rules.
    """
    meta = MetaBuilder()
    project_dir = Path(project_path)
    settings_path = project_dir / ".claude" / "settings.local.json"
    settings_content = _claude_code_settings_content()

    if _auto_configure_enabled():
        # Merge into existing settings
        existing: dict = {}
        if settings_path.exists():
            try:
                existing = json.loads(settings_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                existing = {}

        allows = existing.setdefault("permissions", {}).setdefault("allow", [])
        if "mcp__sylvan__*" not in allows:
            allows.append("mcp__sylvan__*")

        hooks = existing.setdefault("hooks", {})
        for hook_type, hook_entries in settings_content["hooks"].items():
            existing_hooks = hooks.setdefault(hook_type, [])
            has_sylvan = any(
                "sylvan" in h.get("command", "")
                for entry in existing_hooks
                for h in entry.get("hooks", [])
            )
            if not has_sylvan:
                existing_hooks.extend(hook_entries)

        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")

        _unlock_gate()
        return wrap_response({
            "editor": "claude_code",
            "configured": True,
            "auto_written": True,
            "path": str(settings_path),
            "rules": _get_workflow_rules(),
        }, meta.build())

    # Default: return instructions for the agent to apply
    _unlock_gate()
    return wrap_response({
        "editor": "claude_code",
        "configured": False,
        "auto_written": False,
        "path": str(settings_path),
        "instructions": (
            "Add the following to .claude/settings.local.json. "
            "Merge with existing content if the file already exists. "
            "Create .claude/ directory if it does not exist."
        ),
        "content": settings_content,
        "rules": _get_workflow_rules(),
    }, meta.build())


@log_tool_call
async def configure_cursor(project_path: str) -> dict:
    """Configure Cursor to use sylvan tools.

    When auto_configure is enabled, writes .cursor/rules/sylvan.md
    directly. Otherwise returns the content for the agent to write.

    Args:
        project_path: Absolute path to the user's project directory.

    Returns:
        Tool response with config content and workflow rules.
    """
    meta = MetaBuilder()
    project_dir = Path(project_path)
    rules_path = project_dir / ".cursor" / "rules" / "sylvan.md"
    rules_content = _build_rules_markdown()

    if _auto_configure_enabled():
        rules_path.parent.mkdir(parents=True, exist_ok=True)
        rules_path.write_text(rules_content, encoding="utf-8")
        _unlock_gate()
        return wrap_response({
            "editor": "cursor",
            "configured": True,
            "auto_written": True,
            "path": str(rules_path),
            "rules": _get_workflow_rules(),
        }, meta.build())

    _unlock_gate()
    return wrap_response({
        "editor": "cursor",
        "configured": False,
        "auto_written": False,
        "path": str(rules_path),
        "instructions": (
            "Create .cursor/rules/sylvan.md with the content below. "
            "Create the directories if they do not exist."
        ),
        "content": rules_content,
        "rules": _get_workflow_rules(),
    }, meta.build())


@log_tool_call
async def configure_windsurf(project_path: str) -> dict:
    """Configure Windsurf to use sylvan tools.

    When auto_configure is enabled, writes .windsurf/rules/sylvan.md
    directly. Otherwise returns the content for the agent to write.

    Args:
        project_path: Absolute path to the user's project directory.

    Returns:
        Tool response with config content and workflow rules.
    """
    meta = MetaBuilder()
    project_dir = Path(project_path)
    rules_path = project_dir / ".windsurf" / "rules" / "sylvan.md"
    rules_content = _build_rules_markdown()

    if _auto_configure_enabled():
        rules_path.parent.mkdir(parents=True, exist_ok=True)
        rules_path.write_text(rules_content, encoding="utf-8")
        _unlock_gate()
        return wrap_response({
            "editor": "windsurf",
            "configured": True,
            "auto_written": True,
            "path": str(rules_path),
            "rules": _get_workflow_rules(),
        }, meta.build())

    _unlock_gate()
    return wrap_response({
        "editor": "windsurf",
        "configured": False,
        "auto_written": False,
        "path": str(rules_path),
        "instructions": (
            "Create .windsurf/rules/sylvan.md with the content below. "
            "Create the directories if they do not exist."
        ),
        "content": rules_content,
        "rules": _get_workflow_rules(),
    }, meta.build())


@log_tool_call
async def configure_copilot(project_path: str) -> dict:
    """Configure GitHub Copilot to use sylvan tools.

    When auto_configure is enabled, writes .github/copilot-instructions.md
    directly. Otherwise returns the content for the agent to write.

    Args:
        project_path: Absolute path to the user's project directory.

    Returns:
        Tool response with config content and workflow rules.
    """
    meta = MetaBuilder()
    project_dir = Path(project_path)
    instructions_path = project_dir / ".github" / "copilot-instructions.md"
    rules_content = _build_rules_markdown()

    if _auto_configure_enabled():
        instructions_path.parent.mkdir(parents=True, exist_ok=True)
        instructions_path.write_text(rules_content, encoding="utf-8")
        _unlock_gate()
        return wrap_response({
            "editor": "copilot",
            "configured": True,
            "auto_written": True,
            "path": str(instructions_path),
            "rules": _get_workflow_rules(),
        }, meta.build())

    _unlock_gate()
    return wrap_response({
        "editor": "copilot",
        "configured": False,
        "auto_written": False,
        "path": str(instructions_path),
        "instructions": (
            "Create .github/copilot-instructions.md with the content below. "
            "Create the .github/ directory if it does not exist."
        ),
        "content": rules_content,
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
