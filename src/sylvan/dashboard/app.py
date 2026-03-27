"""Dashboard Starlette application — routes, templates, and data endpoints."""

import time
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route, WebSocketRoute

from sylvan.logging import get_logger

logger = get_logger(__name__)

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_jinja = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True)
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


_jinja.globals["uptime"] = _uptime
_jinja.globals["format_duration"] = _format_duration


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
    """Aggregate efficiency across all active instances.

    Args:
        sessions: List of instance dicts from _get_cluster_sessions.

    Returns:
        Combined efficiency dict, or None if no data.
    """
    total_ret = sum(s.get("efficiency_returned", 0) for s in sessions if s.get("alive"))
    total_eq = sum(s.get("efficiency_equivalent", 0) for s in sessions if s.get("alive"))
    if total_eq == 0:
        return None

    combined_cats: dict = {}
    for s in sessions:
        if not s.get("alive"):
            continue
        for cat_name, cat_data in s.get("category_data", {}).items():
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


async def overview(request: Request) -> HTMLResponse:
    """Render the overview dashboard page.

    Args:
        request: The incoming HTTP request.

    Returns:
        Rendered HTML response.
    """
    data = await _get_overview_data()
    template = _jinja.get_template("overview.html")
    return HTMLResponse(template.render(**data))


async def overview_partial(request: Request) -> HTMLResponse:
    """Return just the stats section for htmx refresh.

    Args:
        request: The incoming HTTP request.

    Returns:
        Rendered HTML partial.
    """
    data = await _get_overview_data()
    template = _jinja.get_template("partials/stats.html")
    return HTMLResponse(template.render(**data))


async def quality(request: Request) -> HTMLResponse:
    """Render the quality report page.

    Args:
        request: The incoming HTTP request.

    Returns:
        Rendered HTML response.
    """
    repo_name = request.query_params.get("repo", "")
    from sylvan.database.orm import Repo

    repos = await Repo.where_not(repo_type="library").get()
    repo_names = [r.name for r in repos]

    data = {}
    if repo_name:
        data = await _get_quality_data(repo_name)

    template = _jinja.get_template("quality.html")
    return HTMLResponse(template.render(repos=repo_names, selected_repo=repo_name, **data))


async def quality_partial(request: Request) -> HTMLResponse:
    """Return quality report content for htmx swap.

    Args:
        request: The incoming HTTP request.

    Returns:
        Rendered HTML partial.
    """
    repo_name = request.query_params.get("repo", "")
    if not repo_name:
        return HTMLResponse("<p class='text-muted font-mono text-sm'>Select a repository above.</p>")
    try:
        data = await _get_quality_data(repo_name)
        if "error" in data:
            return HTMLResponse(
                f"<p class='text-muted font-mono text-sm' style='color:var(--danger)'>{data['error']}</p>"
            )
        template = _jinja.get_template("partials/quality_report.html")
        return HTMLResponse(template.render(**data))
    except Exception as error:
        return HTMLResponse(f"<p class='font-mono text-sm' style='color:var(--danger)'>Error: {error}</p>")


async def libraries(request: Request) -> HTMLResponse:
    """Render the libraries management page.

    Args:
        request: The incoming HTTP request.

    Returns:
        Rendered HTML response.
    """
    data = await _get_overview_data()
    template = _jinja.get_template("libraries.html")
    return HTMLResponse(template.render(**data))


async def workspaces_page(request: Request) -> HTMLResponse:
    """Render the workspaces page."""
    from sylvan.database.orm import FileRecord, Symbol, Workspace

    ws_list = await Workspace.all().get()
    workspaces = []

    for ws in ws_list:
        await ws.load("repos")
        repos_data = []
        total_files = 0
        total_symbols = 0

        for repo in ws.repos or []:
            files = await FileRecord.where(repo_id=repo.id).count()
            symbols = await (
                Symbol.query().join("files", "files.id = symbols.file_id").where("files.repo_id", repo.id).count()
            )
            repos_data.append({"name": repo.name, "files": files, "symbols": symbols})
            total_files += files
            total_symbols += symbols

        workspaces.append(
            {
                "name": ws.name,
                "description": ws.description or "",
                "created_at": ws.created_at or "",
                "repo_count": len(repos_data),
                "repos": repos_data,
                "total_files": total_files,
                "total_symbols": total_symbols,
            }
        )

    template = _jinja.get_template("workspaces.html")
    return HTMLResponse(template.render(workspaces=workspaces))


async def extensions_page(request: Request) -> HTMLResponse:
    """Render the extensions page."""
    from pathlib import Path

    from sylvan.config import get_config
    from sylvan.extensions import get_registered_tools

    config = get_config()
    enabled = config.extensions.enabled
    extensions_path = str(Path.home() / ".sylvan" / "extensions")

    tools = [{"name": info["name"], "description": info["description"]} for info in get_registered_tools().values()]

    # Collect registered extension languages/parsers/providers
    languages = []
    parsers = []
    providers = []

    template = _jinja.get_template("extensions.html")
    return HTMLResponse(
        template.render(
            enabled=enabled,
            extensions_path=extensions_path,
            loaded_count=len(tools) + len(languages) + len(parsers) + len(providers),
            tools=tools,
            languages=languages,
            parsers=parsers,
            providers=providers,
        )
    )


async def history_page(request: Request) -> HTMLResponse:
    """Render the session history page."""
    from sylvan.database.orm.models.coding_session import CodingSession

    # Coding sessions (most recent first)
    cs_list = await CodingSession.all().order_by("started_at", "DESC").limit(50).get()
    sessions = []
    for cs in cs_list:
        duration_str = ""
        if cs.started_at and cs.ended_at:
            try:
                from datetime import datetime

                start = datetime.fromisoformat(cs.started_at)
                end = datetime.fromisoformat(cs.ended_at)
                delta = end - start
                minutes = int(delta.total_seconds() // 60)
                if minutes >= 60:
                    duration_str = f"{minutes // 60}h {minutes % 60}m"
                else:
                    duration_str = f"{minutes}m"
            except Exception:
                duration_str = "?"
        elif cs.started_at and not cs.ended_at:
            duration_str = "active"

        eq = cs.total_efficiency_equivalent or 0
        ret = cs.total_efficiency_returned or 0
        reduction = round((1 - ret / eq) * 100, 1) if eq > 0 else 0

        sessions.append(
            {
                "id": cs.id,
                "started_at": cs.started_at or "",
                "duration": duration_str,
                "instances_spawned": cs.instances_spawned or 0,
                "total_tool_calls": cs.total_tool_calls or 0,
                "total_tokens_avoided": cs.total_tokens_avoided or 0,
                "reduction_pct": reduction,
            }
        )

    # Daily usage stats
    daily_stats = []
    try:
        from sylvan.database.orm.runtime.connection_manager import get_backend

        backend = get_backend()
        rows = await backend.fetch_all(
            "SELECT us.date, r.name as repo, us.sessions, us.tool_calls, "
            "us.symbols_retrieved, us.sections_retrieved, us.tokens_avoided "
            "FROM usage_stats us JOIN repos r ON r.id = us.repo_id "
            "ORDER BY us.date DESC, us.tool_calls DESC LIMIT 100"
        )
        for row in rows:
            daily_stats.append(
                {
                    "date": row["date"],
                    "repo": row["repo"],
                    "sessions": row["sessions"] or 0,
                    "tool_calls": row["tool_calls"] or 0,
                    "symbols_retrieved": row["symbols_retrieved"] or 0,
                    "sections_retrieved": row["sections_retrieved"] or 0,
                    "tokens_avoided": row["tokens_avoided"] or 0,
                }
            )
    except Exception:  # noqa: S110 -- usage_stats table may not exist yet
        pass

    # Totals
    totals = None
    if sessions:
        totals = {
            "tool_calls": sum(s["total_tool_calls"] for s in sessions),
            "tokens_avoided": sum(s["total_tokens_avoided"] for s in sessions),
            "symbols": sum((cs_list[i].total_symbols_retrieved or 0) for i in range(len(cs_list))),
            "sessions": len(sessions),
        }

    template = _jinja.get_template("history.html")
    return HTMLResponse(
        template.render(
            sessions=sessions,
            daily_stats=daily_stats,
            totals=totals,
        )
    )


async def search(request: Request) -> HTMLResponse:
    """Render the search page.

    Args:
        request: The incoming HTTP request.

    Returns:
        Rendered HTML response.
    """
    from sylvan.database.orm import Repo

    repos = await Repo.where_not(repo_type="library").get()
    repo_names = [r.name for r in repos]
    template = _jinja.get_template("search.html")
    return HTMLResponse(template.render(repos=repo_names))


async def search_results(request: Request) -> HTMLResponse:
    """Return search results for htmx swap.

    Args:
        request: The incoming HTTP request.

    Returns:
        Rendered HTML partial with search results.
    """
    query = request.query_params.get("q", "")
    repo = request.query_params.get("repo", "") or None
    kind = request.query_params.get("kind", "") or None
    results = await _search_symbols(query, repo)
    if kind:
        results = [r for r in results if r.get("kind") == kind]
    template = _jinja.get_template("partials/search_results.html")
    return HTMLResponse(template.render(results=results, query=query))


async def session_page(request: Request) -> HTMLResponse:
    """Render the session stats page.

    Shows the current instance's session stats plus any registered
    follower sessions from the cluster.

    Args:
        request: The incoming HTTP request.

    Returns:
        Rendered HTML response.
    """
    from sylvan.cluster.state import get_cluster_state
    from sylvan.database.orm.runtime.query_cache import get_query_cache
    from sylvan.session.tracker import get_session

    session = get_session()
    stats = session.get_session_stats()
    efficiency = session.get_efficiency_stats()
    cache = get_query_cache().stats()

    cluster = get_cluster_state()
    cluster_sessions = await _get_cluster_sessions()
    combined = _combine_session_efficiency(cluster_sessions)
    coding_history = await _get_coding_session_history()
    cs_totals = await _get_current_coding_session_totals(cluster.coding_session_id)

    template = _jinja.get_template("session.html")
    return HTMLResponse(
        template.render(
            session=stats,
            efficiency=combined or efficiency,
            cache=cache,
            cluster_role=cluster.role,
            cluster_session_id=cluster.session_id,
            cluster_sessions=cluster_sessions,
            coding_history=coding_history,
            cs_totals=cs_totals,
        )
    )


async def session_partial(request: Request) -> HTMLResponse:
    """Return session stats for htmx refresh.

    Args:
        request: The incoming HTTP request.

    Returns:
        Rendered HTML partial.
    """
    from sylvan.cluster.state import get_cluster_state
    from sylvan.database.orm.runtime.query_cache import get_query_cache
    from sylvan.session.tracker import get_session

    session = get_session()
    stats = session.get_session_stats()
    efficiency = session.get_efficiency_stats()
    cache = get_query_cache().stats()

    cluster = get_cluster_state()
    cluster_sessions = await _get_cluster_sessions()
    combined = _combine_session_efficiency(cluster_sessions)
    coding_history = await _get_coding_session_history()
    cs_totals = await _get_current_coding_session_totals(cluster.coding_session_id)

    template = _jinja.get_template("partials/session_stats.html")
    return HTMLResponse(
        template.render(
            session=stats,
            efficiency=combined or efficiency,
            cache=cache,
            cluster_role=cluster.role,
            cluster_session_id=cluster.session_id,
            cluster_sessions=cluster_sessions,
            coding_history=coding_history,
            cs_totals=cs_totals,
        )
    )


async def uptime_partial(request: Request) -> HTMLResponse:
    """Return the current uptime string for htmx polling.

    Args:
        request: The incoming HTTP request.

    Returns:
        Plain text uptime string.
    """
    return HTMLResponse(f"UPTIME {_uptime()}")


async def symbol_source(request: Request) -> HTMLResponse:
    """Return the source code of a symbol for htmx expansion.

    Args:
        request: The incoming HTTP request with 'id' query param.

    Returns:
        Rendered HTML with the symbol source in a code block.
    """
    symbol_id = request.query_params.get("id", "")
    if not symbol_id:
        return HTMLResponse("<div class='mono text-xs text-dim'>No symbol ID</div>")

    from sylvan.database.orm import Symbol
    from sylvan.database.orm.models.blob import Blob

    sym = await Symbol.where(symbol_id=symbol_id).first()
    if sym is None:
        return HTMLResponse("<div class='mono text-xs text-dim'>Symbol not found</div>")

    await sym.load("file")
    source = ""
    if sym.file and sym.file.content_hash:
        content = await Blob.get(sym.file.content_hash)
        if content and sym.byte_offset is not None and sym.byte_length:
            raw = content[sym.byte_offset : sym.byte_offset + sym.byte_length]
            source = raw.decode("utf-8", errors="replace")

    if not source:
        source = sym.signature or "(source unavailable)"

    lang = sym.language or ""
    prism_lang = {
        "python": "python",
        "javascript": "javascript",
        "typescript": "typescript",
        "tsx": "typescript",
        "go": "go",
        "rust": "rust",
        "java": "java",
        "c": "c",
        "cpp": "cpp",
        "c_sharp": "csharp",
        "ruby": "ruby",
        "php": "php",
        "swift": "swift",
        "kotlin": "kotlin",
        "dart": "dart",
        "scala": "scala",
        "bash": "bash",
        "sql": "sql",
    }.get(lang, "")

    import html as html_mod

    escaped = html_mod.escape(source)
    lang_class = f" language-{prism_lang}" if prism_lang else ""
    return HTMLResponse(f'<pre class="code-block"><code class="{lang_class}">{escaped}</code></pre>')


async def blast_radius_page(request: Request) -> HTMLResponse:
    """Render the blast radius explorer page.

    Args:
        request: The incoming HTTP request.

    Returns:
        Rendered HTML response.
    """
    from sylvan.database.orm import Repo

    repos = await Repo.where_not(repo_type="library").get()
    repo_names = [r.name for r in repos]
    template = _jinja.get_template("blast_radius.html")
    return HTMLResponse(template.render(repos=repo_names))


async def blast_radius_partial(request: Request) -> HTMLResponse:
    """Run blast radius analysis and return mermaid graph + details.

    Args:
        request: The incoming HTTP request.

    Returns:
        Rendered HTML partial with mermaid diagram and file lists.
    """
    symbol_id = request.query_params.get("symbol_id", "").strip()
    depth = int(request.query_params.get("depth", "2"))

    if not symbol_id:
        return HTMLResponse("<div class='empty-state'>Enter a symbol ID above</div>")

    from sylvan.analysis.impact.blast_radius import get_blast_radius as _blast

    result = await _blast(symbol_id, max_depth=depth)

    if "error" in result:
        return HTMLResponse(
            f"<div class='empty-state' style='color:var(--danger)'>{result['error']}: {result.get('symbol_id', '')}</div>"
        )

    # Build mermaid graph
    target_name = result["symbol"]["name"]
    confirmed = result.get("confirmed", [])
    potential = result.get("potential", [])

    mermaid_lines = ["graph LR"]
    target_node = f'target["{target_name}"]'
    mermaid_lines.append("    style target fill:#1a3a2a,stroke:#3dd68c,color:#3dd68c")

    seen_nodes = set()
    for entry in confirmed:
        fname = entry["file"].rsplit("/", 1)[-1]
        node_id = fname.replace(".", "_").replace("-", "_")
        if node_id not in seen_nodes:
            seen_nodes.add(node_id)
            refs = entry.get("occurrences", 0)
            label = f'"{fname}<br/>{refs} refs"' if refs else f'"{fname}"'
            mermaid_lines.append(f"    {target_node} -->|d{entry['depth']}| {node_id}[{label}]")
            mermaid_lines.append(f"    style {node_id} fill:#2a1a1a,stroke:#e84855,color:#e84855")

    for entry in potential:
        fname = entry["file"].rsplit("/", 1)[-1]
        node_id = fname.replace(".", "_").replace("-", "_")
        if node_id not in seen_nodes:
            seen_nodes.add(node_id)
            mermaid_lines.append(f'    {target_node} -.->|d{entry["depth"]}| {node_id}["{fname}"]')
            mermaid_lines.append(f"    style {node_id} fill:#1a1a20,stroke:#f0a030,color:#f0a030")

    mermaid_code = "\n".join(mermaid_lines)

    template = _jinja.get_template("partials/blast_radius_result.html")
    return HTMLResponse(
        template.render(
            result=result,
            confirmed=confirmed,
            potential=potential,
            mermaid_code=mermaid_code,
            total=len(confirmed) + len(potential),
        )
    )


async def symbol_search_partial(request: Request) -> HTMLResponse:
    """Search symbols for the blast radius autocomplete.

    Args:
        request: The incoming HTTP request.

    Returns:
        HTML options for the symbol dropdown.
    """
    query = request.query_params.get("q", "").strip()
    repo = request.query_params.get("repo", "").strip() or None

    if not query or len(query) < 2:
        return HTMLResponse("")

    results = await _search_symbols(query, repo)
    options = []
    for sym in results[:15]:
        sid = sym["symbol_id"].replace("'", "\\'")
        options.append(
            f'<div class="autocomplete-item" onclick="selectSymbol(\'{sid}\')">'
            f'<span class="badge badge-{sym["kind"]}">{sym["kind"]}</span> '
            f'<span class="mono text-white" style="font-size:12px">{sym["name"]}</span> '
            f'<span class="mono text-xs text-faint">{sym["file"]}</span>'
            f"</div>"
        )
    return HTMLResponse("".join(options))


async def api_stats(request: Request) -> JSONResponse:
    """Return dashboard stats as JSON for programmatic access.

    Args:
        request: The incoming HTTP request.

    Returns:
        JSON response with overview data.
    """
    data = await _get_overview_data()
    data["uptime"] = _uptime()
    return JSONResponse(data)


async def _context_middleware(request: Request, call_next):
    """Set up a SylvanContext for each dashboard request.

    The dashboard runs outside the MCP dispatch, so it needs its own
    context with the shared backend.

    Args:
        request: The incoming HTTP request.
        call_next: The next middleware or route handler.

    Returns:
        The HTTP response.
    """
    from sylvan.config import get_config
    from sylvan.context import SylvanContext, using_context
    from sylvan.database.orm.runtime.identity_map import IdentityMap
    from sylvan.database.orm.runtime.query_cache import get_query_cache
    from sylvan.server import _get_or_create_backend
    from sylvan.session.tracker import get_session

    backend = await _get_or_create_backend()
    ctx = SylvanContext(
        backend=backend,
        config=get_config(),
        session=get_session(),
        cache=get_query_cache(),
        identity_map=IdentityMap(),
    )
    async with using_context(ctx):
        response = await call_next(request)
    return response


def create_dashboard_app() -> Starlette:
    """Create and return the Starlette dashboard application.

    Returns:
        Configured Starlette app with all dashboard routes.
    """
    from starlette.middleware import Middleware
    from starlette.middleware.base import BaseHTTPMiddleware

    from sylvan.cluster.api import handle_heartbeat, handle_proxy
    from sylvan.cluster.websocket import handle_follower_connection

    routes = [
        Route("/", overview),
        Route("/quality", quality),
        Route("/libraries", libraries),
        Route("/search", search),
        Route("/session", session_page),
        Route("/workspaces", workspaces_page),
        Route("/extensions", extensions_page),
        Route("/history", history_page),
        Route("/api/stats", api_stats),
        Route("/api/proxy", handle_proxy, methods=["POST"]),
        Route("/api/session/heartbeat", handle_heartbeat, methods=["POST"]),
        WebSocketRoute("/ws/cluster", handle_follower_connection),
        Route("/htmx/stats", overview_partial),
        Route("/htmx/quality", quality_partial),
        Route("/htmx/search", search_results),
        Route("/htmx/session", session_partial),
        Route("/htmx/symbol", symbol_source),
        Route("/blast-radius", blast_radius_page),
        Route("/htmx/blast-radius", blast_radius_partial),
        Route("/htmx/symbol-search", symbol_search_partial),
        Route("/partials/uptime", uptime_partial),
    ]
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
