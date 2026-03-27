"""MCP server -- registers tools and routes requests to async handlers."""

import asyncio
import contextlib
import functools
import json
import uuid
from collections.abc import Callable
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

from sylvan.logging import get_logger
from sylvan.tools.definitions.analysis import TOOLS as ANALYSIS_TOOLS
from sylvan.tools.definitions.core import TOOLS as CORE_TOOLS
from sylvan.tools.definitions.support import TOOLS as SUPPORT_TOOLS

logger = get_logger(__name__)

_tool_semaphore: asyncio.Semaphore | None = None  # created lazily from config

server = Server("sylvan")

_backend = None
"""Cached async storage backend instance (created on first tool call)."""

_backend_lock = asyncio.Lock()


async def _get_or_create_backend():
    """Get or create the async SQLite storage backend.

    Creates the backend on first call, connects it, and runs schema
    migrations. Subsequent calls return the cached instance.  Uses a
    lock to prevent races that could create multiple backends.

    Returns:
        The connected SQLiteBackend instance.
    """
    global _backend, _tool_semaphore
    if _backend is not None:
        return _backend

    async with _backend_lock:
        if _backend is not None:
            return _backend

        from sylvan.config import get_config
        from sylvan.database.backends.sqlite.backend import SQLiteBackend
        from sylvan.database.migrations.runner import run_migrations

        config = get_config()
        backend = SQLiteBackend(config.db_path)
        await backend.connect()
        await run_migrations(backend)

        _backend = backend
        logger.info("async_backend_ready", db_path=str(config.db_path))

        if _tool_semaphore is None:
            _tool_semaphore = asyncio.Semaphore(config.server.max_concurrent_tools)

        import atexit

        atexit.register(_shutdown_backend_sync)

        # Cluster discovery -- determine leader/follower role via DB lock
        from sylvan.cluster.discovery import discover_role, generate_coding_session_id, generate_node_id
        from sylvan.cluster.state import ClusterState, set_cluster_state

        cluster_cfg = config.cluster
        if cluster_cfg.enabled:
            role, node_id, coding_session_id = await discover_role(
                stale_seconds=cluster_cfg.lock_stale_threshold,
            )
        else:
            coding_session_id = generate_coding_session_id()
            role, node_id = "leader", generate_node_id()

        # Set follower mode on the backend so reads use the read-only connection
        if role == "follower" and hasattr(backend, "set_follower_mode"):
            backend.set_follower_mode(True)

        leader_url = None
        if role == "follower":
            leader_url = f"http://127.0.0.1:{cluster_cfg.port}"

        set_cluster_state(
            ClusterState(
                role=role,
                session_id=node_id,
                coding_session_id=coding_session_id,
                leader_url=leader_url,
            )
        )
        logger.info("cluster_role_set", role=role, node_id=node_id, coding_session_id=coding_session_id)

        # Start dashboard only if we're the leader
        from sylvan.cluster.state import get_cluster_state

        if get_cluster_state().is_leader:
            try:
                from sylvan.dashboard.server import start_dashboard

                await start_dashboard()
            except Exception as exc:
                logger.debug("dashboard_start_skipped", error=str(exc))
        else:
            logger.info("dashboard_skipped_follower")

        # Clean up dead instances from previous runs
        try:
            from sylvan.cluster.heartbeat import cleanup_dead_instances

            await cleanup_dead_instances(backend)
        except Exception as exc:
            logger.debug("instance_cleanup_failed", error=str(exc))

        # Create/update coding session row
        try:
            from sylvan.cluster.heartbeat import ensure_coding_session

            await ensure_coding_session(backend, coding_session_id)
        except Exception as exc:
            logger.debug("coding_session_init_failed", error=str(exc))

        # Register this node in the cluster and start heartbeat
        try:
            from sylvan.cluster.heartbeat import register_node, start_heartbeat
            from sylvan.database.orm.runtime.query_cache import get_query_cache
            from sylvan.session.tracker import get_session as _get_heartbeat_session

            await register_node(backend, node_id, coding_session_id, role, cluster_cfg.port)
            await start_heartbeat(
                backend,
                _get_heartbeat_session(),
                get_query_cache(),
                node_id,
                coding_session_id,
                role,
                interval=cluster_cfg.heartbeat_interval,
            )
        except Exception as exc:
            logger.debug("heartbeat_start_failed", error=str(exc))

        return _backend


def _shutdown_backend_sync() -> None:
    """Close the backend connection on process exit.

    Called via atexit and signal handlers. The async event loop is
    typically already closed, so we bypass aiosqlite's async API
    and work directly with its internals: checkpoint WAL on the raw
    connection, send the stop sentinel to the worker thread, and
    join the thread so it finishes before the process exits.

    Note: In-flight tool calls may be interrupted on shutdown.
    The semaphore is not drained because _shutdown_backend_sync runs
    from signal handlers or atexit where the event loop is unavailable.
    """
    global _backend
    if _backend is None:
        return
    import contextlib

    aio_conn = _backend._connection
    if aio_conn is None:
        _backend = None
        return

    with contextlib.suppress(Exception):
        from aiosqlite.core import _STOP_RUNNING_SENTINEL

        aio_conn._running = False

        def _checkpoint_close_and_stop():
            """Run on aiosqlite's worker thread where the connection lives."""
            with contextlib.suppress(Exception):
                if aio_conn._connection is not None:
                    aio_conn._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                    aio_conn._connection.close()
                    aio_conn._connection = None
            return _STOP_RUNNING_SENTINEL

        aio_conn._tx.put_nowait((None, _checkpoint_close_and_stop))
        aio_conn._thread.join(timeout=2)

    logger.info("backend_disconnected")
    _backend = None


@server.list_tools()
async def list_tools() -> list[Tool]:
    """Return all registered MCP tools.

    Kicks off backend + dashboard init in the background so the dashboard
    is ready by the time the user makes their first tool call.

    Returns:
        Combined list of core, analysis, and support tool definitions.
    """
    asyncio.ensure_future(_get_or_create_backend())

    core_tools = [*CORE_TOOLS, *ANALYSIS_TOOLS, *SUPPORT_TOOLS]
    core_names = {t.name for t in core_tools}

    from sylvan.extensions import get_registered_tools

    ext_tools = [
        Tool(name=info["name"], description=info["description"], inputSchema=info["schema"])
        for info in get_registered_tools().values()
        if info["name"] not in core_names
    ]

    return [*core_tools, *ext_tools]


@server.call_tool(validate_input=False)
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Route tool calls to their async implementations.

    Disables MCP SDK input validation so we can coerce JSON-encoded
    strings back to native arrays before dispatch.  Some MCP clients
    serialize array parameters as JSON strings during deferred tool
    loading, which fails strict jsonschema validation.

    Args:
        name: Tool name from the MCP request.
        arguments: Tool arguments dict.

    Returns:
        List containing a single TextContent with JSON response.
    """
    for key, value in arguments.items():
        if isinstance(value, str):
            if value.startswith("[") or value.startswith("{"):
                with contextlib.suppress(json.JSONDecodeError, ValueError):
                    arguments[key] = json.loads(value)
            elif value.isdigit():
                arguments[key] = int(value)

    logger.info("tool_call_received", tool=name, args=str(arguments)[:200])
    try:
        result = await _dispatch(name, arguments)
        logger.info("tool_call_completed", tool=name)
        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
    except Exception as exc:
        logger.exception("tool_call_failed", tool=name, error=str(exc))
        error_result = {"error": "Internal error. Check server logs for details.", "tool": name}
        return [TextContent(type="text", text=json.dumps(error_result))]


async def _dispatch(name: str, arguments: dict) -> dict:
    """Route a tool call to its async handler.

    Creates a SylvanContext with the async storage backend for each
    request, acquires the concurrency semaphore, and dispatches to
    the appropriate handler.

    Args:
        name: Tool name from MCP request.
        arguments: Tool arguments dict.

    Returns:
        Tool response dict.
    """
    global _tool_semaphore

    import structlog

    from sylvan.context import SylvanContext, using_context
    from sylvan.error_codes import SylvanError

    request_id = uuid.uuid4().hex[:8]
    structlog.contextvars.bind_contextvars(request_id=request_id)

    backend = await _get_or_create_backend()

    # Gate: require workflow guide before real tools (checked early so
    # followers don't proxy write tools before the agent sees the rules)
    from sylvan.config import get_config as _get_gate_config
    from sylvan.session.tracker import get_session as _early_session

    _ungated = {
        "get_workflow_guide",
        "list_repos",
        "list_libraries",
        "get_session_stats",
        "get_dashboard_url",
        "get_server_config",
        "get_logs",
        "suggest_queries",
        "index_folder",
        "configure_claude_code",
        "configure_cursor",
        "configure_windsurf",
        "configure_copilot",
    }
    _gate_enabled = _get_gate_config().server.workflow_gate
    if _gate_enabled and not _early_session()._workflow_loaded and name not in _ungated:
        from sylvan.server.startup import get_update_info

        gate_response = {
            "setup_required": True,
            "message": (
                "Sylvan session is not configured. Call your editor's configure tool "
                "(configure_claude_code, configure_cursor, configure_windsurf, or "
                "configure_copilot) to set up and unlock all tools. Alternatively, "
                "call get_workflow_guide for manual setup."
            ),
            "blocked_tool": name,
            "blocked_args": arguments,
        }
        update = get_update_info()
        if update:
            gate_response["update_available"] = update
        return gate_response

    # If we're a follower and this is a write tool, proxy to leader
    from sylvan.cluster.proxy import is_write_tool, proxy_to_leader
    from sylvan.cluster.state import get_cluster_state

    cluster = get_cluster_state()
    if cluster.is_follower and is_write_tool(name):
        logger.info("proxying_write_to_leader", tool=name, leader=cluster.leader_url)
        return await proxy_to_leader(name, arguments)

    from sylvan.config import get_config
    from sylvan.database.orm.runtime.identity_map import IdentityMap
    from sylvan.database.orm.runtime.query_cache import get_query_cache
    from sylvan.session.tracker import get_session

    ctx = SylvanContext(
        backend=backend,
        config=get_config(),
        session=get_session(),
        cache=get_query_cache(),
        identity_map=IdentityMap(),
    )

    logger.info("tool_call_dispatching", tool=name, request_id=request_id)

    if _tool_semaphore is None:
        from sylvan.config import get_config as _get_dispatch_config

        _dispatch_cfg = _get_dispatch_config()
        _tool_semaphore = asyncio.Semaphore(_dispatch_cfg.server.max_concurrent_tools)

    async with using_context(ctx):
        try:
            from sylvan.config import get_config as _get_timeout_config

            _timeout = _get_timeout_config().server.request_timeout
            await asyncio.wait_for(_tool_semaphore.acquire(), timeout=_timeout)
        except TimeoutError:
            return {"error": "server_busy", "detail": "Too many concurrent tool calls. Try again."}

        try:
            from sylvan.session.tracker import get_session as _get_session

            session = _get_session()
            session.record_tool_call(name)

            handlers = _get_handlers()
            handler = handlers.get(name)
            if handler is None:
                return {"error": f"Unknown tool: {name}"}
            try:
                result = handler(**arguments)
                if asyncio.iscoroutine(result):
                    result = await result

                # Record token efficiency from tool response
                if isinstance(result, dict):
                    meta = result.get("_meta", {})
                    efficiency = meta.get("token_efficiency")
                    if efficiency:
                        category = _tool_category(name)
                        returned = efficiency.get("returned", 0)
                        equivalent = efficiency.get("equivalent_file_read", 0)
                        _get_session().record_efficiency(
                            category,
                            returned,
                            equivalent,
                        )

                        # Persist per-repo efficiency to usage_stats
                        repo_id = meta.get("repo_id")
                        if repo_id:
                            from sylvan.session.usage_stats import record_usage

                            eff_kwargs: dict[str, int] = {}
                            if category == "search":
                                eff_kwargs["tokens_returned_search"] = returned
                                eff_kwargs["tokens_equivalent_search"] = equivalent
                            elif category == "retrieval":
                                eff_kwargs["tokens_returned_retrieval"] = returned
                                eff_kwargs["tokens_equivalent_retrieval"] = equivalent
                            if eff_kwargs:
                                record_usage(repo_id, tool_calls=0, **eff_kwargs)

                return result
            except SylvanError as exc:
                return exc.to_dict()
            finally:
                try:
                    from sylvan.session.usage_stats import get_accumulator

                    acc = get_accumulator()
                    if acc._call_count >= acc._FLUSH_INTERVAL:
                        from sylvan.session.usage_stats import async_flush_usage

                        await async_flush_usage()
                except Exception as flush_exc:
                    logger.debug("usage_flush_failed", error=str(flush_exc))
        finally:
            _tool_semaphore.release()
            structlog.contextvars.unbind_contextvars("request_id")


@functools.cache
def _get_handlers() -> dict[str, Callable[..., dict]]:
    """Build the handler dispatch table.

    Imports are deferred to avoid loading all tool modules at import time.
    After warmup, all modules are already cached so this is cheap.

    Returns:
        Mapping of tool names to their handler callables.
    """
    from sylvan.tools.analysis.find_importers import batch_find_importers, find_importers
    from sylvan.tools.analysis.get_blast_radius import batch_blast_radius, get_blast_radius
    from sylvan.tools.analysis.get_class_hierarchy import get_class_hierarchy
    from sylvan.tools.analysis.get_dependency_graph import get_dependency_graph
    from sylvan.tools.analysis.get_git_context import get_git_context
    from sylvan.tools.analysis.get_quality import get_quality
    from sylvan.tools.analysis.get_quality_report import get_quality_report
    from sylvan.tools.analysis.get_recent_changes import get_recent_changes
    from sylvan.tools.analysis.get_references import get_references
    from sylvan.tools.analysis.get_related import get_related
    from sylvan.tools.analysis.get_symbol_diff import get_symbol_diff
    from sylvan.tools.analysis.rename_symbol import rename_symbol
    from sylvan.tools.analysis.search_columns import search_columns
    from sylvan.tools.browsing.get_context_bundle import get_context_bundle
    from sylvan.tools.browsing.get_file_outline import get_file_outline, get_file_outlines
    from sylvan.tools.browsing.get_file_tree import get_file_tree
    from sylvan.tools.browsing.get_repo_outline import get_repo_outline
    from sylvan.tools.browsing.get_section import get_section, get_sections
    from sylvan.tools.browsing.get_symbol import get_symbol, get_symbols
    from sylvan.tools.browsing.get_toc import get_toc, get_toc_tree
    from sylvan.tools.indexing.index_file import index_file
    from sylvan.tools.indexing.index_folder import index_folder
    from sylvan.tools.library.add import add_library as add_library_tool
    from sylvan.tools.library.check import check_library_versions
    from sylvan.tools.library.compare import compare_library_versions
    from sylvan.tools.library.list import list_libraries as list_libraries_tool
    from sylvan.tools.library.remove import remove_library as remove_library_tool
    from sylvan.tools.meta.configure_editor import (
        configure_claude_code,
        configure_copilot,
        configure_cursor,
        configure_windsurf,
    )
    from sylvan.tools.meta.get_logs import get_logs
    from sylvan.tools.meta.get_server_config import get_server_config
    from sylvan.tools.meta.get_workflow_guide import get_workflow_guide
    from sylvan.tools.meta.list_repos import list_repos
    from sylvan.tools.meta.remove_repo import remove_repo
    from sylvan.tools.meta.scaffold import scaffold as scaffold_tool
    from sylvan.tools.meta.suggest_queries import suggest_queries
    from sylvan.tools.search.search_sections import search_sections
    from sylvan.tools.search.search_similar import search_similar_symbols
    from sylvan.tools.search.search_symbols import batch_search_symbols, search_symbols
    from sylvan.tools.search.search_text import search_text
    from sylvan.tools.workspace import (
        add_to_workspace,
        index_workspace,
        workspace_blast_radius,
        workspace_search,
    )
    from sylvan.tools.workspace.pin_library import pin_library

    async def _list_repos_wrapper(**_kwargs: Any) -> dict:
        """Wrap list_repos to accept and ignore empty kwargs from dispatch.

        Returns:
            Tool response dict from list_repos.
        """
        return await list_repos()

    async def _list_libraries_wrapper(**_kwargs: Any) -> dict:
        """Wrap list_libraries to accept and ignore empty kwargs from dispatch.

        Returns:
            Tool response dict from list_libraries.
        """
        return await list_libraries_tool()

    async def _get_session_stats(**kwargs: Any) -> dict:
        """Handle get_session_stats with custom argument unpacking.

        Args:
            **kwargs: Optional 'repo' key to filter stats to a specific project.

        Returns:
            Usage stats dict at session, project, and overall levels.
        """
        return await _get_usage_stats(kwargs)

    handlers = {
        "index_folder": index_folder,
        "index_file": index_file,
        "search_symbols": search_symbols,
        "batch_search_symbols": batch_search_symbols,
        "get_symbol": get_symbol,
        "get_symbols": get_symbols,
        "get_file_outline": get_file_outline,
        "get_file_outlines": get_file_outlines,
        "get_file_tree": get_file_tree,
        "list_repos": _list_repos_wrapper,
        "search_sections": search_sections,
        "get_section": get_section,
        "get_sections": get_sections,
        "get_toc": get_toc,
        "get_toc_tree": get_toc_tree,
        "get_repo_outline": get_repo_outline,
        "get_blast_radius": get_blast_radius,
        "batch_blast_radius": batch_blast_radius,
        "get_class_hierarchy": get_class_hierarchy,
        "get_references": get_references,
        "find_importers": find_importers,
        "batch_find_importers": batch_find_importers,
        "get_dependency_graph": get_dependency_graph,
        "get_symbol_diff": get_symbol_diff,
        "search_columns": search_columns,
        "get_related": get_related,
        "get_quality": get_quality,
        "get_quality_report": get_quality_report,
        "get_git_context": get_git_context,
        "get_recent_changes": get_recent_changes,
        "rename_symbol": rename_symbol,
        "search_text": search_text,
        "get_context_bundle": get_context_bundle,
        "suggest_queries": suggest_queries,
        "get_session_stats": _get_session_stats,
        "scaffold": scaffold_tool,
        "add_library": add_library_tool,
        "check_library_versions": check_library_versions,
        "compare_library_versions": compare_library_versions,
        "list_libraries": _list_libraries_wrapper,
        "remove_library": remove_library_tool,
        "index_workspace": index_workspace,
        "workspace_search": workspace_search,
        "workspace_blast_radius": workspace_blast_radius,
        "add_to_workspace": add_to_workspace,
        "pin_library": pin_library,
        "get_dashboard_url": _get_dashboard_url,
        "get_logs": get_logs,
        "get_workflow_guide": get_workflow_guide,
        "get_server_config": get_server_config,
        "configure_claude_code": configure_claude_code,
        "configure_cursor": configure_cursor,
        "configure_windsurf": configure_windsurf,
        "configure_copilot": configure_copilot,
        "search_similar_symbols": search_similar_symbols,
        "remove_repo": remove_repo,
    }

    # Merge extension tool handlers (cannot overwrite core tools)
    from sylvan.extensions import get_registered_tools

    for name, info in get_registered_tools().items():
        if name in handlers:
            logger.warning("extension_tool_conflicts_with_core", tool=name)
            continue
        handlers[name] = info["handler"]

    return handlers


_TOOL_CATEGORIES: dict[str, str] = {
    # search
    "search_symbols": "search",
    "batch_search_symbols": "search",
    "search_text": "search",
    "search_sections": "search",
    "search_similar_symbols": "search",
    # retrieval
    "get_symbol": "retrieval",
    "get_symbols": "retrieval",
    "get_section": "retrieval",
    "get_sections": "retrieval",
    "get_context_bundle": "retrieval",
    "get_file_outline": "retrieval",
    "get_file_outlines": "retrieval",
    "get_toc": "retrieval",
    "get_toc_tree": "retrieval",
    "get_repo_outline": "retrieval",
    "get_file_tree": "retrieval",
    # analysis
    "get_blast_radius": "analysis",
    "batch_blast_radius": "analysis",
    "get_class_hierarchy": "analysis",
    "get_references": "analysis",
    "find_importers": "analysis",
    "batch_find_importers": "analysis",
    "get_related": "analysis",
    "get_quality": "analysis",
    "get_quality_report": "analysis",
    "get_dependency_graph": "analysis",
    "get_symbol_diff": "analysis",
    "search_columns": "analysis",
    "get_git_context": "analysis",
    "get_recent_changes": "analysis",
    "rename_symbol": "analysis",
    # indexing
    "index_folder": "indexing",
    "index_file": "indexing",
    "index_workspace": "indexing",
    # meta
    "list_repos": "meta",
    "suggest_queries": "meta",
    "get_session_stats": "meta",
    "get_logs": "meta",
    "get_server_config": "meta",
    "get_workflow_guide": "meta",
    "configure_claude_code": "meta",
    "configure_cursor": "meta",
    "configure_windsurf": "meta",
    "configure_copilot": "meta",
    "scaffold": "meta",
    "get_dashboard_url": "meta",
    "add_library": "meta",
    "list_libraries": "meta",
    "remove_library": "meta",
    "check_library_versions": "meta",
    "compare_library_versions": "meta",
    "add_to_workspace": "meta",
    "workspace_search": "meta",
    "workspace_blast_radius": "meta",
    "pin_library": "meta",
    "remove_repo": "meta",
}
"""Mapping of tool names to efficiency categories."""


def _tool_category(name: str) -> str:
    """Get the efficiency category for a tool name.

    Args:
        name: MCP tool name.

    Returns:
        Category string ('search', 'retrieval', 'analysis', 'indexing', or 'meta').
    """
    return _TOOL_CATEGORIES.get(name, "meta")


async def _get_dashboard_url(**_kwargs: object) -> dict:
    """Return the dashboard URL if the web server is running.

    Returns:
        Dict with 'url' key, or 'message' if dashboard is not available.
    """
    from sylvan.dashboard.server import get_dashboard_url

    url = get_dashboard_url()
    if url:
        return {"url": url, "status": "running"}
    return {"status": "not_running", "message": "Dashboard is not available."}


async def _get_usage_stats(args: dict) -> dict:
    """Build usage stats at session, project, and overall levels.

    Uses the async backend for usage queries when available, falling
    back to the sync path for backward compatibility.

    Args:
        args: Optional dict with a 'repo' key to filter project-level stats.

    Returns:
        Dict with 'session', optionally 'project', and 'overall' usage data.
    """
    from sylvan.database.orm import Repo
    from sylvan.session.tracker import get_session
    from sylvan.session.usage_stats import (
        async_get_overall_usage,
        async_get_project_usage,
    )

    session = get_session()
    session_stats = session.get_session_stats()
    session_stats["token_efficiency"] = session.get_efficiency_stats()
    result: dict = {"session": session_stats}

    backend = await _get_or_create_backend()
    repo_name = args.get("repo")
    if repo_name:
        repo = await Repo.where(name=repo_name).first()
        if repo:
            project_stats = await async_get_project_usage(backend, repo.id)
            # Compute per-repo efficiency summary
            search_ret = project_stats.get("total_tokens_returned_search", 0)
            search_eq = project_stats.get("total_tokens_equivalent_search", 0)
            retrieval_ret = project_stats.get("total_tokens_returned_retrieval", 0)
            retrieval_eq = project_stats.get("total_tokens_equivalent_retrieval", 0)
            total_eq = search_eq + retrieval_eq
            total_ret = search_ret + retrieval_ret
            reduction = round((1 - total_ret / total_eq) * 100, 1) if total_eq > 0 else 0.0
            project_stats["efficiency"] = {
                "search": {"returned": search_ret, "equivalent": search_eq},
                "retrieval": {"returned": retrieval_ret, "equivalent": retrieval_eq},
                "reduction_percent": reduction,
            }
            result["project"] = project_stats

    result["overall"] = await async_get_overall_usage(backend)

    # Cluster: nodes and coding sessions from DB
    from sylvan.cluster.state import get_cluster_state
    from sylvan.database.orm import ClusterNode, CodingSession, Instance

    cluster = get_cluster_state()
    result["cluster"] = {
        "role": cluster.role,
        "session_id": cluster.session_id,
        "coding_session_id": cluster.coding_session_id,
    }

    cs = await CodingSession.where(id=cluster.coding_session_id).first()
    if cs:
        result["cluster"]["coding_session"] = {
            "id": cs.id,
            "started_at": cs.started_at,
            "ended_at": cs.ended_at,
            "total_tool_calls": cs.total_tool_calls,
            "total_efficiency_returned": cs.total_efficiency_returned,
            "total_efficiency_equivalent": cs.total_efficiency_equivalent,
            "instances_spawned": cs.instances_spawned,
        }

    nodes = await ClusterNode.query().order_by("role").order_by("last_seen", "DESC").get()
    nodes_list = []
    for node in nodes:
        nodes_list.append(
            {
                "node_id": node.node_id,
                "coding_session_id": node.coding_session_id,
                "pid": node.pid,
                "role": node.role or "unknown",
                "ws_port": node.ws_port,
                "last_seen": node.last_seen or "",
            }
        )
    result["cluster"]["nodes"] = nodes_list
    result["cluster"]["active_count"] = len(nodes_list)

    active_instances = await Instance.active().get()
    total_tool_calls = sum(inst.tool_calls or 0 for inst in active_instances)
    result["cluster"]["total_tool_calls"] = total_tool_calls

    history_sessions = await CodingSession.query().order_by("started_at", "DESC").limit(10).get()
    history = []
    for h in history_sessions:
        eq = h.total_efficiency_equivalent or 0
        ret = h.total_efficiency_returned or 0
        history.append(
            {
                "id": h.id,
                "started_at": h.started_at,
                "ended_at": h.ended_at,
                "total_tool_calls": h.total_tool_calls or 0,
                "instances_spawned": h.instances_spawned or 0,
                "reduction_percent": round((1 - ret / eq) * 100, 1) if eq > 0 else 0,
            }
        )
    result["cluster"]["coding_session_history"] = history

    from sylvan.database.orm.runtime.query_cache import get_query_cache

    result["cache"] = get_query_cache().stats()

    return result
