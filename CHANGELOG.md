# Changelog

## 1.4.2

- Deep keyword extraction for k8s resources (all nested keys and values searchable)
- Searching for "nvidia", "gpumem", "secretKeyRef", or any nested field now finds the right resource

## 1.4.1

- Fixed k8s YAML files not being indexed (content handler now runs before language detection)
- Fixed FileImport crash on k8s cross-references (upsert replaced with create)
- Added public Python API: `from sylvan import Sylvan` for programmatic use without MCP

## 1.4.0

### Kubernetes support

- Kubernetes YAML files indexed as first-class symbols with cross-references
- Core k8s: Deployment, StatefulSet, DaemonSet, Job, CronJob, Service, Ingress, ConfigMap, Secret, Namespace, PVC, PV, StorageClass, ServiceAccount, Role, ClusterRole, RoleBinding, HPA, PDB, LimitRange, ResourceQuota, PriorityClass, RuntimeClass, Kustomization
- ArgoCD: Application (single + multi-source), AppProject, ApplicationSet
- External Secrets: ExternalSecret with vault paths and target secret refs
- Traefik: IngressRoute (HTTP/TCP/UDP), Middleware
- Cert-Manager: Certificate, Issuer, ClusterIssuer
- Cross-references: Deployments reference Secrets, ConfigMaps, PVCs, ServiceAccounts, images
- Secret values stripped (data/stringData redacted, key names preserved)
- Helm templates auto-detected and skipped ({{ }} detection)
- Multi-document YAML support (--- separators)
- Unknown CRDs get generic extraction (name, namespace, labels, annotations)

### Native extension system

- Content handler registry: extensions register sniffers to claim file types
- file_processor routes to registered handlers instead of hardcoded logic
- Native extensions shipped with sylvan, loaded at startup
- Pluggable architecture: future content types (Terraform, Docker Compose, etc.) just register a sniffer + handler

## 1.3.5

- Bumped claude-agent-sdk to 0.1.50
- Widened constraints: starlette <2.0.0, pathspec <2.0.0, tree-sitter-language-pack <2.0.0, uv-build <0.12.0
- Updated GitHub Actions: checkout v6, setup-python v6, setup-uv v7
- Added branch protection (CI required, review required, enforce admins)
- Added dependabot auto-merge for patch/minor updates
- Switched CI to PR-only triggers (no redundant runs on merge)
- Removed release drafter (manual releases for now)

## 1.3.4

- Added CI lint for tests/ directory
- Added issue templates (YAML form-based with dropdowns)
- Added PR template with checklist
- Added contributing guide
- Added dependabot config (pip + github-actions, weekly)
- Added release drafter workflow
- Added security policy (GitHub private vulnerability reporting)
- Added docs deployment badge to README
- Ruff formatted all test files
- Version check now only triggers when PyPI has a newer version

## 1.3.3

- Version check on startup, notifies agent when a newer version is available
- Detects install method (pip, uv pip, uv tool, editable) for correct upgrade command
- Update info surfaced in gate response, configure tools, and get_workflow_guide

## 1.3.2

- Added CI workflow (lint + tests on Ubuntu and Windows, Python 3.12/3.13/3.14)
- Applied ruff format across entire codebase
- Switched pre-commit to local ruff via uv
- Updated .gitignore for IDE and AI assistant config directories
- Handle missing `enable_load_extension` on restricted Python builds

## 1.3.1

- Configure tools now return instructions by default instead of writing files directly
- Added `server.auto_configure` option (default false) to opt into direct file writes

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
- Added staleness checks to all retrieval tools (previously only get_symbol had it)
- Added context_lines support to get_symbol (was accepted but ignored)
- Fixed get_toc N+1 query problem (up to 5000 extra DB queries per call)
- Fixed edit hints not generated for get_section and get_context_bundle
- Added server.workflow_gate config option to disable the workflow guide requirement

### Extension system

- Added `~/.sylvan/extensions/` for user-defined extensions (languages, parsers, providers, tools)
- Extensions are Python files using existing decorators (`@register_language`, `@register_parser`, etc.)
- New `@register_tool` decorator for custom MCP tools from extensions
- Extensions validated at startup (syntax check), import errors logged but don't crash the server
- Configurable via `extensions.enabled` and `extensions.exclude` in config.yaml

### Editor configuration tools

- Added `configure_claude_code` - creates .claude/settings.local.json with permissions + SubagentStart hook
- Added `configure_cursor` - creates .cursor/rules/sylvan.md with tool usage instructions
- Added `configure_windsurf` - creates .windsurf/rules/sylvan.md with tool usage instructions
- Added `configure_copilot` - creates .github/copilot-instructions.md with tool routing rules
- All configure_* tools are ungated (can be called without get_workflow_guide first)
- `index_folder` is now ungated (always the first action, shouldn't require setup)

### Dashboard

- Added workspaces page (list workspaces, member repos, file/symbol counts)
- Added extensions page (loaded extension tools, languages, parsers, providers)
- Added history page (past coding sessions with duration, tool calls, efficiency, daily usage stats)
- Fixed null crash on empty language counts in overview
- Fixed N+1 queries in dashboard search (60 queries down to ~5)
- Fixed search page showing library repos in dropdown
- Fixed double-counting tool calls in session stats fallback

### Cluster, search, and cleanup

- Added per-repo efficiency tracking for all search tools (repo_id in meta)
- Added get_quality and get_quality_report to WRITE_TOOLS (followers now proxy to leader)
- Fixed quality metrics not invalidated on reindex (stale rows persisted)
- Removed dead _registered_sessions dict and unused register/deregister endpoints (memory leak)
- Fixed get_file_outlines reporting wrong token efficiency method

Migrated from internal development tracked at gitlab (da1bcbd).

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
