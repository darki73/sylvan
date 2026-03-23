# Teaching Your Agent to Use the Tools

Your agent has access to sylvan's MCP tools, but it will default to Read/Grep/Glob unless you force the issue. Three mechanisms work together to fix this.

## 1. The Workflow Guide

`get_workflow_guide` is the first tool your agent should call in every session. It returns:

- **Rules** -- "always search before reading", "use get_symbol instead of Read", "follow _hints in responses", etc.
- **Common workflows** -- step-by-step tool chains for code exploration, safe editing, dependency analysis, and library integration.
- **Setup actions** -- if `.claude/settings.local.json` is missing or misconfigured, the response includes exact instructions for what to create or fix.

When the agent calls `get_workflow_guide` with the project path, sylvan checks the settings file, loads the rules into the session, and unlocks all other tools.

```
get_workflow_guide(project_path="/absolute/path/to/your/project")
```

Once the guide is loaded, the session is marked as configured and the tool gate (below) opens.

## 2. The Tool Gate

Until `get_workflow_guide` has been called and the session is configured, **all gated tools return `setup_required: true`** instead of real results. The response looks like:

```json
{
  "setup_required": true,
  "message": "Sylvan session is not configured. Call get_workflow_guide first to load the tool usage rules, then retry your request.",
  "blocked_tool": "search_symbols",
  "blocked_args": { "query": "..." }
}
```

This forces the agent to learn the rules before using the tools. It cannot skip straight to `search_symbols` or `get_symbol`.

A small set of tools are **ungated** and work without calling the guide first:

- `get_workflow_guide`
- `list_repos`
- `list_libraries`
- `get_session_stats`
- `get_dashboard_url`
- `get_server_config`
- `get_logs`
- `suggest_queries`

Everything else is gated.

## 3. The SubagentStart Hook

A hook in `.claude/settings.local.json` injects instructions into every subagent spawned by Claude Code's Agent tool. Without this hook, subagents will default to Read/Grep/Glob even though they have access to the sylvan tools.

The hook outputs a JSON payload with `additionalContext` that tells the subagent:

> CRITICAL: Always try mcp__sylvan__* tools FIRST before falling back to Read/Grep/Glob. mcp__sylvan__search_symbols to find code, mcp__sylvan__get_symbol to read source, mcp__sylvan__get_file_outline to understand files, mcp__sylvan__find_importers for dependencies, mcp__sylvan__get_blast_radius before refactoring. These return only the exact code you need and save 90%+ tokens. Only fall back to Read/Grep if the repo is not indexed or sylvan returns no results.

This text appears as a `system-reminder` in every subagent thread, so the subagent sees the instructions before it starts working.

## The Complete Settings File

When `get_workflow_guide` detects that `.claude/settings.local.json` is missing, it returns a `setup_actions` response with the exact file content to create. Here is the complete file:

```json
{
  "permissions": {
    "allow": [
      "mcp__sylvan__*"
    ]
  },
  "hooks": {
    "SubagentStart": [
      {
        "matcher": "*",
        "hooks": [
          {
            "type": "command",
            "command": "echo '{\"hookSpecificOutput\":{\"hookEventName\":\"SubagentStart\",\"additionalContext\":\"CRITICAL: Always try mcp__sylvan__* tools FIRST before falling back to Read/Grep/Glob. mcp__sylvan__search_symbols to find code, mcp__sylvan__get_symbol to read source, mcp__sylvan__get_file_outline to understand files, mcp__sylvan__find_importers for dependencies, mcp__sylvan__get_blast_radius before refactoring. These return only the exact code you need and save 90%+ tokens. Only fall back to Read/Grep if the repo is not indexed or sylvan returns no results.\"}}'",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

Place this file at `<project-root>/.claude/settings.local.json`.

**What each section does:**

| Section | Purpose |
|---|---|
| `permissions.allow` | Auto-approves all `mcp__sylvan__*` tool calls so the agent does not prompt for confirmation on every call |
| `hooks.SubagentStart` | Runs a shell command before every subagent starts. The command echoes a JSON payload that Claude Code injects as `additionalContext` into the subagent's system prompt |
| `matcher: "*"` | The hook fires for all subagent prompts, not just specific patterns |
| `timeout: 5` | The echo command must complete within 5 seconds (it is instant) |

## Setup Flow

1. Agent calls `get_workflow_guide(project_path="/path/to/project")`
2. Sylvan checks `.claude/settings.local.json`
3. If missing or incomplete: returns `setup_actions` with exact file content
4. Agent creates/fixes the settings file
5. Agent calls `get_workflow_guide` again
6. Sylvan verifies the settings, marks the session as configured
7. All tools are now unlocked
8. Subagents spawned from this point forward receive the sylvan instructions automatically
