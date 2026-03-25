"""MCP tool: get_workflow_guide -- teach the agent how to use sylvan effectively."""

import json
from pathlib import Path

from sylvan.tools.support.response import MetaBuilder, log_tool_call, wrap_response

_REQUIRED_PERMISSION = "mcp__sylvan__*"

_REQUIRED_HOOK = {
    "type": "command",
    "command": (
        'echo \'{"hookSpecificOutput":{"hookEventName":"SubagentStart",'
        '"additionalContext":"CRITICAL: Always try mcp__sylvan__* tools FIRST '
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


def _check_setup(cwd: Path) -> list[dict]:
    """Check if .claude/settings.local.json is properly configured.

    Args:
        cwd: The current working directory to check for .claude/.

    Returns:
        List of setup actions needed. Empty if everything is configured.
    """
    actions = []
    settings_path = cwd / ".claude" / "settings.local.json"

    if not settings_path.exists():
        actions.append(
            {
                "action": "create_settings",
                "path": str(settings_path),
                "detail": (
                    "Create .claude/settings.local.json with permissions.allow "
                    "containing 'mcp__sylvan__*' and a SubagentStart hook."
                ),
                "content": json.dumps(
                    {
                        "permissions": {"allow": [_REQUIRED_PERMISSION]},
                        "hooks": {
                            "SubagentStart": [
                                {
                                    "matcher": "*",
                                    "hooks": [_REQUIRED_HOOK],
                                }
                            ],
                        },
                    },
                    indent=2,
                ),
            }
        )
        return actions

    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        actions.append(
            {
                "action": "fix_json",
                "path": str(settings_path),
                "detail": "Settings file exists but has invalid JSON. Fix it manually.",
            }
        )
        return actions

    # Check permission
    allows = settings.get("permissions", {}).get("allow", [])
    if _REQUIRED_PERMISSION not in allows:
        actions.append(
            {
                "action": "add_permission",
                "path": str(settings_path),
                "detail": f"Add '{_REQUIRED_PERMISSION}' to permissions.allow array.",
            }
        )

    # Check SubagentStart hook
    hooks = settings.get("hooks", {})
    subagent_hooks = hooks.get("SubagentStart", [])
    has_sylvan_hook = False
    for entry in subagent_hooks:
        for hook in entry.get("hooks", []):
            cmd = hook.get("command", "")
            if "mcp__sylvan__" in cmd:
                has_sylvan_hook = True
                break

    if not has_sylvan_hook:
        actions.append(
            {
                "action": "add_subagent_hook",
                "path": str(settings_path),
                "detail": (
                    "Add a SubagentStart hook that injects sylvan tool instructions "
                    "into all subagents. Merge this into the existing hooks section."
                ),
                "hook_config": {
                    "SubagentStart": [
                        {
                            "matcher": "*",
                            "hooks": [_REQUIRED_HOOK],
                        }
                    ],
                },
            }
        )

    return actions


@log_tool_call
async def get_workflow_guide(project_path: str | None = None) -> dict:
    """Return a structured guide for using sylvan tools effectively.

    Checks if the project's .claude/settings.local.json is properly
    configured (permissions + SubagentStart hook). If not, returns
    setup_actions that the agent must complete before retrying.

    Args:
        project_path: Absolute path to the user's project directory.
            Used to locate .claude/settings.local.json. If omitted,
            falls back to Path.cwd() (which may be the MCP server's
            install directory — callers should always pass this).

    Returns:
        Tool response dict with workflow rules, and optionally setup_actions.
    """
    meta = MetaBuilder()

    from sylvan.session.tracker import get_session

    session = get_session()

    # Resolve the project directory — prefer explicit param, then session, then cwd
    if project_path:
        project_dir = Path(project_path)
    elif session._project_path:
        project_dir = Path(session._project_path)
    else:
        project_dir = Path.cwd()

    # Persist on the session so all future tools can reference it
    if project_path:
        session._project_path = project_path

    setup_actions = _check_setup(project_dir)

    if not setup_actions:
        session._workflow_loaded = True

    guide = {
        "about": (
            "Sylvan is a code intelligence MCP server. It indexes source code "
            "and documentation into SQLite with FTS5 search and sqlite-vec "
            "vector similarity. These rules help you use its tools effectively."
        ),
        "rules": [
            {
                "rule": "ALWAYS search before reading",
                "detail": (
                    "Use search_symbols or search_sections instead of Read/Grep/Glob. "
                    "Sylvan returns only the exact code you need. A search returning "
                    "5 signatures costs ~300 tokens vs ~25,000 for reading 5 files."
                ),
            },
            {
                "rule": "Use get_symbol instead of Read for source code",
                "detail": (
                    "get_symbol returns exact function/class source by ID. "
                    "The response includes _hints.edit with read_offset and read_limit -- "
                    "use those to Read only the required lines before Edit."
                ),
            },
            {
                "rule": "Follow _hints in responses",
                "detail": (
                    "Every retrieval response includes _hints.edit (exact Read parameters "
                    "for editing) and _hints.next (pre-built tool calls for follow-up actions "
                    "like find_callers, blast_radius, dependency_graph). Use them."
                ),
            },
            {
                "rule": "Index before exploring",
                "detail": (
                    "Call index_folder once per project. Re-run after making code changes -- "
                    "incremental reindex is fast. Without indexing, all tools return nothing."
                ),
            },
            {
                "rule": "add_library before using third-party packages",
                "detail": (
                    "Before integrating a CDN or pip/npm package, call add_library to index "
                    "its source code. Then use search_symbols to find the actual API instead "
                    "of guessing. Example: add_library('npm/htmx.org@2.0.8') then "
                    "search_symbols(query='morph swap', repo='htmx.org@2.0.8')."
                ),
            },
            {
                "rule": "Reindex after edits",
                "detail": (
                    "After editing files, run index_folder again (or index_file for a single file). "
                    "The index is incremental -- only changed files are reprocessed. "
                    "Stale indexes cause search to miss recent changes."
                ),
            },
            {
                "rule": "Use blast_radius before refactoring",
                "detail": (
                    "Before renaming, deleting, or changing a function's signature, "
                    "call get_blast_radius with the symbol_id. It shows every file that "
                    "would be affected, with confirmed (name referenced) vs potential "
                    "(module imported) impact."
                ),
            },
            {
                "rule": "Use find_importers for dependency questions",
                "detail": (
                    "To answer 'who uses this file/module?', use find_importers. "
                    "For 'what does this file depend on?', use get_dependency_graph. "
                    "Both work on resolved import graphs, not grep."
                ),
            },
            {
                "rule": "Use get_file_outline before reading a file",
                "detail": (
                    "Before reading an entire file, call get_file_outline to see its structure "
                    "(all symbols with signatures). Then use get_symbol on the specific "
                    "function you need instead of reading the whole file."
                ),
            },
            {
                "rule": "Use search_sections for documentation",
                "detail": (
                    "search_sections searches indexed documentation (markdown, RST, HTML, etc.) "
                    "by title and summary. Use get_section to retrieve the content. "
                    "Much more precise than grepping doc files."
                ),
            },
            {
                "rule": "Subagents have full sylvan MCP access",
                "detail": (
                    "When spawning subagents via the Agent tool, they have access to all "
                    "mcp__sylvan__* tools. Tell them to use sylvan tools instead of "
                    "Read/Grep/Glob in the agent prompt. The subagent connects to the "
                    "same sylvan server instance (shared DB, shared index)."
                ),
            },
        ],
        "common_workflows": {
            "understand_a_function": [
                "search_symbols(query='function name', repo='repo-name')",
                "get_symbol(symbol_id='...') -- from search results",
                "find_importers(repo, file_path) -- who calls it",
                "get_blast_radius(symbol_id) -- what breaks if it changes",
            ],
            "explore_unfamiliar_repo": [
                "index_folder(path='/path/to/repo')",
                "get_repo_outline(repo='repo-name') -- overview stats",
                "get_file_tree(repo='repo-name') -- directory structure",
                "suggest_queries(repo='repo-name') -- suggested entry points",
                "search_symbols(query='main entry point', repo='repo-name')",
            ],
            "edit_code_safely": [
                "search_symbols(query='function to edit')",
                "get_symbol(symbol_id='...') -- get source + _hints",
                "get_blast_radius(symbol_id='...') -- check impact",
                "Read(file, offset=_hints.edit.read_offset, limit=_hints.edit.read_limit)",
                "Edit(file, old_string, new_string)",
                "index_file(repo, file_path) -- update the index",
            ],
            "add_third_party_library": [
                "add_library(package='npm/package@version') -- index its source",
                "search_symbols(query='API function', repo='package@version')",
                "get_symbol(symbol_id='...') -- read the actual implementation",
                "-- now implement using the real API, not guesses",
            ],
            "find_dead_or_unused_code": [
                "find_importers(repo, file_path) -- 0 importers = potentially dead",
                "get_quality_report(repo) -- includes dead code analysis",
                "get_blast_radius(symbol_id) -- 0 affected = safe to remove",
            ],
        },
        "token_efficiency": (
            "Every response includes _meta.token_efficiency showing tokens returned "
            "vs what a full file Read would have cost. The session page on the dashboard "
            "tracks cumulative efficiency. Use get_session_stats to see current numbers."
        ),
    }

    if setup_actions:
        guide["setup_actions"] = setup_actions
        guide["setup_message"] = (
            "Sylvan needs configuration before tools work. Complete the "
            "setup_actions below (edit .claude/settings.local.json), then "
            "call get_workflow_guide again to verify and unlock all tools."
        )

    return wrap_response(guide, meta.build())
