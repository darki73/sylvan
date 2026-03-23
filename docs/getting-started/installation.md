# Installation

This guide takes you from a fresh machine to a running MCP server connected to your agent.

## Requirements

- **Python 3.12+**
- **uv** (recommended) or pip

## Install as a global tool (recommended)

The cleanest way to install — makes `sylvan` available everywhere without polluting any project's dependencies:

```bash
uv tool install sylvan
```

This installs `sylvan` into an isolated environment managed by uv. The `sylvan` command is available globally.

To update later:

```bash
uv tool upgrade sylvan
```

## Install as a project dependency

If you want sylvan as part of a specific project:

```bash
uv add sylvan
```

Or with pip:

```bash
pip install sylvan
```

## Verify the installation

```bash
sylvan doctor
```

This checks that Python, tree-sitter, sqlite-vec, and embedding dependencies are all available. Fix anything it flags before continuing.

## Connect to your agent

The server communicates over MCP (Model Context Protocol). You need to tell your agent how to start it. The configuration depends on how you installed it.

### stdio (default)

The simplest option. The agent spawns the server as a subprocess and communicates over stdin/stdout. This is what Claude Code, Cursor, and most MCP clients expect.

**If installed as a global tool** (`uv tool install`):

```json
{
  "mcpServers": {
    "sylvan": {
      "command": "sylvan",
      "args": ["serve"]
    }
  }
}
```

**If installed as a project dependency** (`uv add`):

```json
{
  "mcpServers": {
    "sylvan": {
      "command": "uv",
      "args": ["run", "sylvan", "serve"]
    }
  }
}
```

**If running from a cloned repo:**

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

For **Claude Code**, you can also add it via the CLI:

```bash
# Global tool install
claude mcp add sylvan -- sylvan serve

# Project dependency
claude mcp add sylvan -- uv run sylvan serve
```

For **Cursor**, add the config to `.cursor/mcp.json` in your project root.

### SSE (Server-Sent Events)

For agents that connect to a long-running server over HTTP. Start the server first:

```bash
sylvan serve --transport sse
```

This binds to `127.0.0.1:8420` by default. Then point your agent at:

```json
{
  "mcpServers": {
    "sylvan": {
      "url": "http://127.0.0.1:8420/sse"
    }
  }
}
```

### Streamable HTTP

The newest MCP transport. Same idea as SSE but uses standard HTTP request/response:

```bash
sylvan serve --transport http
```

```json
{
  "mcpServers": {
    "sylvan": {
      "url": "http://127.0.0.1:8420/mcp"
    }
  }
}
```

### Changing host and port

Both SSE and HTTP transports accept `--host` and `--port`:

```bash
sylvan serve --transport sse --host 0.0.0.0 --port 9000
```

## What's next

Now that the server is running and your agent can reach it, you need something to search.

[Index your first project -->](your-first-project.md)
