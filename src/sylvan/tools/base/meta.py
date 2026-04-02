"""Typed MetaBuilder for ``_meta`` response envelopes.

Replaces arbitrary ``set(key, value)`` calls with typed methods so field
names can't drift across tools. Stored on a contextvar so deeply nested
code (services, analysis functions) can contribute to the response
metadata without passing the builder through every call.
"""

from __future__ import annotations

import contextvars
import time
from typing import Any

_current_meta: contextvars.ContextVar[ToolMeta | None] = contextvars.ContextVar("sylvan_tool_meta", default=None)


def get_meta() -> ToolMeta:
    """Get the ToolMeta for the current tool call.

    The dispatch layer creates one per request and stores it on the
    contextvar. Code anywhere in the call stack can call this to
    contribute metadata to the response.
    """
    meta = _current_meta.get()
    if meta is None:
        return ToolMeta()
    return meta


def set_meta(meta: ToolMeta) -> contextvars.Token:
    """Set the ToolMeta for the current request."""
    return _current_meta.set(meta)


def reset_meta(token: contextvars.Token) -> None:
    """Reset the contextvar after the request completes."""
    _current_meta.reset(token)


class ToolMeta:
    """Typed builder for ``_meta`` response envelopes.

    Every field that can appear in ``_meta`` has a dedicated method.
    No arbitrary string keys - typos become AttributeError.
    """

    def __init__(self) -> None:
        self._start = time.monotonic()
        self._repo: str | None = None
        self._repo_id: int | None = None
        self._results_count: int | None = None
        self._query: str | None = None
        self._found: int | None = None
        self._not_found_count: int | None = None
        self._files_indexed: int | None = None
        self._symbols_extracted: int | None = None
        self._already_seen: int | None = None
        self._returned_tokens: int = 0
        self._equivalent_tokens: int = 0
        self._efficiency_method: str = "byte_estimate"
        self._extra: dict[str, Any] = {}

    def repo(self, name: str | None) -> ToolMeta:
        self._repo = name
        return self

    def repo_id(self, id: int) -> ToolMeta:
        self._repo_id = id
        return self

    def results_count(self, count: int) -> ToolMeta:
        self._results_count = count
        return self

    def query(self, q: str) -> ToolMeta:
        self._query = q
        return self

    def found(self, count: int) -> ToolMeta:
        self._found = count
        return self

    def not_found_count(self, count: int) -> ToolMeta:
        self._not_found_count = count
        return self

    def files_indexed(self, count: int) -> ToolMeta:
        self._files_indexed = count
        return self

    def symbols_extracted(self, count: int) -> ToolMeta:
        self._symbols_extracted = count
        return self

    def already_seen(self, count: int) -> ToolMeta:
        self._already_seen = count
        return self

    def token_efficiency(self, returned: int, equivalent: int, method: str = "byte_estimate") -> ToolMeta:
        self._returned_tokens += returned
        self._equivalent_tokens += equivalent
        self._efficiency_method = method
        return self

    def extra(self, key: str, value: Any) -> ToolMeta:
        """Set a tool-specific meta key not covered by typed methods.

        Use sparingly - prefer adding a typed method if the key will
        be used by more than one tool.
        """
        self._extra[key] = value
        return self

    def elapsed_ms(self) -> float:
        return round((time.monotonic() - self._start) * 1000, 1)

    def build(self) -> dict:
        """Finalize the envelope."""
        result: dict[str, Any] = {
            "timing_ms": self.elapsed_ms(),
            "repo": self._repo,
        }

        if self._repo_id is not None:
            result["repo_id"] = self._repo_id
        if self._results_count is not None:
            result["results_count"] = self._results_count
        if self._query is not None:
            result["query"] = self._query
        if self._found is not None:
            result["found"] = self._found
        if self._not_found_count is not None:
            result["not_found_count"] = self._not_found_count
        if self._files_indexed is not None:
            result["files_indexed"] = self._files_indexed
        if self._symbols_extracted is not None:
            result["symbols_extracted"] = self._symbols_extracted
        if self._already_seen is not None:
            result["already_seen_deprioritized"] = self._already_seen

        if self._returned_tokens > 0 or self._equivalent_tokens > 0:
            reduction = (
                round((1 - self._returned_tokens / self._equivalent_tokens) * 100, 1)
                if self._equivalent_tokens > 0
                else 0.0
            )
            result["token_efficiency"] = {
                "returned": self._returned_tokens,
                "equivalent_file_read": self._equivalent_tokens,
                "reduction_percent": reduction,
                "method": self._efficiency_method,
            }

        result.update(self._extra)
        return result
