"""Sylvan — Unified code + documentation retrieval MCP server."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("sylvan")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"
