"""Tool definitions -- documentation, workspace, library, and scaffold tools."""

from mcp.types import Tool

TOOLS: list[Tool] = [
    Tool(
        name="search_sections",
        description=(
            "PREFERRED over Read/Grep for finding documentation. Searches indexed "
            "doc sections (markdown, RST, HTML, OpenAPI, etc.) by title, summary, "
            "or tags. Returns section summaries without reading files. Use this to "
            "find configuration docs, API references, or any documentation section."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "repo": {"type": "string", "description": "Filter to a specific repo"},
                "doc_path": {"type": "string", "description": "Filter to a specific document"},
                "max_results": {"type": "integer", "description": "Maximum results (default: 10)", "default": 10},
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="get_section",
        description=(
            "PREFERRED over Read for viewing documentation. Retrieves the exact "
            "content of a doc section by ID -- one heading's worth of content instead "
            "of the entire file. Use section IDs from search_sections or get_toc."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "section_id": {"type": "string", "description": "Section identifier"},
                "verify": {"type": "boolean", "description": "Verify content hash", "default": False},
            },
            "required": ["section_id"],
        },
    ),
    Tool(
        name="get_sections",
        description="Batch retrieve multiple doc sections at once. More efficient than multiple get_section calls.",
        inputSchema={
            "type": "object",
            "properties": {
                "section_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of section identifiers",
                },
            },
            "required": ["section_ids"],
        },
    ),
    Tool(
        name="get_toc",
        description=(
            "PREFERRED over Read for browsing documentation. Returns a structured "
            "table of contents for all indexed docs -- every heading, section, and "
            "their hierarchy. Use this to navigate docs instead of reading files."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository name"},
                "doc_path": {"type": "string", "description": "Filter to a specific document"},
            },
            "required": ["repo"],
        },
    ),
    Tool(
        name="get_toc_tree",
        description=(
            "Nested tree table of contents grouped by document. Richer than get_toc "
            "for multi-doc repos. Use max_depth to limit heading levels and reduce output size."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Repository name"},
                "max_depth": {
                    "type": "integer",
                    "description": "Max heading depth to include (default: 3, max: 6)",
                    "default": 3,
                },
            },
            "required": ["repo"],
        },
    ),
    Tool(
        name="index_workspace",
        description=(
            "BEST WAY to set up multi-repo projects. Indexes multiple folders at once, "
            "groups them into a workspace, and resolves cross-repo imports automatically. "
            "Enables cross-repo search, blast radius, and dependency analysis."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "workspace": {"type": "string", "description": "Workspace name"},
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of absolute folder paths to index",
                },
                "description": {"type": "string", "description": "Workspace description"},
            },
            "required": ["workspace", "paths"],
        },
    ),
    Tool(
        name="workspace_search",
        description=(
            "Search symbols across ALL repos in a workspace simultaneously. "
            "Results from different repos are ranked together. Use this when "
            "working on multi-repo projects (frontend + backend + shared)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "workspace": {"type": "string", "description": "Workspace name"},
                "query": {"type": "string", "description": "Search query"},
                "kind": {"type": "string", "enum": ["function", "class", "method", "constant", "type"]},
                "language": {"type": "string"},
                "max_results": {"type": "integer", "default": 20},
            },
            "required": ["workspace", "query"],
        },
    ),
    Tool(
        name="workspace_blast_radius",
        description=(
            "Cross-repo blast radius -- shows impact ACROSS repositories. "
            "If you change a shared type, this tells you which files in the "
            "backend AND frontend are affected. Grep cannot do this."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "workspace": {"type": "string", "description": "Workspace name"},
                "symbol_id": {"type": "string", "description": "Symbol to analyze"},
                "depth": {"type": "integer", "default": 2},
            },
            "required": ["workspace", "symbol_id"],
        },
    ),
    Tool(
        name="add_to_workspace",
        description="Add an already-indexed repo to a workspace.",
        inputSchema={
            "type": "object",
            "properties": {
                "workspace": {"type": "string", "description": "Workspace name"},
                "repo": {"type": "string", "description": "Repository name"},
            },
            "required": ["workspace", "repo"],
        },
    ),
    Tool(
        name="pin_library",
        description=(
            "Pin a specific library version to a workspace. The library must "
            "already be indexed via add_library. Once pinned, workspace_search "
            "includes that library version's symbols. Use this to give each "
            "project access to the exact library versions it depends on."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "workspace": {"type": "string", "description": "Workspace name"},
                "library": {
                    "type": "string",
                    "description": "Library display name with version (e.g., 'numpy@2.2.2')",
                },
            },
            "required": ["workspace", "library"],
        },
    ),
    Tool(
        name="compare_library_versions",
        description=(
            "Compare two indexed versions of the same library to generate a migration "
            "guide. Shows symbols added, removed, and with changed signatures between "
            "versions. Use BEFORE upgrading a workspace's pinned library version to "
            "assess breaking changes. Both versions must be indexed via add_library."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "package": {
                    "type": "string",
                    "description": "Package name without manager prefix (e.g., 'numpy', 'react')",
                },
                "from_version": {
                    "type": "string",
                    "description": "The old version to compare from (e.g., '1.1.1')",
                },
                "to_version": {
                    "type": "string",
                    "description": "The new version to compare to (e.g., '2.2.2')",
                },
            },
            "required": ["package", "from_version", "to_version"],
        },
    ),
    Tool(
        name="check_library_versions",
        description=(
            "Compare a project's installed dependencies against indexed library "
            "versions. Reads pyproject.toml, package.json, go.mod, etc. and reports "
            "which libraries are outdated (installed version differs from indexed), "
            "up-to-date, or not indexed at all. Use after uv sync or npm install "
            "to detect version drift and decide which libraries to re-index."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Indexed repository name to check dependencies for",
                },
            },
            "required": ["repo"],
        },
    ),
    Tool(
        name="add_library",
        description=(
            "Index a third-party library's SOURCE CODE for precise API lookup. "
            "Fetches the real implementation at a specific version -- more reliable "
            "than documentation. When you encounter an unfamiliar library or need to "
            "look up how an API actually works, use this tool FIRST to index it, then "
            "search_symbols to find the implementation. "
            "Format: pip/django@4.2, npm/react@18, go/github.com/gin-gonic/gin, cargo/serde"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "package": {
                    "type": "string",
                    "description": "Package spec: manager/name[@version] (e.g., pip/django@4.2, npm/react)",
                },
            },
            "required": ["package"],
        },
    ),
    Tool(
        name="list_libraries",
        description=(
            "List all indexed third-party libraries. Check this to see what library "
            "source code is available for search. If a library you need isn't listed, "
            "use add_library to index it."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="remove_library",
        description="Remove an indexed library and its source files from disk.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Library name (e.g., django@4.2)"},
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="scaffold",
        description=(
            "Generate sylvan/ project context directory and agent instructions. "
            "Creates auto-generated architecture docs, quality reports, dependency maps, "
            "and planning directories (future/working/completed). Also generates the "
            "agent instruction file (CLAUDE.md or .cursorrules) that teaches the agent "
            "how to use the sylvan/ directory. Run after indexing a project."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Indexed repo name"},
                "agent": {
                    "type": "string",
                    "enum": ["claude", "cursor", "copilot", "generic"],
                    "description": "Agent format for instruction file",
                    "default": "claude",
                },
                "root": {"type": "string", "description": "Override project root path"},
            },
            "required": ["repo"],
        },
    ),
    Tool(
        name="get_dashboard_url",
        description=(
            "Get the URL for the Sylvan web dashboard. The dashboard provides "
            "a visual overview of indexed repositories, quality reports, library "
            "management, and interactive symbol search. Opens automatically on "
            "a random localhost port when the MCP server starts."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="get_workflow_guide",
        description=(
            "CALL THIS FIRST in every session. Returns the optimal workflow rules "
            "and tool sequences for using sylvan effectively. The guide teaches you "
            "when to use add_library before integrating packages, how to follow "
            "_hints for editing, and the correct tool chains for common tasks like "
            "code exploration, safe editing, and dependency analysis. Saves tokens "
            "by preventing wrong tool choices. Pass project_path so sylvan knows "
            "where your .claude/settings.local.json lives."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "project_path": {
                    "type": "string",
                    "description": (
                        "Absolute path to the user's project directory. Sylvan uses "
                        "this to find .claude/settings.local.json and configure the "
                        "session. Pass the working directory of your Claude Code session."
                    ),
                },
            },
        },
    ),
    Tool(
        name="get_logs",
        description=(
            "Retrieve sylvan server log entries for debugging. Returns the "
            "most recent lines by default (tail). Use from_start=true for "
            "head, offset to paginate. Use this to diagnose errors, check "
            "tool call history, or debug issues without searching for log files."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "lines": {
                    "type": "integer",
                    "description": "Number of lines to return (1-500, default 50)",
                    "default": 50,
                },
                "from_start": {
                    "type": "boolean",
                    "description": "Read from beginning instead of end",
                    "default": False,
                },
                "offset": {
                    "type": "integer",
                    "description": "Skip this many lines before reading",
                    "default": 0,
                },
            },
        },
    ),
    Tool(
        name="get_server_config",
        description=(
            "Returns this sylvan server's MCP connection config -- the exact "
            "command, args, and working directory needed to connect to this "
            "instance as an MCP server. Use this to configure SDK clients, "
            "subagents, or other tools that need sylvan MCP access."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="remove_repo",
        description=(
            "Delete an indexed repository and ALL its data (files, symbols, "
            "sections, imports, quality records, references). This is permanent "
            "and cannot be undone. Use list_repos first to verify the repo name."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository name to delete (as shown in list_repos)",
                },
            },
            "required": ["repo"],
        },
    ),
]
