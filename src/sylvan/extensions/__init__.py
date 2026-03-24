"""Sylvan extension system -- user-defined tools, languages, parsers, and providers."""

from __future__ import annotations

from typing import Any, Callable

_registered_tools: dict[str, dict[str, Any]] = {}


def register_tool(
    name: str,
    description: str,
    schema: dict,
) -> Callable:
    """Register a custom MCP tool from an extension.

    Args:
        name: Tool name (must be unique across core + extensions).
        description: Tool description shown to the agent.
        schema: JSON Schema for the tool's input parameters.

    Returns:
        Decorator that registers the function as a tool handler.
    """
    def decorator(func: Callable) -> Callable:
        _registered_tools[name] = {
            "name": name,
            "description": description,
            "schema": schema,
            "handler": func,
        }
        return func
    return decorator


def get_registered_tools() -> dict[str, dict[str, Any]]:
    """Return all tools registered by extensions."""
    return _registered_tools
