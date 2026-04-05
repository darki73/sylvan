"""MCP tools: configure_* -- per-editor setup to unlock the workflow gate."""

from pathlib import Path

from sylvan.tools.base import HasProjectPath, Tool, ToolParams
from sylvan.tools.meta.editor_setup import (
    EditorKind,
    SetupAction,
    _build_rules_markdown,
    _claude_code_settings_content,
    check_setup,
)


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
                "Use find_code or find_docs instead of Read/Grep/Glob. Sylvan returns only the exact code you need."
            ),
        },
        {
            "rule": "Use read_symbol instead of Read for source code",
            "detail": (
                "read_symbol returns exact function/class source by ID. "
                "Responses include _hints.edit with read_offset and read_limit."
            ),
        },
        {
            "rule": "Index before exploring",
            "detail": (
                "Call index_project once per project. Re-run after code changes. "
                "Incremental reindex only processes changed files."
            ),
        },
        {
            "rule": "index_library_source before using third-party packages",
            "detail": (
                "Index library source code with index_library_source, then find_code "
                "to find the real API instead of guessing."
            ),
        },
        {
            "rule": "Check impact before refactoring",
            "detail": (
                "Call what_breaks_if_i_change before renaming or changing signatures. Shows every file that would be affected."
            ),
        },
        {
            "rule": "Reindex after edits",
            "detail": (
                "After editing files, call reindex_file with the repo name and "
                "relative file path. Stale indexes miss recent changes."
            ),
        },
    ]


def _actions_to_dicts(actions: list[SetupAction]) -> list[dict]:
    """Convert SetupAction list to serializable dicts."""
    return [{"action": a.action, "path": a.path, "detail": a.detail} for a in actions]


class ConfigureClaudeCode(Tool):
    name = "setup_claude_code"
    category = "meta"
    description = (
        "Creates or updates .claude/settings.local.json with sylvan tool "
        "permissions and SubagentStart hook for this project."
    )

    class Params(HasProjectPath, ToolParams):
        pass

    async def handle(self, p: Params) -> dict:
        project_dir = Path(p.project_path)
        settings_path = project_dir / ".claude" / "settings.local.json"
        actions = check_setup(EditorKind.CLAUDE_CODE, project_dir)
        _unlock_gate()

        if not actions:
            return {
                "editor": "claude_code",
                "configured": True,
                "path": str(settings_path),
                "rules": _get_workflow_rules(),
            }

        return {
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
        }


class ConfigureCursor(Tool):
    name = "setup_cursor"
    category = "meta"
    description = "Creates .cursor/rules/sylvan.md with tool routing rules for this project."

    class Params(HasProjectPath, ToolParams):
        pass

    async def handle(self, p: Params) -> dict:
        project_dir = Path(p.project_path)
        rules_path = project_dir / ".cursor" / "rules" / "sylvan.md"
        actions = check_setup(EditorKind.CURSOR, project_dir)
        _unlock_gate()

        if not actions:
            return {
                "editor": "cursor",
                "configured": True,
                "path": str(rules_path),
                "rules": _get_workflow_rules(),
            }

        return {
            "editor": "cursor",
            "configured": False,
            "path": str(rules_path),
            "setup_actions": _actions_to_dicts(actions),
            "instructions": (
                "Create .cursor/rules/sylvan.md with the content below. Create the directories if they do not exist."
            ),
            "content": _build_rules_markdown(),
            "rules": _get_workflow_rules(),
        }


class ConfigureWindsurf(Tool):
    name = "setup_windsurf"
    category = "meta"
    description = "Creates .windsurf/rules/sylvan.md with tool routing rules for this project."

    class Params(HasProjectPath, ToolParams):
        pass

    async def handle(self, p: Params) -> dict:
        project_dir = Path(p.project_path)
        rules_path = project_dir / ".windsurf" / "rules" / "sylvan.md"
        actions = check_setup(EditorKind.WINDSURF, project_dir)
        _unlock_gate()

        if not actions:
            return {
                "editor": "windsurf",
                "configured": True,
                "path": str(rules_path),
                "rules": _get_workflow_rules(),
            }

        return {
            "editor": "windsurf",
            "configured": False,
            "path": str(rules_path),
            "setup_actions": _actions_to_dicts(actions),
            "instructions": (
                "Create .windsurf/rules/sylvan.md with the content below. Create the directories if they do not exist."
            ),
            "content": _build_rules_markdown(),
            "rules": _get_workflow_rules(),
        }


class ConfigureCopilot(Tool):
    name = "setup_copilot"
    category = "meta"
    description = "Creates .github/copilot-instructions.md with tool routing rules for this project."

    class Params(HasProjectPath, ToolParams):
        pass

    async def handle(self, p: Params) -> dict:
        project_dir = Path(p.project_path)
        instructions_path = project_dir / ".github" / "copilot-instructions.md"
        actions = check_setup(EditorKind.COPILOT, project_dir)
        _unlock_gate()

        if not actions:
            return {
                "editor": "copilot",
                "configured": True,
                "path": str(instructions_path),
                "rules": _get_workflow_rules(),
            }

        return {
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
        }


async def _inject_update(result: dict) -> dict:
    """Add update_available to a tool response if an update exists."""
    from sylvan.server.startup import get_update_info

    update = get_update_info()
    if update:
        result["update_available"] = update
    return result


async def configure_claude_code(project_path: str, **_kwargs: object) -> dict:
    result = await ConfigureClaudeCode().execute({"project_path": project_path})
    return await _inject_update(result)


async def configure_cursor(project_path: str, **_kwargs: object) -> dict:
    result = await ConfigureCursor().execute({"project_path": project_path})
    return await _inject_update(result)


async def configure_windsurf(project_path: str, **_kwargs: object) -> dict:
    result = await ConfigureWindsurf().execute({"project_path": project_path})
    return await _inject_update(result)


async def configure_copilot(project_path: str, **_kwargs: object) -> dict:
    result = await ConfigureCopilot().execute({"project_path": project_path})
    return await _inject_update(result)
