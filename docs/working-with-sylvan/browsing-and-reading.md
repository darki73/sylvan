# Browsing and Reading Code

The previous chapter found things. This chapter is about reading them -- seeing
the actual source, understanding file structure, and navigating a codebase without
wasting tokens on code you do not need.


## Reading a symbol with `get_symbol`

After `search_symbols` returns a match, you have a `symbol_id`. Use it to get the
exact source:

```
get_symbol(symbol_id="src/config/parser.py::parse_config#function")
```

```json
{
  "symbol_id": "src/config/parser.py::parse_config#function",
  "name": "parse_config",
  "kind": "function",
  "file": "src/config/parser.py",
  "signature": "def parse_config(path: Path, strict: bool = False) -> Config",
  "source": "def parse_config(path: Path, strict: bool = False) -> Config:\n    \"\"\"Parse a YAML config file...\"\"\"\n    ...",
  "line_start": 42,
  "line_end": 78,
  "_meta": {
    "savings": {
      "returned_tokens": 220,
      "total_file_tokens": 1840,
      "tokens_avoided": 1620,
      "method": "tiktoken_cl100k"
    }
  },
  "_hints": {
    "edit": {
      "read_file": "src/config/parser.py",
      "read_offset": 37,
      "read_limit": 46
    },
    "next": {
      "find_callers": "find_importers(repo, 'src/config/parser.py')",
      "blast_radius": "get_blast_radius('src/config/parser.py::parse_config#function')",
      "dependency_graph": "get_dependency_graph(repo, 'src/config/parser.py')"
    }
  }
}
```

This returns only the lines that belong to `parse_config` -- not the 1,800 other
tokens in that file. The `_meta.savings` block shows exactly what was avoided.

**Why this beats reading the file directly:**

- A 500-line file might contain 20 functions. You need one. `get_symbol` returns
  just that one.
- The response includes the signature, docstring, decorators, and source in a
  structured format -- no parsing needed.
- The `_hints` block tells you what to do next (see below).

Use `context_lines` to include surrounding code when you need to see what is
above or below the symbol:

```
get_symbol(symbol_id="...", context_lines=5)
```

Use `verify=true` to confirm the indexed content still matches the file on disk.
If the file has changed since indexing, the response will flag the drift.


## The `_hints` system

Every `get_symbol` response includes `_hints` with two sections:

**`_hints.edit`** -- If you need to edit this symbol using a file-reading tool,
these are the exact offset and limit to pass:

```json
"edit": {
  "read_file": "src/config/parser.py",
  "read_offset": 37,
  "read_limit": 46
}
```

This means: read `src/config/parser.py` starting at line 37, reading 46 lines.
You get exactly the symbol and its surrounding context, nothing more.

**`_hints.next`** -- Suggested follow-up tool calls based on what you just read:

```json
"next": {
  "find_callers": "find_importers(repo, 'src/config/parser.py')",
  "blast_radius": "get_blast_radius('src/config/parser.py::parse_config#function')",
  "dependency_graph": "get_dependency_graph(repo, 'src/config/parser.py')"
}
```

These are ready-to-use parameter suggestions. If you plan to change the function,
use `blast_radius`. If you want to understand who uses it, use `find_callers`.


## Understanding a file with `get_file_outline`

Before reading any file, check its outline. This shows every symbol in the file
with signatures and line numbers -- without returning any source code.

```
get_file_outline(repo="my-project", file_path="src/config/parser.py")
```

```json
{
  "file": "src/config/parser.py",
  "outline": [
    {
      "symbol_id": "src/config/parser.py::ConfigError#class",
      "name": "ConfigError",
      "kind": "class",
      "signature": "class ConfigError(Exception)",
      "line_start": 10,
      "line_end": 15,
      "children": []
    },
    {
      "symbol_id": "src/config/parser.py::parse_config#function",
      "name": "parse_config",
      "kind": "function",
      "signature": "def parse_config(path: Path, strict: bool = False) -> Config",
      "line_start": 42,
      "line_end": 78,
      "children": []
    }
  ],
  "_meta": {
    "symbol_count": 2,
    "token_efficiency": {
      "returned": 180,
      "equivalent_file_read": 1840,
      "reduction_percent": 90.2
    }
  }
}
```

Classes show their methods as `children`, so you can see the full structure at a
glance. Use this to decide which symbols to fetch with `get_symbol`.


## Exploring the repo with `get_file_tree`

To understand how a project is organized:

```
get_file_tree(repo="my-project", max_depth=3)
```

This returns a compact indented tree (like the `tree` command) with file counts
and language breakdowns. Directories deeper than `max_depth` are collapsed with
a count of their contents.


## Getting the big picture with `get_repo_outline`

Start here when you first encounter a repository:

```
get_repo_outline(repo="my-project")
```

```json
{
  "repo": "my-project",
  "files": 208,
  "symbols": 1542,
  "sections": 87,
  "languages": {"python": 180, "typescript": 28},
  "symbol_kinds": {
    "function": 420,
    "class": 180,
    "method": 890,
    "constant": 52
  }
}
```

This tells you the scale, the languages involved, and the distribution of symbol
types. From here, use `get_file_tree` to see the structure, or `search_symbols`
to start finding things.


## Navigating documentation with `get_toc` and `get_toc_tree`

If the repository has documentation files, use `get_toc` for a flat list of all
headings:

```
get_toc(repo="my-project")
```

Or `get_toc_tree` for a nested hierarchy grouped by document:

```
get_toc_tree(repo="my-project", max_depth=2)
```

Both return `section_id` values you can pass to `get_section` to read individual
sections without loading entire documents.


## Getting the full picture with `get_context_bundle`

When you need to understand a symbol in context -- not just its source, but what
it imports, what else is in the same file, and who calls it -- use
`get_context_bundle` instead of making multiple calls:

```
get_context_bundle(
    symbol_id="src/config/parser.py::parse_config#function",
    include_imports=true,
    include_callers=true
)
```

This returns the symbol's source, the file's imports, sibling symbols in the same
file, and callers from other files -- all in one response. It replaces what would
otherwise be 3-5 separate tool calls.


## Batch operations

When you need to read multiple things at once, use the batch variants:

| Instead of calling... | Use... |
|---|---|
| `get_symbol` three times | `get_symbols(symbol_ids=["id1", "id2", "id3"])` |
| `get_section` three times | `get_sections(section_ids=["id1", "id2", "id3"])` |
| `get_file_outline` three times | `get_file_outlines(repo="x", file_paths=["a.py", "b.py", "c.py"])` |

Each batch call is a single round-trip and returns all results together.


## The workflow

A typical browsing session looks like this:

1. `get_repo_outline` -- understand the scale
2. `get_file_tree` -- see the directory layout
3. `search_symbols` -- find what you are looking for
4. `get_file_outline` -- understand the file it lives in
5. `get_symbol` -- read the exact source you need
6. Follow `_hints.next` -- check callers, blast radius, or dependencies

Each step returns only what you asked for, and each response tells you what to
do next. You never need to read an entire file to find a 20-line function.
