# Working with Libraries

When you need to understand how a third-party library actually works -- not the
documentation's version, but the real implementation -- you can index its source
code and search it the same way you search your own code.


## Indexing a library with `add_library`

To index a library, specify the package manager and package name with an optional
version:

```
add_library(package="pip/django@4.2")
```

The server fetches the real source code for that version, indexes every symbol,
and makes it searchable. Supported package managers:

| Prefix | Ecosystem | Example |
|---|---|---|
| `pip/` | Python (PyPI) | `pip/django@4.2` |
| `npm/` | JavaScript (npm) | `npm/react@18` |
| `cargo/` | Rust (crates.io) | `cargo/serde` |
| `go/` | Go modules | `go/github.com/gin-gonic/gin` |

If you omit the version, the latest release is fetched. Pin a version when you
need to match what your project actually uses.


## Searching library code

Once indexed, library symbols appear in `search_symbols` results alongside your
own code. Use the `repo` filter to search only within a library:

```
search_symbols(query="ModelForm.save", repo="django@4.2")
```

This returns the actual implementation of `ModelForm.save` in Django 4.2 -- the
real source code, not a documentation summary. You can then use `get_symbol` to
read it:

```
get_symbol(symbol_id="django/forms/models.py::ModelForm.save#method")
```

This is how you answer questions like "what does this method actually do under
the hood?" or "what exceptions can this function raise?" -- by reading the
implementation directly.


## Listing indexed libraries

To see what is already indexed:

```
list_libraries()
```

```json
{
  "libraries": [
    {
      "name": "django@4.2",
      "manager": "pip",
      "version": "4.2",
      "symbols": 8420,
      "indexed_at": "2025-01-15T10:30:00Z"
    },
    {
      "name": "react@18",
      "manager": "npm",
      "version": "18",
      "symbols": 1240,
      "indexed_at": "2025-01-15T11:00:00Z"
    }
  ]
}
```

Check this before indexing -- the library might already be available.


## Comparing versions with `compare_library_versions`

When upgrading a dependency, you need to know what changed. If both the old and
new versions are indexed, `compare_library_versions` generates a migration guide:

```
compare_library_versions(
    package="numpy",
    from_version="1.24",
    to_version="2.0"
)
```

```json
{
  "package": "numpy",
  "from_version": "1.24",
  "to_version": "2.0",
  "added": [
    {"name": "matrix_transpose", "kind": "function", "file": "numpy/..."}
  ],
  "removed": [
    {"name": "float_", "kind": "type", "file": "numpy/..."}
  ],
  "changed": [
    {
      "name": "array",
      "old_signature": "def array(object, dtype=None, ...)",
      "new_signature": "def array(object, dtype=None, *, copy=None, ...)"
    }
  ]
}
```

This shows symbols added, removed, and with changed signatures. Use it to assess
breaking changes before upgrading.

Both versions must be indexed first. If you only have one version, use
`add_library` to index the other.


## Detecting version drift with `check_library_versions`

Over time, the libraries indexed by the server can fall out of sync with what your
project actually has installed. `check_library_versions` compares your project's
dependency file (pyproject.toml, package.json, go.mod, etc.) against what is
indexed:

```
check_library_versions(repo="my-project")
```

```json
{
  "up_to_date": ["django@4.2", "requests@2.31"],
  "outdated": [
    {"name": "numpy", "installed": "2.0", "indexed": "1.24"}
  ],
  "not_indexed": ["pydantic", "httpx"]
}
```

Use this after running `uv sync`, `npm install`, or similar commands to spot
libraries that need re-indexing.


## Pinning libraries to workspaces

When you have a workspace (a group of related repos), you can pin specific library
versions to it. This means `workspace_search` will include that library's symbols
in results:

```
pin_library(workspace="my-stack", library="django@4.2")
```

Each workspace can have its own set of pinned library versions. This is covered
in more detail in the multi-repo projects chapter.


## Removing a library

To remove a library and free up disk space:

```
remove_library(name="django@4.2")
```

This deletes the indexed data and the fetched source files.


## The workflow

A typical library investigation looks like this:

1. You encounter an unfamiliar API call in your code
2. `list_libraries` -- check if the library is already indexed
3. `add_library` if not -- index it
4. `search_symbols` with the library's repo name -- find the implementation
5. `get_symbol` -- read the actual source

This replaces guessing from documentation or searching GitHub manually. You get
the exact source code for the exact version your project uses, searchable with
the same tools you use for your own code.
