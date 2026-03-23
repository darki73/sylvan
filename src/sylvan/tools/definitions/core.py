"""Tool definitions -- indexing, search, and code browsing."""

from mcp.types import Tool

TOOLS: list[Tool] = [
    Tool(
        name="index_folder",
        description=(
            "REQUIRED FIRST STEP: Index a local folder before exploring its code or docs. "
            "Run this once per project, and RE-RUN after making code changes (edits, "
            "new files, refactors) to keep the index current -- incremental reindex is "
            "fast and only processes changed files. After indexing, ALWAYS prefer sylvan "
            "tools (search_symbols, get_symbol, get_file_outline, search_sections) over "
            "reading files directly with Read/cat. Sylvan returns only the exact code "
            "you need instead of entire files. "
            "For third-party libraries, use add_library instead (fetches source from PyPI/npm/etc)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the folder to index",
                },
                "name": {
                    "type": "string",
                    "description": "Display name for the repository (defaults to folder name)",
                },
            },
            "required": ["path"],
        },
    ),
    Tool(
        name="index_file",
        description=(
            "Surgical single-file reindex -- much faster than index_folder when you've "
            "only edited one file. Use after editing a file to keep the index current."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository name (as shown in list_repos)",
                },
                "file_path": {
                    "type": "string",
                    "description": "Relative path within the repo (e.g., 'src/main.py')",
                },
            },
            "required": ["repo", "file_path"],
        },
    ),
    Tool(
        name="search_symbols",
        description=(
            "PREFERRED over Grep/Glob for finding code. Searches indexed symbols "
            "(functions, classes, methods, constants, types) by name, signature, "
            "docstring, or keywords with ranked results. Returns signatures and "
            "locations without reading any files. Use this FIRST when looking for "
            "any code -- it's faster and more precise than grep or glob. If the repo is "
            "indexed, always use search_symbols before falling back to Grep. "
            "Also searches indexed third-party libraries -- use add_library first to "
            "index a library's source code for precise API lookup. "
            "NOTE: If results seem stale (missing recent changes), re-run index_folder to refresh."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query (symbol name, keyword, or description)",
                },
                "repo": {
                    "type": "string",
                    "description": "Filter to a specific repository",
                },
                "kind": {
                    "type": "string",
                    "enum": ["function", "class", "method", "constant", "type"],
                    "description": "Filter by symbol kind",
                },
                "language": {
                    "type": "string",
                    "description": "Filter by language (e.g., python, typescript, go)",
                },
                "file_pattern": {
                    "type": "string",
                    "description": "Glob pattern to filter by file path",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum results (default: 20)",
                    "default": 20,
                },
                "token_budget": {
                    "type": "integer",
                    "description": (
                        "Optional token budget -- greedy-pack results until budget is "
                        "exhausted. Reports tokens_used and tokens_remaining in _meta."
                    ),
                },
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="get_symbol",
        description=(
            "PREFERRED over Read for viewing code. Retrieves the exact source of a "
            "function, class, or method by ID -- without reading the entire file. "
            "Returns only the symbol's source lines instead of the full file. "
            "Use symbol IDs from search_symbols results. ALWAYS use this instead of "
            "Read when you know the symbol name or have its ID."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "symbol_id": {
                    "type": "string",
                    "description": "Symbol identifier (from search results)",
                },
                "verify": {
                    "type": "boolean",
                    "description": "Verify content hasn't drifted since indexing",
                    "default": False,
                },
                "context_lines": {
                    "type": "integer",
                    "description": "Number of surrounding lines to include (0-50)",
                    "default": 0,
                },
            },
            "required": ["symbol_id"],
        },
    ),
    Tool(
        name="get_symbols",
        description=(
            "Batch retrieve multiple symbols at once. More efficient than multiple "
            "get_symbol calls or reading multiple files with Read."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "symbol_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of symbol identifiers to retrieve",
                },
            },
            "required": ["symbol_ids"],
        },
    ),
    Tool(
        name="get_file_outline",
        description=(
            "PREFERRED over Read for understanding a file's structure. Returns a "
            "hierarchical outline of all symbols (functions, classes, methods) with "
            "signatures and line numbers -- without reading the file content. Use this "
            "BEFORE reading a file to understand what's in it, then use get_symbol "
            "to fetch only the specific symbol you need."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository name"},
                "file_path": {"type": "string", "description": "Relative file path"},
            },
            "required": ["repo", "file_path"],
        },
    ),
    Tool(
        name="get_file_tree",
        description=(
            "PREFERRED over ls/Glob for exploring repo structure. Returns a compact "
            "indented tree (like the `tree` command) with language and symbol counts. "
            "Directories beyond max_depth are collapsed with file counts. "
            "Use this instead of running ls or Glob to understand a project layout."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository name"},
                "max_depth": {
                    "type": "integer",
                    "description": "Max directory depth to expand (default: 3, max: 10)",
                    "default": 3,
                },
            },
            "required": ["repo"],
        },
    ),
    Tool(
        name="list_repos",
        description=(
            "List all indexed repositories. Check this FIRST to see if a repo is "
            "already indexed before using index_folder. Shows file count, symbol "
            "count, and indexing timestamp."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    Tool(
        name="search_text",
        description=(
            "Full-text search across all indexed file content -- like Grep but searches "
            "cached content without hitting the filesystem. Use for comments, strings, "
            "TODOs, or literal text that search_symbols wouldn't find."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Text to search for"},
                "repo": {"type": "string", "description": "Repository filter"},
                "file_pattern": {"type": "string", "description": "Glob pattern for files"},
                "max_results": {"type": "integer", "default": 20},
                "context_lines": {"type": "integer", "default": 2},
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="batch_search_symbols",
        description=(
            "Run multiple symbol searches in ONE call. More efficient than calling "
            "search_symbols repeatedly. Each query can override repo, kind, and language. "
            "Use when you need to find several unrelated symbols at once."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "queries": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "repo": {"type": "string"},
                            "kind": {"type": "string", "enum": ["function", "class", "method", "constant", "type"]},
                            "language": {"type": "string"},
                            "max_results": {"type": "integer"},
                        },
                        "required": ["query"],
                    },
                    "description": "List of search queries to run",
                },
                "repo": {"type": "string", "description": "Default repo filter for all queries"},
                "max_results_per_query": {
                    "type": "integer",
                    "description": "Default max results per query (default: 10)",
                    "default": 10,
                },
            },
            "required": ["queries"],
        },
    ),
    Tool(
        name="get_file_outlines",
        description=(
            "Batch retrieve outlines for multiple files in ONE call. More efficient "
            "than calling get_file_outline repeatedly. Returns symbol trees for each "
            "file with signatures and line numbers."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository name"},
                "file_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of relative file paths",
                },
            },
            "required": ["repo", "file_paths"],
        },
    ),
    Tool(
        name="search_similar_symbols",
        description=(
            "Find symbols semantically similar to a given source symbol using "
            "vector similarity search. Useful for discovering related code, "
            "alternative implementations, or patterns similar to a known symbol. "
            "Requires the source symbol's ID (from search_symbols or get_symbol)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "symbol_id": {
                    "type": "string",
                    "description": "Source symbol identifier to find similar symbols for",
                },
                "repo": {
                    "type": "string",
                    "description": "Filter results to a specific repository",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum similar symbols to return (default: 10)",
                    "default": 10,
                },
            },
            "required": ["symbol_id"],
        },
    ),
]
