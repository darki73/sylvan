# Changelog

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
