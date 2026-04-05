# The Dashboard

The server includes a web dashboard that provides a visual overview of everything
it tracks -- repositories, libraries, quality metrics, search, and session
activity. It starts automatically when the MCP server starts and runs on a local
port.


## Accessing the dashboard

The dashboard URL is available through the MCP tool:

```
open_dashboard()
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

- **Indexed repositories** -- each repo listed with its name, file count, symbol
  count, section count, last indexed timestamp, and abbreviated git HEAD hash.
  Languages used in each repo are broken down by file count.
- **Indexed libraries** -- each third-party library with its name, version,
  package manager, symbol count, and source repo URL.
- **Totals** -- aggregate counts across all repos and libraries: total files,
  total symbols, total sections, number of repos, number of libraries.
- **Session efficiency ring** -- a circular visualization showing token savings
  for the current session. The ring displays tokens returned vs. tokens that
  would have been consumed by equivalent file reads. The percentage in the center
  is the reduction rate (e.g., "82%" means 82% fewer tokens were used).
- **All-time efficiency ring** -- a second ring showing cumulative token savings
  across all sessions ever recorded. This aggregates data from the `coding_sessions`
  and `instances` tables, so the numbers persist across server restarts.
- **Tool call counts** -- total tool invocations for the current session, broken
  down by category.

This is the page to check when you want to confirm that a repo or library has
been indexed, or to get a quick sense of scale.


## Session page

The session page shows active server instances and their activity:

- **Cluster role** -- whether this instance is the leader or a follower, plus its
  unique session ID.
- **Active instances** -- each running server process listed with its PID, role
  (leader or follower), heartbeat status, and uptime. The uptime counter updates
  in real time via HTMX polling.
- **Tool calls** -- total count and breakdown by category (search, retrieval,
  analysis, indexing, meta). Each category shows how many times tools in that
  group have been called.
- **Token efficiency** -- combined efficiency across all active instances. Shows
  tokens returned, tokens that would have been consumed by file reads, and the
  reduction percentage. When multiple instances are running, their stats are
  summed.
- **Query cache** -- hit/miss counts and hit rate for the internal LRU cache that
  deduplicates repeated Symbol/Section lookups.
- **Coding session history** -- a table of recent coding sessions (up to 10) with
  their start time, total tool calls, and cumulative efficiency numbers. Each
  session represents one continuous period of agent activity.
- **Current coding session totals** -- aggregated stats for the active coding
  session, combining all instances that share the same session ID.

The category breakdown helps you understand how your agent is using the server.
Heavy search usage with low retrieval might mean search results are sufficient
on their own. Heavy retrieval with no analysis might mean blast radius checks
are being skipped.


## Search page

The search page provides an interactive symbol search:

- **Search box** -- type a query to search across all indexed repos using the same
  hybrid search (FTS5 + vector similarity) that the MCP tools use.
- **Repository filter** -- a dropdown listing all indexed repos. Select one to
  limit results to that repo, or leave it blank to search everything.
- **Kind filter** -- filter results by symbol kind (function, class, method, etc.)
  after the search returns.
- **Syntax-highlighted results** -- each result shows the symbol name, kind,
  signature, file path, and line numbers. Results are rendered with syntax
  highlighting matching the symbol's language.
- **Source preview** -- click a result to expand it and see the full source code
  of the symbol, fetched live from the index.

This is useful for quick manual lookups when you want to browse without going
through an agent.


## Quality page

The quality page shows the quality report for each indexed repository:

- **Repository selector** -- a dropdown to pick which repo's quality data to view.
- **Quality gate** -- pass/fail status based on configurable thresholds for each
  metric.
- **Complexity metrics** -- average and maximum cyclomatic complexity across the
  codebase, with per-file breakdowns for the most complex files.
- **Test coverage** -- percentage of symbols that have associated test files,
  based on naming conventions and import analysis.
- **Documentation coverage** -- percentage of public functions and classes that
  have docstrings.
- **Code smells** -- categorized by severity (critical, warning, info). Each smell
  links to its file and line number.
- **Security findings** -- pattern-based detection of hardcoded secrets, SQL
  injection risks, and other security concerns.
- **Dead code** -- symbols that are defined but never imported or referenced
  anywhere in the codebase.
- **Duplication** -- detected code blocks that appear in multiple locations.

Each metric is shown per-repository, so you can compare quality across your
projects at a glance.


## Libraries page

The libraries page shows all indexed third-party libraries:

- **Library list** -- each library with its name, version, package manager, and
  symbol count. The same data as the overview page but focused on libraries only.
- **Source URLs** -- links to the git repository each library was fetched from.
- **Manager filter** -- filter the library list by package manager (pip, npm,
  cargo, go, composer). Only managers that have at least one indexed library
  appear in the filter.
- **Search filter** -- text search to narrow the list by library name.
- **Add library** -- a form to index a new library directly from the dashboard.
  Select the package manager, enter the package name (with optional version),
  and submit.
- **Library mappings** -- view and manage package-to-repo URL overrides. Add
  new mappings (package spec and git URL) or delete existing ones. These
  overrides are the same ones configured via `sylvan library map` or the
  `libraries.overrides` config section.

Use this page to verify that a library was indexed correctly, to check how
many symbols it contains, and to manage library source mappings.


## Queue page

The queue page shows the background job queue and database maintenance controls:

- **Worker status** -- each registered worker (indexing, embeddings, summaries,
  library repair) listed with its current state (idle, running), pending job
  count, and completed job count.
- **Active jobs** -- jobs currently being processed, with their type, target,
  progress percentage, and elapsed time.
- **Pending jobs** -- jobs waiting in the queue, ordered by priority. Indexing
  jobs run at highest priority, followed by embeddings, then summaries.
- **Database size** -- current size of the SQLite database file on disk.
- **Vacuum button** -- triggers a SQLite VACUUM operation to reclaim disk space
  after large deletions (removing repos or libraries). Shows the amount of space
  freed after completion.

The queue updates in real time via WebSocket. When you index a repository or add
a library, the jobs appear on this page immediately and progress updates stream
in as they are processed.


## Blast radius page

The blast radius page provides interactive impact analysis:

- **Symbol ID input** -- enter a symbol ID (from search results or `read_symbol`
  output) to see its blast radius.
- **Symbol search** -- alternatively, type a symbol name and select from
  autocomplete results. The search uses the same index as the Search page.
- **Mermaid graph** -- results are rendered as a directed graph. Nodes represent
  files, edges represent import relationships. Confirmed impact (the symbol name
  is directly referenced in the file) is highlighted differently from potential
  impact (the module is imported but the specific symbol may not be used).
- **Impact summary** -- counts of directly affected files, potentially affected
  files, and total files in the dependency chain.

This is the visual version of the `what_breaks_if_i_change` MCP tool. It is useful when
you want to see the dependency structure rather than read it as JSON.


## Memory page

The memory page provides management for agent memories and preferences:

- **Memories tab**: all stored memories listed newest first, with repo badges,
  tags, and content previews. Click a memory card to open a detail dialog showing
  the full content, timestamps, and a delete button. A text filter narrows the
  list by content, repo name, or tag.
- **Preferences tab**: all behavioral preferences in a table with key,
  instruction, scope badge (color-coded: green for global, blue for workspace,
  orange for repo), and scope target name. Click a row to see the full
  instruction in a detail dialog. An inline form lets you add new preferences
  with key, instruction, scope, and target selection.

Changes made through MCP tools (e.g., an agent calling `remember_this` or
`save_user_rule`) appear on this page in real time via WebSocket push events.


## Auto-updating

All dashboard pages update automatically via WebSocket. The mechanism works as
follows:

- The browser opens a single WebSocket connection to `/ws/dashboard` when the
  page loads.
- Request/response communication uses JSON messages with correlation IDs. Each
  page composable sends a request (e.g., `get_overview`, `get_memories`) and
  receives the response asynchronously.
- Server-side events are pushed to all connected clients through the sylvan event
  bus. When a memory is saved, a repo is indexed, or a queue job completes, the
  server emits an event that the browser receives and uses to refetch data.
- Pages that need periodic updates (like session uptime) use composable-level
  timers alongside the push events.

When you index a new repo, add a library, save a memory, or make tool calls, the
dashboard reflects the changes immediately without needing a manual browser
refresh.
