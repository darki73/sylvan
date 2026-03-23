# Sylvan

Sylvan is a code intelligence engine that gives AI agents fast, precise access to your codebase. Instead of reading entire files to find a single function or grepping across directories to trace a dependency, agents query sylvan's structured index and get back exactly the symbols, signatures, and relationships they need. The server parses your code with tree-sitter, stores it in a SQLite database with full-text and vector search, and exposes everything through 52 MCP tools. Typical token savings exceed 80%.

```
Agent: search_symbols("authentication middleware")
-> 3 results with signatures, 280 tokens

Agent: get_symbol(symbol_id)
-> exact function source, 150 tokens

vs. Read("src/auth/middleware.py")
-> entire file, 4,200 tokens
```

## Key features

- **52 MCP tools** -- search, browse, analyze, and index code through a single server. Your agent never needs to fall back to Read/Grep/Glob.
- **34 programming languages** -- tree-sitter parsing for Python, TypeScript, Go, Rust, Java, C#, and 28 more, plus 10 document formats (Markdown, RST, HTML, etc.).
- **Hybrid search** -- combines full-text search (FTS5) with vector similarity (sqlite-vec) and reciprocal rank fusion for ranked results.
- **Blast radius analysis** -- before renaming or deleting a function, see every file that would be affected, with confirmed vs. potential impact.
- **Dependency graphs** -- trace imports, find callers, and map relationships across files and repos.
- **Quality reports** -- complexity metrics, code duplication, dead code detection, and security pattern scanning per repository.
- **Third-party library indexing** -- index Django, FastAPI, or any pip/npm package and search its source the same way you search your own code.
- **Session intelligence** -- tracks which symbols the agent has already seen and deprioritizes them in future search results.
- **Multi-instance clustering** -- multiple server instances share the same database, so parallel agents can search simultaneously without contention.
- **Web dashboard** -- live overview of indexed repos, session stats, token efficiency, quality reports, and interactive symbol search.

## Quick install

```bash
uv add sylvan
```

Then connect it to your agent. For Claude Code, add this to `.mcp.json` or `.claude/settings.json`:

```json
{
  "mcpServers": {
    "sylvan": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/sylvan", "sylvan", "serve"]
    }
  }
}
```

For SSE or streamable HTTP transports, see the [installation guide](getting-started/installation.md).

## Index your first project

```bash
sylvan index /path/to/your/project
```

The agent can now search, browse, and analyze the code. See [Your First Project](getting-started/your-first-project.md) for the full walkthrough.

## Documentation

### Getting Started

- [Installation](getting-started/installation.md) -- install, verify, and connect to your agent
- [Your First Project](getting-started/your-first-project.md) -- index a codebase and make your first queries
- [Configuration](getting-started/configuration.md) -- providers, embeddings, and config file options

### Working With Sylvan

- [Searching Code](working-with-sylvan/searching-code.md) -- full-text, vector, and hybrid search
- [Browsing and Reading](working-with-sylvan/browsing-and-reading.md) -- get_symbol, get_file_outline, get_toc
- [Understanding Impact](working-with-sylvan/understanding-impact.md) -- blast radius, dependency graphs, find_importers
- [Working With Libraries](working-with-sylvan/working-with-libraries.md) -- indexing third-party packages
- [Multi-Repo Projects](working-with-sylvan/multi-repo-projects.md) -- workspaces and cross-repo search
- [Quality and Security](working-with-sylvan/quality-and-security.md) -- quality reports, dead code, security scanning
- [The Dashboard](working-with-sylvan/the-dashboard.md) -- web UI for repos, sessions, search, and quality
- [Token Efficiency](working-with-sylvan/token-efficiency.md) -- how token savings are measured
- [CLI Reference](working-with-sylvan/cli.md) -- all commands with options and examples

### For Your Agent

- [Teaching Your Agent](for-your-agent/teaching-your-agent.md) -- the workflow guide, tool gate, and SubagentStart hook
- [Subagent Access](for-your-agent/subagent-access.md) -- how subagents get MCP tool access
- [The Tool Reference](for-your-agent/the-tool-reference.md) -- all 52 tools with parameters and return values

### Extending Sylvan

- [Writing Providers](extending-sylvan/writing-providers.md) -- summary and embedding provider plugins
- [Adding Languages](extending-sylvan/adding-languages.md) -- tree-sitter language specs
- [Building Tools](extending-sylvan/building-tools.md) -- adding new MCP tools
- [The ORM](extending-sylvan/the-orm.md) -- async active record ORM
- [Schema and Migrations](extending-sylvan/schema-and-migrations.md) -- database schema management
