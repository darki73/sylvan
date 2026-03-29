"""Dashboard WebSocket handler.

Single WebSocket connection per browser tab. Handles both request/response
(client asks for data) and server push (events from the sylvan event bus).
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from starlette.websockets import WebSocket, WebSocketDisconnect

from sylvan.logging import get_logger

logger = get_logger(__name__)

_HANDLERS: dict[str, Any] = {}


def _register(name: str):
    """Register a handler function for a message type.

    Args:
        name: The message type string.
    """

    def decorator(fn):
        _HANDLERS[name] = fn
        return fn

    return decorator


async def handle_dashboard_ws(websocket: WebSocket) -> None:
    """Accept a dashboard WebSocket connection and dispatch messages.

    Runs two concurrent tasks: one reads client requests and dispatches
    them, the other streams events from the sylvan event bus.

    Args:
        websocket: The incoming Starlette WebSocket.
    """
    from sylvan.events import create_queue, remove_queue

    await websocket.accept()
    event_queue = create_queue()

    async def _stream_events():
        while True:
            msg = await event_queue.get()
            try:
                await websocket.send_text(json.dumps(msg, default=str))
            except Exception:
                break

    async def _handle_requests():
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            msg_type = msg.get("type", "")
            msg_id = msg.get("id")
            args = msg.get("args", {})

            handler = _HANDLERS.get(msg_type)
            if handler is None:
                await _send(websocket, msg_id, msg_type, error=f"Unknown type: {msg_type}")
                continue

            try:
                result = await handler(**args)
                await _send(websocket, msg_id, msg_type, data=result)
            except Exception as exc:
                logger.warning("dashboard_ws_error", type=msg_type, error=str(exc))
                await _send(websocket, msg_id, msg_type, error=str(exc))

    stream_task = asyncio.ensure_future(_stream_events())
    try:
        await _handle_requests()
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("dashboard_ws_connection_error", error=str(exc))
    finally:
        stream_task.cancel()
        remove_queue(event_queue)


async def _send(
    websocket: WebSocket,
    msg_id: str | None,
    msg_type: str,
    data: Any = None,
    error: str | None = None,
) -> None:
    """Send a response back to the dashboard client.

    Args:
        websocket: The WebSocket connection.
        msg_id: Correlation ID from the request (None for pushes).
        msg_type: The message type.
        data: Response payload.
        error: Error message if the request failed.
    """
    response: dict[str, Any] = {"type": msg_type}
    if msg_id:
        response["id"] = msg_id
    if error:
        response["error"] = error
    else:
        response["data"] = data
    await websocket.send_text(json.dumps(response, default=str))


@_register("get_overview")
async def _handle_get_overview() -> dict:
    """Return overview dashboard data with cluster status and uptime.

    Returns:
        Dict with repos, libraries, stats, efficiency, cluster, uptime,
        and recent_calls.
    """
    from sylvan.cluster.state import get_cluster_state
    from sylvan.dashboard.app import _get_cluster_sessions, _get_overview_data, _start_time, _uptime
    from sylvan.session.tracker import get_session

    data = await _get_overview_data()

    cluster = get_cluster_state()
    cluster_sessions = await _get_cluster_sessions()
    data["cluster"] = {
        "role": cluster.role,
        "session_id": cluster.session_id,
        "nodes": cluster_sessions,
        "active_count": sum(1 for s in cluster_sessions if s.get("alive")),
    }
    import time

    data["uptime"] = _uptime()
    data["uptime_seconds"] = int(time.monotonic() - _start_time)
    data["recent_calls"] = get_session().get_recent_calls()

    from sylvan.database.orm.models.usage_stats import UsageStats

    usage_rows = await UsageStats.query().order_by("date").get()
    usage_agg: dict[str, int] = {}
    for u in usage_rows:
        usage_agg[u.date] = usage_agg.get(u.date, 0) + u.tool_calls
    data["usage_map"] = usage_agg

    return data


@_register("get_stats")
async def _handle_get_stats() -> dict:
    """Return session stats, cluster state, and cache info.

    Returns:
        Dict with session, cluster, efficiency, and cache data.
    """
    from sylvan.cluster.state import get_cluster_state
    from sylvan.dashboard.app import _get_cluster_sessions
    from sylvan.database.orm.runtime.query_cache import get_query_cache
    from sylvan.session.tracker import get_session

    session = get_session()
    stats = session.get_session_stats()
    efficiency = session.get_efficiency_stats()
    cache = get_query_cache().stats()
    cluster = get_cluster_state()
    cluster_sessions = await _get_cluster_sessions()

    from sylvan.dashboard.app import _get_coding_session_history

    coding_history = await _get_coding_session_history(limit=10)

    return {
        "session": stats,
        "efficiency": efficiency,
        "cache": cache,
        "cluster": {
            "role": cluster.role,
            "session_id": cluster.session_id,
            "coding_session_id": cluster.coding_session_id,
            "nodes": cluster_sessions,
            "active_count": sum(1 for s in cluster_sessions if s.get("alive")),
            "total_tool_calls": sum(s.get("tool_calls", 0) for s in cluster_sessions if s.get("alive")),
        },
        "coding_history": coding_history,
    }


@_register("get_quality")
async def _handle_get_quality(repo: str = "") -> dict:
    """Return quality report for a repository.

    Args:
        repo: Repository name.

    Returns:
        Quality data dict.
    """
    from sylvan.dashboard.app import _get_quality_data

    return await _get_quality_data(repo)


@_register("search_symbols")
async def _handle_search_symbols(query: str = "", repo: str | None = None) -> dict:
    """Search for symbols across indexed repositories.

    Args:
        query: Search query string.
        repo: Optional repository filter.

    Returns:
        Dict with search results.
    """
    from sylvan.dashboard.app import _search_symbols

    results = await _search_symbols(query, repo)
    return {"results": results, "query": query}


@_register("get_repositories")
async def _handle_get_repositories() -> dict:
    """Return all indexed repositories with stats.

    Returns:
        Dict with list of repository data.
    """
    from sylvan.services.repository import RepositoryService

    repos = await RepositoryService().exclude_libraries().with_stats().with_languages().get()
    return {
        "repos": [
            {
                "id": r.id,
                "name": r.name,
                "source_path": r.source_path or "",
                "files": r.stats["files"],
                "symbols": r.stats["symbols"],
                "sections": r.stats["sections"],
                "indexed_at": r.indexed_at or "",
                "git_head": (r.git_head or "")[:8],
                "github_url": r.github_url or "",
                "languages": r.languages,
            }
            for r in repos
        ]
    }


@_register("get_repository")
async def _handle_get_repository(name: str = "") -> dict:
    """Return a single repository with full details.

    Args:
        name: Repository name.

    Returns:
        Dict with repo info, stats, languages, symbol breakdown,
        file tree, and usage history.
    """
    import time

    t0 = time.monotonic()

    from sylvan.database.orm import FileRecord, Symbol
    from sylvan.database.orm.models.usage_stats import UsageStats
    from sylvan.services.repository import RepositoryService

    repo = await RepositoryService().with_stats().with_languages().find(name)
    if repo is None:
        return {"error": "repo_not_found", "name": name}

    # Symbol kind breakdown
    kind_rows = await (
        Symbol.query()
        .select("symbols.kind", "COUNT(*) as count")
        .join("files", "files.id = symbols.file_id")
        .where("files.repo_id", repo.id)
        .group_by("symbols.kind")
        .get()
    )
    kind_breakdown = {getattr(r, "kind", ""): getattr(r, "count", 0) for r in kind_rows if getattr(r, "kind", None)}

    # File tree (top-level dirs with counts)
    all_files = await FileRecord.where(repo_id=repo.id).select("path", "language", "byte_size").order_by("path").get()
    file_tree = _build_dir_tree(all_files)

    # Usage history (all time, keyed by date)
    usage_rows = await UsageStats.where(repo_id=repo.id).order_by("date").get()
    usage_map = {u.date: u.tool_calls for u in usage_rows}

    elapsed = round((time.monotonic() - t0) * 1000, 1)

    return {
        "id": repo.id,
        "name": repo.name,
        "source_path": repo.source_path or "",
        "files": repo.stats["files"],
        "symbols": repo.stats["symbols"],
        "sections": repo.stats["sections"],
        "indexed_at": repo.indexed_at or "",
        "git_head": (repo.git_head or "")[:8],
        "github_url": repo.github_url or "",
        "languages": repo.languages,
        "repo_type": repo.repo_type or "project",
        "kind_breakdown": kind_breakdown,
        "file_tree": file_tree,
        "usage_map": usage_map,
        "load_ms": elapsed,
    }


def _build_dir_tree(files: list) -> list[dict]:
    """Build a collapsible directory tree from file records.

    Args:
        files: List of FileRecord model instances.

    Returns:
        Nested list of dicts with name, type, children, language, size.
    """
    root: dict = {}
    for f in files:
        parts = f.path.split("/")
        node = root
        for part in parts[:-1]:
            if part not in node:
                node[part] = {}
            node = node[part]
        node[parts[-1]] = {"_file": True, "language": f.language or "", "size": f.byte_size or 0}

    def _to_list(tree: dict, depth: int = 0) -> list[dict]:
        dirs = []
        file_list = []
        for name, value in sorted(tree.items()):
            if isinstance(value, dict) and "_file" in value:
                file_list.append(
                    {
                        "name": name,
                        "type": "file",
                        "language": value["language"],
                        "size": value["size"],
                    }
                )
            elif isinstance(value, dict):
                children = _to_list(value, depth + 1)
                file_count = sum(1 for c in children if c["type"] == "file") + sum(
                    c.get("file_count", 0) for c in children if c["type"] == "dir"
                )
                dirs.append(
                    {
                        "name": name,
                        "type": "dir",
                        "file_count": file_count,
                        "children": children,
                    }
                )
        return dirs + file_list

    return _to_list(root)


@_register("reindex_repo")
async def _handle_reindex_repo(name: str = "", path: str = "", force: bool = False) -> dict:
    """Submit a re-index job to the queue.

    Returns immediately. Progress is streamed via the event bus.

    Args:
        name: Repository name.
        path: Source path to index.
        force: If True, re-extract all files even if unchanged.

    Returns:
        Dict with job_id confirming the job was queued.
    """
    if not path:
        from sylvan.database.orm import Repo

        repo = await Repo.where(name=name).first()
        if repo is None:
            return {"error": "repo_not_found", "name": name}
        path = repo.source_path or ""
    if not path:
        return {"error": "no_source_path", "name": name}

    from sylvan.queue import submit

    await submit("index_folder", key=f"index:{name}", path=path, name=name, force=force)
    return {"queued": True, "name": name, "force": force}


@_register("delete_repo")
async def _handle_delete_repo(name: str = "") -> dict:
    """Delete a repository and all its data.

    Args:
        name: Repository name.

    Returns:
        Dict with status.
    """
    from sylvan.services.repository import RepositoryService

    result = await RepositoryService().remove(name)
    return {"ok": True, **result}


@_register("get_file_outline")
async def _handle_get_file_outline(repo: str = "", file_path: str = "") -> dict:
    """Return the symbol outline for a file.

    Args:
        repo: Repository name.
        file_path: Relative file path.

    Returns:
        Dict with symbols list.
    """
    from sylvan.services.symbol import SymbolService

    result = await SymbolService().file_outline(repo, file_path)
    return result


@_register("get_symbol_source")
async def _handle_get_symbol_source(symbol_id: str = "") -> dict:
    """Return the source code of a symbol.

    Args:
        symbol_id: Symbol identifier.

    Returns:
        Dict with source, file, line_start, line_end.
    """
    from sylvan.services.symbol import SymbolService

    result = await SymbolService().with_source().find(symbol_id)
    if result is None:
        return {"error": "symbol_not_found", "symbol_id": symbol_id}
    return {
        "source": result.source or "",
        "file": result.file_record.path if result.file_record else "",
        "line_start": result.line_start,
        "line_end": result.line_end,
    }


@_register("get_libraries")
async def _handle_get_libraries() -> dict:
    """Return all indexed libraries with stats and languages.

    Returns:
        Dict with list of library data.
    """
    from sylvan.database.orm import Repo
    from sylvan.services.repository import load_languages, load_stats

    libraries = await Repo.where(repo_type="library").order_by("name").get()
    lib_data = []
    for lib in libraries:
        stats = await load_stats(lib.id)
        languages = await load_languages(lib.id)
        lib_data.append(
            {
                "id": lib.id,
                "name": lib.name,
                "package": lib.package_name or lib.name.split("@")[0],
                "manager": lib.package_manager or "",
                "version": lib.version or "",
                "repo_url": lib.github_url or "",
                "indexed_at": lib.indexed_at or "",
                "languages": languages,
                **stats,
            }
        )
    return {"libraries": lib_data}


@_register("add_library")
async def _handle_add_library(package: str = "") -> dict:
    """Index a third-party library from a package manager.

    Args:
        package: Package spec (e.g. pip/django@4.2, npm/react@18).

    Returns:
        Dict with indexing results.
    """
    from sylvan.services.library import add_library

    return await add_library(package)


@_register("get_library")
async def _handle_get_library(package: str = "") -> dict:
    """Return all versions of a library package with stats.

    Args:
        package: Package name (e.g. "django", "laravel/framework").

    Returns:
        Dict with package info and list of versions with stats.
    """
    from sylvan.database.orm import Repo
    from sylvan.services.repository import load_stats

    repos = await (
        Repo.where(repo_type="library")
        .where_group(lambda q: q.where(package_name=package).or_where(name=package))
        .order_by("name")
        .get()
    )
    if not repos:
        return {"error": "library_not_found", "package": package}

    versions = []
    for repo in repos:
        stats = await load_stats(repo.id)
        versions.append(
            {
                "name": repo.name,
                "version": repo.version or "",
                "manager": repo.package_manager or "",
                "repo_url": repo.github_url or "",
                "source_path": repo.source_path or "",
                "indexed_at": repo.indexed_at or "",
                **stats,
            }
        )

    first = repos[0]
    return {
        "package": first.package_name or package,
        "manager": first.package_manager or "",
        "repo_url": first.github_url or "",
        "versions": versions,
    }


@_register("delete_library")
async def _handle_delete_library(name: str = "") -> dict:
    """Delete a library version.

    Args:
        name: Library repo name (e.g. "django@4.2").

    Returns:
        Dict with status.
    """
    from sylvan.services.repository import RepositoryService

    result = await RepositoryService().remove(name)
    return {"ok": True, **result}


@_register("get_history")
async def _handle_get_history(page: int = 1, per_page: int = 20) -> dict:
    """Return paginated coding session history.

    Args:
        page: Page number (1-based).
        per_page: Items per page.

    Returns:
        Dict with paginated session history.
    """
    from datetime import UTC, datetime

    from sylvan.dashboard.app import _format_duration
    from sylvan.database.orm import CodingSession

    result = await CodingSession.query().order_by("started_at", "DESC").paginate(page, per_page)

    history = []
    for cs in result["data"]:
        started = cs.started_at or ""
        ended = cs.ended_at
        duration = ""
        if started:
            try:
                start_dt = datetime.fromisoformat(started)
                if ended:
                    end_dt = datetime.fromisoformat(ended)
                    secs = (end_dt - start_dt).total_seconds()
                else:
                    secs = (datetime.now(UTC) - start_dt).total_seconds()
                duration = _format_duration(secs)
            except (ValueError, TypeError):
                duration = "--"

        eq = cs.total_efficiency_equivalent or 0
        ret = cs.total_efficiency_returned or 0

        history.append(
            {
                "id": cs.id or "",
                "started_at": started,
                "ended_at": ended,
                "duration": duration,
                "total_tool_calls": cs.total_tool_calls or 0,
                "instances_spawned": cs.instances_spawned or 0,
                "reduction_percent": round((1 - ret / eq) * 100, 1) if eq > 0 else 0,
            }
        )

    return {
        "coding_history": history,
        "total": result["total"],
        "page": result["page"],
        "per_page": result["per_page"],
        "total_pages": result["pages"],
    }


@_register("get_workspaces")
async def _handle_get_workspaces() -> dict:
    """Return all workspaces with repos and per-repo stats.

    Returns:
        Dict with list of workspace data.
    """
    from sylvan.services.workspace import WorkspaceService

    workspaces = await WorkspaceService().with_repos().with_stats().get()
    return {
        "workspaces": [
            {
                "id": ws.id,
                "name": ws.name,
                "description": ws.description or "",
                "created_at": ws.created_at or "",
                "repo_count": len(ws.repos_data or []),
                **(ws.stats or {}),
                "repos": ws.repos_data or [],
            }
            for ws in workspaces
        ]
    }


@_register("get_workspace")
async def _handle_get_workspace(name: str = "") -> dict:
    """Return a single workspace with repos, stats, and available repos.

    Args:
        name: Workspace name.

    Returns:
        Workspace data with available_repos list for adding new ones.
    """
    from sylvan.services.workspace import WorkspaceService

    ws = await WorkspaceService().with_repos().with_stats().with_available_repos().find(name)
    if ws is None:
        return {"error": "workspace_not_found", "name": name}
    return {
        "id": ws.id,
        "name": ws.name,
        "description": ws.description or "",
        "created_at": ws.created_at or "",
        "repo_count": len(ws.repos_data or []),
        **(ws.stats or {}),
        "repos": ws.repos_data or [],
        "available_repos": ws.available_repos or [],
    }


@_register("update_workspace")
async def _handle_update_workspace(name: str = "", new_name: str = "", description: str | None = None) -> dict:
    """Update workspace name or description.

    Args:
        name: Current workspace name.
        new_name: New name (empty to keep current).
        description: New description (None to keep current).

    Returns:
        Dict with ok status and updated name.
    """
    from sylvan.services.workspace import WorkspaceService

    ws = await WorkspaceService().update(name, new_name=new_name or None, description=description)
    if ws is None:
        return {"error": "workspace_not_found", "name": name}
    return {"ok": True, "name": ws.name}


@_register("workspace_add_repo")
async def _handle_workspace_add_repo(name: str = "", repo_id: int = 0) -> dict:
    """Add a repo to a workspace by ID.

    Args:
        name: Workspace name.
        repo_id: ID of the repo to add.

    Returns:
        Dict with ok status.
    """
    from sylvan.services.workspace import WorkspaceService

    if not await WorkspaceService().add_repo_by_id(name, repo_id):
        return {"error": "workspace_not_found", "name": name}
    return {"ok": True}


@_register("workspace_remove_repo")
async def _handle_workspace_remove_repo(name: str = "", repo_id: int = 0) -> dict:
    """Remove a repo from a workspace by ID.

    Args:
        name: Workspace name.
        repo_id: ID of the repo to remove.

    Returns:
        Dict with ok status.
    """
    from sylvan.services.workspace import WorkspaceService

    if not await WorkspaceService().remove_repo_by_id(name, repo_id):
        return {"error": "workspace_not_found", "name": name}
    return {"ok": True}


@_register("delete_workspace")
async def _handle_delete_workspace(name: str = "") -> dict:
    """Delete a workspace and detach all repos.

    Args:
        name: Workspace name.

    Returns:
        Dict with ok status.
    """
    from sylvan.services.workspace import WorkspaceService

    if not await WorkspaceService().delete(name):
        return {"error": "workspace_not_found", "name": name}
    return {"ok": True}
