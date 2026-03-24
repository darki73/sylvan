# Changelog

## 1.3.0

Database foundation, integrity fixes, and audit-driven improvements.

- Fixed double counting of token efficiency in get_symbol/get_section (session stats were ~2x inflated)
- Fixed double counting of tool calls in search_symbols
- Fixed OR precedence bug in quality tools (cross-repo data contamination in duplicate detection, test coverage)
- Fixed remove_library leaving all associated data orphaned (now does full cascade delete)
- Fixed remove_repo missing usage_stats and workspace_repos cleanup, wrapped in transaction
- Fixed find_dead_code flagging all symbols as dead when references table is empty
- Fixed get_references returning silent empty results when reference graph not built
- Fixed shell command being unusable (no database backend)
- Fixed record_section_access missing thread lock
- Fixed index_file missing transaction wrapping, import resolution, and background tasks (now matches index_folder)
- Fixed vec table entries (symbols_vec, sections_vec) not cleaned up on re-index
- Fixed repo upsert running outside transaction in index_folder
- Fixed shutdown not stopping heartbeat and dashboard tasks (instances stuck with ended_at IS NULL)
- Fixed normal exit path missing flush_all (usage stats lost on graceful shutdown)
- Fixed batch tools (get_symbols, get_sections, batch_search_symbols) not recording session activity
- Fixed search_text, search_sections, search_similar_symbols missing query recording
- Changed dead instance cleanup to retain ended instances for 7 days (dashboard visibility)

## 1.2.1

- `get_symbol` now accepts optional `repo` param for disambiguation in multi-repo workspaces
- Cache key includes repo for correct per-repo caching

## 1.2.0

Major extraction improvements for Vue/Nuxt and TypeScript projects:

- Vue SFC: extracts symbols from `<script setup lang="ts">` blocks
- TypeScript: extracts `const` assignments — arrow functions, reactive state (`ref`, `computed`), Vue macros (`defineProps`, `defineEmits`, `withDefaults`), composable calls (`useAuth`, `useFetch`), and literal constants
- TypeScript: extracts destructured composable returns (`const { t } = useI18n()`)
- Nuxt: extracts `export default defineEventHandler()` from server routes using filename as symbol name
- Fixed `.vue` file detection (language registry fallback to extension map)

On a real Nuxt 4 project: 364 → 2,891 symbols (~8x improvement).

## 1.1.6

- Vue SFC support: extracts symbols from `<script setup lang="ts">` blocks as TypeScript
- Byte offsets adjusted to point into the original `.vue` file

## 1.1.5

- Fixed: workflow gate now runs before write proxy — followers enforce `get_workflow_guide` before any tool call
- Agents can no longer bypass the guide by calling write tools directly on followers

## 1.1.4

- Fixed: leader auto-unlocks session for proxied tool calls from followers (workflow gate blocked write tools in cluster mode)

## 1.1.3

- Fixed: follower now promotes to leader when leader process dies (checked every heartbeat)
- Fixed: query cache entries expire after 30s to prevent stale reads after CLI reindex
- Promotion starts the dashboard and claims the leader file automatically

## 1.1.2

- Fixed: `sylvan remove` now commits deletes (data wasn't persisting across runs)
- Fixed: `sylvan remove` on nonexistent repo shows clean message instead of traceback + hang
- Fixed: `remove` command in CLI docs

## 1.1.1

- Fixed: CLI indexing now waits for background tasks (embeddings, summaries) before exiting — no more lost embeddings
- Fixed: `sylvan library add` same issue
- Added: `sylvan remove <name>` command to delete an indexed repo and all its data
- Added: `drain_pending_tasks()` helper in context module

## 1.1.0

- Workspace CLI commands: `workspace create`, `workspace list`, `workspace add`, `workspace show`, `workspace remove`
- CLI reference page in docs
- Installation docs cover `uv tool install`, project dependency, and cloned repo setups
- Dashboard blast radius page: search autocomplete fixed, single-input flow
- Enriched docs for dashboard, agent integration, and subagent access

## 1.0.0

Initial release.

- 52 MCP tools for search, browsing, analysis, indexing, and workspace management
- 34 programming languages via tree-sitter
- Hybrid search: FTS5 full-text + sqlite-vec vector similarity with RRF fusion
- Laravel-style schema builder with Blueprint DSL for migrations
- Async ORM with fluent QueryBuilder, aggregates, subquery chains, grouped conditions
- Third-party library indexing (pip, npm, cargo, go)
- Multi-repo workspaces with cross-repo blast radius and dependency analysis
- Web dashboard with live token efficiency tracking, session history, quality reports
- Multi-instance cluster: leader election, write proxying, heartbeat
- Self-configuring workflow guide with SubagentStart hook injection
- 1401 tests
