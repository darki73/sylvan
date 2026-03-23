# The Dashboard

The server includes a web dashboard that provides a visual overview of everything
it tracks -- repositories, libraries, quality metrics, search, and session
activity. It starts automatically when the MCP server starts and runs on a local
port.


## Accessing the dashboard

The dashboard URL is available through:

```
get_dashboard_url()
```

```json
{
  "url": "http://127.0.0.1:32400",
  "status": "running"
}
```

The port is assigned automatically. Open the URL in a browser to see the
dashboard. It runs entirely locally -- no data leaves your machine.


## Overview page

The landing page shows the state of everything the server knows about:

- **Indexed repositories** -- name, file count, symbol count, last indexed time
- **Indexed libraries** -- name, version, symbol count
- **Total symbols** across all repos and libraries
- **Efficiency rings** -- a visual summary of how many tokens have been saved
  across all sessions

This is the page to check when you want to confirm that a repo or library has
been indexed, or to get a quick sense of scale.


## Session page

The session page shows active server instances and their activity:

- **Active instances** -- each running server process, its PID, role (leader or
  follower), and heartbeat status
- **Tool calls** -- total count and breakdown by category (search, retrieval,
  analysis, indexing, meta)
- **Token efficiency** -- tokens returned versus tokens avoided, shown both for
  the current session and overall

The category breakdown helps you understand how your agent is using the server.
Heavy search usage with low retrieval might mean search results are sufficient
on their own. Heavy retrieval with no analysis might mean blast radius checks
are being skipped.


## Search page

The search page provides an interactive symbol search with:

- A search box that queries all indexed repos
- Syntax-highlighted results showing signatures and locations
- Filters for repository, symbol kind, and language

This is useful for quick manual lookups when you want to browse without going
through an agent. Results link to their source locations.


## Quality page

The quality page shows the quality report for each indexed repository:

- Quality gate pass/fail status
- Test coverage and documentation coverage percentages
- Code smells by severity
- Security findings
- Dead code count

Each metric is shown per-repository, so you can compare quality across your
projects at a glance.


## Blast radius page

The blast radius page provides interactive impact analysis:

- Enter a symbol ID to see its blast radius
- Results are shown as a Mermaid graph -- nodes are files, edges are import
  relationships, confirmed impact is highlighted
- The graph updates in place as you explore different symbols

This is the visual version of `get_blast_radius`, useful when you want to see
the dependency structure rather than read it as JSON.


## Auto-updating

All dashboard pages update automatically via HTMX polling. When you index a new
repo, add a library, or make tool calls, the dashboard reflects the changes
without needing a manual refresh. Session statistics, efficiency numbers, and
instance status all update in near real-time.
