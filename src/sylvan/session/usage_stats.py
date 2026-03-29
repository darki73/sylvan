"""Per-repo per-day usage statistics - direct write, no buffering.

Records every tool call immediately to the usage_stats table.
Followers relay stats to the leader via WebSocket.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

from sylvan.logging import get_logger

logger = get_logger(__name__)


def get_connection() -> sqlite3.Connection:
    """Open a sync sqlite3 connection to the sylvan DB.

    Returns:
        An open sqlite3 connection with row factory set.
    """
    from sylvan.config import get_config

    conn = sqlite3.connect(str(get_config().db_path))
    conn.row_factory = sqlite3.Row
    return conn


async def record_usage(
    repo_id: int,
    tool_calls: int = 1,
    tokens_returned: int = 0,
    tokens_avoided: int = 0,
    symbols_retrieved: int = 0,
    sections_retrieved: int = 0,
    tokens_returned_search: int = 0,
    tokens_equivalent_search: int = 0,
    tokens_returned_retrieval: int = 0,
    tokens_equivalent_retrieval: int = 0,
) -> None:
    """Record a usage event directly to the database.

    For followers, relays the data to the leader via WebSocket.

    Args:
        repo_id: Repository primary key (0 for global/non-repo calls).
        tool_calls: Number of tool calls.
        tokens_returned: Tokens returned in this event.
        tokens_avoided: Tokens saved in this event.
        symbols_retrieved: Symbols retrieved in this event.
        sections_retrieved: Sections retrieved in this event.
        tokens_returned_search: Tokens returned by search tools.
        tokens_equivalent_search: Equivalent file-read tokens for search tools.
        tokens_returned_retrieval: Tokens returned by retrieval tools.
        tokens_equivalent_retrieval: Equivalent file-read tokens for retrieval tools.
    """
    from sylvan.cluster.state import get_cluster_state

    state = get_cluster_state()

    if state.is_follower:
        await _relay_to_leader(
            repo_id=repo_id,
            tool_calls=tool_calls,
            tokens_returned=tokens_returned,
            tokens_avoided=tokens_avoided,
            symbols_retrieved=symbols_retrieved,
            sections_retrieved=sections_retrieved,
            tokens_returned_search=tokens_returned_search,
            tokens_equivalent_search=tokens_equivalent_search,
            tokens_returned_retrieval=tokens_returned_retrieval,
            tokens_equivalent_retrieval=tokens_equivalent_retrieval,
        )
        return

    await _write_to_db(
        repo_id=repo_id,
        tool_calls=tool_calls,
        tokens_returned=tokens_returned,
        tokens_avoided=tokens_avoided,
        symbols_retrieved=symbols_retrieved,
        sections_retrieved=sections_retrieved,
        tokens_returned_search=tokens_returned_search,
        tokens_equivalent_search=tokens_equivalent_search,
        tokens_returned_retrieval=tokens_returned_retrieval,
        tokens_equivalent_retrieval=tokens_equivalent_retrieval,
    )


async def _write_to_db(**kwargs: Any) -> None:
    """Upsert a usage record into the usage_stats table.

    Uses INSERT ON CONFLICT to atomically increment counters.
    """
    from sylvan.database.orm.runtime.connection_manager import get_backend

    backend = get_backend()
    today = date.today().isoformat()

    await backend.execute(
        """INSERT INTO usage_stats
           (repo_id, date, tool_calls, tokens_returned, tokens_avoided,
            symbols_retrieved, sections_retrieved,
            tokens_returned_search, tokens_equivalent_search,
            tokens_returned_retrieval, tokens_equivalent_retrieval)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(repo_id, date) DO UPDATE SET
               tool_calls = tool_calls + excluded.tool_calls,
               tokens_returned = tokens_returned + excluded.tokens_returned,
               tokens_avoided = tokens_avoided + excluded.tokens_avoided,
               symbols_retrieved = symbols_retrieved + excluded.symbols_retrieved,
               sections_retrieved = sections_retrieved + excluded.sections_retrieved,
               tokens_returned_search = tokens_returned_search + excluded.tokens_returned_search,
               tokens_equivalent_search = tokens_equivalent_search + excluded.tokens_equivalent_search,
               tokens_returned_retrieval = tokens_returned_retrieval + excluded.tokens_returned_retrieval,
               tokens_equivalent_retrieval = tokens_equivalent_retrieval + excluded.tokens_equivalent_retrieval""",
        [
            kwargs["repo_id"],
            today,
            kwargs.get("tool_calls", 0),
            kwargs.get("tokens_returned", 0),
            kwargs.get("tokens_avoided", 0),
            kwargs.get("symbols_retrieved", 0),
            kwargs.get("sections_retrieved", 0),
            kwargs.get("tokens_returned_search", 0),
            kwargs.get("tokens_equivalent_search", 0),
            kwargs.get("tokens_returned_retrieval", 0),
            kwargs.get("tokens_equivalent_retrieval", 0),
        ],
    )
    await backend.commit()


async def _relay_to_leader(**kwargs: Any) -> None:
    """Send usage stats to the leader via WebSocket for recording."""
    try:
        from sylvan.cluster.websocket import send_usage_to_leader

        await send_usage_to_leader(kwargs)
    except Exception as exc:
        logger.debug("usage_relay_failed", error=str(exc))


def flush_all() -> None:
    """No-op. Kept for backwards compatibility with signal handlers."""


async def async_get_project_usage(backend: Any, repo_id: int) -> dict:
    """Get lifetime usage stats for a repo via the async backend.

    Args:
        backend: The async storage backend.
        repo_id: Repository primary key.

    Returns:
        Dictionary of aggregated usage metrics.
    """
    from sylvan.database.orm import Count, Max, Min, Sum
    from sylvan.database.orm.models.usage_stats import UsageStats

    stats = await UsageStats.where(repo_id=repo_id).aggregates(
        days_active=Count("date", distinct=True),
        total_tool_calls=Sum("tool_calls"),
        total_tokens_returned=Sum("tokens_returned"),
        total_tokens_avoided=Sum("tokens_avoided"),
        total_symbols_retrieved=Sum("symbols_retrieved"),
        total_sections_retrieved=Sum("sections_retrieved"),
        total_tokens_returned_search=Sum("tokens_returned_search"),
        total_tokens_equivalent_search=Sum("tokens_equivalent_search"),
        total_tokens_returned_retrieval=Sum("tokens_returned_retrieval"),
        total_tokens_equivalent_retrieval=Sum("tokens_equivalent_retrieval"),
    )
    minmax = await UsageStats.where(repo_id=repo_id).aggregates(
        first_used=Min("date"),
        last_used=Max("date"),
    )
    stats["first_used"] = minmax["first_used"] or None
    stats["last_used"] = minmax["last_used"] or None
    return stats


async def async_get_overall_usage(backend: Any) -> dict:
    """Get aggregate usage stats across all repos via the async backend.

    Args:
        backend: The async storage backend.

    Returns:
        Dictionary of aggregated usage metrics.
    """
    from sylvan.database.orm import Count, Max, Min, Sum
    from sylvan.database.orm.models.usage_stats import UsageStats

    stats = await UsageStats.all().aggregates(
        repos_used=Count("repo_id", distinct=True),
        days_active=Count("date", distinct=True),
        total_tool_calls=Sum("tool_calls"),
        total_tokens_returned=Sum("tokens_returned"),
        total_tokens_avoided=Sum("tokens_avoided"),
        total_symbols_retrieved=Sum("symbols_retrieved"),
        total_sections_retrieved=Sum("sections_retrieved"),
        total_tokens_returned_search=Sum("tokens_returned_search"),
        total_tokens_equivalent_search=Sum("tokens_equivalent_search"),
        total_tokens_returned_retrieval=Sum("tokens_returned_retrieval"),
        total_tokens_equivalent_retrieval=Sum("tokens_equivalent_retrieval"),
    )
    minmax = await UsageStats.all().aggregates(
        first_used=Min("date"),
        last_used=Max("date"),
    )
    stats["first_used"] = minmax["first_used"] or None
    stats["last_used"] = minmax["last_used"] or None
    return stats


def get_project_usage(conn: sqlite3.Connection, repo_id: int) -> dict:
    """Get lifetime usage stats for a repo (sync).

    Args:
        conn: Active SQLite connection.
        repo_id: Repository primary key.

    Returns:
        Dictionary of aggregated usage metrics.
    """
    row = conn.execute(
        """SELECT
               COUNT(DISTINCT date) as days_active,
               SUM(tool_calls) as total_tool_calls,
               SUM(tokens_returned) as total_tokens_returned,
               SUM(tokens_avoided) as total_tokens_avoided,
               SUM(symbols_retrieved) as total_symbols_retrieved,
               SUM(sections_retrieved) as total_sections_retrieved,
               SUM(tokens_returned_search) as total_tokens_returned_search,
               SUM(tokens_equivalent_search) as total_tokens_equivalent_search,
               SUM(tokens_returned_retrieval) as total_tokens_returned_retrieval,
               SUM(tokens_equivalent_retrieval) as total_tokens_equivalent_retrieval,
               MIN(date) as first_used,
               MAX(date) as last_used
           FROM usage_stats
           WHERE repo_id = ?""",
        (repo_id,),
    ).fetchone()

    empty = {
        "days_active": 0,
        "total_tool_calls": 0,
        "total_tokens_returned": 0,
        "total_tokens_avoided": 0,
        "total_symbols_retrieved": 0,
        "total_sections_retrieved": 0,
        "total_tokens_returned_search": 0,
        "total_tokens_equivalent_search": 0,
        "total_tokens_returned_retrieval": 0,
        "total_tokens_equivalent_retrieval": 0,
        "first_used": None,
        "last_used": None,
    }
    if row is None or row["total_tool_calls"] is None:
        return empty
    return {**empty, **{k: v for k, v in dict(row).items() if v is not None}}


def get_overall_usage(conn: sqlite3.Connection) -> dict:
    """Get aggregate usage stats across all repos (sync).

    Args:
        conn: Active SQLite connection.

    Returns:
        Dictionary of aggregated usage metrics.
    """
    row = conn.execute(
        """SELECT
               COUNT(DISTINCT repo_id) as repos_used,
               COUNT(DISTINCT date) as days_active,
               SUM(tool_calls) as total_tool_calls,
               SUM(tokens_returned) as total_tokens_returned,
               SUM(tokens_avoided) as total_tokens_avoided,
               SUM(symbols_retrieved) as total_symbols_retrieved,
               SUM(sections_retrieved) as total_sections_retrieved,
               SUM(tokens_returned_search) as total_tokens_returned_search,
               SUM(tokens_equivalent_search) as total_tokens_equivalent_search,
               SUM(tokens_returned_retrieval) as total_tokens_returned_retrieval,
               SUM(tokens_equivalent_retrieval) as total_tokens_equivalent_retrieval,
               MIN(date) as first_used,
               MAX(date) as last_used
           FROM usage_stats""",
    ).fetchone()

    empty = {
        "repos_used": 0,
        "days_active": 0,
        "total_tool_calls": 0,
        "total_tokens_returned": 0,
        "total_tokens_avoided": 0,
        "total_symbols_retrieved": 0,
        "total_sections_retrieved": 0,
        "total_tokens_returned_search": 0,
        "total_tokens_equivalent_search": 0,
        "total_tokens_returned_retrieval": 0,
        "total_tokens_equivalent_retrieval": 0,
        "first_used": None,
        "last_used": None,
    }
    if row is None or row["total_tool_calls"] is None:
        return empty
    return {**empty, **{k: v for k, v in dict(row).items() if v is not None}}
