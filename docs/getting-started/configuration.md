# Configuration

All settings live in a single YAML file at `~/.sylvan/config.yaml`. The server creates this directory on first run. Every option has a sensible default -- you only need to add entries for things you want to change.

To override the config directory location, set the `SYLVAN_HOME` environment variable:

```bash
export SYLVAN_HOME=/opt/sylvan
```

The config file, database, logs, and library sources will all live under that directory instead of `~/.sylvan`.

To bootstrap a config file interactively:

```bash
sylvan init
```

## Server

Controls how the MCP server listens for connections.

```yaml
server:
  transport: stdio          # "stdio", "sse", or "http"
  host: 127.0.0.1           # Bind address for SSE/HTTP
  port: 8420                # Port for SSE/HTTP
  max_concurrent_tools: 8   # Parallel tool calls (semaphore size)
  request_timeout: 30       # Seconds before returning server_busy
  dashboard_port: 32400     # Port for the web dashboard
  dashboard_random_port: false  # Use a random available port for the dashboard
```

| Option | Default | Description |
|--------|---------|-------------|
| `transport` | `stdio` | Transport mode. Use `stdio` for subprocess-based agents, `sse` or `http` for network-based agents. |
| `host` | `127.0.0.1` | Bind address. Set to `0.0.0.0` to accept connections from other machines. |
| `port` | `8420` | Listen port for SSE and HTTP transports. |
| `max_concurrent_tools` | `8` | Maximum tool calls processed in parallel. Increase if your agent batches many calls. |
| `request_timeout` | `30` | Seconds to wait for a tool slot before returning a `server_busy` error. |
| `dashboard_port` | `32400` | Port for the built-in web dashboard. |
| `dashboard_random_port` | `false` | When true, picks a random available port for the dashboard instead of using `dashboard_port`. |

## Database

Where the index is stored.

```yaml
database:
  backend: sqlite           # "sqlite" or "postgres"
  path: ~/.sylvan/sylvan.db # File path (SQLite) or DSN (PostgreSQL)
  pool_size: 1              # Connection pool size
```

| Option | Default | Description |
|--------|---------|-------------|
| `backend` | `sqlite` | Storage backend. SQLite ships built-in and requires no setup. |
| `path` | `~/.sylvan/sylvan.db` | Database file path for SQLite, or a connection DSN for PostgreSQL. |
| `pool_size` | `1` | Connection pool size. Keep at 1 for SQLite; increase for PostgreSQL. |

## Embedding

Controls semantic vector search. The default provider runs locally with no external dependencies.

```yaml
embedding:
  provider: sentence-transformers
  model: sentence-transformers/all-MiniLM-L6-v2
  dimensions: 384
  endpoint: ""
```

| Option | Default | Description |
|--------|---------|-------------|
| `provider` | `sentence-transformers` | Embedding provider. Options: `sentence-transformers` (local), `ollama` (local LLM). |
| `model` | `sentence-transformers/all-MiniLM-L6-v2` | Model identifier. Change this if using a different model with your provider. |
| `dimensions` | `384` | Vector dimensionality. Must match the model's output dimensions. |
| `endpoint` | `""` | Remote endpoint URL. Required for `ollama` (e.g., `http://localhost:11434`). |

## Summary

AI-generated summaries for symbols and sections. The default provider uses heuristic extraction with no external calls.

```yaml
summary:
  provider: heuristic
  endpoint: ""
  model: ""
```

| Option | Default | Description |
|--------|---------|-------------|
| `provider` | `heuristic` | Summary provider. Options: `heuristic` (no AI, extracts from docstrings), `ollama`, `claude-code`, `codex`. |
| `endpoint` | `""` | Remote endpoint URL. Required for `ollama`. |
| `model` | `""` | Model identifier for the provider. |

## Search

Tuning knobs for search result ranking.

```yaml
search:
  default_max_results: 20
  token_budget: null
  fts_weight: 0.7
  vector_weight: 0.3
```

| Option | Default | Description |
|--------|---------|-------------|
| `default_max_results` | `20` | Maximum results returned by search tools. |
| `token_budget` | `null` | When set, search greedily packs results until this token budget is exhausted. |
| `fts_weight` | `0.7` | Weight for full-text search relevance in hybrid search (0 to 1). |
| `vector_weight` | `0.3` | Weight for vector similarity in hybrid search (0 to 1). |

The two weights control the balance in hybrid search. The defaults favor keyword matching (0.7) over semantic similarity (0.3). If your queries are more natural-language ("find the function that handles login"), increase `vector_weight`. If your queries are more exact ("authenticate_request"), keep the defaults.

## Indexing

Limits for the indexing pipeline.

```yaml
indexing:
  max_file_size: 512000
  max_files_local: 5000
  max_files_github: 10000
  source_roots:
    - ""
    - "src/"
    - "lib/"
    - "app/"
```

| Option | Default | Description |
|--------|---------|-------------|
| `max_file_size` | `512000` | Maximum file size in bytes. Files larger than this are skipped. |
| `max_files_local` | `5000` | Maximum files to index for a local repository. |
| `max_files_github` | `10000` | Maximum files to index for a remote repository. |
| `source_roots` | `["", "src/", "lib/", "app/"]` | Prefix paths to try when resolving import specifiers. |

## Cluster

Multi-instance coordination for environments running multiple server instances.

```yaml
cluster:
  enabled: true
  port: 32400
  heartbeat_interval: 10
  leader_timeout: 30
```

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | `true` | Whether multi-instance coordination is active. |
| `port` | `32400` | HTTP port for cluster communication. |
| `heartbeat_interval` | `10` | Seconds between session stat flushes. |
| `leader_timeout` | `30` | Seconds before a dead leader is considered gone. |

## Libraries

Settings for third-party library indexing.

```yaml
libraries:
  path: ~/.sylvan/libraries
  fetch_timeout: 120
  overrides:
    pip/mypackage: https://github.com/org/mypackage
```

| Option | Default | Description |
|--------|---------|-------------|
| `path` | `~/.sylvan/libraries` | Directory where downloaded library sources are stored. |
| `fetch_timeout` | `120` | Timeout in seconds for fetching library source code. |
| `overrides` | `{}` | Manual package-to-repo URL mappings. Use this when automatic resolution picks the wrong repository. |

To add library overrides from the CLI:

```bash
sylvan library map pip/mypackage https://github.com/org/mypackage
```

## Quality

Thresholds for the quality analysis tools (`find_tech_debt`, `code_health_report`).

```yaml
quality:
  max_complexity: 25
  max_function_length: 200
  max_parameters: 8
  min_doc_coverage: 80.0
  min_test_coverage: 60.0
  security_scan: true
  duplication_min_lines: 5
```

| Option | Default | Description |
|--------|---------|-------------|
| `max_complexity` | `25` | Maximum cyclomatic complexity before a function is flagged. |
| `max_function_length` | `200` | Maximum function length in lines. |
| `max_parameters` | `8` | Maximum parameters per function. |
| `min_doc_coverage` | `80.0` | Minimum documentation coverage percentage. |
| `min_test_coverage` | `60.0` | Minimum test coverage percentage. |
| `security_scan` | `true` | Enable security pattern scanning (hardcoded secrets, SQL injection, etc.). |
| `duplication_min_lines` | `5` | Minimum function length in lines for duplication detection. |

## Logging

```yaml
logging:
  level: INFO
  file_max_bytes: 10485760    # 10 MB
  file_backup_count: 3
```

| Option | Default | Description |
|--------|---------|-------------|
| `level` | `INFO` | Minimum log level. Options: `DEBUG`, `INFO`, `WARNING`, `ERROR`. |
| `file_max_bytes` | `10485760` | Maximum log file size before rotation (default 10 MB). |
| `file_backup_count` | `3` | Number of rotated log files to keep. |

## Session

```yaml
session:
  flush_interval: 5
```

| Option | Default | Description |
|--------|---------|-------------|
| `flush_interval` | `5` | Number of tool calls between usage stat flushes. |

## Security

```yaml
security:
  validate_paths: true
  detect_secrets: true
  reject_symlinks: true
```

| Option | Default | Description |
|--------|---------|-------------|
| `validate_paths` | `true` | Enable path traversal validation during indexing. |
| `detect_secrets` | `true` | Detect and exclude files that look like secrets (`.env`, credentials, private keys). |
| `reject_symlinks` | `true` | Reject symlinks that escape the project root directory. |

## Extensions

Controls the user extension system. Extensions are Python files in `~/.sylvan/extensions/` that add custom languages, parsers, providers, or tools.

```yaml
extensions:
  enabled: true
  exclude:
    - tools/broken_experiment.py
```

| Option | Default | Description |
|--------|---------|-------------|
| `enabled` | `true` | Whether to load extensions from `~/.sylvan/extensions/` at startup. |
| `exclude` | `[]` | List of extension files to skip, relative to the extensions directory (e.g. `tools/my_tool.py`). |

See [Building Tools](../extending-sylvan/building-tools.md) for how to create extension tools.

## Complete example

A config file that uses Ollama for embeddings, relaxes quality thresholds, and maps a custom package:

```yaml
server:
  transport: sse
  host: 0.0.0.0
  port: 9000

embedding:
  provider: ollama
  endpoint: http://192.168.1.100:11434
  model: nomic-embed-text
  dimensions: 768

search:
  fts_weight: 0.5
  vector_weight: 0.5

quality:
  max_complexity: 30
  max_function_length: 300

libraries:
  overrides:
    pip/my-internal-lib: https://gitlab.internal/team/my-internal-lib
```

Only the sections that differ from defaults need to appear in the file. Everything else uses the built-in defaults.
