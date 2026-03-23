# Sylvan

AI agents waste most of their token budget just *finding* code. They read entire files to locate a single function, grep across directories to trace a dependency, and piece together call chains one file at a time. The server eliminates this by indexing your codebase into a structured database of symbols, sections, and relationships -- then exposing it all through 52 MCP tools. Your agent asks for exactly what it needs and gets exactly that back: function signatures, dependency graphs, blast radius analysis, semantic search results. No wasted reads. No guesswork. Typical token savings exceed 80%.

## What it looks like

```
Agent: search_symbols("authentication middleware")
-> 3 results with signatures, 280 tokens

Agent: get_symbol(symbol_id)
-> exact function source, 150 tokens

vs. Read("src/auth/middleware.py")
-> entire file, 4,200 tokens
```

## At a glance

- **52 MCP tools** -- symbol lookup, search, analysis, indexing, workspace management
- **34 programming languages** via tree-sitter parsing
- **Hybrid search** combining full-text (FTS5) and vector similarity for ranked results
- **Blast radius analysis** -- know what breaks before you change it
- **Dependency graphs** -- trace imports, find callers, map relationships
- **Quality reports** -- complexity, duplication, dead code, security patterns
- **Third-party library indexing** -- search Django or FastAPI source the same way you search your own code
- **Session intelligence** -- deprioritizes symbols the agent has already seen

## Get started

The quickest path from zero to a working setup takes about five minutes.

[Get started with installation -->](getting-started/installation.md)
