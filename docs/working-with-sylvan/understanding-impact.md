# Understanding Impact

You found the code. You read it. Now you want to change it. Before you do, you
need to know what will break. This chapter covers the tools that answer "what
depends on this?" at every level -- symbols, files, and entire module trees.


## Checking blast radius with `get_blast_radius`

The blast radius of a symbol is every file and symbol that could be affected by
changing it. This goes beyond simple text search -- it follows import chains and
distinguishes between confirmed and potential impact.

```
get_blast_radius(
    symbol_id="src/config/parser.py::parse_config#function"
)
```

```json
{
  "symbol": {
    "symbol_id": "src/config/parser.py::parse_config#function",
    "name": "parse_config",
    "kind": "function",
    "file": "src/config/parser.py"
  },
  "confirmed": [
    {
      "file": "src/server/startup.py",
      "depth": 1,
      "occurrences": 3,
      "symbols": [
        {
          "symbol_id": "src/server/startup.py::initialize#function",
          "name": "initialize",
          "kind": "function",
          "line_start": 15
        }
      ]
    },
    {
      "file": "tests/test_config.py",
      "depth": 1,
      "occurrences": 8,
      "symbols": [...]
    }
  ],
  "potential": [
    {
      "file": "src/server/routes.py",
      "depth": 2,
      "symbols": [...]
    }
  ],
  "depth_reached": 2,
  "total_affected": 3,
  "_meta": { "confirmed_count": 2, "potential_count": 1 }
}
```

**Confirmed impact** means the symbol's name actually appears in that file --
it is directly referenced. The `occurrences` count tells you how many times.

**Potential impact** means the file imports a module that contains the symbol,
but does not reference the symbol by name. It might still be affected through
indirect usage.

The `depth` parameter controls how many import hops to follow (1-3). Depth 1
shows direct importers. Depth 2 follows their importers too. Depth 3 is the
maximum and covers transitive dependencies.

```
get_blast_radius(symbol_id="...", depth=3)
```


## Checking multiple symbols with `batch_blast_radius`

If you are refactoring several functions at once, check them all in one call:

```
batch_blast_radius(
    symbol_ids=[
        "src/config/parser.py::parse_config#function",
        "src/config/parser.py::validate_config#function"
    ],
    depth=2
)
```

Each symbol gets its own confirmed and potential lists. This is always faster
than calling `get_blast_radius` repeatedly.


## Finding who imports a file with `find_importers`

At the file level, `find_importers` answers "who depends on this module?"

```
find_importers(repo="my-project", file_path="src/config/parser.py")
```

```json
{
  "file": "src/config/parser.py",
  "importers": [
    {
      "file": "src/server/startup.py",
      "has_importers": true
    },
    {
      "file": "tests/test_config.py",
      "has_importers": false
    }
  ]
}
```

The `has_importers` field is useful for understanding the dependency chain. When
it is `false`, that file is a leaf -- nothing else imports it. When it is `true`,
the file has its own dependents, so changes can propagate further.

**Checking multiple files:**

```
batch_find_importers(
    repo="my-project",
    file_paths=["src/config/parser.py", "src/config/schema.py"]
)
```


## Visualizing dependencies with `get_dependency_graph`

To see the full picture of what a file imports and what imports it:

```
get_dependency_graph(
    repo="my-project",
    file_path="src/config/parser.py",
    direction="both",
    depth=2
)
```

```json
{
  "center": "src/config/parser.py",
  "nodes": [
    {"file": "src/config/parser.py", "symbols": 5},
    {"file": "src/config/schema.py", "symbols": 3},
    {"file": "src/server/startup.py", "symbols": 12}
  ],
  "edges": [
    {"from": "src/config/parser.py", "to": "src/config/schema.py"},
    {"from": "src/server/startup.py", "to": "src/config/parser.py"}
  ]
}
```

The `direction` parameter controls which side of the graph to build:

| Direction | Shows |
|---|---|
| `"imports"` | Files this module depends on |
| `"importers"` | Files that depend on this module |
| `"both"` | Both directions |

Use `depth` to control how many hops to follow (1-3).


## Finding callers and callees with `get_references`

While `find_importers` works at the file level, `get_references` works at the
symbol level. It answers "who calls this function?" and "what does this function
call?"

```
get_references(
    symbol_id="src/config/parser.py::parse_config#function",
    direction="to"
)
```

- `direction="to"` returns callers -- symbols that reference this one
- `direction="from"` returns callees -- symbols that this one references


## Tracing inheritance with `get_class_hierarchy`

Before changing a base class, check its inheritance chain:

```
get_class_hierarchy(class_name="BaseHandler", repo="my-project")
```

This returns ancestors (what `BaseHandler` extends) and descendants (what extends
`BaseHandler`). If you change a method on `BaseHandler`, every descendant that
overrides it might need updating.


## Planning a rename with `rename_symbol`

If you want to rename a symbol, `rename_symbol` finds every location that needs
to change and gives you exact edit instructions:

```
rename_symbol(
    symbol_id="src/config/parser.py::parse_config#function",
    new_name="load_config"
)
```

```json
{
  "symbol": {
    "name": "parse_config",
    "new_name": "load_config",
    "file": "src/config/parser.py"
  },
  "edits": [
    {
      "file": "src/config/parser.py",
      "line": 42,
      "old_text": "def parse_config(",
      "new_text": "def load_config("
    },
    {
      "file": "src/server/startup.py",
      "line": 8,
      "old_text": "from config.parser import parse_config",
      "new_text": "from config.parser import load_config"
    },
    {
      "file": "src/server/startup.py",
      "line": 23,
      "old_text": "config = parse_config(path)",
      "new_text": "config = load_config(path)"
    }
  ],
  "files_affected": 2,
  "total_edits": 3
}
```

Each edit has the exact file, line, old text, and new text. Your agent can apply
these directly with a file-editing tool.


## The refactoring workflow

Putting it all together, the safe workflow for any code change is:

1. **Search** -- `search_symbols` to find the symbol you want to change
2. **Read** -- `get_symbol` to see the current source
3. **Assess** -- `get_blast_radius` to see what depends on it
4. **Understand** -- `get_references` or `get_class_hierarchy` for details
5. **Change** -- make the edit
6. **Reindex** -- `index_file` to update the index with your changes

The blast radius check in step 3 is the critical one. It turns "I think this is
safe to change" into "I can see exactly what will be affected." When the confirmed
list is short and the potential list is empty, you can change with confidence.
When either list is long, you know to proceed carefully.
