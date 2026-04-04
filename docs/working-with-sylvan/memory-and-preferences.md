# Memory and Preferences

Agents start every session cold. They re-read configuration files, load an
index, and hope for the best. Context from yesterday's session (why a decision
was made, what approach the user prefers, which patterns to avoid) is gone.

Most harnesses have their own memory systems (flat files, markdown with
frontmatter), but those are tied to one tool, one machine, and one user. They
also lack vector search and scope hierarchy.

Sylvan's memory system complements harness memory with project-scoped knowledge
and behavioral preferences that travel with the codebase. Your harness memory
is still the right place for personal identity and cross-project preferences.
Sylvan memory is for context tied to a repository: architecture decisions,
debugging discoveries, project-specific workflow rules. Everything lives in the
same SQLite database as the code index.


## Memories

Memories are project insights, decisions, and context that an agent learns during
a session. They are stored per-repository and searchable via vector similarity.

### Saving a memory

```
save_memory(
    repo="my-project",
    content="Auth middleware rewrite is driven by compliance requirements, not tech debt. Scope decisions should favor compliance over ergonomics.",
    tags=["architecture", "auth", "compliance"]
)
```

```json
{
  "id": 4,
  "status": "created"
}
```

The content should summarize what was learned, decided, or discovered. Tags are
optional but help with filtering in the dashboard.

If the content is very similar to an existing memory (above 92% cosine
similarity), the existing memory is updated instead of creating a duplicate.
This prevents the same insight from being saved ten times across sessions.

### Searching memories

```
search_memory(
    repo="my-project",
    query="auth middleware decision"
)
```

```json
{
  "memories": [
    {
      "id": 4,
      "content": "Auth middleware rewrite is driven by compliance requirements...",
      "tags": ["architecture", "auth", "compliance"],
      "similarity": 0.72,
      "created_at": "2025-03-15T14:32:00+00:00",
      "updated_at": "2025-03-15T14:32:00+00:00"
    }
  ],
  "count": 1
}
```

Results are ranked by semantic similarity. The search uses the same embedding
provider as the code index (sentence-transformers by default, configurable to
Ollama).

### Retrieving and deleting

Direct lookup by ID:

```
retrieve_memory(repo="my-project", id=4)
```

Delete a memory that is no longer accurate:

```
delete_memory(repo="my-project", id=4)
```


## Preferences

Preferences are behavioral instructions that tell agents how to work in a
project. They are structured as key-value pairs with a scope hierarchy.

### Scope levels

Preferences exist at three levels. When the same key appears at multiple scopes,
the narrower scope wins:

| Scope | Applies to | Example |
|-------|-----------|---------|
| `global` | All repositories | "Never add Co-Authored-By lines to commits" |
| `workspace` | All repos in a workspace | "Use pnpm, not npm" |
| `repo` | One specific repository | "Run tests with `uv run pytest tests/ -v`" |

For the same key, repo overrides workspace, workspace overrides global.

### Saving a preference

```
save_preference(
    key="commit_format",
    instruction="Use conventional commits with feat:, fix:, docs: prefixes. Keep messages under 72 characters.",
    scope="global"
)
```

For repo or workspace scope, pass the numeric ID:

```
save_preference(
    key="test_command",
    instruction="Always run tests with uv run pytest, never bare pytest.",
    scope="repo",
    scope_id=1
)
```

If a preference with the same key and scope already exists, it is updated.

### Loading preferences

```
get_preferences(repo="my-project")
```

```json
{
  "preferences": [
    {
      "key": "commit_format",
      "instruction": "Use conventional commits with feat:, fix:, docs: prefixes.",
      "scope": "global",
      "scope_id": null
    },
    {
      "key": "test_command",
      "instruction": "Always run tests with uv run pytest, never bare pytest.",
      "scope": "repo",
      "scope_id": 1
    }
  ],
  "count": 2,
  "scopes_loaded": {
    "global": 1,
    "workspace": 0,
    "repo": 1
  }
}
```

The response merges all applicable scopes. If a global preference and a repo
preference share the same key, only the repo version appears. Semantically
similar instructions across scopes are deduplicated automatically, keeping the
narrower scope.

The `get_preferences` tool description instructs agents to call it at the start
of every session, before doing any work. Without it, agents risk repeating
mistakes the user already corrected in a previous session.

### Deleting a preference

```
delete_preference(key="test_command", scope="repo", scope_id=1)
```


## What to save where

Memories and preferences serve different purposes:

| | Memories | Preferences |
|---|---------|------------|
| **Content** | Insights, decisions, context | Behavioral rules |
| **Search** | Vector similarity | Key lookup, bulk load |
| **Scope** | Per-repository | Global, workspace, or repo |
| **When to save** | Agent learns something | User corrects behavior |
| **When to load** | Agent needs context | Start of every session |

Do not save things that are already in the code (read the code), in git history
(use `git log`), or ephemeral to the current conversation.


## The dashboard

The Memory page in the web dashboard shows both memories and preferences in a
tabbed view. Memories display as cards with repo badges, tags, and content
previews. Click one to see the full content in a dialog. Preferences display
as a table with scope badges (color-coded by level) and an inline form for
adding new ones.

Changes made through MCP tools update the dashboard in real time via WebSocket
push events.
