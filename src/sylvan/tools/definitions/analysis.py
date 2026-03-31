"""Tool definitions -- analysis, navigation, and code intelligence."""

from mcp.types import Tool

TOOLS: list[Tool] = [
    Tool(
        name="get_blast_radius",
        description=(
            "BEFORE making changes, check the blast radius. Shows which files and "
            "symbols would be affected by changing a symbol -- with confirmed (name "
            "referenced) vs potential (file imported) impact. Grep cannot answer this."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "symbol_id": {"type": "string", "description": "Symbol to analyze"},
                "depth": {"type": "integer", "description": "Import hops to follow (1-3)", "default": 2},
            },
            "required": ["symbol_id"],
        },
    ),
    Tool(
        name="get_class_hierarchy",
        description=(
            "Traverse class inheritance chains -- ancestors and descendants. "
            "Answers 'what does this class extend?' and 'what extends this class?' "
            "without manual grep. Use before refactoring a base class."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "class_name": {"type": "string", "description": "Class name to analyze"},
                "repo": {"type": "string", "description": "Optional repo filter"},
            },
            "required": ["class_name"],
        },
    ),
    Tool(
        name="get_references",
        description=(
            "PREFERRED over Grep for 'who calls this function?'. Returns symbol-level "
            "references -- callers (direction=to) or callees (direction=from). "
            "Structural query that Grep cannot answer accurately."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "symbol_id": {"type": "string", "description": "Symbol to query"},
                "direction": {
                    "type": "string",
                    "enum": ["to", "from"],
                    "description": "to=callers, from=callees",
                    "default": "to",
                },
            },
            "required": ["symbol_id"],
        },
    ),
    Tool(
        name="find_importers",
        description=(
            "Find all files that import a given file. Answers 'who depends on this "
            "module?' -- a structural query that Grep cannot reliably answer. Each "
            "importer includes has_importers: when false, the importer has no importers "
            "itself -- meaning the import chain is transitively dead."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository name"},
                "file_path": {"type": "string", "description": "File to find importers of"},
                "max_results": {"type": "integer", "default": 50},
            },
            "required": ["repo", "file_path"],
        },
    ),
    Tool(
        name="get_related",
        description=(
            "Find symbols related to a given symbol -- by co-location, shared imports, "
            "or name similarity. Useful for discovering related code to understand context."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "symbol_id": {"type": "string", "description": "Symbol to find relations for"},
                "max_results": {"type": "integer", "default": 10},
            },
            "required": ["symbol_id"],
        },
    ),
    Tool(
        name="get_quality",
        description=(
            "Find untested, undocumented, or complex code. Returns quality metrics "
            "per symbol: has_tests, has_docs, has_types, complexity score. "
            "Use for code review targeting or identifying technical debt."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository name"},
                "untested_only": {"type": "boolean", "default": False},
                "undocumented_only": {"type": "boolean", "default": False},
                "min_complexity": {"type": "integer", "default": 0},
                "limit": {"type": "integer", "default": 50},
            },
            "required": ["repo"],
        },
    ),
    Tool(
        name="get_quality_report",
        description=(
            "Run a comprehensive quality analysis on a repository -- the mini SonarQube. "
            "Returns test coverage, documentation coverage, code smells, security "
            "findings, code duplication, and quality gate pass/fail status. "
            "All analysis is static (no test execution needed) and fast."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository name"},
            },
            "required": ["repo"],
        },
    ),
    Tool(
        name="get_symbol_diff",
        description=(
            "Compare symbols between the current index and a previous git commit. "
            "Shows which symbols were added, removed, or changed -- with signature "
            "diffs. Use before reviewing a PR or after a rebase to understand what "
            "actually changed at the symbol level."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository name"},
                "commit": {
                    "type": "string",
                    "description": "Git ref to compare against (default: HEAD~1)",
                    "default": "HEAD~1",
                },
                "file_path": {"type": "string", "description": "Optional file path filter"},
                "max_files": {"type": "integer", "default": 50},
            },
            "required": ["repo"],
        },
    ),
    Tool(
        name="get_dependency_graph",
        description=(
            "Build a file-level import dependency graph. Shows what a file imports "
            "(direction=imports), what imports it (direction=importers), or both. "
            "Returns nodes with symbol counts and directed edges. Use to understand "
            "module coupling before refactoring."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository name"},
                "file_path": {"type": "string", "description": "File to centre the graph on"},
                "direction": {
                    "type": "string",
                    "enum": ["imports", "importers", "both"],
                    "description": "Traversal direction",
                    "default": "both",
                },
                "depth": {
                    "type": "integer",
                    "description": "Import hops to follow (1-3)",
                    "default": 1,
                },
            },
            "required": ["repo", "file_path"],
        },
    ),
    Tool(
        name="search_columns",
        description=(
            "Search column metadata from ecosystem context providers (dbt, etc.). "
            "Finds columns by name or description across all models. Use to answer "
            "'what columns does this model have?' or 'where is this field defined?'"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository name"},
                "query": {"type": "string", "description": "Column name or description to search"},
                "model_pattern": {"type": "string", "description": "Glob pattern to filter model names"},
                "max_results": {"type": "integer", "default": 20},
            },
            "required": ["repo", "query"],
        },
    ),
    Tool(
        name="get_git_context",
        description=(
            "Get git blame, change frequency, and recent commits for a file or symbol. "
            "Answers 'who last touched this?' and 'how often does this change?' "
            "without running git commands manually."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository name"},
                "file_path": {"type": "string", "description": "File path"},
                "symbol_id": {"type": "string", "description": "Symbol ID (alternative to file_path)"},
            },
            "required": ["repo"],
        },
    ),
    Tool(
        name="get_context_bundle",
        description=(
            "MOST EFFICIENT way to understand a symbol. Returns source + imports + "
            "callers + sibling symbols in ONE call -- replaces what would otherwise be "
            "3-5 separate Read/Grep calls. Use this when you need to understand a "
            "symbol in its full context."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "symbol_id": {"type": "string", "description": "Symbol to get context for"},
                "include_callers": {"type": "boolean", "default": False},
                "include_imports": {"type": "boolean", "default": True},
            },
            "required": ["symbol_id"],
        },
    ),
    Tool(
        name="get_repo_outline",
        description=(
            "START HERE when exploring an unfamiliar repo. Returns a high-level "
            "summary: file count, languages, symbol breakdown by kind, documentation "
            "coverage. Use this to orient before diving into search_symbols or get_toc."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository name"},
            },
            "required": ["repo"],
        },
    ),
    Tool(
        name="suggest_queries",
        description=(
            "Not sure where to start? This suggests the best queries for exploring "
            "a repo -- key entry points, popular classes, unexplored areas, docs. "
            "Session-aware: adapts based on what you've already looked at."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository name"},
            },
            "required": ["repo"],
        },
    ),
    Tool(
        name="batch_blast_radius",
        description=(
            "Check blast radius for MULTIPLE symbols in ONE call. More efficient "
            "than calling get_blast_radius repeatedly before a large refactor. "
            "Returns confirmed and potential impact for each symbol."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "symbol_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of symbol identifiers to analyse",
                },
                "depth": {"type": "integer", "description": "Import hops to follow (1-3)", "default": 2},
            },
            "required": ["symbol_ids"],
        },
    ),
    Tool(
        name="batch_find_importers",
        description=(
            "Find importers for MULTIPLE files in ONE call. More efficient than "
            "calling find_importers repeatedly. Use to check dependency status "
            "of several modules at once."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository name"},
                "file_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of file paths to find importers of",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max importers per file (default: 20)",
                    "default": 20,
                },
            },
            "required": ["repo", "file_paths"],
        },
    ),
    Tool(
        name="rename_symbol",
        description=(
            "Find all edit locations needed to rename a symbol. Returns exact "
            "file/line/old_text/new_text for each occurrence so the agent can "
            "apply edits directly. Uses blast radius to find affected files."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "symbol_id": {"type": "string", "description": "Symbol to rename"},
                "new_name": {"type": "string", "description": "Desired new name (must be a valid identifier)"},
            },
            "required": ["symbol_id", "new_name"],
        },
    ),
    Tool(
        name="get_recent_changes",
        description=(
            "Show what changed in the last N commits at the file level. For each "
            "changed file in the index, shows language, symbol count, and last commit "
            "message. A lighter alternative to get_symbol_diff when you just need an "
            "overview of recent activity."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository name"},
                "commits": {
                    "type": "integer",
                    "description": "Number of commits to look back (default: 5)",
                    "default": 5,
                },
                "file_path": {"type": "string", "description": "Optional file path filter"},
            },
            "required": ["repo"],
        },
    ),
    Tool(
        name="get_session_stats",
        description=(
            "Usage statistics at three levels: current session, per-project lifetime, "
            "and overall across all repos. Shows tokens returned vs avoided, tool calls, "
            "symbols/sections retrieved. Optionally filter to a specific repo."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Optional: show stats for a specific repo"},
            },
        },
    ),
    Tool(
        name="who_calls",
        description=(
            "Find all symbols that call a given function or method. Returns callers "
            "with file paths, signatures, and line numbers. Use before changing a "
            "function to see exactly what breaks. More precise than find_importers "
            "which works at file level."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "symbol_id": {"type": "string", "description": "Symbol to find callers of"},
                "max_results": {"type": "integer", "default": 50},
            },
            "required": ["symbol_id"],
        },
    ),
    Tool(
        name="calls_to",
        description=(
            "Find all symbols that a given function or method calls. Returns callees "
            "with file paths, signatures, and line numbers. Use when debugging to "
            "understand what a function depends on."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "symbol_id": {"type": "string", "description": "Symbol to find callees of"},
                "max_results": {"type": "integer", "default": 50},
            },
            "required": ["symbol_id"],
        },
    ),
]
