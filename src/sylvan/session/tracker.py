"""Per-session state tracking -- seen symbols, working files, query patterns.

Tracks what the agent has already retrieved in this MCP session so we can:
- Deprioritize already-seen results in search
- Boost related symbols to the current working context
- Predict what the agent needs next
"""

import collections
import threading
import time
from dataclasses import dataclass, field

_EFFICIENCY_CATEGORIES = ("search", "retrieval", "analysis", "indexing", "meta")
"""Valid token efficiency categories for session tracking."""


@dataclass
class SessionTracker:
    """Tracks agent activity within a single MCP session.

    Attributes:
        _seen_symbols: Mapping of symbol IDs to access timestamps.
        _seen_sections: Mapping of section IDs to access timestamps.
        _working_files: Mapping of file paths to access timestamps.
        _query_history: Chronological list of query records.
        _tool_calls: Total tool invocation count.
        _start_time: Session start time (monotonic).
        _tokens_returned: Cumulative tokens returned to the agent.
        _tokens_avoided: Cumulative tokens saved by partial retrieval.
        _efficiency_by_category: Per-category token efficiency counters.
    """

    _seen_symbols: dict[str, float] = field(default_factory=dict)
    _seen_sections: dict[str, float] = field(default_factory=dict)
    _working_files: dict[str, float] = field(default_factory=dict)
    _query_history: list[dict] = field(default_factory=list)
    _tool_calls: int = 0
    _start_time: float = field(default_factory=time.monotonic)
    _started_at: str = ""
    _tokens_returned: int = 0
    _tokens_avoided: int = 0
    _workflow_loaded: bool = False
    _project_path: str | None = None
    _efficiency_by_category: dict[str, dict] = field(
        default_factory=lambda: {cat: {"calls": 0, "returned": 0, "equivalent": 0} for cat in _EFFICIENCY_CATEGORIES}
    )
    _recent_calls: collections.deque = field(default_factory=lambda: collections.deque(maxlen=20))

    def __post_init__(self) -> None:
        """Create the threading lock and set the start timestamp."""
        self._lock = threading.Lock()
        if not self._started_at:
            from datetime import UTC, datetime

            self._started_at = datetime.now(UTC).isoformat()

    def record_symbol_access(self, symbol_id: str, file_path: str | None = None) -> None:
        """Record that a symbol was retrieved.

        Args:
            symbol_id: Unique identifier of the retrieved symbol.
            file_path: Optional file path associated with the symbol.
        """
        with self._lock:
            now = time.monotonic()
            self._seen_symbols[symbol_id] = now
            if file_path:
                self._working_files[file_path] = now

    def record_section_access(self, section_id: str, file_path: str | None = None) -> None:
        """Record that a doc section was retrieved.

        Args:
            section_id: Unique identifier of the retrieved section.
            file_path: Optional file path associated with the section.
        """
        with self._lock:
            now = time.monotonic()
            self._seen_sections[section_id] = now
            if file_path:
                self._working_files[file_path] = now

    def record_query(self, query: str, tool: str) -> None:
        """Record a search query.

        Args:
            query: The search query string.
            tool: Name of the tool that issued the query.
        """
        with self._lock:
            self._query_history.append(
                {
                    "query": query,
                    "tool": tool,
                    "timestamp": time.monotonic(),
                }
            )

    def record_tool_call(
        self,
        tool_name: str,
        *,
        repo: str | None = None,
        duration_ms: float | None = None,
        category: str | None = None,
        tokens_returned: int = 0,
        tokens_equivalent: int = 0,
    ) -> None:
        """Record a tool call with all associated metrics.

        This is the single entry point for all statistics recording.
        Called once per tool call from _dispatch.

        Args:
            tool_name: Name of the invoked tool.
            repo: Repository the call targeted.
            duration_ms: How long the call took in milliseconds.
            category: Tool category (search, retrieval, analysis, indexing, meta).
            tokens_returned: Tokens actually returned to the agent.
            tokens_equivalent: Tokens a raw file read would have cost.
        """
        from datetime import UTC, datetime

        with self._lock:
            self._tool_calls += 1
            self._recent_calls.appendleft(
                {
                    "name": tool_name,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "repo": repo,
                    "duration_ms": duration_ms,
                }
            )
            if category and category in self._efficiency_by_category:
                cat = self._efficiency_by_category[category]
                cat["calls"] += 1
                cat["returned"] += tokens_returned
                cat["equivalent"] += tokens_equivalent
            self._tokens_returned += tokens_returned
            self._tokens_avoided += max(0, tokens_equivalent - tokens_returned)

    def get_efficiency_stats(self) -> dict:
        """Get cumulative token efficiency statistics.

        Returns:
            Dict with total returned/equivalent tokens, reduction percent,
            and per-category breakdown.
        """
        with self._lock:
            total_returned = sum(c["returned"] for c in self._efficiency_by_category.values())
            total_equivalent = sum(c["equivalent"] for c in self._efficiency_by_category.values())
            reduction = round((1 - total_returned / total_equivalent) * 100, 1) if total_equivalent > 0 else 0.0
            return {
                "total_returned": total_returned,
                "total_equivalent": total_equivalent,
                "reduction_percent": reduction,
                "by_category": {k: dict(v) for k, v in self._efficiency_by_category.items()},
            }

    def get_recent_calls(self, limit: int = 20) -> list[dict]:
        """Get the most recent tool calls.

        Args:
            limit: Maximum number of calls to return.

        Returns:
            List of recent tool call dicts, newest first.
        """
        with self._lock:
            return list(self._recent_calls)[:limit]

    def is_symbol_seen(self, symbol_id: str) -> bool:
        """Check if a symbol was already retrieved in this session.

        Args:
            symbol_id: Symbol identifier to look up.

        Returns:
            ``True`` if the symbol has been retrieved previously.
        """
        return symbol_id in self._seen_symbols

    def is_section_seen(self, section_id: str) -> bool:
        """Check if a section was already retrieved in this session.

        Args:
            section_id: Section identifier to look up.

        Returns:
            ``True`` if the section has been retrieved previously.
        """
        return section_id in self._seen_sections

    def get_working_files(self, max_count: int = 10) -> list[str]:
        """Get recently accessed files, most recent first.

        Args:
            max_count: Maximum number of file paths to return.

        Returns:
            List of file path strings.
        """
        sorted_files = sorted(self._working_files.items(), key=lambda x: -x[1])
        return [f for f, _ in sorted_files[:max_count]]

    def get_recent_queries(self, max_count: int = 10) -> list[str]:
        """Get recent search queries.

        Args:
            max_count: Maximum number of queries to return.

        Returns:
            List of query strings (most recent last).
        """
        return [q["query"] for q in self._query_history[-max_count:]]

    def get_seen_symbol_ids(self) -> set[str]:
        """Get all symbol IDs retrieved in this session.

        Returns:
            Set of symbol ID strings.
        """
        return set(self._seen_symbols.keys())

    def get_session_stats(self) -> dict:
        """Get session statistics.

        Returns:
            Dictionary of session metrics.
        """
        elapsed = time.monotonic() - self._start_time
        return {
            "start_time": self._started_at,
            "duration_seconds": round(elapsed, 1),
            "tool_calls": self._tool_calls,
            "symbols_retrieved": len(self._seen_symbols),
            "sections_retrieved": len(self._seen_sections),
            "files_touched": len(self._working_files),
            "queries": len(self._query_history),
            "tokens_returned": self._tokens_returned,
            "tokens_avoided": self._tokens_avoided,
        }

    def compute_file_boost(self, file_path: str) -> float:
        """Compute a relevance boost for a file based on session context.

        Files recently accessed get a boost that decays with time.

        Args:
            file_path: File path to compute boost for.

        Returns:
            Boost value between 0.0 and 1.0.
        """
        if file_path not in self._working_files:
            return 0.0

        age = time.monotonic() - self._working_files[file_path]
        if age < 60:
            return 1.0
        elif age < 300:
            return 0.5
        elif age < 1800:
            return 0.2
        return 0.0

    def predict_next_needs(self) -> dict:
        """Predict what the agent might need next based on session patterns.

        Returns:
            Dictionary with ``working_files``, ``recent_queries``, and
            ``symbols_seen_count`` hints for pre-fetching.
        """
        working = self.get_working_files(5)
        recent_queries = self.get_recent_queries(5)

        return {
            "working_files": working,
            "recent_queries": recent_queries,
            "symbols_seen_count": len(self._seen_symbols),
        }


# Global session instance (one per MCP server process)
_session: SessionTracker | None = None


def get_session() -> SessionTracker:
    """Get or create the global session tracker.

    Returns:
        The shared :class:`SessionTracker` instance.
    """
    global _session
    if _session is None:
        _session = SessionTracker()
    return _session


def reset_session() -> None:
    """Reset the session (for testing)."""
    global _session
    _session = SessionTracker()
