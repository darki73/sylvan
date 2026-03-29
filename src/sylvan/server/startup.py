"""Server startup -- warmup, signal handling, and entry point."""

from sylvan.logging import get_logger

logger = get_logger(__name__)


def warm_up() -> None:
    """Pre-load everything so the first tool call is fast.

    Runs before the MCP event loop starts:
    1. Imports all tool modules (triggers their import chains)
    2. Loads the embedding model (biggest cold-start cost)

    Database schema setup is deferred to the async backend which
    initialises lazily on the first tool call via
    ``_get_or_create_backend()``.
    """
    logger.info("warmup_starting")

    from sylvan.tools.analysis import (  # noqa: F401
        find_importers,
        get_blast_radius,
        get_class_hierarchy,
        get_git_context,
        get_quality,
        get_references,
        get_related,
    )
    from sylvan.tools.browsing import (  # noqa: F401
        get_context_bundle,
        get_file_outline,
        get_file_tree,
        get_repo_outline,
        get_section,
        get_symbol,
        get_toc,
    )
    from sylvan.tools.indexing import index_file, index_folder  # noqa: F401
    from sylvan.tools.library import add, list, remove  # noqa: F401
    from sylvan.tools.meta import list_repos, scaffold, suggest_queries  # noqa: F401
    from sylvan.tools.search import search_sections, search_symbols, search_text  # noqa: F401

    logger.info("warmup_tools_imported")

    try:
        from sylvan.extensions.loader import load_extensions

        count = load_extensions()
        if count:
            logger.info("warmup_extensions_loaded", count=count)
    except Exception as e:
        logger.debug("warmup_extensions_skipped", error=str(e))

    try:
        from sylvan.search.embeddings import get_embedding_provider

        provider = get_embedding_provider()
        if provider and provider.available():
            provider.embed_one("warmup")
            logger.info("warmup_embeddings_ready", provider=provider.name)
    except Exception as e:
        logger.debug("warmup_embeddings_skipped", error=str(e))

    import contextlib

    with contextlib.suppress(Exception):
        _check_for_updates()

    logger.info("warmup_complete")


_update_info: dict[str, str] = {}


def get_update_info() -> dict[str, str]:
    """Return cached update info. Empty dict if up to date or check failed."""
    return _update_info


def _check_for_updates() -> None:
    """Check PyPI for a newer version and cache the result."""
    import json
    import urllib.request
    from importlib.metadata import distribution

    dist = distribution("sylvan")
    current = dist.metadata["Version"]

    # Detect install method for correct upgrade command
    installer = "pip"
    is_editable = False
    is_uv_tool = False
    installer_file = dist._path / "INSTALLER"
    if installer_file.exists():
        installer = installer_file.read_text().strip()
    direct_url_file = dist._path / "direct_url.json"
    if direct_url_file.exists():
        direct = json.loads(direct_url_file.read_text())
        is_editable = direct.get("dir_info", {}).get("editable", False)
    site_path = str(dist._path.parent).replace("\\", "/")
    if "/uv/tools/" in site_path:
        is_uv_tool = True

    req = urllib.request.Request(
        "https://pypi.org/pypi/sylvan/json",
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=3) as resp:  # noqa: S310
        data = json.loads(resp.read())

    latest = data["info"]["version"]

    def _version_tuple(v: str) -> tuple[int, ...]:
        return tuple(int(x) for x in v.split(".") if x.isdigit())

    if _version_tuple(latest) > _version_tuple(current):
        _update_info["current"] = current
        _update_info["latest"] = latest
        if is_editable:
            _update_info["upgrade"] = "git pull && uv sync"
        elif is_uv_tool:
            _update_info["upgrade"] = "uv tool upgrade sylvan"
        elif installer == "uv":
            _update_info["upgrade"] = "uv pip install --upgrade sylvan"
        else:
            _update_info["upgrade"] = "pip install --upgrade sylvan"
        logger.info("update_available", current=current, latest=latest)
    else:
        logger.debug("version_up_to_date", version=current)


def _register_signal_handlers() -> None:
    """Flush usage stats on SIGTERM/SIGINT before exiting.

    MCP clients shut down via SIGTERM; Python's atexit doesn't run on
    SIGTERM, so we register explicit handlers to persist session data.
    """
    import os
    import signal

    def _flush_and_exit(signum: int, frame: object) -> None:
        """Flush usage stats, close backend, then re-raise the signal.

        Signal handlers are sync, so we access the raw sqlite3 connection
        directly for the WAL checkpoint and close. atexit doesn't run on
        SIGTERM, which is how MCP clients shut down the server.

        Args:
            signum: The signal number received.
            frame: The interrupted stack frame (unused).
        """
        try:
            from sylvan.session.usage_stats import flush_all

            flush_all()
        except Exception as exc:
            logger.warning("flush_all_failed_on_signal", error=str(exc))
        try:
            from sylvan.server import _shutdown_backend_sync

            _shutdown_backend_sync()
        except Exception as exc:
            logger.warning("shutdown_backend_failed_on_signal", error=str(exc))
        try:
            from sylvan.cluster.discovery import release_leadership_sync

            release_leadership_sync()
        except Exception as exc:
            logger.warning("release_leadership_failed_on_signal", error=str(exc))
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    signal.signal(signal.SIGTERM, _flush_and_exit)
    import contextlib

    with contextlib.suppress(OSError, ValueError):
        signal.signal(signal.SIGINT, _flush_and_exit)


def main(transport: str = "stdio", host: str = "127.0.0.1", port: int = 8420) -> None:
    """Entry point for the MCP server.

    Configures logging, warms up tool imports and embeddings,
    then starts the selected transport loop.
    Database schema is initialised asynchronously on first tool call.

    Args:
        transport: Transport mode -- "stdio", "sse", or "http".
        host: Bind address for SSE/HTTP modes.
        port: Port for SSE/HTTP modes.

    Raises:
        ValueError: If *transport* is not one of the recognised modes.
    """
    import asyncio
    import logging as _logging
    import os
    import sys

    from sylvan.logging import configure_logging

    os.environ["PYTHONUNBUFFERED"] = "1"
    try:
        sys.stdout.reconfigure(write_through=True)
        sys.stderr.reconfigure(write_through=True)
    except Exception:  # noqa: S110 -- reconfigure not available on all platforms
        pass

    if transport == "stdio":
        configure_logging(level="DEBUG", log_to_file=True)
        root = _logging.getLogger()
        root.handlers = [h for h in root.handlers if isinstance(h, _logging.FileHandler)]
    else:
        configure_logging(level="INFO", log_to_file=True)

    logger.info("mcp_server_starting", transport=transport)

    try:
        warm_up()
    except Exception as e:
        logger.error("warmup_failed", error=str(e))

    _register_signal_handlers()

    from sylvan.server import server
    from sylvan.server.lifecycle import ServerLifecycle
    from sylvan.server.transports import run_sse, run_stdio, run_streamable_http

    async def _run_with_lifecycle(coro):
        """Run the transport inside the lifecycle context manager.

        All background tasks spawned via lifecycle.spawn() are
        automatically cancelled when the transport coroutine returns.
        """
        async with ServerLifecycle():
            await coro

    try:
        match transport:
            case "stdio":
                asyncio.run(_run_with_lifecycle(run_stdio(server)))
            case "sse":
                asyncio.run(_run_with_lifecycle(run_sse(server, host=host, port=port)))
            case "http":
                asyncio.run(_run_with_lifecycle(run_streamable_http(server, host=host, port=port)))
            case _:
                logger.error("unknown_transport", transport=transport)
                raise ValueError(f"Unknown transport: {transport!r}. Use stdio, sse, or http.")
    except Exception as e:
        logger.error("mcp_server_crashed", error=str(e), transport=transport)
        raise
    finally:
        try:
            from sylvan.session.usage_stats import flush_all

            flush_all()
        except Exception:  # noqa: S110 -- shutdown must not crash on cleanup
            pass
        from sylvan.server import _shutdown_backend_sync

        _shutdown_backend_sync()
        from sylvan.cluster.discovery import release_leadership_sync

        release_leadership_sync()
