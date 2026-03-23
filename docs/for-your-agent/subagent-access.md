# Subagent Access

When you spawn subagents via Claude Code's Agent tool, they get full access to sylvan's MCP tools. This page explains how it works and how to use it effectively.

## How the Hook Works

The `SubagentStart` hook in `.claude/settings.local.json` runs before every subagent starts. It outputs a JSON payload containing `additionalContext` -- a block of text that Claude Code injects into the subagent's system prompt as a `system-reminder`.

The subagent sees this reminder before it begins working:

> CRITICAL: Always try mcp__sylvan__* tools FIRST before falling back to Read/Grep/Glob. mcp__sylvan__search_symbols to find code, mcp__sylvan__get_symbol to read source, mcp__sylvan__get_file_outline to understand files, mcp__sylvan__find_importers for dependencies, mcp__sylvan__get_blast_radius before refactoring. These return only the exact code you need and save 90%+ tokens. Only fall back to Read/Grep if the repo is not indexed or sylvan returns no results.

Without this hook, subagents default to Read/Grep/Glob even though the `mcp__sylvan__*` tools appear in their deferred tool list.

## What the Subagent Sees

When a subagent starts, it has:

- **Deferred tools** -- all `mcp__sylvan__*` tools appear in `<available-deferred-tools>`. The subagent calls `ToolSearch` to fetch their schemas before use.
- **The system reminder** -- injected by the SubagentStart hook, telling it to prefer sylvan tools.
- **The same MCP server** -- the subagent connects to the same running sylvan instance as the parent agent. Same database, same index, same session.

## How to Prompt Subagents

Always include sylvan instructions in the Agent tool prompt. The hook provides a baseline, but explicit instructions in the prompt reinforce the behavior:

```
Use sylvan MCP tools (mcp__sylvan__search_symbols, mcp__sylvan__get_symbol,
mcp__sylvan__get_file_outline) instead of Read/Grep/Glob.
The project is indexed as repo 'my-project'.
```

Provide the repo name so the subagent does not need to call `list_repos` first.

## The Multi-Instance Cluster

Multiple sylvan server instances can run simultaneously (one per Claude Code session or terminal). They share the same SQLite database and coordinate through a leader-follower model:

| Concern | How it works |
|---|---|
| **Reads** | All instances read concurrently. SQLite WAL mode allows concurrent readers without blocking. |
| **Writes** | Write operations (index_folder, index_file, index_workspace, add_library) are proxied to the leader instance. Followers detect write tools and forward them over HTTP. |
| **Leader election** | The first instance to start becomes the leader. Followers discover the leader through the cluster state file. |
| **Consistency** | All instances see the same data. After a write completes on the leader, followers immediately see the updated index on their next read. |

This means multiple agents can search and browse the index simultaneously without contention. Only writes serialize through the leader.

## Session Tracking

Each sylvan server instance tracks its own session:

- **Tool calls** -- every tool invocation is counted per session
- **Token efficiency** -- tokens returned vs. equivalent file-read cost, broken down by search vs. retrieval
- **Symbols seen** -- which symbols the agent has already retrieved (used to deprioritize repeated results in search)
- **Dashboard** -- each instance appears on the web dashboard with its session stats

Call `get_session_stats` to see current session numbers. The dashboard (via `get_dashboard_url`) shows all instances and their activity.

## Subagent Workflow Example

Parent agent spawns a subagent to investigate a module:

```
Agent tool prompt:
"Investigate the authentication module in the 'backend' repo.
Find all auth-related functions, check their blast radius, and
report which ones have no test coverage.

Use sylvan MCP tools (mcp__sylvan__search_symbols, mcp__sylvan__get_symbol,
mcp__sylvan__get_file_outline, mcp__sylvan__get_blast_radius,
mcp__sylvan__get_quality) instead of Read/Grep/Glob.
The project is indexed as repo 'backend'."
```

The subagent then:

1. Calls `search_symbols(query="auth", repo="backend")` to find symbols
2. Calls `get_symbol` on each result to read source
3. Calls `get_blast_radius` to check impact
4. Calls `get_quality(repo="backend", untested_only=True)` to find gaps
5. Reports back to the parent agent
