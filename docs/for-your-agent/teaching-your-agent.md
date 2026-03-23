# Teaching Your Agent to Use the Tools

Your agent has access to sylvan's MCP tools, but it will default to Read/Grep/Glob unless you force the issue. Three mechanisms work together to fix this.

## 1. The Workflow Guide

`get_workflow_guide` is the first tool your agent should call in every session. It returns:

- **Rules** -- "always search before reading", "use get_symbol instead of Read", "follow _hints in responses", "index before exploring", "add_library before using third-party packages", "use blast_radius before refactoring", and more.
- **Common workflows** -- step-by-step tool chains for:
    - **Understanding a function** -- search, get source, find callers, check blast radius
    - **Exploring an unfamiliar repo** -- index, outline, file tree, suggested queries
    - **Editing code safely** -- search, get source with `_hints`, check blast radius, read exact lines, edit, reindex
    - **Adding a third-party library** -- add_library, search its symbols, read the actual API
    - **Finding dead code** -- find_importers, quality report, blast radius
- **Setup actions** -- if `.claude/settings.local.json` is missing or misconfigured, the response includes exact instructions for what to create or fix, including the complete file content.

### The project_path parameter

The tool takes one parameter:

```
get_workflow_guide(project_path="/absolute/path/to/your/project")
```

The `project_path` must be an absolute path to the project directory where the agent is working. Sylvan uses this path to:

1. Locate `.claude/settings.local.json` and verify it exists and has the correct content
2. Determine which indexed repository corresponds to this project
3. Configure the session for this specific project

If the path is wrong or missing, sylvan cannot verify the settings file and the setup flow will fail.

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

This forces the agent to learn the rules before using the tools. It cannot skip straight to `search_symbols` or `get_symbol` without reading the workflow rules first.

### Why the gate exists

Without the gate, agents call sylvan tools the same way they call Read or Grep -- one-off lookups with no strategy. The workflow guide teaches the agent to:

- Search before reading (saves tokens)
- Follow `_hints` in responses (avoids redundant lookups)
- Check blast radius before refactoring (prevents breakage)
- Reindex after edits (keeps the index fresh)

Once the agent has loaded these rules, it uses sylvan far more effectively for the rest of the session.

### Ungated tools

A small set of tools work without calling the guide first:

- `get_workflow_guide` -- the gate opener itself
- `list_repos` -- so the agent can check what's indexed
- `list_libraries` -- same for libraries
- `get_session_stats` -- session diagnostics
- `get_dashboard_url` -- access the web UI
- `get_server_config` -- server configuration
- `get_logs` -- server logs for debugging
- `suggest_queries` -- entry point suggestions for a repo

Everything else -- search, retrieval, analysis, indexing, workspace tools -- is gated.

## 3. The SubagentStart Hook

When the parent agent spawns a subagent via Claude Code's Agent tool, the subagent starts as a fresh context with no knowledge of sylvan's rules. The SubagentStart hook fixes this by injecting instructions before the subagent begins working.

### How the injection works

1. Claude Code fires the `SubagentStart` event before creating the subagent thread.
2. The hook (defined in `.claude/settings.local.json`) runs a shell command that echoes a JSON payload.
3. Claude Code reads the `additionalContext` field from the payload and injects it as a `system-reminder` in the subagent's system prompt.
4. The subagent sees the reminder before it processes its first message.

### What the hook injects

The injected text is:

> CRITICAL: Always try mcp__sylvan__* tools FIRST before falling back to Read/Grep/Glob. mcp__sylvan__search_symbols to find code, mcp__sylvan__get_symbol to read source, mcp__sylvan__get_file_outline to understand files, mcp__sylvan__find_importers for dependencies, mcp__sylvan__get_blast_radius before refactoring. These return only the exact code you need and save 90%+ tokens. Only fall back to Read/Grep if the repo is not indexed or sylvan returns no results.

This appears as a `<system-reminder>` block in every subagent thread, so the subagent sees it before any user instructions.

### Why this matters

Without the hook, subagents default to Read/Grep/Glob even though `mcp__sylvan__*` tools appear in their `<available-deferred-tools>` list. The tools are available but the subagent has no reason to prefer them over built-in tools. The hook provides that reason.

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

### Where the file goes

The file must be at `<project-root>/.claude/settings.local.json`, where `<project-root>` is the directory you open in Claude Code. This is a per-project file -- each project that uses sylvan needs its own copy.

The file is named `settings.local.json` (not `settings.json`) because it contains project-specific configuration that may vary between developers. It is typically added to `.gitignore`.

## Setup Flow

The complete setup sequence, from first launch to a fully configured session:

1. Agent calls `get_workflow_guide(project_path="/path/to/project")`
2. Sylvan checks `.claude/settings.local.json` at the given path
3. If missing or incomplete: returns `setup_actions` with the exact file content to create
4. Agent creates or fixes the settings file
5. Agent calls `get_workflow_guide` again
6. Sylvan verifies the settings, loads the workflow rules, marks the session as configured
7. All gated tools are now unlocked -- search, retrieval, analysis, etc.
8. Subagents spawned from this point forward receive the sylvan instructions automatically via the SubagentStart hook

If the settings file already exists and is correct, steps 3-5 are skipped and the session is configured on the first call.
