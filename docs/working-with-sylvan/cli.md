# CLI Reference

All commands use the `sylvan` entry point. When invoked with no arguments, it starts the MCP server in stdio mode.

```
sylvan [command] [options]
```


## serve

Start the MCP server.

```
sylvan serve [options]
```

| Option | Default | Description |
|---|---|---|
| `--transport`, `-t` | `stdio` | Transport mode: `stdio`, `sse`, or `http` (streamable-http) |
| `--host` | `127.0.0.1` | Bind address for SSE/HTTP modes |
| `--port`, `-p` | `8420` | Port for SSE/HTTP modes |

Running `sylvan` with no command is equivalent to `sylvan serve`.

```bash
# Default stdio mode (what MCP clients expect)
sylvan serve

# SSE on all interfaces
sylvan serve --transport sse --host 0.0.0.0

# Streamable HTTP on a custom port
sylvan serve --transport http --port 9000
```


## index

Index a local folder for code symbol retrieval.

```
sylvan index <path> [options]
```

| Option | Default | Description |
|---|---|---|
| `--name`, `-n` | directory name | Display name for the repo |
| `--watch`, `-w` | off | Watch for file changes and auto-reindex |

```bash
# Index a project
sylvan index /path/to/my-project

# Index with a custom name
sylvan index /path/to/my-project --name backend

# Index and watch for changes
sylvan index /path/to/my-project --watch
```


## scaffold

Generate a `sylvan/` directory and agent instruction files for a project.

```
sylvan scaffold <repo> [options]
```

| Argument / Option | Default | Description |
|---|---|---|
| `repo` | required | Name of an already-indexed repository |
| `--agent`, `-a` | `claude` | Agent format: `claude`, `cursor`, `copilot`, `generic` |
| `--root`, `-r` | auto-detected | Override project root path |

```bash
# Generate Claude Code instructions
sylvan scaffold my-project

# Generate for Cursor
sylvan scaffold my-project --agent cursor

# Override the project root
sylvan scaffold my-project --root /home/user/projects/my-project
```


## init

Interactive configuration setup. Walks through provider selection for summary generation and embeddings.

```
sylvan init
```

No options. The command prompts for:

1. **Summary provider** -- heuristic (default), Ollama, Claude Code, or Codex CLI
2. Writes the configuration to `~/.sylvan/config.yaml`

```bash
sylvan init
# Sylvan -- first time setup
#
# Summary provider (generates richer search metadata):
#   [1] Heuristic only (no AI, always works) [default]
#   [2] Ollama / local LLM
#   [3] Claude Code (detected)
#   [4] Codex CLI (not detected)
```


## status

Show all indexed repositories with file and symbol counts.

```
sylvan status
```

No options. Prints each repo with its stats:

```
  my-project: 223 files, 1401 symbols (indexed 2026-03-23T10:15:00)
  django@4.2 [library]: 850 files, 12340 symbols (indexed 2026-03-20T08:00:00)
```


## doctor

Diagnose installation health. Checks Python version, SQLite, sqlite-vec, tree-sitter, embedding model, database status, configuration, and indexed repositories.

```
sylvan doctor
```

No options. Output shows pass/fail for each check:

```
Sylvan Doctor

  [+] Python version -- 3.12.4
  [+] SQLite version -- 3.45.1
  [+] sqlite-vec extension -- loaded
  [+] Database -- ~/.sylvan/sylvan.db (42.3 MB)
  [+] Configuration -- summary=heuristic, embedding=sentence-transformers
  [+] Embedding model -- sentence-transformers (384d)
  [+] Indexed repositories -- 3 repos
      my-project: 223 files
      backend: 150 files
      django@4.2: 850 files
  [+] Tree-sitter -- language pack available

  7 passed, 0 failed
```


## shell

Start an interactive Python REPL with the ORM preloaded. All models, the database connection, and the query builder are imported and ready.

```
sylvan shell
```

No options. The shell provides:

- `Symbol`, `Section`, `FileRecord`, `FileImport`, `Repo`, `Blob`, `Reference`, `Quality`, `Workspace` models
- `QueryBuilder` for ad-hoc queries

```python
# Inside the shell
import asyncio
asyncio.run(Symbol.search("parse").where(kind="function").get())
```


## export

Export an indexed repository to JSON.

```
sylvan export <repo> [options]
```

| Option | Default | Description |
|---|---|---|
| `--output`, `-o` | `-` (stdout) | Output file path |
| `--format`, `-f` | `json` | Export format (currently only `json`) |

```bash
# Export to stdout
sylvan export my-project

# Export to a file
sylvan export my-project --output backup.json
```

The output includes all symbols, sections, files, and imports for the repository.


## hook

Handle Claude Code hook events for auto-indexing worktrees. Reads a JSON payload from stdin.

```
sylvan hook <event>
```

| Argument | Description |
|---|---|
| `event` | Event type: `worktree-create` or `worktree-remove` |

This command is called automatically by Claude Code hooks, not manually. It expects a JSON payload on stdin with a `worktreePath` field.


## migrate

Run all pending database migrations. When invoked with no subcommand, applies pending migrations.

```
sylvan migrate [options]
```

| Option | Default | Description |
|---|---|---|
| `--dry-run` | off | Show pending migrations without applying them |

```bash
# Apply all pending migrations
sylvan migrate

# Preview what would be applied
sylvan migrate --dry-run
# Current version: 3
# Pending: 2 migration(s)
#   004: add_quality_table
#   005: add_workspace_table
#
# --dry-run: no migrations applied.
```


### migrate create

Create a new empty migration file.

```
sylvan migrate create <description>
```

| Argument | Description |
|---|---|
| `description` | Human-readable description for the migration |

```bash
sylvan migrate create "add analytics table"
# Created: src/sylvan/database/migrations/006_add_analytics_table.py
# Edit up() and down(), then run: sylvan migrate
```


### migrate rollback

Roll back the most recent migration.

```
sylvan migrate rollback
```

No options. Runs the `down()` function of the last applied migration.

```bash
sylvan migrate rollback
# Current version: 5
# Rolled back: add_workspace_table
```


## library add

Add a third-party library by fetching and indexing its source code.

```
sylvan library add <spec> [options]
```

| Argument / Option | Default | Description |
|---|---|---|
| `spec` | required | Package spec: `manager/name[@version]` (e.g., `pip/django@4.2`) |
| `--timeout`, `-t` | `120` | Fetch timeout in seconds |

```bash
# Index a specific version
sylvan library add pip/django@4.2

# Index latest version
sylvan library add pip/fastapi

# npm package
sylvan library add npm/htmx.org@2.0.8

# With a longer timeout for large packages
sylvan library add pip/tensorflow --timeout 300
```


## library list

List all indexed third-party libraries.

```
sylvan library list
```

No options.

```
  django@4.2: 850 files, 12340 symbols (pip)
  fastapi@0.115.0: 120 files, 890 symbols (pip)
  htmx.org@2.0.8: 15 files, 230 symbols (npm)
```


## library remove

Remove an indexed library and its cached source files.

```
sylvan library remove <name>
```

| Argument | Description |
|---|---|
| `name` | Library name as shown in `library list` (e.g., `django@4.2`) |

```bash
sylvan library remove django@4.2
#   Removed: django@4.2
```


## library update

Update a library to its latest version. Removes the old version and indexes the new one.

```
sylvan library update <name>
```

| Argument | Description |
|---|---|
| `name` | Library name to update |

```bash
sylvan library update django@4.2
# Updating django@4.2...
#   Updated to django@5.1: 14200 symbols
```


## library map

Map a package name to a git repository URL. Use this when a package's registry metadata does not include a source repo link, so `library add` cannot find the source automatically.

```
sylvan library map <spec> <repo_url>
```

| Argument | Description |
|---|---|
| `spec` | Package spec: `manager/name` (e.g., `pip/tiktoken`) |
| `repo_url` | Git repository URL |

Mappings are saved in `~/.sylvan/registry.toml` and reused automatically by `library add`.

```bash
sylvan library map pip/tiktoken https://github.com/openai/tiktoken
#   Mapped pip/tiktoken -> https://github.com/openai/tiktoken
#   Now run: sylvan library add pip/tiktoken
```


## library unmap

Remove a package-to-repo URL mapping.

```
sylvan library unmap <spec>
```

| Argument | Description |
|---|---|
| `spec` | Package spec to remove (e.g., `pip/tiktoken`) |

```bash
sylvan library unmap pip/tiktoken
#   Removed mapping for pip/tiktoken
```


## library mappings

List all user-provided package-to-repo URL mappings.

```
sylvan library mappings
```

No options.

```
  pip/tiktoken -> https://github.com/openai/tiktoken
  pip/tree-sitter -> https://github.com/tree-sitter/py-tree-sitter
```
