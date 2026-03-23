# Subagent Access

When you spawn subagents via Claude Code's Agent tool, they get full access to sylvan's MCP tools. This page explains how it works and how to use it effectively.

## How Subagents Get Tool Access

Subagents in Claude Code inherit the parent session's MCP server connections. This means all `mcp__sylvan__*` tools appear in the subagent's `<available-deferred-tools>` list automatically. The subagent calls `ToolSearch` to fetch a tool's schema, then invokes it like any other tool.

However, having access to the tools is not enough. Without explicit instructions, subagents default to Read/Grep/Glob because those are built-in tools they already know how to use. Two mechanisms ensure subagents prefer sylvan tools instead.

## The SubagentStart Hook

The `SubagentStart` hook in `.claude/settings.local.json` runs before every subagent starts. It outputs a JSON payload containing `additionalContext` -- a block of text that Claude Code injects into the subagent's system prompt as a `system-reminder`.

The hook command:

```json
{
  "type": "command",
  "command": "echo '{\"hookSpecificOutput\":{\"hookEventName\":\"SubagentStart\",\"additionalContext\":\"CRITICAL: Always try mcp__sylvan__* tools FIRST before falling back to Read/Grep/Glob. mcp__sylvan__search_symbols to find code, mcp__sylvan__get_symbol to read source, mcp__sylvan__get_file_outline to understand files, mcp__sylvan__find_importers for dependencies, mcp__sylvan__get_blast_radius before refactoring. These return only the exact code you need and save 90%+ tokens. Only fall back to Read/Grep if the repo is not indexed or sylvan returns no results.\"}}'",
  "timeout": 5
}
```

The subagent sees this reminder before it begins working:

> CRITICAL: Always try mcp__sylvan__* tools FIRST before falling back to Read/Grep/Glob. mcp__sylvan__search_symbols to find code, mcp__sylvan__get_symbol to read source, mcp__sylvan__get_file_outline to understand files, mcp__sylvan__find_importers for dependencies, mcp__sylvan__get_blast_radius before refactoring. These return only the exact code you need and save 90%+ tokens. Only fall back to Read/Grep if the repo is not indexed or sylvan returns no results.

The `matcher: "*"` setting means this hook fires for every subagent, regardless of the prompt content.

## What the Subagent Sees

When a subagent starts, it has:

- **Deferred tools** -- all `mcp__sylvan__*` tools appear in `<available-deferred-tools>`. The subagent calls `ToolSearch` to fetch their schemas before use.
- **The system reminder** -- injected by the SubagentStart hook, telling it to prefer sylvan tools over Read/Grep/Glob.
- **The same MCP server** -- the subagent connects to the same running sylvan instance as the parent agent. Same database, same index, same session.

## How to Prompt Subagents

The hook provides a baseline instruction, but explicit instructions in the Agent tool prompt reinforce the behavior. Always include:

1. Which tools to use
2. The repo name (so the subagent does not need to call `list_repos`)
3. What to search for

**Good prompt:**

```
Investigate the authentication module in the 'backend' repo.
Find all auth-related functions, check their blast radius, and
report which ones have no test coverage.

Use sylvan MCP tools (mcp__sylvan__search_symbols, mcp__sylvan__get_symbol,
mcp__sylvan__get_file_outline, mcp__sylvan__get_blast_radius,
mcp__sylvan__get_quality) instead of Read/Grep/Glob.
The project is indexed as repo 'backend'.
```

**Why this works:** The subagent knows the repo name immediately, knows which specific tools to use for each part of the task, and has the system reminder reinforcing the preference.

**Bad prompt:**

```
Look at the auth code and tell me what it does.
```

This gives the subagent no repo name, no tool guidance, and no specific task. It will fall back to Read/Grep/Glob.

## What the Subagent Does

Given a well-structured prompt, the subagent follows this pattern:

1. Calls `ToolSearch` to fetch schemas for the sylvan tools it needs
2. Calls `search_symbols(query="auth", repo="backend")` to find relevant symbols
3. Calls `get_symbol(symbol_id=...)` on each result to read source code
4. Calls `get_blast_radius(symbol_id=...)` to check impact
5. Calls `get_quality(repo="backend")` or other analysis tools as needed
6. Reports findings back to the parent agent

Each tool call goes to the same sylvan server instance, so the subagent sees the same index as the parent.

## The Multi-Instance Cluster

Multiple sylvan server instances can run simultaneously (one per Claude Code session or terminal). They share the same SQLite database and coordinate through a leader-follower model:

| Concern | How it works |
|---|---|
| **Reads** | All instances read concurrently. SQLite WAL mode allows concurrent readers without blocking. |
| **Writes** | Write operations (index_folder, index_file, index_workspace, add_library) are proxied to the leader instance. Followers detect write tools and forward them over HTTP. |
| **Leader election** | The first instance to start becomes the leader. Followers discover the leader through the cluster state file. |
| **Consistency** | All instances see the same data. After a write completes on the leader, followers immediately see the updated index on their next read. |

This means multiple agents can search and browse the index simultaneously without contention. Only writes serialize through the leader.

## Session Tracking and the Dashboard

Each sylvan server instance tracks its own session. Subagent activity rolls up into the same instance stats as the parent agent (because they share the same server process).

- **Tool calls** -- every tool invocation is counted per instance. When a subagent calls `search_symbols`, it shows up in the same instance's tool call count as the parent.
- **Token efficiency** -- tokens returned vs. equivalent file-read cost, tracked per tool call. The efficiency numbers on the dashboard include both parent and subagent activity.
- **Symbols seen** -- which symbols the agent has already retrieved. This is shared across parent and subagents on the same instance, so a symbol retrieved by the parent will be deprioritized if the subagent searches for related terms.
- **Dashboard visibility** -- open the dashboard (via `get_dashboard_url`) to see all instances and their activity. The Session page shows tool call breakdowns, efficiency rings, and coding session history. Subagent tool calls are not distinguished from parent calls -- they all appear under the same instance.

Call `get_session_stats` to see current session numbers programmatically.

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
3. Calls `get_blast_radius` to check impact of each symbol
4. Calls `get_quality(repo="backend", untested_only=True)` to find coverage gaps
5. Reports back to the parent agent with findings

The parent sees a summary of what the subagent found. The dashboard shows the cumulative tool calls and token savings from both the parent and subagent activity.
