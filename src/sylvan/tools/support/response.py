"""Response envelope builder for MCP tool responses."""

import contextvars
import functools
import inspect
import time
from collections.abc import Callable
from typing import Any

from sylvan.logging import get_logger

_tool_logger = get_logger("sylvan.tools")

RESPONSE_VERSION = "1.0"

_current_meta: contextvars.ContextVar["MetaBuilder | None"] = contextvars.ContextVar("sylvan_meta", default=None)


def get_meta() -> "MetaBuilder":
    """Get the MetaBuilder for the current tool call.

    The dispatch layer creates one MetaBuilder per request and stores
    it in this contextvar. Tools call this to record token efficiency
    or set custom metadata.

    Returns:
        The active MetaBuilder for this request.

    Raises:
        RuntimeError: If called outside of a tool dispatch context.
    """
    meta = _current_meta.get()
    if meta is None:
        return MetaBuilder()
    return meta


def set_meta(meta: "MetaBuilder") -> contextvars.Token:
    """Set the MetaBuilder for the current tool call.

    Args:
        meta: The MetaBuilder to make current.

    Returns:
        A token to reset it.
    """
    return _current_meta.set(meta)


def reset_meta(token: contextvars.Token) -> None:
    """Reset the MetaBuilder contextvar.

    Args:
        token: The token from set_meta().
    """
    _current_meta.reset(token)


def _sanitize_log_kwargs(kwargs: dict) -> dict:
    """Replace full file paths with basenames in log kwargs.

    Args:
        kwargs: Tool call keyword arguments.

    Returns:
        Copy with paths shortened to basenames.
    """
    sanitized = {}
    for key, value in kwargs.items():
        if isinstance(value, str) and ("/" in value or "\\" in value):
            from pathlib import PurePosixPath

            try:
                sanitized[key] = PurePosixPath(value).name or value
            except Exception:
                sanitized[key] = value
        else:
            sanitized[key] = value
    return sanitized


def log_tool_call(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator that logs tool call entry, exit, duration, and errors.

    Wraps a tool handler function to automatically log structured events
    without any boilerplate in the handler itself.  Supports both sync
    and async handler functions.

    Args:
        func: The tool handler function to wrap.

    Returns:
        Wrapped function with automatic logging.
    """
    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            """Async logging wrapper for tool handlers."""
            tool_name = func.__module__.rsplit(".", 1)[-1]
            start = time.monotonic()
            _tool_logger.info("tool_call_start", tool=tool_name, args=str(_sanitize_log_kwargs(kwargs))[:200])
            try:
                result = await func(*args, **kwargs)
                elapsed_ms = (time.monotonic() - start) * 1000
                _tool_logger.info("tool_call_complete", tool=tool_name, elapsed_ms=round(elapsed_ms, 1))
                return result
            except Exception as exc:
                elapsed_ms = (time.monotonic() - start) * 1000
                _tool_logger.error("tool_call_error", tool=tool_name, error=str(exc), elapsed_ms=round(elapsed_ms, 1))
                raise

        return async_wrapper
    else:

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            """Sync logging wrapper for tool handlers."""
            tool_name = func.__module__.rsplit(".", 1)[-1]
            start = time.monotonic()
            _tool_logger.info("tool_call_start", tool=tool_name, args=str(_sanitize_log_kwargs(kwargs))[:200])
            try:
                result = func(*args, **kwargs)
                elapsed_ms = (time.monotonic() - start) * 1000
                _tool_logger.info("tool_call_complete", tool=tool_name, elapsed_ms=round(elapsed_ms, 1))
                return result
            except Exception as exc:
                elapsed_ms = (time.monotonic() - start) * 1000
                _tool_logger.error("tool_call_error", tool=tool_name, error=str(exc), elapsed_ms=round(elapsed_ms, 1))
                raise

        return wrapper


class MetaBuilder:
    """Builds ``_meta`` response envelopes with timing and diagnostics.

    Attributes:
        _start: Monotonic start time for elapsed-time calculation.
        _data: Accumulated key-value pairs to include in the envelope.
        _returned_tokens: Tokens actually returned to the agent.
        _equivalent_tokens: Tokens a raw file read would have cost.
    """

    def __init__(self) -> None:
        """Initialize the builder and start the timing clock."""
        self._start = time.monotonic()
        self._data: dict[str, Any] = {}
        self._returned_tokens: int = 0
        self._equivalent_tokens: int = 0
        self._efficiency_method: str = "tiktoken_cl100k"

    def set(self, key: str, value: Any) -> "MetaBuilder":
        """Set a key-value pair in the meta envelope.

        Args:
            key: The metadata key.
            value: The metadata value.

        Returns:
            This builder instance for chaining.
        """
        self._data[key] = value
        return self

    def record_token_efficiency(
        self,
        returned_tokens: int,
        equivalent_tokens: int,
        method: str = "tiktoken_cl100k",
    ) -> "MetaBuilder":
        """Record tokens returned vs what a file Read would cost.

        Args:
            returned_tokens: Tokens actually returned to the agent.
            equivalent_tokens: Tokens a raw file read would have cost.
            method: Estimation method used (e.g. "tiktoken_cl100k", "byte_estimate").

        Returns:
            This builder instance for chaining.
        """
        self._returned_tokens += returned_tokens
        self._equivalent_tokens += equivalent_tokens
        if method != "tiktoken_cl100k":
            self._efficiency_method = method
        return self

    def build(self) -> dict:
        """Finalize the envelope, injecting elapsed timing and token efficiency.

        Returns:
            Dict with ``timing_ms``, optional ``token_efficiency``,
            and all accumulated metadata.
        """
        elapsed = (time.monotonic() - self._start) * 1000
        result: dict[str, Any] = {"timing_ms": round(elapsed, 1), **self._data}
        if self._equivalent_tokens > 0:
            result["token_efficiency"] = {
                "returned": self._returned_tokens,
                "equivalent_file_read": self._equivalent_tokens,
                "reduction_percent": round((1 - self._returned_tokens / self._equivalent_tokens) * 100, 1),
                "method": self._efficiency_method,
            }
        return result


def wrap_response(data: dict, meta: dict, include_hints: bool = False) -> dict:
    """Wrap a tool response with a ``_meta`` envelope.

    If *include_hints* is True, appends prefetch hints from the session
    tracker and read_command hints for editing workflows.

    Args:
        data: The tool response payload.
        meta: The built meta envelope dict.
        include_hints: Whether to append session-based prefetch hints.

    Returns:
        Merged dict of *data* with ``_meta`` (and optionally ``_hints``).
    """
    result = {**data, "_meta": meta, "_version": RESPONSE_VERSION}

    if include_hints:
        hints: dict = {}
        try:
            from sylvan.session.tracker import get_session

            session = get_session()
            needs = session.predict_next_needs()
            if needs.get("working_files"):
                hints["working_files"] = needs["working_files"][:3]
        except Exception:  # noqa: S110 -- best-effort hint
            pass

        # Add contextual next-action hints based on response data.
        # Check top-level keys first, then nested "symbol" for context_bundle.
        nested = data.get("symbol", {}) if isinstance(data.get("symbol"), dict) else {}
        file_path = data.get("file") or nested.get("file") or ""
        line_start = data.get("line_start") or nested.get("line_start")
        line_end = data.get("line_end") or nested.get("line_end")
        symbol_id = data.get("symbol_id") or nested.get("symbol_id") or ""
        section_id = data.get("section_id") or ""

        if file_path and line_start is not None and line_end is not None:
            ctx_lines = 5
            hints["edit"] = {
                "read_file": file_path,
                "read_offset": max(1, line_start - ctx_lines),
                "read_limit": (line_end - line_start) + (ctx_lines * 2),
            }

        if symbol_id:
            hints["next"] = {
                "find_callers": f"who_depends_on_this(repo, '{file_path}')",
                "blast_radius": f"what_breaks_if_i_change('{symbol_id}')",
                "dependency_graph": f"import_graph(repo, '{file_path}')",
            }
        elif section_id and file_path:
            hints["next"] = {
                "toc": f"doc_table_of_contents(repo, doc_path='{file_path}')",
                "find_callers": f"who_depends_on_this(repo, '{file_path}')",
            }
        elif file_path:
            hints["next"] = {
                "file_outline": f"whats_in_file(repo, '{file_path}')",
                "find_callers": f"who_depends_on_this(repo, '{file_path}')",
            }

        if hints:
            result["_hints"] = hints

    return result


def clamp(value: int, low: int, high: int) -> int:
    """Clamp a numeric parameter to a safe range.

    Args:
        value: The input value.
        low: Minimum allowed value (inclusive).
        high: Maximum allowed value (inclusive).

    Returns:
        The clamped value within [low, high].
    """
    return min(max(value, low), high)


def inject_meta(exc: Exception, meta: "MetaBuilder") -> Exception:
    """Re-raise a SylvanError with ``_meta`` attached.

    Service-layer functions raise SylvanError subclasses without meta
    (they should not depend on the response module). This helper copies
    the original error's fields and attaches the tool-level meta so the
    dispatch layer can serialize it properly.

    Args:
        exc: The caught SylvanError instance.
        meta: The MetaBuilder to attach.

    Returns:
        A new exception of the same type with ``_meta`` set.
    """
    from sylvan.error_codes import SylvanError

    if not isinstance(exc, SylvanError):
        return exc

    new_exc = type(exc)(exc.detail, _meta=meta.build(), **exc.context)
    return new_exc


_staleness_cache: dict[int, bool | None] = {}
"""Per-session cache of repo_id to staleness flag, checked at most once per repo."""


async def check_staleness(repo_id: int, result: dict) -> dict:
    """Check if a repo's index is stale and append a warning if so.

    For git repos, compares stored ``git_head`` against current HEAD.
    For non-git repos, the check is skipped (no cheap way to detect
    changes).  Caches the result per *repo_id* so we only check once
    per session.

    Args:
        repo_id: The database ID of the repository.
        result: The tool response dict to potentially annotate.

    Returns:
        The same *result* dict, possibly with a ``_stale`` warning added.
    """
    if repo_id in _staleness_cache:
        is_stale = _staleness_cache[repo_id]
    else:
        is_stale = await _detect_staleness(repo_id)
        _staleness_cache[repo_id] = is_stale

    if is_stale:
        result["_stale"] = (
            "Index may be outdated -- files have changed since last indexing. Re-run index_folder to refresh."
        )
    return result


async def _detect_staleness(repo_id: int) -> bool | None:
    """Check if stored ``git_head`` differs from current HEAD.

    Args:
        repo_id: The database ID of the repository.

    Returns:
        True if the index is stale, False if current, or None if the
        repo is not a git repo or has no stored head.
    """
    try:
        from pathlib import Path

        from sylvan.database.orm import Repo
        from sylvan.git import run_git

        repo = await Repo.find(repo_id)
        if repo is None or not repo.source_path or not repo.git_head:
            return None

        current_head = run_git(Path(repo.source_path), ["rev-parse", "HEAD"], timeout=5)
        if current_head is None:
            return None

        return current_head != repo.git_head
    except Exception:
        return None


def reset_orm() -> None:
    """No-op, kept for backward compatibility."""


def ensure_orm() -> None:
    """No-op, kept for backward compatibility with user extensions."""
