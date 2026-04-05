# Your first project

You have the server running and your agent connected. Here is what the first five minutes look like -- a conversation between your agent and the server, starting from an unindexed codebase.

## Step 1: Index the project

Your agent calls `index_project` to build the index:

```
Agent: index_project(path="/home/user/projects/webapp")
```

```json
{
  "repo": "webapp",
  "files_indexed": 142,
  "symbols_extracted": 1847,
  "sections_extracted": 89,
  "languages": {"python": 98, "typescript": 37, "yaml": 7},
  "timing_ms": 3200
}
```

The server walks the project, parses every supported file with tree-sitter, extracts symbols (functions, classes, methods, constants), and stores them in a local SQLite database. For a typical project with a few hundred files, this takes a few seconds.

## Step 2: Get the lay of the land

Before diving into specific code, the agent asks for a high-level view:

```
Agent: repo_overview(repo="webapp")
```

```json
{
  "repo": "webapp",
  "files": 142,
  "symbols": 1847,
  "languages": {"python": 98, "typescript": 37, "yaml": 7},
  "symbol_kinds": {
    "class": 45,
    "function": 312,
    "method": 1420,
    "constant": 70
  }
}
```

For a more detailed view, `project_structure` returns the full directory structure:

```
Agent: project_structure(repo="webapp")
```

```
webapp/
  src/
    auth/
      middleware.py (8 symbols)
      providers.py (12 symbols)
      tokens.py (6 symbols)
    api/
      routes.py (15 symbols)
      handlers.py (22 symbols)
    models/
      user.py (9 symbols)
      ...
```

## Step 3: Search for code

Now the agent needs to find something specific. Instead of grepping across every file, it searches the index:

```
Agent: find_code(query="authenticate user", repo="webapp")
```

```json
{
  "symbols": [
    {
      "symbol_id": "src/auth/middleware.py::authenticate_request#function",
      "name": "authenticate_request",
      "kind": "function",
      "signature": "async def authenticate_request(request: Request) -> User",
      "file": "src/auth/middleware.py",
      "line_start": 24
    },
    {
      "symbol_id": "src/auth/providers.py::AuthProvider.verify_credentials#method",
      "name": "verify_credentials",
      "kind": "method",
      "signature": "async def verify_credentials(self, username: str, password: str) -> bool",
      "file": "src/auth/providers.py",
      "line_start": 67
    }
  ]
}
```

Two results, with signatures and locations. The agent spent about 200 tokens instead of reading through auth files to find these.

## Step 4: Read the exact source

The agent picks the function it needs and requests its source:

```
Agent: read_symbol(symbol_id="src/auth/middleware.py::authenticate_request#function")
```

```json
{
  "name": "authenticate_request",
  "kind": "function",
  "signature": "async def authenticate_request(request: Request) -> User",
  "source": "async def authenticate_request(request: Request) -> User:\n    \"\"\"Extract and validate the auth token from the request.\"\"\"\n    token = request.headers.get(\"Authorization\", \"\").removeprefix(\"Bearer \")\n    if not token:\n        raise AuthError(\"Missing token\")\n    payload = decode_token(token)\n    return await User.find(payload[\"user_id\"])",
  "line_start": 24,
  "line_end": 31
}
```

Just the function. Not the imports, not the module docstring, not the 40 other functions in the file. About 150 tokens.

## Step 5: Trace dependencies

Before modifying this function, the agent checks who calls it:

```
Agent: who_depends_on_this(repo="webapp", file_path="src/auth/middleware.py")
```

```json
{
  "importers": [
    {"file": "src/api/routes.py", "symbols_used": ["authenticate_request"]},
    {"file": "src/api/handlers.py", "symbols_used": ["authenticate_request"]},
    {"file": "tests/test_auth.py", "symbols_used": ["authenticate_request"]}
  ]
}
```

Three files depend on this module. The agent now knows the scope of any change.

## Step 6: Check blast radius

For a more thorough impact analysis:

```
Agent: what_breaks_if_i_change(symbol_id="src/auth/middleware.py::authenticate_request#function")
```

```json
{
  "symbol": "authenticate_request",
  "direct_callers": 5,
  "transitive_callers": 12,
  "files_affected": 4,
  "risk": "medium"
}
```

The agent knows that changing this function could affect 12 call sites across 4 files. It can plan the refactor accordingly.

## What just happened

In six tool calls, the agent:

1. Indexed the entire project
2. Understood its structure
3. Found the right function by intent, not filename
4. Read only the source it needed
5. Mapped every caller
6. Assessed the impact of a change

Total tokens spent: roughly 800. Reading the same files manually would have cost over 10,000.

## What's next

The defaults work well out of the box, but you can tune search weights, configure AI-powered summaries, and adjust quality thresholds.

[Configure the server -->](configuration.md)
