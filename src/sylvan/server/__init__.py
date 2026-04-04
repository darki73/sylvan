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
from sylvan.tools.base.tool import get_all_tools as _get_all_base_tools

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

        from sylvan.cluster.discovery import discover_role, generate_coding_session_id, generate_node_id
        from sylvan.cluster.state import ClusterState, set_cluster_state
        from sylvan.context import init_app_state
        from sylvan.database.orm.runtime.query_cache import get_query_cache
        from sylvan.session.tracker import get_session

        init_app_state(
            backend=backend,
            config=config,
            session=get_session(),
            cache=get_query_cache(),
        )

        cluster_cfg = config.cluster
        if cluster_cfg.enabled:
            role, node_id, coding_session_id = await discover_role(
                stale_seconds=cluster_cfg.lock_stale_threshold,
            )
        else:
            coding_session_id = generate_coding_session_id()
            role, node_id = "leader", generate_node_id()

        if role == "follower" and hasattr(backend, "enable_follower_mode"):
            await backend.enable_follower_mode()
        elif hasattr(backend, "enable_leader_mode"):
            await backend.enable_leader_mode()

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

        # Start dashboard + WebSocket server (leader) or connect to leader (follower)
        from sylvan.cluster.state import get_cluster_state

        if get_cluster_state().is_leader:
            try:
                from sylvan.dashboard.server import start_dashboard

                await start_dashboard()
            except Exception as exc:
                logger.debug("dashboard_start_skipped", error=str(exc))

            try:
                from sylvan.cluster.websocket import start_leader_pings

                await start_leader_pings(interval=cluster_cfg.ws_ping_interval)
            except Exception as exc:
                logger.debug("leader_pings_start_failed", error=str(exc))
        else:
            logger.info("dashboard_skipped_follower")

            try:
                from sylvan.cluster.websocket import connect_to_leader

                await connect_to_leader(leader_url, node_id)
            except Exception as exc:
                logger.debug("leader_connection_failed", error=str(exc))

            try:
                import logging

                from sylvan.cluster.logging import ClusterLogHandler

                handler = ClusterLogHandler(node_id=node_id, role="follower")
                logging.getLogger().addHandler(handler)
            except Exception as exc:
                logger.debug("cluster_log_handler_failed", error=str(exc))

        # Clean up dead nodes from previous runs (leader only)
        if get_cluster_state().is_leader:
            try:
                from sylvan.cluster.heartbeat import cleanup_dead_nodes

                await cleanup_dead_nodes(backend)
            except Exception as exc:
                logger.debug("node_cleanup_failed", error=str(exc))

        # Create/update coding session row and register node (leader only)
        if get_cluster_state().is_leader:
            try:
                from sylvan.cluster.heartbeat import ensure_coding_session

                await ensure_coding_session(backend, coding_session_id)
            except Exception as exc:
                logger.debug("coding_session_init_failed", error=str(exc))

            try:
                from sylvan.cluster.heartbeat import register_node

                await register_node(backend, node_id, coding_session_id, role, cluster_cfg.port)
            except Exception as exc:
                logger.debug("node_registration_failed", error=str(exc))

        # Start heartbeat
        try:
            from sylvan.cluster.heartbeat import start_heartbeat
            from sylvan.database.orm.runtime.query_cache import get_query_cache
            from sylvan.session.tracker import get_session as _get_heartbeat_session

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

        # Follower: send stats to leader on every tool call
        if get_cluster_state().is_follower:
            try:
                from sylvan.cluster.heartbeat import _send_stats_to_leader
                from sylvan.database.orm.runtime.query_cache import get_query_cache as _get_follower_cache
                from sylvan.events import on as _on_event
                from sylvan.session.tracker import get_session as _get_follower_session

                _f_session = _get_follower_session()
                _f_cache = _get_follower_cache()
                _f_node_id = node_id

                def _on_follower_tool_call(_data):
                    import asyncio

                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(_send_stats_to_leader(_f_session, _f_cache, _f_node_id))
                    except RuntimeError:
                        pass

                _on_event("tool_call", _on_follower_tool_call)
            except Exception as exc:
                logger.debug("follower_stats_hook_failed", error=str(exc))

        # Start the job queue runner (leader only)
        if get_cluster_state().is_leader:
            try:
                from sylvan.queue import get_runner
                from sylvan.server.lifecycle import get_lifecycle

                lifecycle = get_lifecycle()
                if lifecycle:
                    runner = get_runner()
                    lifecycle.spawn(runner.run(), name="job_queue")
            except Exception as exc:
                logger.debug("queue_runner_start_failed", error=str(exc))

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

    def _stop_aio_connection(conn):
        """Checkpoint, close, and stop an aiosqlite connection's worker thread."""
        if conn is None:
            return
        with contextlib.suppress(Exception):
            from aiosqlite.core import _STOP_RUNNING_SENTINEL

            conn._running = False

            def _close():
                with contextlib.suppress(Exception):
                    if conn._connection is not None:
                        conn._connection.close()
                        conn._connection = None
                return _STOP_RUNNING_SENTINEL

            conn._tx.put_nowait((None, _close))
            conn._thread.join(timeout=0.5)

    from sylvan.cluster.state import get_cluster_state

    if get_cluster_state().is_leader:
        with contextlib.suppress(Exception):
            if aio_conn and aio_conn._connection is not None:
                aio_conn._connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")

    _stop_aio_connection(_backend._read_connection)
    _stop_aio_connection(aio_conn)

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

    # Probe MCP client for editor and project info (protocol-driven setup)
    try:
        from urllib.parse import unquote

        from sylvan.session.tracker import get_session as _list_session
        from sylvan.tools.meta.editor_setup import EditorKind, check_setup, detect_editor

        ctx = server.request_context
        mcp_session = ctx.session
        tracker = _list_session()

        if not tracker._setup_checked:
            client_name = ""
            if mcp_session._client_params and mcp_session._client_params.clientInfo:
                client_name = mcp_session._client_params.clientInfo.name or ""
            editor = detect_editor(client_name)
            tracker._editor = editor.value

            project_path = None
            try:
                roots_result = await mcp_session.list_roots()
                if roots_result.roots:
                    uri = str(roots_result.roots[0].uri)
                    if uri.startswith("file:///"):
                        project_path = unquote(uri[8:] if uri[9:10] == ":" else uri[7:])
            except Exception:
                logger.debug("list_roots_unavailable")

            if project_path:
                tracker._project_path = project_path

            if project_path and editor != EditorKind.UNKNOWN:
                from pathlib import Path as _ListPath

                tracker._setup_actions = check_setup(editor, _ListPath(project_path))
            else:
                tracker._setup_actions = []

            tracker._setup_checked = True
    except LookupError:
        pass

    _import_all_tool_modules()
    core_tools = [t.to_mcp_tool() for t in _get_all_base_tools()]
    core_names = {t.name for t in core_tools}

    # Server-level tools not in the registry
    for name, desc, schema in _SERVER_TOOLS:
        if name not in core_names:
            core_tools.append(Tool(name=name, description=desc, inputSchema=schema))
            core_names.add(name)

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

    from sylvan.error_codes import SylvanError

    request_id = uuid.uuid4().hex[:8]
    structlog.contextvars.bind_contextvars(request_id=request_id)

    await _get_or_create_backend()

    # Gate: if setup incomplete, elicit user permission before executing gated tools
    from sylvan.session.tracker import get_session as _early_session

    _ungated = {
        "get_workflow_guide",
        "list_repos",
        "list_libraries",
        "get_session_stats",
        "get_dashboard_url",
        "get_peak_status",
        "get_server_config",
        "get_logs",
        "suggest_queries",
        "index_folder",
        "configure_claude_code",
        "configure_cursor",
        "configure_windsurf",
        "configure_copilot",
    }

    _session = _early_session()
    if name not in _ungated and not _session._workflow_loaded and _session._setup_actions:
        from sylvan.tools.meta.editor_setup import (
            EditorKind,
            apply_setup,
            build_elicitation_message,
            get_settings_file,
        )

        accepted = False
        editor = EditorKind(_session._editor) if _session._editor else EditorKind.UNKNOWN

        try:
            ctx = server.request_context
            mcp_session = ctx.session

            has_elicitation = False
            if mcp_session._client_params and mcp_session._client_params.capabilities:
                has_elicitation = mcp_session._client_params.capabilities.elicitation is not None

            if has_elicitation and _session._project_path:
                settings_file = get_settings_file(editor)
                message = build_elicitation_message(_session._setup_actions, settings_file)

                result = await mcp_session.elicit(
                    message=message,
                    requestedSchema={
                        "type": "object",
                        "properties": {
                            "confirm": {
                                "type": "boolean",
                                "description": "Allow sylvan to write configuration",
                                "default": True,
                            }
                        },
                    },
                )

                if result.action == "accept" and result.content and result.content.get("confirm"):
                    from pathlib import Path as _GatePath

                    apply_setup(editor, _GatePath(_session._project_path))
                    _session._setup_actions = []
                    accepted = True

        except LookupError:
            pass
        except Exception as exc:
            logger.warning("gate_elicitation_failed", error=str(exc))

        if not accepted:
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
    from sylvan.cluster import is_write_tool
    from sylvan.cluster.state import get_cluster_state

    cluster = get_cluster_state()
    if cluster.is_follower and is_write_tool(name):
        from sylvan.cluster.websocket import proxy_to_leader

        logger.info("proxying_write_to_leader", tool=name)
        return await proxy_to_leader(name, arguments)

    from sylvan.context import reset_identity_map, set_identity_map
    from sylvan.database.orm.runtime.identity_map import IdentityMap

    _im_token = set_identity_map(IdentityMap())

    logger.info("tool_call_dispatching", tool=name, request_id=request_id)

    if _tool_semaphore is None:
        from sylvan.config import get_config as _get_dispatch_config

        _dispatch_cfg = _get_dispatch_config()
        _tool_semaphore = asyncio.Semaphore(_dispatch_cfg.server.max_concurrent_tools)

    try:
        try:
            from sylvan.config import get_config as _get_timeout_config

            _timeout = _get_timeout_config().server.request_timeout
            await asyncio.wait_for(_tool_semaphore.acquire(), timeout=_timeout)
        except TimeoutError:
            return {"error": "server_busy", "detail": "Too many concurrent tool calls. Try again."}

        try:
            from sylvan.session.tracker import get_session as _get_session

            session = _get_session()

            handlers = _get_handlers()
            handler = handlers.get(name)
            if handler is None:
                return {"error": f"Unknown tool: {name}"}
            try:
                from datetime import UTC, datetime

                from sylvan.tools.base.meta import ToolMeta, reset_meta, set_meta

                _request_meta = ToolMeta()
                _request_meta.repo(arguments.get("repo") or arguments.get("workspace") or arguments.get("name"))
                _meta_token = set_meta(_request_meta)

                try:
                    result = handler(**arguments)
                    if asyncio.iscoroutine(result):
                        result = await result
                finally:
                    reset_meta(_meta_token)

                built_meta = _request_meta.build()
                category = _tool_category(name)
                _call_repo = built_meta.get("repo")

                if isinstance(result, dict):
                    existing_meta = result.get("_meta", {})
                    existing_meta.update(
                        {k: v for k, v in built_meta.items() if k not in existing_meta or existing_meta[k] is None}
                    )
                    existing_meta["timing_ms"] = built_meta["timing_ms"]
                    if not existing_meta.get("repo"):
                        existing_meta["repo"] = _call_repo
                    if not existing_meta.get("repo") and arguments.get("symbol_id"):
                        from sylvan.database.orm import Symbol as _SymLookup

                        _sym_row = await _SymLookup.where(symbol_id=arguments["symbol_id"]).with_("file.repo").first()
                        if _sym_row and getattr(_sym_row, "file", None) and getattr(_sym_row.file, "repo", None):
                            existing_meta["repo"] = _sym_row.file.repo.name
                    result["_meta"] = existing_meta

                _call_timing = built_meta.get("timing_ms")
                if isinstance(result, dict):
                    _call_repo = result.get("_meta", {}).get("repo") or _call_repo

                # Extract token efficiency from result
                _eff = {}
                if isinstance(result, dict):
                    _eff = result.get("_meta", {}).get("token_efficiency", {})
                _tokens_returned = _eff.get("returned", 0)
                _tokens_equivalent = _eff.get("equivalent_file_read", 0)

                # Single recording call - all stats in one place
                session.record_tool_call(
                    name,
                    repo=_call_repo,
                    duration_ms=_call_timing,
                    category=category,
                    tokens_returned=_tokens_returned,
                    tokens_equivalent=_tokens_equivalent,
                )

                # Per-repo per-day DB stats
                from sylvan.session.usage_stats import record_usage

                _repo_id = result.get("_meta", {}).get("repo_id", 0) if isinstance(result, dict) else 0
                _usage_kwargs: dict[str, int] = {"tool_calls": 1}
                if _tokens_returned:
                    _usage_kwargs["tokens_returned"] = _tokens_returned
                    _usage_kwargs["tokens_avoided"] = max(0, _tokens_equivalent - _tokens_returned)
                    if category == "search":
                        _usage_kwargs["tokens_returned_search"] = _tokens_returned
                        _usage_kwargs["tokens_equivalent_search"] = _tokens_equivalent
                    elif category == "retrieval":
                        _usage_kwargs["tokens_returned_retrieval"] = _tokens_returned
                        _usage_kwargs["tokens_equivalent_retrieval"] = _tokens_equivalent
                await record_usage(_repo_id or 0, **_usage_kwargs)

                from sylvan.events import emit as _emit_event

                _tool_call_efficiency = session.get_efficiency_stats()
                try:
                    from sylvan.cluster.state import get_cluster_state as _get_tc_state

                    if _get_tc_state().is_leader:
                        from sylvan.dashboard.app import _combine_session_efficiency, _get_cluster_sessions

                        _tc_sessions = await _get_cluster_sessions()
                        _tc_combined = _combine_session_efficiency(_tc_sessions)
                        if _tc_combined:
                            _tool_call_efficiency = _tc_combined
                except Exception:  # noqa: S110
                    pass

                _emit_event(
                    "tool_call",
                    {
                        "name": name,
                        "timestamp": datetime.now(UTC).isoformat(),
                        "repo": _call_repo,
                        "duration_ms": _call_timing,
                        "session": session.get_session_stats(),
                        "efficiency": _tool_call_efficiency,
                    },
                )

                return result
            except SylvanError as exc:
                return exc.to_dict()
        finally:
            _tool_semaphore.release()
            structlog.contextvars.unbind_contextvars("request_id")
    finally:
        reset_identity_map(_im_token)


def _import_all_tool_modules() -> None:
    """Import all tool modules so __init_subclass__ registers them."""
    import sylvan.tools.analysis.calls_to
    import sylvan.tools.analysis.find_importers
    import sylvan.tools.analysis.get_blast_radius
    import sylvan.tools.analysis.get_class_hierarchy
    import sylvan.tools.analysis.get_dependency_graph
    import sylvan.tools.analysis.get_git_context
    import sylvan.tools.analysis.get_hotspots
    import sylvan.tools.analysis.get_quality
    import sylvan.tools.analysis.get_quality_report
    import sylvan.tools.analysis.get_recent_changes
    import sylvan.tools.analysis.get_references
    import sylvan.tools.analysis.get_related
    import sylvan.tools.analysis.get_symbol_diff
    import sylvan.tools.analysis.rename_symbol
    import sylvan.tools.analysis.search_columns
    import sylvan.tools.analysis.who_calls
    import sylvan.tools.browsing.get_context_bundle
    import sylvan.tools.browsing.get_file_outline
    import sylvan.tools.browsing.get_file_tree
    import sylvan.tools.browsing.get_repo_briefing
    import sylvan.tools.browsing.get_repo_outline
    import sylvan.tools.browsing.get_section
    import sylvan.tools.browsing.get_symbol
    import sylvan.tools.browsing.get_toc
    import sylvan.tools.indexing.index_file
    import sylvan.tools.indexing.index_folder
    import sylvan.tools.library.add
    import sylvan.tools.library.check
    import sylvan.tools.library.compare
    import sylvan.tools.library.list
    import sylvan.tools.library.remove
    import sylvan.tools.memory.delete_memory
    import sylvan.tools.memory.delete_preference
    import sylvan.tools.memory.get_preferences
    import sylvan.tools.memory.retrieve_memory
    import sylvan.tools.memory.save_memory
    import sylvan.tools.memory.save_preference
    import sylvan.tools.memory.search_memory
    import sylvan.tools.meta.configure_editor
    import sylvan.tools.meta.get_logs
    import sylvan.tools.meta.get_server_config
    import sylvan.tools.meta.get_workflow_guide
    import sylvan.tools.meta.list_repos
    import sylvan.tools.meta.remove_repo
    import sylvan.tools.meta.scaffold
    import sylvan.tools.meta.suggest_queries
    import sylvan.tools.search.search_sections
    import sylvan.tools.search.search_similar
    import sylvan.tools.search.search_symbols
    import sylvan.tools.search.search_text
    import sylvan.tools.workspace
    import sylvan.tools.workspace.pin_library  # noqa: F401


_SERVER_TOOLS: list[tuple[str, str, dict]] = [
    (
        "get_session_stats",
        "Usage statistics at three levels: current session, per-project lifetime, "
        "and overall across all repos. Shows tokens returned vs avoided, tool calls, "
        "symbols/sections retrieved. Optionally filter to a specific repo.",
        {
            "type": "object",
            "properties": {
                "repo": {"type": "string", "description": "Optional: show stats for a specific repo"},
            },
        },
    ),
    (
        "get_dashboard_url",
        "Get the URL for the Sylvan web dashboard. The dashboard provides "
        "a visual overview of indexed repositories, quality reports, library "
        "management, and interactive symbol search.",
        {"type": "object", "properties": {}},
    ),
    (
        "get_peak_status",
        "Check if Claude is currently in peak or off-peak usage hours. "
        "Peak: weekdays 13:00-19:00 UTC. Weekends are always off-peak. "
        "Returns current status, time until next transition, and the peak window.",
        {"type": "object", "properties": {}},
    ),
]


@functools.cache
def _get_handlers() -> dict[str, Callable[..., dict]]:
    """Build the handler dispatch table from the tool registry.

    All Tool subclasses register themselves via __init_subclass__.
    This function imports all tool modules (triggering registration),
    then builds a handler dict that maps tool names to callables.
    """
    _import_all_tool_modules()

    from sylvan.tools.base.tool import get_registry

    registry = get_registry()
    handlers: dict[str, Callable[..., dict]] = {}

    def _make_handler(tool: Any) -> Callable[..., dict]:
        async def handler(**kw: Any) -> dict:
            return await tool.execute(kw)

        return handler

    for name, tool_cls in registry.items():
        handlers[name] = _make_handler(tool_cls())

    async def _get_session_stats(**kwargs: Any) -> dict:
        return await _get_usage_stats(kwargs)

    handlers["get_session_stats"] = _get_session_stats
    handlers["get_dashboard_url"] = _get_dashboard_url
    handlers["get_peak_status"] = _get_peak_status

    from sylvan.extensions import get_registered_tools

    for name, info in get_registered_tools().items():
        if name in handlers:
            logger.warning("extension_tool_conflicts_with_core", tool=name)
            continue
        handlers[name] = info["handler"]

    return handlers


def _tool_category(name: str) -> str:
    """Get the efficiency category for a tool from the registry."""
    from sylvan.tools.base.tool import get_registry

    registry = get_registry()
    tool_cls = registry.get(name)
    if tool_cls:
        return tool_cls.category
    return "meta"


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


async def _get_peak_status(**_kwargs: object) -> dict:
    """Check Claude peak/off-peak usage status.

    Returns:
        Dict with is_peak, current time, and transition info.
    """
    from sylvan.services.peak import get_peak_status

    return get_peak_status()


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
