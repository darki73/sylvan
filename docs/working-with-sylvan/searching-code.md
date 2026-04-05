# Searching Code

You need to find a function. Maybe you know part of its name. Maybe you only know
what it does. Maybe you just know it exists somewhere in 300 files. This chapter
covers four ways to find things, and when to use each one.


## Finding symbols with `find_code`

Symbols are the named things in code: functions, classes, methods, constants, types.
`find_code` searches across all of them by name, signature, docstring, and
extracted keywords. It returns ranked results without reading any files.

**Basic search by name:**

```
find_code(query="parse_config")
```

```json
{
  "symbols": [
    {
      "symbol_id": "src/config/parser.py::parse_config#function",
      "name": "parse_config",
      "kind": "function",
      "language": "python",
      "file": "src/config/parser.py",
      "signature": "def parse_config(path: Path, strict: bool = False) -> Config",
      "summary": "Parse a YAML config file into a Config object.",
      "repo": "my-project",
      "line_start": 42
    }
  ],
  "_meta": {
    "results_count": 1,
    "token_efficiency": {
      "returned": 112,
      "equivalent_file_read": 4830,
      "reduction_percent": 97.7,
      "method": "byte_estimate"
    }
  }
}
```

You get the signature, location, and a summary -- enough to decide if this is
the right function -- at a fraction of the cost of reading the file.

**Search by what it does:**

```
find_code(query="validate user email address")
```

This searches docstrings and keywords, not just names. If someone wrote a function
called `check_email` with a docstring mentioning "validate", it will match.

**Narrow with filters:**

| Filter | Example | What it does |
|---|---|---|
| `repo` | `repo="backend"` | Restrict to one repository |
| `kind` | `kind="class"` | Only classes, functions, methods, constants, or types |
| `language` | `language="typescript"` | Only symbols from that language |
| `file_pattern` | `file_pattern="**/test_*.py"` | Glob pattern on file paths |

```
find_code(
    query="authenticate",
    repo="backend",
    kind="function",
    language="python",
    max_results=5
)
```

**Token budgets:**

If you want the server to pack as many results as possible into a fixed budget:

```
find_code(query="handler", token_budget=500)
```

The response will include `tokens_used` and `tokens_remaining` in `_meta` so you
know exactly where you stand.


## Finding literal text with `find_text`

Not everything is a symbol. Comments, string literals, TODOs, configuration
values, error messages -- these live in file content but are not extracted as
symbols. `find_text` runs a full-text search across all indexed file content.

```
find_text(query="TODO: refactor", repo="my-project")
```

```json
{
  "matches": [
    {
      "file_path": "src/handlers/auth.py",
      "repo_name": "my-project",
      "line": 87,
      "match": "# TODO: refactor this to use the new token validator",
      "context": "    token = request.headers.get('Authorization')\n    # TODO: refactor this to use the new token validator\n    if not token:"
    }
  ],
  "_meta": { "results_count": 1 }
}
```

Each match includes surrounding context lines. Use `context_lines` to control
how many (default: 2). Use `file_pattern` to restrict to certain files.

Use `find_text` when you are looking for:

- Comments and TODOs
- String literals and error messages
- Configuration keys or magic values
- Anything that is not a function, class, method, constant, or type


## Finding documentation with `find_docs`

If the repository contains markdown, RST, HTML, or OpenAPI docs, those are indexed
as sections. `find_docs` finds them by title, summary, or tags.

```
find_docs(query="authentication setup", repo="my-project")
```

```json
{
  "sections": [
    {
      "section_id": "docs/guides/auth.md::authentication-setup",
      "title": "Authentication Setup",
      "doc_path": "docs/guides/auth.md",
      "summary": "How to configure OAuth2 providers and API keys.",
      "depth": 2,
      "repo": "my-project"
    }
  ]
}
```

Once you have a `section_id`, use `read_doc_section` to read that section's content
without loading the entire document.


## Searching in bulk with `find_code_batch`

When you need to find several unrelated things, run them all in one call instead
of making separate requests. Each query can override the repo, kind, and language
filters independently.

```
find_code_batch(
    queries=[
        {"query": "parse_config", "kind": "function"},
        {"query": "DatabaseConnection", "kind": "class"},
        {"query": "MAX_RETRIES", "kind": "constant"}
    ],
    repo="my-project",
    max_results_per_query=5
)
```

```json
{
  "results": [
    {"query": "parse_config", "count": 2, "symbols": [...]},
    {"query": "DatabaseConnection", "count": 1, "symbols": [...]},
    {"query": "MAX_RETRIES", "count": 3, "symbols": [...]}
  ],
  "_meta": { "queries": 3, "total_results": 6 }
}
```

Results are grouped by query. This is always faster than three separate
`find_code` calls.


## Finding similar code with `find_similar_code`

Sometimes you have a function and want to find others like it -- similar patterns,
similar purposes, alternative implementations. `find_similar_code` uses vector
similarity (embeddings) to find semantically related symbols.

You need a `symbol_id` to start from. Get one from `find_code` first:

```
find_similar_code(
    symbol_id="src/auth/validators.py::validate_token#function",
    max_results=5
)
```

This returns symbols that are semantically close to `validate_token`, even if they
have completely different names. It might surface `check_api_key` or
`verify_session` -- things that do similar work in different contexts.

Use `repo` to restrict results to a specific repository, or leave it out to search
across everything indexed.


## Which search tool to use

| You want to find... | Use |
|---|---|
| A function, class, method, constant, or type | `find_code` |
| A comment, string, TODO, or literal text | `find_text` |
| A documentation section or heading | `find_docs` |
| Several symbols at once | `find_code_batch` |
| Code that does something similar to a known function | `find_similar_code` |

Every search tool returns a `_meta` block with `token_efficiency`, showing how
many tokens the response used versus what a full file read would have cost. When
results come back, the next step is usually `read_symbol` to read the actual source
of anything interesting -- covered in the next chapter.
