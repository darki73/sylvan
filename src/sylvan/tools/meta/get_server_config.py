"""MCP tool: get_server_config -- return this server's MCP connection config."""

import sys
from pathlib import Path

from sylvan.tools.support.response import get_meta, log_tool_call, wrap_response


@log_tool_call
async def get_server_config() -> dict:
    """Return the MCP server connection config for this sylvan instance.

    Provides the exact command, args, and working directory needed to
    connect to this sylvan server as an MCP server. Use this to configure
    SDK clients, subagents, or other tools that need MCP access.

    Returns:
        Tool response dict with server config and connection info.
    """
    meta = get_meta()

    # Find the project root (where pyproject.toml lives)
    sylvan_src = Path(__file__).resolve()
    project_root = sylvan_src
    for _ in range(10):
        project_root = project_root.parent
        if (project_root / "pyproject.toml").exists():
            break

    from sylvan.config import get_config

    cfg = get_config()

    config = {
        "server_name": "sylvan",
        "project_root": str(project_root),
        "python": sys.executable,
        "mcp_config": {
            "command": "uv",
            "args": [
                "--directory",
                str(project_root),
                "run",
                "sylvan",
                "serve",
            ],
        },
        "dashboard_url": None,
        "db_path": str(cfg.db_path),
    }

    try:
        from sylvan.dashboard.server import get_dashboard_url

        config["dashboard_url"] = get_dashboard_url()
    except Exception:  # noqa: S110 -- dashboard may not be running
        pass

    return wrap_response(config, meta.build())
