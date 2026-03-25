"""Usage tracking -- per-session (in-memory) + per-project/overall (SQLite).

Supports both sync flush (signal handlers, CLI) and async flush (server
dispatch). The accumulator batches writes in memory and periodically
persists them to the database.
"""

import contextlib
import sqlite3
import threading
from datetime import date
from typing import Any

from sylvan.database.connection import get_connection
from sylvan.logging import get_logger

logger = get_logger(__name__)


class UsageAccumulator:
    """Thread-safe accumulator that batches writes to SQLite.

    Collects usage deltas in memory and flushes to the DB periodically
    (every N calls or on explicit flush).  Avoids a DB write per tool call.
    """

    _FLUSH_INTERVAL = 5  # flush every N increments

    def __init__(self) -> None:
        """Initialize the accumulator with empty pending state."""
        self._lock = threading.Lock()
        self._pending: dict[int, dict] = {}  # repo_id -> {field: delta}
        self._call_count = 0

    def increment(
        self,
        repo_id: int,
        tool_calls: int = 0,
        tokens_returned: int = 0,
        tokens_avoided: int = 0,
        symbols_retrieved: int = 0,
        sections_retrieved: int = 0,
        tokens_returned_search: int = 0,
        tokens_equivalent_search: int = 0,
        tokens_returned_retrieval: int = 0,
        tokens_equivalent_retrieval: int = 0,
    ) -> None:
        """Accumulate a usage delta for a repo.

        Args:
            repo_id: Repository primary key.
            tool_calls: Number of tool calls to add.
            tokens_returned: Number of tokens returned to add.
            tokens_avoided: Number of tokens avoided to add.
            symbols_retrieved: Number of symbols retrieved to add.
            sections_retrieved: Number of sections retrieved to add.
            tokens_returned_search: Tokens returned by search tools.
            tokens_equivalent_search: Equivalent file-read tokens for search tools.
            tokens_returned_retrieval: Tokens returned by retrieval tools.
            tokens_equivalent_retrieval: Equivalent file-read tokens for retrieval tools.
        """
        with self._lock:
            if repo_id not in self._pending:
                self._pending[repo_id] = {
                    "tool_calls": 0,
                    "tokens_returned": 0,
                    "tokens_avoided": 0,
                    "symbols_retrieved": 0,
                    "sections_retrieved": 0,
                    "tokens_returned_search": 0,
                    "tokens_equivalent_search": 0,
                    "tokens_returned_retrieval": 0,
                    "tokens_equivalent_retrieval": 0,
                }

            p = self._pending[repo_id]
            p["tool_calls"] += tool_calls
            p["tokens_returned"] += tokens_returned
            p["tokens_avoided"] += tokens_avoided
            p["symbols_retrieved"] += symbols_retrieved
            p["sections_retrieved"] += sections_retrieved
            p["tokens_returned_search"] += tokens_returned_search
            p["tokens_equivalent_search"] += tokens_equivalent_search
            p["tokens_returned_retrieval"] += tokens_returned_retrieval
            p["tokens_equivalent_retrieval"] += tokens_equivalent_retrieval
            self._call_count += 1

    def flush(self) -> None:
        """Force flush pending stats to DB (sync)."""
        with self._lock:
            self._flush_locked()

    async def async_flush(self) -> None:
        """Force flush pending stats via the async backend.

        Falls back to sync flush if no async backend is available.
        """
        with self._lock:
            pending = dict(self._pending)
            self._pending.clear()
            self._call_count = 0

        if not pending:
            return

        try:
            from sylvan.context import get_context

            ctx = get_context()
            if ctx.backend is not None:
                today = date.today().isoformat()
                for repo_id, deltas in pending.items():
                    # column names are from a hardcoded list -- not user input
                    await ctx.backend.execute(
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
                            repo_id,
                            today,
                            deltas["tool_calls"],
                            deltas["tokens_returned"],
                            deltas["tokens_avoided"],
                            deltas["symbols_retrieved"],
                            deltas["sections_retrieved"],
                            deltas["tokens_returned_search"],
                            deltas["tokens_equivalent_search"],
                            deltas["tokens_returned_retrieval"],
                            deltas["tokens_equivalent_retrieval"],
                        ],
                    )
                await ctx.backend.commit()
                return
        except Exception as exc:
            logger.debug("async_usage_flush_failed", error=str(exc))

        # Fallback: re-enqueue and flush sync
        with self._lock:
            for repo_id, deltas in pending.items():
                if repo_id not in self._pending:
                    self._pending[repo_id] = deltas
                else:
                    for k, v in deltas.items():
                        self._pending[repo_id][k] += v
            self._flush_locked()

    def _flush_locked(self) -> None:
        """Flush while lock is held (sync path).

        Uses ``INSERT ... ON CONFLICT DO UPDATE SET column = column + excluded.column``
        so that concurrent processes accumulate additively rather than
        overwriting each other's values.
        """
        if not self._pending:
            return

        try:
            conn = get_connection()
            today = date.today().isoformat()

            for repo_id, deltas in self._pending.items():
                # column names are from a hardcoded list -- not user input
                conn.execute(
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
                    (
                        repo_id,
                        today,
                        deltas["tool_calls"],
                        deltas["tokens_returned"],
                        deltas["tokens_avoided"],
                        deltas["symbols_retrieved"],
                        deltas["sections_retrieved"],
                        deltas["tokens_returned_search"],
                        deltas["tokens_equivalent_search"],
                        deltas["tokens_returned_retrieval"],
                        deltas["tokens_equivalent_retrieval"],
                    ),
                )

            conn.commit()
            conn.close()
        except Exception as e:
            from sylvan.logging import get_logger

            get_logger(__name__).debug("usage_flush_failed", error=str(e))

        self._pending.clear()
        self._call_count = 0


# Module-level singleton
_accumulator: UsageAccumulator | None = None


def get_accumulator() -> UsageAccumulator:
    """Get or create the module-level usage accumulator singleton.

    Returns:
        The shared :class:`UsageAccumulator` instance.
    """
    global _accumulator
    if _accumulator is None:
        _accumulator = UsageAccumulator()
    return _accumulator


def record_usage(
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
    """Record a usage event.  Batched to DB automatically.

    Args:
        repo_id: Repository primary key.
        tool_calls: Number of tool calls (default 1).
        tokens_returned: Tokens returned in this event.
        tokens_avoided: Tokens saved in this event.
        symbols_retrieved: Symbols retrieved in this event.
        sections_retrieved: Sections retrieved in this event.
        tokens_returned_search: Tokens returned by search tools.
        tokens_equivalent_search: Equivalent file-read tokens for search tools.
        tokens_returned_retrieval: Tokens returned by retrieval tools.
        tokens_equivalent_retrieval: Equivalent file-read tokens for retrieval tools.
    """
    get_accumulator().increment(
        repo_id,
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


def flush_usage() -> None:
    """Force flush any pending usage stats (sync)."""
    get_accumulator().flush()


async def async_flush_usage() -> None:
    """Force flush any pending usage stats (async)."""
    await get_accumulator().async_flush()


def flush_all() -> None:
    """Flush the module-level accumulator if it exists.

    Safe to call from signal handlers or atexit -- silently ignores errors.
    """
    global _accumulator
    if _accumulator is not None:
        with contextlib.suppress(Exception):
            _accumulator.flush()


def get_project_usage(conn: sqlite3.Connection, repo_id: int) -> dict:
    """Get lifetime usage stats for a repo.

    Args:
        conn: Active SQLite connection.
        repo_id: Repository primary key.

    Returns:
        Dictionary of aggregated usage metrics.
    """
    flush_usage()
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

    empty_project = {
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
        return empty_project

    return {**empty_project, **{k: v for k, v in dict(row).items() if v is not None}}


async def async_get_project_usage(backend: Any, repo_id: int) -> dict:
    """Get lifetime usage stats for a repo via the async backend.

    Args:
        backend: The async storage backend.
        repo_id: Repository primary key.

    Returns:
        Dictionary of aggregated usage metrics.
    """
    from sylvan.database.orm import Count, Max, Min, Sum, UsageStats

    await get_accumulator().async_flush()

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


def get_overall_usage(conn: sqlite3.Connection) -> dict:
    """Get aggregate usage stats across all repos.

    Args:
        conn: Active SQLite connection.

    Returns:
        Dictionary of aggregated usage metrics.
    """
    flush_usage()
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

    empty_overall = {
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
        return empty_overall

    return {**empty_overall, **{k: v for k, v in dict(row).items() if v is not None}}


async def async_get_overall_usage(backend: Any) -> dict:
    """Get aggregate usage stats across all repos via the async backend.

    Args:
        backend: The async storage backend.

    Returns:
        Dictionary of aggregated usage metrics.
    """
    from sylvan.database.orm import Count, Max, Min, Sum, UsageStats

    await get_accumulator().async_flush()

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
