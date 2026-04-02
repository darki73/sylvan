"""MCP tool: get_workflow_guide -- teach the agent how to use sylvan effectively."""

from sylvan.tools.base import HasOptionalProjectPath, Tool, ToolParams


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


class GetWorkflowGuide(Tool):
    name = "get_workflow_guide"
    category = "meta"
    description = (
        "CALL THIS FIRST in every session. Returns the optimal workflow rules "
        "and tool sequences for using sylvan effectively. The guide teaches you "
        "when to use add_library before integrating packages, how to follow "
        "_hints for editing, and the correct tool chains for common tasks like "
        "code exploration, safe editing, and dependency analysis. Saves tokens "
        "by preventing wrong tool choices. Pass project_path so sylvan knows "
        "where your .claude/settings.local.json lives."
    )

    class Params(HasOptionalProjectPath, ToolParams):
        pass

    async def handle(self, p: Params) -> dict:
        from dataclasses import asdict
        from pathlib import Path

        from sylvan.session.tracker import get_session
        from sylvan.tools.meta.editor_setup import EditorKind, check_setup, detect_editor

        session = get_session()

        if p.project_path:
            project_dir = Path(p.project_path)
        elif session._project_path:
            project_dir = Path(session._project_path)
        else:
            project_dir = Path.cwd()

        if p.project_path:
            session._project_path = p.project_path

        editor_name = getattr(session, "_editor", None)
        if editor_name:
            editor = detect_editor(editor_name)
        else:
            editor = EditorKind.CLAUDE_CODE

        setup_actions = [asdict(a) for a in check_setup(editor, project_dir)]

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

        return guide


async def get_workflow_guide(project_path: str | None = None, **_kwargs: object) -> dict:
    tool = GetWorkflowGuide()
    result = await tool.execute({"project_path": project_path} if project_path else {})
    from sylvan.server.startup import get_update_info

    update = get_update_info()
    if update:
        result["update_available"] = update
    return result
