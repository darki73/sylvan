"""Structured logging for sylvan.

Backed by ``sylvan-logging`` (Rust) since v2.x. All Python log calls are
routed through the Rust tracing subscriber, so level filtering, file
rotation, and output formatting are handled uniformly whether the event
originated in Python or Rust.

Public API is unchanged from v1.x::

    from sylvan.logging import get_logger

    logger = get_logger(__name__)
    logger.info("indexed_repo", repo="sylvan", files=126)
"""

from __future__ import annotations

import json
import logging as stdlib_logging
import os
from pathlib import Path
from typing import Any

import structlog

from sylvan._rust import logging as _rust_logging

_configured = False


def _get_log_dir() -> Path:
    """Return the directory for sylvan log files, creating it if needed."""
    home = Path(os.environ.get("SYLVAN_HOME", Path.home() / ".sylvan"))
    d = home / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


class _RustBridgeHandler(stdlib_logging.Handler):
    """Forwards stdlib ``LogRecord`` instances to the Rust subscriber."""

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

    if json_output:
        final_processor: Any = structlog.processors.JSONRenderer()
    else:
        final_processor = structlog.dev.ConsoleRenderer(colors=False)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.UnicodeDecoder(),
            final_processor,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a structured logger routed through the Rust subscriber.

    Args:
        name: Logger name, typically ``__name__``.

    Returns:
        A structlog ``BoundLogger`` whose output flows to the configured
        console and file sinks via the Rust bridge.
    """
    return structlog.get_logger(name)


_auto_level = os.environ.get("SYLVAN_LOG_LEVEL", "INFO")
_auto_json = os.environ.get("SYLVAN_LOG_FORMAT", "").lower() == "json"
configure_logging(level=_auto_level, json_output=_auto_json, log_to_file=True)
