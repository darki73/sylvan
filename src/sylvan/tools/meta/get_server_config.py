"""MCP tool: get_server_config -- return this server's MCP connection config."""

from sylvan.tools.base import Tool, ToolParams


class GetServerConfig(Tool):
    name = "connection_config"
    category = "meta"
    description = (
        "Returns this server's MCP connection config: command, args, working "
        "directory, dashboard URL, and database path. Useful for connecting "
        "subagents or SDK clients."
    )

    class Params(ToolParams):
        pass

    async def handle(self, p: Params) -> dict:
        import sys
        from pathlib import Path

        from sylvan.config import get_config

        sylvan_src = Path(__file__).resolve()
        project_root = sylvan_src
        for _ in range(10):
            project_root = project_root.parent
            if (project_root / "pyproject.toml").exists():
                break

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
        except Exception:  # noqa: S110
            pass

        return config


async def get_server_config(**_kwargs: object) -> dict:
    return await GetServerConfig().execute({})
