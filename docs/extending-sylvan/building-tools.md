# Building Tools

There are two ways to add tools to sylvan: **extensions** (recommended for users) and **core tools** (for contributing to sylvan itself). Both use the same `Tool` base class.

## Extension tools (recommended)

Drop a Python file in `~/.sylvan/extensions/tools/` and restart the server. No need to modify sylvan's source code.

```python
# ~/.sylvan/extensions/tools/search_jira.py

from sylvan.tools.base import Tool, HasQuery, HasOptionalRepo, ToolParams, schema_field


class SearchJira(Tool):
    name = "search_jira"
    category = "search"
    description = "Search JIRA tickets linked to code symbols"

    class Params(HasQuery, HasOptionalRepo, ToolParams):
        project: str = schema_field(default="ENG", description="JIRA project key")

    async def handle(self, p: Params) -> dict:
        import httpx

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                "https://jira.company.com/rest/api/2/search",
                params={"jql": f"project={p.project} AND text ~ '{p.query}'"},
                headers={"Authorization": "Bearer ..."},
            )
            data = resp.json()

        return {
            "results": [
                {"key": i["key"], "summary": i["fields"]["summary"]}
                for i in data.get("issues", [])
            ],
        }
```

Extension tools:

- Are auto-discovered and registered on startup (no decorator needed)
- Get the same framework features as core tools: param validation, type coercion, `_meta` envelope, timing, staleness checks, hints
- Use param traits (`HasRepo`, `HasQuery`, `HasPagination`, etc.) for consistent field names
- Can use any Python package installed in sylvan's environment
- Cannot overwrite built-in tools (conflicts are logged and skipped)
- Can use the ORM, context, and all internal sylvan APIs

To disable a specific extension without deleting it:

```yaml
# ~/.sylvan/config.yaml
extensions:
  exclude:
    - tools/search_jira.py
```

## Core tools (for contributors)

Core tools follow the same pattern as extensions but live in `src/sylvan/tools/`.

## The Tool base class

Every tool is a class that inherits from `Tool`:

```python
from sylvan.tools.base import Tool, HasRepo, HasPagination, ToolParams, schema_field

class MyTool(Tool):
    name = "my_tool"            # MCP tool name (unique)
    category = "analysis"       # search, retrieval, analysis, indexing, or meta
    description = "What this tool does, written for the agent."

    class Params(HasRepo, HasPagination, ToolParams):
        threshold: int = schema_field(default=10, ge=1, le=100, description="Minimum score")

    async def handle(self, p: Params) -> dict:
        # Your logic here. Access params as p.repo, p.max_results, p.threshold
        return {"results": [...]}
```

The framework handles everything else:

- **Schema generation**: `inputSchema` is derived from `Params` type hints. No hand-written JSON schemas.
- **Param validation**: required fields, type coercion (`"5"` -> `5`, `"true"` -> `True`), unknown keys filtered.
- **`_meta` envelope**: timing, repo, token efficiency - all automatic.
- **`_version`**: always `"1.0"`.
- **Staleness checks**: if the tool reads indexed data and it's outdated, `_stale` is added automatically.
- **Auto-registration**: defining a Tool subclass registers it. No manual wiring.

## Param traits

Traits are reusable field definitions that guarantee consistent naming. Mix them into your `Params` class:

```python
class Params(HasRepo, HasSymbol, HasPagination, ToolParams):
    pass
```

Available traits:

| Trait | Field | Type | Default |
|---|---|---|---|
| `HasRepo` | `repo` | `str` | required |
| `HasOptionalRepo` | `repo` | `str \| None` | `None` |
| `HasSymbol` | `symbol_id` | `str` | required |
| `HasOptionalSymbol` | `symbol_id` | `str \| None` | `None` |
| `HasQuery` | `query` | `str` | required |
| `HasFilePath` | `file_path` | `str` | required |
| `HasOptionalFilePath` | `file_path` | `str \| None` | `None` |
| `HasPagination` | `max_results` | `int` | `20` |
| `HasDepth` | `depth` | `int` | `2` |
| `HasKindFilter` | `kind` | `str \| None` | `None` |
| `HasLanguageFilter` | `language` | `str \| None` | `None` |
| `HasFileFilter` | `file_pattern` | `str \| None` | `None` |
| `HasWorkspace` | `workspace` | `str` | required |
| `HasProjectPath` | `project_path` | `str` | required |
| `HasContextLines` | `context_lines` | `int` | `0` |
| `HasVerify` | `verify` | `bool` | `False` |
| `HasDirection` | `direction` | `str` | `"both"` |
| `HasMaxDepth` | `max_depth` | `int` | `3` |
| `HasDocPath` | `doc_path` | `str \| None` | `None` |

For tool-specific fields, use `schema_field()`:

```python
class Params(HasRepo, ToolParams):
    threshold: int = schema_field(default=10, ge=1, le=100, description="Minimum score")
    include_tests: bool = schema_field(default=False, description="Include test symbols")
```

### Param constraints

```python
class Params(HasOptionalSymbol, HasOptionalFilePath, ToolParams):
    require_any_of = [("symbol_id", "file_path")]      # at least one must be provided
    mutually_exclusive = [("symbol_id", "file_path")]   # cannot provide both
```

## Token efficiency tracking

Override `measure()` to enable automatic token efficiency in `_meta`:

```python
class MyTool(Tool):
    ...

    def measure(self, result: dict) -> tuple[int, int]:
        from sylvan.tools.support.token_counting import token_len
        returned = token_len(str(result.get("results", [])))
        equivalent = result.get("_raw_file_tokens", 0)
        return returned, equivalent

    def measure_method(self) -> str:
        return MeasureMethod.TIKTOKEN_CL100K
```

## Adding hints

Use `self.hints()` to suggest next actions for the agent:

```python
async def handle(self, p: Params) -> dict:
    result = {"results": symbols}

    if symbols:
        first = symbols[0]
        self.hints() \
            .next_symbol(first["symbol_id"]) \
            .next_blast_radius(first["symbol_id"]) \
            .working_files_from_session() \
            .apply(result)

    return result
```

Available hint methods:

| Method | Purpose |
|---|---|
| `.read(file, start, end)` | Suggest a file region to read |
| `.edit(file, first_line)` | Suggest a symbol to edit |
| `.reindex(repo, file)` | Suggest reindexing after edits |
| `.test_files(paths)` | Suggest test files to run |
| `.next_symbol(id)` | Suggest viewing a symbol |
| `.next_blast_radius(id)` | Suggest checking impact |
| `.next_importers(repo, file)` | Suggest finding dependents |
| `.next_outline(repo, file)` | Suggest viewing file structure |
| `.next_search(query, repo, kind)` | Suggest a narrower search |
| `.next_tool(label, call)` | Suggest any follow-up call |
| `.working_files(files)` | Set relevant files |
| `.for_symbol(id, file, start, end, first_line, repo)` | Standard symbol hint block |

## Typed metadata

Use `get_meta()` for typed metadata in `_meta`:

```python
from sylvan.tools.base.meta import get_meta

async def handle(self, p: Params) -> dict:
    meta = get_meta()
    meta.repo(p.repo)
    meta.results_count(len(results))
    meta.query(p.query)
    return {"results": results}
```

Available methods: `.repo()`, `.repo_id()`, `.results_count()`, `.query()`, `.found()`, `.not_found_count()`, `.files_indexed()`, `.symbols_extracted()`, `.already_seen()`, `.token_efficiency()`, `.extra(key, value)`.

## Presenters

Use presenters for consistent model serialization:

```python
from sylvan.tools.base.presenters import SymbolPresenter, FilePresenter

symbols = [SymbolPresenter.brief(s) for s in results]
files = [FilePresenter.brief(f) for f in importers]
```

| Presenter | Methods |
|---|---|
| `SymbolPresenter` | `.brief()`, `.standard()`, `.full()`, `.sibling()`, `.outline()` |
| `FilePresenter` | `.brief()`, `.with_counts()` |
| `ImportPresenter` | `.standard()` |
| `SectionPresenter` | `.brief()`, `.standard()`, `.full()` |
| `ReferencePresenter` | `.caller()`, `.callee()` |

## File layout

```
src/sylvan/tools/
    base/         -- Tool class, params, hints, meta, presenters
    search/       -- find_code, find_text, find_docs
    browsing/     -- read_symbol, whats_in_file, doc_table_of_contents
    analysis/     -- blast_radius, hierarchy, references, quality
    indexing/     -- index_project, reindex_file
    workspace/    -- index_multi_repo, search_all_repos
    library/      -- add, list, remove
    meta/         -- indexed_repos, where_to_start, generate_project_docs
```

Adding a tool: create one file with one class. No definitions files, no handler registration, no category mapping.

## Testing

```python
import pytest
from sylvan.tools.analysis.my_tool import MyTool

class TestMyTool:
    @pytest.mark.asyncio
    async def test_returns_results(self, orm_ctx):
        tool = MyTool()
        result = await tool.execute({"repo": "test-repo", "threshold": 5})
        assert "results" in result
        assert "_meta" in result

    @pytest.mark.asyncio
    async def test_missing_required_param(self):
        tool = MyTool()
        with pytest.raises(TypeError, match="Missing required parameter"):
            await tool.execute({})
```
