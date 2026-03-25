"""Dashboard server — launches alongside the MCP server."""

import asyncio
import socket

import uvicorn

from sylvan.logging import get_logger

logger = get_logger(__name__)

_dashboard_port: int | None = None
_dashboard_task: asyncio.Task | None = None


def _find_free_port() -> int:
    """Find a free TCP port on localhost.

    Returns:
        An available port number.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


async def start_dashboard() -> int | None:
    """Start the dashboard web server as a background async task.

    Returns:
        The port number the dashboard is running on, or None if it failed.
    """
    global _dashboard_port, _dashboard_task

    try:
        from sylvan.config import get_config
        from sylvan.dashboard.app import create_dashboard_app

        cfg = get_config()
        port = _find_free_port() if cfg.server.dashboard_random_port else cfg.server.dashboard_port
        app = create_dashboard_app()

        config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        server = uvicorn.Server(config)

        _dashboard_task = asyncio.get_running_loop().create_task(server.serve())
        _dashboard_port = port
        logger.info("dashboard_started", url=f"http://127.0.0.1:{port}")
        return port
    except Exception as error:
        logger.warning("dashboard_start_failed", error=str(error))
        return None


async def stop_dashboard() -> None:
    """Cancel the dashboard background task if running."""
    global _dashboard_task
    if _dashboard_task is not None:
        _dashboard_task.cancel()
        _dashboard_task = None
        logger.info("dashboard_stopped")


def stop_dashboard_sync() -> None:
    """Cancel the dashboard task (sync, for signal handlers and finally blocks)."""
    global _dashboard_task
    if _dashboard_task is not None:
        _dashboard_task.cancel()
        _dashboard_task = None
        logger.info("dashboard_stopped")


def get_dashboard_url() -> str | None:
    """Return the dashboard URL if the server is running.

    Returns:
        URL string like 'http://127.0.0.1:PORT', or None.
    """
    if _dashboard_port is None:
        return None
    return f"http://127.0.0.1:{_dashboard_port}"
