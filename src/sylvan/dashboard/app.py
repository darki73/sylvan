"""Dashboard Starlette application - routes and data helpers."""

import time
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse
from starlette.routing import Mount, Route, WebSocketRoute

from sylvan.logging import get_logger

logger = get_logger(__name__)

_start_time = time.monotonic()


def _uptime() -> str:
    """Calculate server uptime as a human-readable string.

    Returns:
        Formatted uptime string like '2h 34m' or '5d 12h'.
    """
    elapsed = int(time.monotonic() - _start_time)
    days, remainder = divmod(elapsed, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)
    if days > 0:
        return f"{days}d {hours}h"
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _format_duration(seconds: float) -> str:
    """Format seconds into a human-readable duration string."""
    s = int(seconds)
    if s >= 3600:
        return f"{s // 3600}h {(s % 3600) // 60}m"
    if s >= 60:
        return f"{s // 60}m {s % 60}s"
    return f"{s}s"


async def _get_cluster_sessions() -> list[dict]:
    """Get all cluster nodes and their stats from the DB.

    Returns:
        List of node info dicts for rendering in the template.
    """
    from sylvan.cluster.discovery import _is_pid_alive
    from sylvan.database.orm import ClusterNode, Instance

    nodes = await ClusterNode.query().order_by("role").order_by("last_seen", "DESC").get()
    sessions = []

    for node in nodes:
        pid = node.pid or 0
        alive = _is_pid_alive(pid)

        # Get the latest instance stats for this node
        inst = await Instance.where(node_id=node.node_id).where_null("ended_at").first()
        eq = (inst.efficiency_equivalent or 0) if inst else 0
        ret = (inst.efficiency_returned or 0) if inst else 0

        sessions.append(
            {
                "session_id": node.node_id or "",
                "coding_session_id": node.coding_session_id or "",
                "pid": pid,
                "role": node.role or "unknown",
                "alive": alive,
                "tool_calls": (inst.tool_calls or 0) if inst else 0,
                "tokens_returned": (inst.tokens_returned or 0) if inst else 0,
                "tokens_avoided": (inst.tokens_avoided or 0) if inst else 0,
                "efficiency_returned": ret,
                "efficiency_equivalent": eq,
                "reduction_percent": round((1 - ret / eq) * 100, 1) if eq > 0 else 0,
                "symbols_retrieved": (inst.symbols_retrieved or 0) if inst else 0,
                "queries": (inst.queries or 0) if inst else 0,
                "category_data": (inst.category_data or {}) if inst else {},
                "last_heartbeat": node.last_seen or "",
            }
        )
    return sessions


def _combine_session_efficiency(sessions: list[dict]) -> dict | None:
    """Aggregate efficiency across all instances, including ended ones.

    Args:
        sessions: List of instance dicts from _get_cluster_sessions.

    Returns:
        Combined efficiency dict, or None if no data.
    """
    total_ret = sum(s.get("efficiency_returned", 0) for s in sessions)
    total_eq = sum(s.get("efficiency_equivalent", 0) for s in sessions)
    if total_eq == 0:
        return None

    combined_cats: dict = {}
    for s in sessions:
        for cat_name, cat_data in (s.get("category_data") or {}).items():
            if cat_name not in combined_cats:
                combined_cats[cat_name] = {"calls": 0, "returned": 0, "equivalent": 0}
            combined_cats[cat_name]["calls"] += cat_data.get("calls", 0)
            combined_cats[cat_name]["returned"] += cat_data.get("returned", 0)
            combined_cats[cat_name]["equivalent"] += cat_data.get("equivalent", 0)

    return {
        "total_returned": total_ret,
        "total_equivalent": total_eq,
        "reduction_percent": round((1 - total_ret / total_eq) * 100, 1) if total_eq > 0 else 0,
        "by_category": combined_cats,
    }


async def _get_current_coding_session_totals(coding_session_id: str) -> dict:
    """Get the aggregated totals from the coding_sessions row.

    These include stats from dead instances that were already merged.

    Args:
        coding_session_id: The current coding session ID.

    Returns:
        Dict with total_tool_calls, total_efficiency_returned, etc.
    """
    if not coding_session_id:
        return {}

    from sylvan.database.orm import CodingSession

    session = await CodingSession.where(id=coding_session_id).first()
    if not session:
        return {}
    return {
        "tool_calls": session.total_tool_calls or 0,
        "efficiency_returned": session.total_efficiency_returned or 0,
        "efficiency_equivalent": session.total_efficiency_equivalent or 0,
    }


async def _get_coding_session_history(limit: int = 10) -> list[dict]:
    """Get recent coding sessions with aggregated stats.

    Args:
        limit: Maximum number of sessions to return.

    Returns:
        List of coding session dicts with duration and efficiency.
    """
    from datetime import datetime

    from sylvan.database.orm import CodingSession

    sessions = await CodingSession.query().order_by("started_at", "DESC").limit(limit).get()

    history = []
    for cs in sessions:
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
                    from datetime import UTC

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
    return history


async def _get_overview_data() -> dict:
    """Gather data for the overview dashboard page.

    Returns:
        Dict with repos, libraries, symbol counts, and uptime.
    """
    from sylvan.database.orm import CodingSession, FileRecord, Instance, Repo, Section, Sum, Symbol

    repos = await Repo.where_not(repo_type="library").get()
    libraries = await Repo.where(repo_type="library").order_by("name").get()

    repo_data = []
    for repo in repos:
        file_count = await FileRecord.where(repo_id=repo.id).count()
        symbol_count = (
            await Symbol.query().join("files", "files.id = symbols.file_id").where("files.repo_id", repo.id).count()
        )
        section_count = (
            await Section.query().join("files", "files.id = sections.file_id").where("files.repo_id", repo.id).count()
        )
        repo_data.append(
            {
                "name": repo.name,
                "files": file_count,
                "symbols": symbol_count,
                "sections": section_count,
                "indexed_at": repo.indexed_at or "",
                "git_head": (repo.git_head or "")[:8],
            }
        )

    lib_data = []
    for lib in libraries:
        symbol_count = (
            await Symbol.query().join("files", "files.id = symbols.file_id").where("files.repo_id", lib.id).count()
        )
        lib_data.append(
            {
                "name": lib.name,
                "package": lib.package_name or lib.name.split("@")[0],
                "manager": lib.package_manager or "",
                "version": lib.version or "",
                "symbols": symbol_count,
                "repo_url": lib.github_url or "",
            }
        )

    total_symbols = await Symbol.all().count()
    total_files = await FileRecord.all().count()
    total_sections = await Section.all().count()

    from sylvan.session.tracker import get_session

    session = get_session()
    efficiency = session.get_efficiency_stats()

    for rd in repo_data:
        repo_obj = next((r for r in repos if r.name == rd["name"]), None)
        if repo_obj:
            lang_counts = await (
                FileRecord.where(repo_id=repo_obj.id)
                .where_not_null("language")
                .where_not(language="")
                .group_by("language")
                .count()
            )
            if lang_counts:
                rd["languages"] = dict(sorted(lang_counts.items(), key=lambda x: x[1], reverse=True))

    cs = await CodingSession.all().aggregates(
        eff_ret=Sum("total_efficiency_returned"),
        eff_eq=Sum("total_efficiency_equivalent"),
        calls=Sum("total_tool_calls"),
    )
    inst = await Instance.all().aggregates(
        eff_ret=Sum("efficiency_returned"),
        eff_eq=Sum("efficiency_equivalent"),
        calls=Sum("tool_calls"),
    )

    alltime_eff_returned = cs["eff_ret"] + inst["eff_ret"]
    alltime_eff_equivalent = cs["eff_eq"] + inst["eff_eq"]
    alltime_calls = cs["calls"] + inst["calls"]

    alltime_efficiency = {
        "total_returned": alltime_eff_returned,
        "total_equivalent": alltime_eff_equivalent,
        "reduction_percent": round((1 - alltime_eff_returned / alltime_eff_equivalent) * 100, 1)
        if alltime_eff_equivalent > 0
        else 0,
        "total_calls": alltime_calls,
    }

    return {
        "repos": repo_data,
        "libraries": lib_data,
        "total_symbols": total_symbols,
        "total_files": total_files,
        "total_sections": total_sections,
        "total_repos": len(repo_data),
        "total_libraries": len(lib_data),
        "efficiency": efficiency,
        "alltime_efficiency": alltime_efficiency,
        "tool_calls": session._tool_calls,
    }


async def _get_quality_data(repo_name: str) -> dict:
    """Gather quality report data for a specific repository.

    Args:
        repo_name: Name of the repository to analyze.

    Returns:
        Dict with coverage, smells, security findings, and duplication data.
    """
    from sylvan.database.orm import Quality, Repo

    repo = await Repo.where(name=repo_name).first()
    if repo is None:
        return {"error": f"Repository '{repo_name}' not found"}

    repo_id = repo.id

    from sylvan.analysis.quality.code_smells import detect_code_smells
    from sylvan.analysis.quality.duplication import detect_duplicates
    from sylvan.analysis.quality.quality_metrics import compute_quality_metrics
    from sylvan.analysis.quality.security_scanner import scan_security
    from sylvan.analysis.quality.test_coverage import analyze_test_coverage

    await compute_quality_metrics(repo_id)
    coverage = await analyze_test_coverage(repo_id)
    smells = await detect_code_smells(repo_id)
    security = await scan_security(repo_id)
    duplicates = await detect_duplicates(repo_id)

    _repo_join = (
        Quality.query()
        .join("symbols", "symbols.symbol_id = quality.symbol_id")
        .join("files", "files.id = symbols.file_id")
        .where("files.repo_id", repo_id)
    )

    total = await _repo_join.count()
    documented = (
        await Quality.query()
        .join("symbols", "symbols.symbol_id = quality.symbol_id")
        .join("files", "files.id = symbols.file_id")
        .where("files.repo_id", repo_id)
        .where(has_docs=True)
        .count()
    )
    typed = (
        await Quality.query()
        .join("symbols", "symbols.symbol_id = quality.symbol_id")
        .join("files", "files.id = symbols.file_id")
        .where("files.repo_id", repo_id)
        .where(has_types=True)
        .count()
    )

    total = total or 0
    doc_pct = round((documented or 0) / total * 100, 1) if total > 0 else 0.0
    type_pct = round((typed or 0) / total * 100, 1) if total > 0 else 0.0

    return {
        "repo": repo_name,
        "test_coverage": coverage["coverage_percent"],
        "uncovered_count": len(coverage["uncovered"]),
        "uncovered_symbols": coverage["uncovered"][:30],
        "doc_coverage": doc_pct,
        "type_coverage": type_pct,
        "smells": [
            {
                "name": s.name,
                "file": s.file,
                "line": s.line,
                "type": s.smell_type,
                "severity": s.severity,
                "message": s.message,
            }
            for s in smells[:50]
        ],
        "smells_by_severity": {
            "high": len([s for s in smells if s.severity == "high"]),
            "medium": len([s for s in smells if s.severity == "medium"]),
            "low": len([s for s in smells if s.severity == "low"]),
        },
        "security": [
            {
                "file": f.file,
                "line": f.line,
                "rule": f.rule,
                "severity": f.severity,
                "message": f.message,
                "snippet": f.snippet,
            }
            for f in security[:30]
        ],
        "security_by_severity": {
            "critical": len([f for f in security if f.severity == "critical"]),
            "high": len([f for f in security if f.severity == "high"]),
            "medium": len([f for f in security if f.severity == "medium"]),
            "low": len([f for f in security if f.severity == "low"]),
        },
        "duplicates": [
            {
                "hash": g.hash,
                "line_count": g.line_count,
                "instances": [{"name": s["name"], "file": s["file"], "line": s["line_start"]} for s in g.symbols],
            }
            for g in duplicates[:10]
        ],
    }


async def _search_symbols(query: str, repo_name: str | None = None) -> list[dict]:
    """Search symbols for the dashboard search page.

    Args:
        query: Search query string.
        repo_name: Optional repository filter.

    Returns:
        List of matching symbol dicts.
    """
    from sylvan.database.orm import Symbol

    if not query or len(query) < 2:
        return []

    qb = Symbol.search(query).with_("file")
    if repo_name:
        qb = qb.in_repo(repo_name)
    qb = qb.limit(30)

    results = await qb.get()

    # Build repo cache to avoid N+1 on repo lookups
    from sylvan.database.orm import Repo

    repo_ids = {sym.file.repo_id for sym in results if sym.file}
    repo_map: dict[int, str] = {}
    for rid in repo_ids:
        repo_obj = await Repo.find(rid)
        if repo_obj:
            repo_map[rid] = repo_obj.name

    symbols = []
    for sym in results:
        file_rec = sym.file
        symbols.append(
            {
                "symbol_id": sym.symbol_id,
                "name": sym.name,
                "qualified_name": sym.qualified_name,
                "kind": sym.kind,
                "language": sym.language,
                "file": file_rec.path if file_rec else "",
                "signature": sym.signature or "",
                "line": sym.line_start,
                "repo": repo_map.get(file_rec.repo_id, "") if file_rec else "",
            }
        )
    return symbols


async def _context_middleware(request: Request, call_next):
    """Set a per-request identity map for each dashboard request.

    Args:
        request: The incoming HTTP request.
        call_next: The next middleware or route handler.

    Returns:
        The HTTP response.
    """
    from sylvan.context import reset_identity_map, set_identity_map
    from sylvan.database.orm.runtime.identity_map import IdentityMap

    token = set_identity_map(IdentityMap())
    try:
        response = await call_next(request)
    finally:
        reset_identity_map(token)
    return response


def _spa_catchall(request: Request) -> HTMLResponse:
    """Serve the Vue SPA index.html for client-side routing.

    Args:
        request: The incoming HTTP request.

    Returns:
        The SPA index.html file content.
    """
    spa_index = Path(__file__).parent / "static" / "dist" / "index.html"
    if spa_index.exists():
        return HTMLResponse(spa_index.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Dashboard not built</h1><p>Run pnpm build in frontend/</p>", status_code=503)


def create_dashboard_app() -> Starlette:
    """Create and return the Starlette dashboard application.

    Returns:
        Configured Starlette app with all dashboard routes.
    """
    from starlette.middleware import Middleware
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.staticfiles import StaticFiles

    from sylvan.cluster.websocket import handle_follower_connection
    from sylvan.dashboard.ws import handle_dashboard_ws

    spa_dist = Path(__file__).parent / "static" / "dist"

    routes = [
        WebSocketRoute("/ws/dashboard", handle_dashboard_ws),
        WebSocketRoute("/ws/cluster", handle_follower_connection),
    ]

    if spa_dist.exists():
        routes.append(Mount("/assets", app=StaticFiles(directory=str(spa_dist / "assets"))))

    # SPA catch-all must be last
    routes.append(Route("/{path:path}", _spa_catchall))

    middleware = [
        Middleware(BaseHTTPMiddleware, dispatch=_context_middleware),
    ]
    app = Starlette(routes=routes, middleware=middleware)
    from starlette.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_methods=["GET", "POST", "DELETE"],
    )
    return app
