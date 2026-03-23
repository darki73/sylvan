"""Structured logging configuration for sylvan.

Logs to both stderr (for dev) and a file in ``~/.sylvan/logs/`` (always).
The file log is critical for debugging MCP server issues where stderr
is not visible.

Usage::

    from sylvan.logging import get_logger

    logger = get_logger(__name__)
    logger.info("indexed_repo", repo="sylvan", files=126)
"""

import logging
import os
import sys
from pathlib import Path

import structlog


def _get_log_dir() -> Path:
    """Get the log directory, creating it if needed.

    Returns:
        Path to ``~/.sylvan/logs/``.
    """
    home = Path(os.environ.get("SYLVAN_HOME", Path.home() / ".sylvan"))
    log_dir = home / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def configure_logging(
    level: str = "INFO",
    json_output: bool = False,
    log_to_file: bool = True,
) -> None:
    """Configure structured logging for the process.

    Always logs to ``~/.sylvan/logs/sylvan.log`` at DEBUG level.
    Optionally logs to stderr at a configurable level.

    Args:
        level: Minimum log level for the stderr handler (e.g. ``"INFO"``).
        json_output: If ``True``, render stderr logs as JSON instead of
            human-readable console output.
        log_to_file: If ``True``, also write JSON logs to the sylvan log file.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if json_output:
        console_renderer = structlog.processors.JSONRenderer()
    else:
        console_renderer = structlog.dev.ConsoleRenderer(
            colors=sys.stderr.isatty(),
        )

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    root = logging.getLogger()
    root.handlers.clear()

    foreign_pre_chain = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.ExtraAdder(),
    ]

    console_formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            console_renderer,
        ],
        foreign_pre_chain=foreign_pre_chain,
    )
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(console_formatter)
    console_handler.setLevel(log_level)
    root.addHandler(console_handler)

    if log_to_file:
        try:
            log_dir = _get_log_dir()
            log_file = log_dir / "sylvan.log"

            file_formatter = structlog.stdlib.ProcessorFormatter(
                processors=[
                    structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                    structlog.processors.JSONRenderer(),
                ],
                foreign_pre_chain=foreign_pre_chain,
            )
            from logging.handlers import RotatingFileHandler
            file_handler = RotatingFileHandler(
                str(log_file),
                maxBytes=10 * 1024 * 1024,
                backupCount=3,
                encoding="utf-8",
            )
            file_handler.setFormatter(file_formatter)
            file_handler.setLevel(logging.DEBUG)
            _original_emit = file_handler.emit
            def _flushing_emit(record, _orig=_original_emit):
                """Emit and immediately flush to ensure log lines are visible for debugging."""
                _orig(record)
                file_handler.flush()
            file_handler.emit = _flushing_emit
            root.addHandler(file_handler)
        except Exception:  # noqa: S110 -- can't log about logging failure
            pass

    root.setLevel(logging.DEBUG)

    noisy_loggers = (
        "httpx", "httpcore", "urllib3", "huggingface_hub",
        "onnxruntime", "filelock", "aiosqlite", "asyncio",
        "mcp", "mcp.server", "mcp.server.lowlevel",
        "mcp.server.lowlevel.server", "mcp.shared", "mcp.server.stdio",
    )
    for name in noisy_loggers:
        logging.getLogger(name).setLevel(logging.WARNING)

    for uv_name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        uv_logger = logging.getLogger(uv_name)
        uv_logger.handlers.clear()
        uv_logger.propagate = True
        uv_logger.setLevel(logging.WARNING)


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance.

    Args:
        name: Logger name, typically ``__name__``.

    Returns:
        A bound structlog logger.
    """
    return structlog.get_logger(name)


# Auto-configure on import
_configured = False


def _auto_configure() -> None:
    """Apply default logging configuration on first import.
    """
    global _configured
    if _configured:
        return
    _configured = True

    level = os.environ.get("SYLVAN_LOG_LEVEL", "WARNING")
    json_out = os.environ.get("SYLVAN_LOG_FORMAT", "").lower() == "json"
    configure_logging(level=level, json_output=json_out, log_to_file=True)


_auto_configure()
