"""Structured logging for sylvan.

Backed by ``sylvan-logging`` (Rust) since v2.x. Rendering, level
filtering, file rotation, and output formatting all happen in the Rust
subscriber. The Python side is a forwarding shim over
``sylvan._rust.logging``.

Public API is unchanged from v1.x::

    from sylvan.logging import get_logger

    logger = get_logger(__name__)
    logger.info("indexed_repo", repo="sylvan", files=126)
"""

from __future__ import annotations

import contextvars
import json
import logging as stdlib_logging
import os
import sys
import traceback
from pathlib import Path
from typing import Any

from sylvan._rust import logging as _rust_logging

__all__ = [
    "SylvanLogger",
    "bind_contextvars",
    "clear_contextvars",
    "configure_logging",
    "get_logger",
    "unbind_contextvars",
]

_configured = False

_log_context: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "sylvan_log_context",
    default=None,
)


def _current_context() -> dict[str, Any]:
    return _log_context.get() or {}


def _get_log_dir() -> Path:
    """Return the directory for sylvan log files, creating it if needed."""
    home = Path(os.environ.get("SYLVAN_HOME", Path.home() / ".sylvan"))
    d = home / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def bind_contextvars(**kwargs: Any) -> None:
    """Attach ``kwargs`` to the current async context.

    Every subsequent :class:`SylvanLogger` call in this context merges the
    bound fields into its event. Use :func:`unbind_contextvars` or
    :func:`clear_contextvars` to remove them.
    """
    current = _current_context()
    _log_context.set({**current, **kwargs})


def unbind_contextvars(*keys: str) -> None:
    """Remove ``keys`` from the current async context."""
    current = _current_context()
    if not current:
        return
    _log_context.set({k: v for k, v in current.items() if k not in keys})


def clear_contextvars() -> None:
    """Drop all bound fields from the current async context."""
    _log_context.set(None)


class SylvanLogger:
    """Forwarding structured logger.

    Every log method serializes its event + kwargs + bound context + the
    current :func:`bind_contextvars` state to JSON and calls into the
    Rust subscriber. No rendering happens on the Python side.
    """

    __slots__ = ("_bound", "_name")

    def __init__(self, name: str, bound: dict[str, Any] | None = None) -> None:
        self._name = name
        self._bound = bound or {}

    def bind(self, **kwargs: Any) -> SylvanLogger:
        """Return a new logger with ``kwargs`` merged into the bound context."""
        return SylvanLogger(self._name, {**self._bound, **kwargs})

    def new(self, **kwargs: Any) -> SylvanLogger:
        """Return a fresh logger discarding any previously-bound fields."""
        return SylvanLogger(self._name, kwargs)

    def unbind(self, *keys: str) -> SylvanLogger:
        """Return a new logger with ``keys`` removed from the bound context."""
        return SylvanLogger(
            self._name,
            {k: v for k, v in self._bound.items() if k not in keys},
        )

    def trace(self, event: str, **kwargs: Any) -> None:
        """Emit a TRACE-level event."""
        self._emit("TRACE", event, kwargs)

    def debug(self, event: str, **kwargs: Any) -> None:
        """Emit a DEBUG-level event."""
        self._emit("DEBUG", event, kwargs)

    def info(self, event: str, **kwargs: Any) -> None:
        """Emit an INFO-level event."""
        self._emit("INFO", event, kwargs)

    def warning(self, event: str, **kwargs: Any) -> None:
        """Emit a WARN-level event."""
        self._emit("WARN", event, kwargs)

    # Structlog compat alias.
    warn = warning

    def error(self, event: str, **kwargs: Any) -> None:
        """Emit an ERROR-level event."""
        self._emit("ERROR", event, kwargs)

    def critical(self, event: str, **kwargs: Any) -> None:
        """Emit an ERROR-level event (critical is folded into error)."""
        self._emit("ERROR", event, kwargs)

    def exception(self, event: str, **kwargs: Any) -> None:
        """Emit an ERROR-level event with the current traceback attached."""
        kwargs.setdefault("exc_info", traceback.format_exc().rstrip())
        self._emit("ERROR", event, kwargs)

    def log(self, level: str, event: str, **kwargs: Any) -> None:
        """Emit ``event`` at the given level name."""
        self._emit(level.upper(), event, kwargs)

    def _emit(self, level: str, event: str, kwargs: dict[str, Any]) -> None:
        fields = _current_context()
        if self._bound or kwargs:
            merged = {**fields, **self._bound, **kwargs}
        else:
            merged = fields
        if merged:
            fields_json = json.dumps(merged, default=_json_default)
        else:
            fields_json = ""
        _rust_logging.emit_structured(level, self._name, event, fields_json)


def _json_default(value: Any) -> str:
    """Fallback serializer for types the stdlib JSON encoder cannot handle."""
    return str(value)


class _RustBridgeHandler(stdlib_logging.Handler):
    """Forwards stdlib ``LogRecord`` instances to the Rust subscriber.

    Used for third-party libraries (httpx, aiosqlite, uvicorn, ...) that
    emit through stdlib logging directly.
    """

    def emit(self, record: stdlib_logging.LogRecord) -> None:
        try:
            message = self.format(record)
            _rust_logging.emit(record.levelname, record.name, message)
        except Exception:
            self.handleError(record)


def configure_logging(
    level: str = "INFO",
    json_output: bool = False,
    log_to_file: bool = True,
) -> None:
    """Configure sylvan's logging pipeline.

    Idempotent: subsequent calls after the first are no-ops, matching the
    one-shot semantics of the underlying Rust subscriber.

    Args:
        level: Minimum level for the console sink. Case-insensitive.
        json_output: If ``True``, render logs as newline-delimited JSON.
        log_to_file: If ``True``, also write to
            ``~/.sylvan/logs/sylvan.log`` with daily rotation.
    """
    global _configured
    if _configured:
        return
    _configured = True

    config: dict[str, Any] = {
        "level": level.lower() if level else "info",
        "format": "json" if json_output else "pretty",
        "overrides": {
            "httpx": "warn",
            "httpcore": "warn",
            "urllib3": "warn",
            "huggingface_hub": "warn",
            "onnxruntime": "warn",
            "filelock": "warn",
            "aiosqlite": "warn",
            "asyncio": "warn",
            "mcp": "warn",
            "uvicorn": "warn",
            "uvicorn.access": "warn",
            "uvicorn.error": "warn",
        },
    }
    if log_to_file:
        config["file"] = {
            "path": str(_get_log_dir() / "sylvan.log"),
            "rotation": "daily",
            "format": "json" if json_output else "pretty",
        }

    _rust_logging.init_from_json(json.dumps(config))

    root = stdlib_logging.getLogger()
    root.handlers.clear()
    root.addHandler(_RustBridgeHandler())
    # Keep stdlib permissive; the Rust subscriber does level filtering.
    root.setLevel(stdlib_logging.DEBUG)


def get_logger(name: str | None = None) -> SylvanLogger:
    """Return a structured logger routed through the Rust subscriber.

    Args:
        name: Logger name. Defaults to the caller's module when omitted.

    Returns:
        A :class:`SylvanLogger` bound to ``name``.
    """
    if name is None:
        # Mirror structlog's behavior: fall back to the caller's module.
        frame = sys._getframe(1)
        name = frame.f_globals.get("__name__", "sylvan")
    return SylvanLogger(name)


_auto_level = os.environ.get("SYLVAN_LOG_LEVEL", "INFO")
_auto_json = os.environ.get("SYLVAN_LOG_FORMAT", "").lower() == "json"
configure_logging(level=_auto_level, json_output=_auto_json, log_to_file=True)
