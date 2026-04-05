# Multi-Repo Projects

Most real projects span multiple repositories -- a frontend, a backend, a shared
library, maybe an infrastructure repo. Workspaces let you group these together
so you can search, analyze dependencies, and check blast radius across all of
them at once.


## Creating a workspace

### From the CLI

```bash
# All at once — index and group
sylvan workspace create my-stack -d "Full-stack application" \
    -p /home/dev/frontend \
    -p /home/dev/backend \
    -p /home/dev/shared-types

# Or step by step
sylvan workspace create my-stack -d "Full-stack application"
sylvan index /home/dev/frontend
sylvan index /home/dev/backend
sylvan workspace add my-stack --repo frontend
sylvan workspace add my-stack --repo backend
```

### From MCP tools

The `index_multi_repo` tool does the same thing in one call:

```
index_multi_repo(
    workspace="my-stack",
    paths=[
        "/home/dev/frontend",
        "/home/dev/backend",
        "/home/dev/shared-types"
    ],
    description="Full-stack application"
)
```

Either way, each folder becomes its own repo in the index, but the workspace
ties them together. Cross-repo imports are resolved automatically.


## Searching across repos with `search_all_repos`

Once the workspace exists, search all repos simultaneously:

```
search_all_repos(workspace="my-stack", query="UserProfile")
```

```json
{
  "symbols": [
    {
      "symbol_id": "src/models/user.py::UserProfile#class",
      "name": "UserProfile",
      "kind": "class",
      "repo": "backend",
      "file": "src/models/user.py",
      "signature": "class UserProfile(BaseModel)"
    },
    {
      "symbol_id": "src/types/user.ts::UserProfile#type",
      "name": "UserProfile",
      "kind": "type",
      "repo": "frontend",
      "file": "src/types/user.ts",
      "signature": "export interface UserProfile { ... }"
    },
    {
      "symbol_id": "src/schemas.py::UserProfile#class",
      "name": "UserProfile",
      "kind": "class",
      "repo": "shared-types",
      "file": "src/schemas.py",
      "signature": "class UserProfile(TypedDict)"
    }
  ]
}
```

Results from different repos are ranked together. The `repo` field tells you
which repository each result comes from. You can still filter by `kind` and
`language` to narrow results.


## Cross-repo blast radius with `cross_repo_impact`

This is where workspaces become essential. If you change a shared type, you need
to know which files in *every* repo are affected:

```
cross_repo_impact(
    workspace="my-stack",
    symbol_id="src/schemas.py::UserProfile#class"
)
```

```json
{
  "symbol": {
    "name": "UserProfile",
    "kind": "class",
    "repo": "shared-types"
  },
  "confirmed": [
    {
      "file": "src/models/user.py",
      "repo": "backend",
      "occurrences": 5,
      "symbols": [...]
    },
    {
      "file": "src/types/user.ts",
      "repo": "frontend",
      "occurrences": 3,
      "symbols": [...]
    }
  ],
  "potential": [...]
}
```

A regular `what_breaks_if_i_change` only sees the repo the symbol lives in.
`cross_repo_impact` follows imports across repo boundaries, so you see
impact in the backend *and* frontend when changing a shared type.


## Adding repos to an existing workspace

If you already have indexed repos and want to group them:

```
add_repo_to_workspace(workspace="my-stack", repo="infrastructure")
```

This adds the already-indexed repo to the workspace without re-indexing it. Use
this when a new repo joins the project, or when you want to include a repo that
was indexed separately.


## Pinning library versions

Workspaces can have pinned library versions. When pinned, `search_all_repos`
includes that library's symbols in results:

```
pin_library_version(workspace="my-stack", library="django@4.2")
```

This means a search for `ModelForm` in the `my-stack` workspace will return both
your code and Django's implementation. Each workspace can pin different versions
of the same library -- useful when your frontend and backend use different versions
of a shared dependency.


## When to use workspaces vs individual repos

**Use individual repos when:**

- You are working on a single project
- The repos do not share code or types
- You only need to search one codebase at a time

**Use workspaces when:**

- Multiple repos share types, interfaces, or contracts
- You need cross-repo blast radius analysis
- Changes in one repo can break another
- You want unified search across the full stack

Workspaces add no overhead to individual repo operations. `find_code` with
a `repo` filter still searches just that repo. The workspace tools are additional
capabilities, not replacements.


## The workflow

Setting up a multi-repo project:

1. `index_multi_repo` with all repo paths -- index and group in one call
2. `search_all_repos` -- find code across all repos
3. `cross_repo_impact` before changing shared code -- see cross-repo impact
4. `pin_library_version` for shared dependencies -- include library source in searches

Adding a repo later:

1. `sylvan index /path/to/new-repo` -- index it (via CLI or `index_project`)
2. `add_repo_to_workspace` -- add it to the workspace
3. Cross-repo analysis now includes the new repo automatically
