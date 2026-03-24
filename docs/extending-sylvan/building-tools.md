# Building Tools

There are two ways to add tools to sylvan: **extensions** (recommended for users) and **core tools** (for contributing to sylvan itself).

## Extension tools (recommended)

Drop a Python file in `~/.sylvan/extensions/tools/` and restart the server. No need to modify sylvan's source code.

```python
# ~/.sylvan/extensions/tools/search_jira.py

from sylvan.extensions import register_tool

@register_tool(
    name="search_jira",
    description="Search JIRA tickets linked to code symbols",
    schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query for JIRA tickets",
            },
            "project": {
                "type": "string",
                "description": "JIRA project key (default: ENG)",
            },
        },
        "required": ["query"],
    },
)
async def search_jira(query: str, project: str = "ENG") -> dict:
    """Search JIRA for tickets matching the query."""
    import httpx

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://jira.company.com/rest/api/2/search",
            params={"jql": f"project={project} AND text ~ '{query}'"},
            headers={"Authorization": "Bearer ..."},
        )
        data = resp.json()

    return {
        "tickets": [
            {"key": i["key"], "summary": i["fields"]["summary"]}
            for i in data.get("issues", [])
        ],
    }
```

Extension tools:

- Are automatically registered as MCP tools on startup
- Can use any Python package installed in sylvan's environment
- Cannot overwrite built-in tools (conflicts are logged and skipped)
- Are categorized as "extension" for usage tracking
- Are ungated (no workflow guide needed)
- Can use the ORM, context, and all internal sylvan APIs

To disable a specific extension without deleting it:

```yaml
# ~/.sylvan/config.yaml
extensions:
  exclude:
    - tools/search_jira.py
```

## Core tools (for contributors)

MCP tools are async Python functions that query the database, format results,
and return a response envelope. Adding one takes four steps: write the handler,
define the schema, register the handler, and categorize it for tracking.

## Anatomy of a tool handler

Here is the real `search_symbols` handler, trimmed for clarity:

```python
# src/sylvan/tools/search/search_symbols.py

from sylvan.tools.support.response import (
    MetaBuilder, ensure_orm, log_tool_call, wrap_response, clamp,
)

@log_tool_call
async def search_symbols(
    query: str,
    repo: str | None = None,
    kind: str | None = None,
    max_results: int = 20,
) -> dict:
    from sylvan.context import get_context
    meta = MetaBuilder()
    ensure_orm()

    max_results = clamp(max_results, 1, 1000)

    query_builder = Symbol.search(query)
    if repo:
        query_builder = query_builder.in_repo(repo)
    if kind:
        query_builder = query_builder.where(kind=kind)

    results = await query_builder.limit(max_results).get()

    formatted = [format_symbol(s) for s in results]
    meta.set("results_count", len(formatted))
    meta.set("query", query)

    returned_tokens = sum(estimate(e) for e in formatted)
    meta.record_token_efficiency(returned_tokens, equivalent_tokens)

    return wrap_response({"symbols": formatted}, meta.build())
```

### Key patterns

| Pattern | Purpose |
|---|---|
| `@log_tool_call` | Logs entry, exit, duration, and errors automatically |
| `MetaBuilder()` | Starts a timing clock; collects metadata for the response |
| `ensure_orm()` | Guards that the async storage backend is available |
| `clamp(value, low, high)` | Bounds user input to safe ranges |
| `meta.record_token_efficiency(returned, equivalent)` | Tracks how many tokens were saved vs a raw file read |
| `wrap_response(data, meta.build())` | Wraps the payload with `_meta` and `_version` |

## Step 1: Write the handler

Create a new file in the appropriate `tools/` subdirectory:

```
src/sylvan/tools/
    search/       -- search_symbols, search_text, search_sections
    browsing/     -- get_symbol, get_file_outline, get_toc
    analysis/     -- blast_radius, hierarchy, references, quality
    indexing/     -- index_folder, index_file
    workspace/    -- index_workspace, workspace_search
    library/      -- add, list, remove
    meta/         -- list_repos, suggest_queries, scaffold
```

### Minimal handler template

```python
# src/sylvan/tools/analysis/my_tool.py

from sylvan.tools.support.response import (
    MetaBuilder,
    ensure_orm,
    log_tool_call,
    wrap_response,
)


@log_tool_call
async def my_tool(repo: str, threshold: int = 10) -> dict:
    """Analyze something interesting in a repository.

    Args:
        repo: Repository name.
        threshold: Minimum score to include.

    Returns:
        Tool response dict with results and _meta envelope.
    """
    from sylvan.database.orm.models import Symbol, Repo

    meta = MetaBuilder()
    ensure_orm()

    repo_obj = await Repo.where(name=repo).first()
    if not repo_obj:
        return wrap_response(
            {"error": f"Repository '{repo}' not found"},
            meta.build(),
        )

    results = await (
        Symbol.where(repo_id=repo_obj.id)
        .where("complexity", ">", threshold)
        .order_by("complexity", "DESC")
        .limit(50)
        .get()
    )

    formatted = [
        {"name": s.name, "file": s.file_path, "complexity": s.complexity}
        for s in results
    ]

    meta.set("results_count", len(formatted))

    return wrap_response({"results": formatted}, meta.build())
```

## Step 2: Define the tool schema

Add a `Tool(...)` entry to the appropriate definitions file. Tool schemas use
the MCP `Tool` class with a JSON Schema `inputSchema`:

```python
# src/sylvan/tools/definitions/analysis.py

from mcp.types import Tool

TOOLS: list[Tool] = [
    # ... existing tools ...
    Tool(
        name="my_tool",
        description=(
            "Analyze something interesting. Returns items above "
            "the given complexity threshold."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository name",
                },
                "threshold": {
                    "type": "integer",
                    "description": "Minimum complexity score (default: 10)",
                    "default": 10,
                },
            },
            "required": ["repo"],
        },
    ),
]
```

There are three definition files:

- `tools/definitions/core.py` -- indexing, search, browsing (the most-used tools)
- `tools/definitions/analysis.py` -- blast radius, hierarchy, quality, etc.
- `tools/definitions/support.py` -- workspace, library, scaffold, meta

## Step 3: Register the handler

Add the import and mapping in `_get_handlers()` in `src/sylvan/server/__init__.py`:

```python
@functools.cache
def _get_handlers() -> dict[str, Callable[..., dict]]:
    # ... existing imports ...
    from sylvan.tools.analysis.my_tool import my_tool

    return {
        # ... existing handlers ...
        "my_tool": my_tool,
    }
```

The key must exactly match the `name` in your `Tool(...)` definition.

## Step 4: Add to _TOOL_CATEGORIES

The `_TOOL_CATEGORIES` dict in the same file tracks which category each tool
belongs to for usage statistics:

```python
_TOOL_CATEGORIES: dict[str, str] = {
    # ... existing entries ...
    "my_tool": "analysis",
}
```

Categories: `"search"`, `"retrieval"`, `"analysis"`, `"indexing"`, `"meta"`.

## The response envelope

Every tool response has this shape:

```python
{
    "results": [...],          # your data
    "_meta": {
        "timing_ms": 12.3,
        "results_count": 5,
        "token_efficiency": {
            "returned": 340,
            "equivalent_file_read": 2800,
            "reduction_percent": 87.9,
            "method": "tiktoken_cl100k",
        },
    },
    "_version": "1.0",
}
```

Build it with `MetaBuilder` and `wrap_response`:

```python
meta = MetaBuilder()                              # starts the clock
meta.set("results_count", len(results))           # add any key-value pairs
meta.record_token_efficiency(340, 2800)           # optional savings tracking
result = wrap_response({"results": data}, meta.build())
```

### Adding edit hints

Pass `include_hints=True` to `wrap_response` for tools that return symbol
source. This appends `_hints` with:

- `working_files` -- files the agent is currently editing (from session tracker)
- `edit` -- `read_file`, `read_offset`, `read_limit` for the Edit tool
- `next` -- suggested follow-up tool calls (find_importers, blast_radius, etc.)

```python
return wrap_response(data, meta.build(), include_hints=True)
```

## Testing

Tools are async functions that need a `SylvanContext` with a backend. Tests use
`set_context()` for isolation:

```python
# tests/test_tools/test_my_tool.py

import pytest
from sylvan.context import SylvanContext, set_context

class TestMyTool:
    @pytest.fixture(autouse=True)
    async def setup(self, backend):
        ctx = SylvanContext(backend=backend)
        set_context(ctx)

    async def test_returns_results(self, indexed_repo):
        from sylvan.tools.analysis.my_tool import my_tool
        result = await my_tool(repo="test-repo", threshold=5)
        assert "results" in result
        assert "_meta" in result
        assert result["_meta"]["timing_ms"] >= 0

    async def test_unknown_repo(self):
        from sylvan.tools.analysis.my_tool import my_tool
        result = await my_tool(repo="nonexistent")
        assert "error" in result
```

Run with:

```bash
uv run pytest tests/test_tools/test_my_tool.py -v
```
