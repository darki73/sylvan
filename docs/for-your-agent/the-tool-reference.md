# The Tool Reference

Complete reference for all 52 sylvan MCP tools. Every parameter, every default.

---

## Indexing (3 tools)

### index_folder

Index a local folder. Run once per project, re-run after code changes. Incremental reindex only processes changed files.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string | yes | -- | Absolute path to the folder to index |
| `name` | string | no | folder name | Display name for the repository |

```
index_folder(path="/home/user/my-project", name="my-project")
```

### index_file

Surgical single-file reindex. Use after editing one file instead of re-indexing the whole folder.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `repo` | string | yes | -- | Repository name (as shown in list_repos) |
| `file_path` | string | yes | -- | Relative path within the repo |

```
index_file(repo="my-project", file_path="src/main.py")
```

### index_workspace

Index multiple folders at once, group them into a workspace, and resolve cross-repo imports.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `workspace` | string | yes | -- | Workspace name |
| `paths` | string[] | yes | -- | List of absolute folder paths to index |
| `description` | string | no | -- | Workspace description |

```
index_workspace(workspace="my-app", paths=["/path/to/frontend", "/path/to/backend"])
```

---

## Search (5 tools)

### search_symbols

Search indexed symbols by name, signature, docstring, or keywords. Returns signatures and locations without reading files.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | yes | -- | Search query (symbol name, keyword, or description) |
| `repo` | string | no | -- | Filter to a specific repository |
| `kind` | string | no | -- | Filter by kind: `function`, `class`, `method`, `constant`, `type` |
| `language` | string | no | -- | Filter by language (e.g., python, typescript, go) |
| `file_pattern` | string | no | -- | Glob pattern to filter by file path |
| `max_results` | integer | no | 20 | Maximum results |
| `token_budget` | integer | no | -- | Greedy-pack results until budget exhausted |

```
search_symbols(query="authenticate", repo="backend", kind="function")
```

### batch_search_symbols

Run multiple symbol searches in one call.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `queries` | object[] | yes | -- | List of search queries. Each has: `query` (required), `repo`, `kind`, `language`, `max_results` |
| `repo` | string | no | -- | Default repo filter for all queries |
| `max_results_per_query` | integer | no | 10 | Default max results per query |

```
batch_search_symbols(queries=[{"query": "auth"}, {"query": "session"}], repo="backend")
```

### search_text

Full-text search across all indexed file content. Use for comments, strings, TODOs, or literal text that search_symbols would not find.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | yes | -- | Text to search for |
| `repo` | string | no | -- | Repository filter |
| `file_pattern` | string | no | -- | Glob pattern for files |
| `max_results` | integer | no | 20 | Maximum results |
| `context_lines` | integer | no | 2 | Lines of context around matches |

```
search_text(query="TODO: fix", repo="backend")
```

### search_sections

Search indexed documentation sections by title, summary, or tags.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `query` | string | yes | -- | Search query |
| `repo` | string | no | -- | Filter to a specific repo |
| `doc_path` | string | no | -- | Filter to a specific document |
| `max_results` | integer | no | 10 | Maximum results |

```
search_sections(query="configuration", repo="my-project")
```

### search_similar_symbols

Find symbols semantically similar to a given source symbol using vector similarity.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `symbol_id` | string | yes | -- | Source symbol ID to find similar symbols for |
| `repo` | string | no | -- | Filter results to a specific repository |
| `max_results` | integer | no | 10 | Maximum similar symbols to return |

```
search_similar_symbols(symbol_id="src/auth.py::login#function", repo="backend")
```

---

## Browsing (11 tools)

### get_symbol

Retrieve the exact source of a function, class, or method by ID.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `symbol_id` | string | yes | -- | Symbol identifier (from search results) |
| `verify` | boolean | no | false | Verify content has not drifted since indexing |
| `context_lines` | integer | no | 0 | Number of surrounding lines to include (0-50) |

```
get_symbol(symbol_id="src/auth.py::login#function")
```

### get_symbols

Batch retrieve multiple symbols at once.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `symbol_ids` | string[] | yes | -- | List of symbol identifiers to retrieve |

```
get_symbols(symbol_ids=["src/auth.py::login#function", "src/auth.py::logout#function"])
```

### get_file_outline

Hierarchical outline of all symbols in a file with signatures and line numbers.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `repo` | string | yes | -- | Repository name |
| `file_path` | string | yes | -- | Relative file path |

```
get_file_outline(repo="backend", file_path="src/auth.py")
```

### get_file_outlines

Batch retrieve outlines for multiple files in one call.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `repo` | string | yes | -- | Repository name |
| `file_paths` | string[] | yes | -- | List of relative file paths |

```
get_file_outlines(repo="backend", file_paths=["src/auth.py", "src/users.py"])
```

### get_file_tree

Compact indented tree of the repo structure with language and symbol counts.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `repo` | string | yes | -- | Repository name |
| `max_depth` | integer | no | 3 | Max directory depth to expand (max: 10) |

```
get_file_tree(repo="backend", max_depth=2)
```

### get_section

Retrieve the exact content of a doc section by ID.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `section_id` | string | yes | -- | Section identifier |
| `verify` | boolean | no | false | Verify content hash |

```
get_section(section_id="docs/config.md::database-setup#section")
```

### get_sections

Batch retrieve multiple doc sections at once.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `section_ids` | string[] | yes | -- | List of section identifiers |

```
get_sections(section_ids=["docs/config.md::setup#section", "docs/config.md::options#section"])
```

### get_toc

Structured table of contents for all indexed docs.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `repo` | string | yes | -- | Repository name |
| `doc_path` | string | no | -- | Filter to a specific document |

```
get_toc(repo="backend")
```

### get_toc_tree

Nested tree table of contents grouped by document.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `repo` | string | yes | -- | Repository name |
| `max_depth` | integer | no | 3 | Max heading depth to include (max: 6) |

```
get_toc_tree(repo="backend", max_depth=2)
```

### get_repo_outline

High-level summary of a repo: file count, languages, symbol breakdown, documentation coverage.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `repo` | string | yes | -- | Repository name |

```
get_repo_outline(repo="backend")
```

### get_context_bundle

Source + imports + callers + sibling symbols in one call. Replaces 3-5 separate Read/Grep calls.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `symbol_id` | string | yes | -- | Symbol to get context for |
| `include_callers` | boolean | no | false | Include caller symbols |
| `include_imports` | boolean | no | true | Include import information |

```
get_context_bundle(symbol_id="src/auth.py::login#function", include_callers=true)
```

---

## Analysis (15 tools)

### get_blast_radius

Show which files and symbols would be affected by changing a symbol. Check this before refactoring.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `symbol_id` | string | yes | -- | Symbol to analyze |
| `depth` | integer | no | 2 | Import hops to follow (1-3) |

```
get_blast_radius(symbol_id="src/auth.py::login#function")
```

### batch_blast_radius

Check blast radius for multiple symbols in one call.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `symbol_ids` | string[] | yes | -- | List of symbol identifiers to analyze |
| `depth` | integer | no | 2 | Import hops to follow (1-3) |

```
batch_blast_radius(symbol_ids=["src/auth.py::login#function", "src/auth.py::logout#function"])
```

### get_class_hierarchy

Traverse class inheritance chains -- ancestors and descendants.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `class_name` | string | yes | -- | Class name to analyze |
| `repo` | string | no | -- | Optional repo filter |

```
get_class_hierarchy(class_name="BaseModel", repo="backend")
```

### get_references

Symbol-level references -- callers or callees.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `symbol_id` | string | yes | -- | Symbol to query |
| `direction` | string | no | "to" | `to` = callers, `from` = callees |

```
get_references(symbol_id="src/auth.py::login#function", direction="to")
```

### find_importers

Find all files that import a given file.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `repo` | string | yes | -- | Repository name |
| `file_path` | string | yes | -- | File to find importers of |
| `max_results` | integer | no | 50 | Maximum results |

```
find_importers(repo="backend", file_path="src/auth.py")
```

### batch_find_importers

Find importers for multiple files in one call.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `repo` | string | yes | -- | Repository name |
| `file_paths` | string[] | yes | -- | List of file paths to find importers of |
| `max_results` | integer | no | 20 | Max importers per file |

```
batch_find_importers(repo="backend", file_paths=["src/auth.py", "src/users.py"])
```

### get_related

Find symbols related to a given symbol by co-location, shared imports, or name similarity.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `symbol_id` | string | yes | -- | Symbol to find relations for |
| `max_results` | integer | no | 10 | Maximum results |

```
get_related(symbol_id="src/auth.py::login#function")
```

### get_dependency_graph

File-level import dependency graph. Shows what a file imports and what imports it.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `repo` | string | yes | -- | Repository name |
| `file_path` | string | yes | -- | File to center the graph on |
| `direction` | string | no | "both" | `imports`, `importers`, or `both` |
| `depth` | integer | no | 1 | Import hops to follow (1-3) |

```
get_dependency_graph(repo="backend", file_path="src/auth.py", direction="imports")
```

### get_symbol_diff

Compare symbols between the current index and a previous git commit.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `repo` | string | yes | -- | Repository name |
| `commit` | string | no | "HEAD~1" | Git ref to compare against |
| `file_path` | string | no | -- | Optional file path filter |
| `max_files` | integer | no | 50 | Maximum files to compare |

```
get_symbol_diff(repo="backend", commit="HEAD~3")
```

### get_git_context

Git blame, change frequency, and recent commits for a file or symbol.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `repo` | string | yes | -- | Repository name |
| `file_path` | string | no | -- | File path |
| `symbol_id` | string | no | -- | Symbol ID (alternative to file_path) |

```
get_git_context(repo="backend", file_path="src/auth.py")
```

### rename_symbol

Find all edit locations needed to rename a symbol. Returns exact file/line/old_text/new_text for each occurrence.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `symbol_id` | string | yes | -- | Symbol to rename |
| `new_name` | string | yes | -- | Desired new name (must be a valid identifier) |

```
rename_symbol(symbol_id="src/auth.py::login#function", new_name="authenticate")
```

### get_recent_changes

Show what changed in the last N commits at the file level.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `repo` | string | yes | -- | Repository name |
| `commits` | integer | no | 5 | Number of commits to look back |
| `file_path` | string | no | -- | Optional file path filter |

```
get_recent_changes(repo="backend", commits=10)
```

### get_quality

Quality metrics per symbol: has_tests, has_docs, has_types, complexity score.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `repo` | string | yes | -- | Repository name |
| `untested_only` | boolean | no | false | Show only untested symbols |
| `undocumented_only` | boolean | no | false | Show only undocumented symbols |
| `min_complexity` | integer | no | 0 | Minimum complexity threshold |
| `limit` | integer | no | 50 | Maximum results |

```
get_quality(repo="backend", untested_only=true)
```

### get_quality_report

Comprehensive quality analysis: test coverage, documentation coverage, code smells, security findings, duplication, quality gate status.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `repo` | string | yes | -- | Repository name |

```
get_quality_report(repo="backend")
```

### search_columns

Search column metadata from ecosystem context providers (dbt, etc.).

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `repo` | string | yes | -- | Repository name |
| `query` | string | yes | -- | Column name or description to search |
| `model_pattern` | string | no | -- | Glob pattern to filter model names |
| `max_results` | integer | no | 20 | Maximum results |

```
search_columns(repo="analytics", query="user_id")
```

---

## Library (5 tools)

### add_library

Index a third-party library's source code for precise API lookup.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `package` | string | yes | -- | Package spec: `manager/name[@version]` (e.g., `pip/django@4.2`, `npm/react@18`, `go/github.com/gin-gonic/gin`) |

```
add_library(package="pip/django@4.2")
```

### list_libraries

List all indexed third-party libraries. No parameters.

```
list_libraries()
```

### remove_library

Remove an indexed library and its source files from disk.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | string | yes | -- | Library name (e.g., `django@4.2`) |

```
remove_library(name="django@4.2")
```

### compare_library_versions

Compare two indexed versions of the same library. Shows added, removed, and changed symbols.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `package` | string | yes | -- | Package name without manager prefix (e.g., `numpy`) |
| `from_version` | string | yes | -- | The old version to compare from |
| `to_version` | string | yes | -- | The new version to compare to |

```
compare_library_versions(package="numpy", from_version="1.26.0", to_version="2.2.2")
```

### check_library_versions

Compare a project's installed dependencies against indexed library versions.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `repo` | string | yes | -- | Indexed repository name to check |

```
check_library_versions(repo="backend")
```

---

## Workspace (5 tools)

### index_workspace

*Also listed under Indexing.* Index multiple folders and group into a workspace.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `workspace` | string | yes | -- | Workspace name |
| `paths` | string[] | yes | -- | List of absolute folder paths |
| `description` | string | no | -- | Workspace description |

```
index_workspace(workspace="my-app", paths=["/path/to/frontend", "/path/to/backend"])
```

### workspace_search

Search symbols across all repos in a workspace.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `workspace` | string | yes | -- | Workspace name |
| `query` | string | yes | -- | Search query |
| `kind` | string | no | -- | Filter by kind: `function`, `class`, `method`, `constant`, `type` |
| `language` | string | no | -- | Filter by language |
| `max_results` | integer | no | 20 | Maximum results |

```
workspace_search(workspace="my-app", query="authenticate")
```

### workspace_blast_radius

Cross-repo blast radius -- shows impact across repositories.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `workspace` | string | yes | -- | Workspace name |
| `symbol_id` | string | yes | -- | Symbol to analyze |
| `depth` | integer | no | 2 | Import hops to follow |

```
workspace_blast_radius(workspace="my-app", symbol_id="shared/types.ts::User#type")
```

### add_to_workspace

Add an already-indexed repo to a workspace.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `workspace` | string | yes | -- | Workspace name |
| `repo` | string | yes | -- | Repository name |

```
add_to_workspace(workspace="my-app", repo="shared-lib")
```

### pin_library

Pin a specific library version to a workspace. The library must already be indexed via add_library.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `workspace` | string | yes | -- | Workspace name |
| `library` | string | yes | -- | Library display name with version (e.g., `numpy@2.2.2`) |

```
pin_library(workspace="my-app", library="numpy@2.2.2")
```

---

## Meta (9 tools)

### get_workflow_guide

Call this first in every session. Returns workflow rules, common tool chains, and checks settings configuration.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `project_path` | string | no | cwd | Absolute path to the project directory |

```
get_workflow_guide(project_path="/home/user/my-project")
```

### list_repos

List all indexed repositories. Shows file count, symbol count, and indexing timestamp. No parameters.

```
list_repos()
```

### remove_repo

Delete an indexed repository and all its data. Permanent and cannot be undone.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `repo` | string | yes | -- | Repository name to delete |

```
remove_repo(repo="old-project")
```

### suggest_queries

Suggest the best queries for exploring a repo. Session-aware.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `repo` | string | yes | -- | Repository name |

```
suggest_queries(repo="backend")
```

### get_session_stats

Usage statistics for the current session, per-project lifetime, and overall.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `repo` | string | no | -- | Show stats for a specific repo |

```
get_session_stats(repo="backend")
```

### get_dashboard_url

Get the URL for the sylvan web dashboard. No parameters.

```
get_dashboard_url()
```

### get_server_config

Returns this server's MCP connection config (command, args, working directory). No parameters.

```
get_server_config()
```

### get_logs

Retrieve sylvan server log entries for debugging.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `lines` | integer | no | 50 | Number of lines to return (1-500) |
| `from_start` | boolean | no | false | Read from beginning instead of end |
| `offset` | integer | no | 0 | Skip this many lines before reading |

```
get_logs(lines=100)
```

### scaffold

Generate a sylvan/ project context directory and agent instructions.

| Parameter | Type | Required | Default | Description |
|---|---|---|---|---|
| `repo` | string | yes | -- | Indexed repo name |
| `agent` | string | no | "claude" | Agent format: `claude`, `cursor`, `copilot`, `generic` |
| `root` | string | no | -- | Override project root path |

```
scaffold(repo="backend", agent="claude")
```
