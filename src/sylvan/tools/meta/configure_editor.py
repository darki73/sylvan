"""MCP tools: configure_* - per-editor setup to unlock the workflow gate."""

from pathlib import Path

from sylvan.tools.meta.editor_setup import (
    EditorKind,
    SetupAction,
    _build_rules_markdown,
    _claude_code_settings_content,
    check_setup,
)
from sylvan.tools.support.response import get_meta, log_tool_call, wrap_response


def _unlock_gate() -> None:
    """Clear setup actions and mark setup as checked."""
    from sylvan.session.tracker import get_session

    session = get_session()
    session._setup_actions = []
    session._setup_checked = True


def _with_update_check(func):
    """Decorator that injects update_available into tool responses."""
    import functools

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        result = await func(*args, **kwargs)
        if isinstance(result, dict):
            from sylvan.server.startup import get_update_info

            update = get_update_info()
            if update:
                result["update_available"] = update
        return result

    return wrapper


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
                "Call get_blast_radius before renaming or changing signatures. Shows every file that would be affected."
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


def _actions_to_dicts(actions: list[SetupAction]) -> list[dict]:
    """Convert SetupAction list to serializable dicts."""
    return [{"action": a.action, "path": a.path, "detail": a.detail} for a in actions]


@_with_update_check
@log_tool_call
async def configure_claude_code(project_path: str) -> dict:
    """Configure Claude Code to use sylvan tools.

    Checks current setup state, unlocks the workflow gate, and returns
    instructions if configuration is needed.

    Args:
        project_path: Absolute path to the user's project directory.

    Returns:
        Tool response with config content and workflow rules.
    """
    meta = get_meta()
    project_dir = Path(project_path)
    settings_path = project_dir / ".claude" / "settings.local.json"
    actions = check_setup(EditorKind.CLAUDE_CODE, project_dir)

    _unlock_gate()

    if not actions:
        return wrap_response(
            {
                "editor": "claude_code",
                "configured": True,
                "path": str(settings_path),
                "rules": _get_workflow_rules(),
            },
            meta.build(),
        )

    return wrap_response(
        {
            "editor": "claude_code",
            "configured": False,
            "path": str(settings_path),
            "setup_actions": _actions_to_dicts(actions),
            "instructions": (
                "Add the following to .claude/settings.local.json. "
                "Merge with existing content if the file already exists. "
                "Create .claude/ directory if it does not exist."
            ),
            "content": _claude_code_settings_content(),
            "rules": _get_workflow_rules(),
        },
        meta.build(),
    )


@_with_update_check
@log_tool_call
async def configure_cursor(project_path: str) -> dict:
    """Configure Cursor to use sylvan tools.

    Checks current setup state, unlocks the workflow gate, and returns
    instructions if configuration is needed.

    Args:
        project_path: Absolute path to the user's project directory.

    Returns:
        Tool response with config content and workflow rules.
    """
    meta = get_meta()
    project_dir = Path(project_path)
    rules_path = project_dir / ".cursor" / "rules" / "sylvan.md"
    actions = check_setup(EditorKind.CURSOR, project_dir)

    _unlock_gate()

    if not actions:
        return wrap_response(
            {
                "editor": "cursor",
                "configured": True,
                "path": str(rules_path),
                "rules": _get_workflow_rules(),
            },
            meta.build(),
        )

    return wrap_response(
        {
            "editor": "cursor",
            "configured": False,
            "path": str(rules_path),
            "setup_actions": _actions_to_dicts(actions),
            "instructions": (
                "Create .cursor/rules/sylvan.md with the content below. Create the directories if they do not exist."
            ),
            "content": _build_rules_markdown(),
            "rules": _get_workflow_rules(),
        },
        meta.build(),
    )


@_with_update_check
@log_tool_call
async def configure_windsurf(project_path: str) -> dict:
    """Configure Windsurf to use sylvan tools.

    Checks current setup state, unlocks the workflow gate, and returns
    instructions if configuration is needed.

    Args:
        project_path: Absolute path to the user's project directory.

    Returns:
        Tool response with config content and workflow rules.
    """
    meta = get_meta()
    project_dir = Path(project_path)
    rules_path = project_dir / ".windsurf" / "rules" / "sylvan.md"
    actions = check_setup(EditorKind.WINDSURF, project_dir)

    _unlock_gate()

    if not actions:
        return wrap_response(
            {
                "editor": "windsurf",
                "configured": True,
                "path": str(rules_path),
                "rules": _get_workflow_rules(),
            },
            meta.build(),
        )

    return wrap_response(
        {
            "editor": "windsurf",
            "configured": False,
            "path": str(rules_path),
            "setup_actions": _actions_to_dicts(actions),
            "instructions": (
                "Create .windsurf/rules/sylvan.md with the content below. Create the directories if they do not exist."
            ),
            "content": _build_rules_markdown(),
            "rules": _get_workflow_rules(),
        },
        meta.build(),
    )


@_with_update_check
@log_tool_call
async def configure_copilot(project_path: str) -> dict:
    """Configure GitHub Copilot to use sylvan tools.

    Checks current setup state, unlocks the workflow gate, and returns
    instructions if configuration is needed.

    Args:
        project_path: Absolute path to the user's project directory.

    Returns:
        Tool response with config content and workflow rules.
    """
    meta = get_meta()
    project_dir = Path(project_path)
    instructions_path = project_dir / ".github" / "copilot-instructions.md"
    actions = check_setup(EditorKind.COPILOT, project_dir)

    _unlock_gate()

    if not actions:
        return wrap_response(
            {
                "editor": "copilot",
                "configured": True,
                "path": str(instructions_path),
                "rules": _get_workflow_rules(),
            },
            meta.build(),
        )

    return wrap_response(
        {
            "editor": "copilot",
            "configured": False,
            "path": str(instructions_path),
            "setup_actions": _actions_to_dicts(actions),
            "instructions": (
                "Create .github/copilot-instructions.md with the content below. "
                "Create the .github/ directory if it does not exist."
            ),
            "content": _build_rules_markdown(),
            "rules": _get_workflow_rules(),
        },
        meta.build(),
    )
