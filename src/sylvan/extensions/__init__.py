"""Sylvan extension system -- user-defined tools, languages, parsers, and providers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

_registered_tools: dict[str, dict[str, Any]] = {}
_registered_content_handlers: list[dict[str, Any]] = []


def register_tool(
    name: str,
    description: str,
    schema: dict,
) -> Callable:
    """Register a custom MCP tool from an extension.

    .. deprecated::
        Use ``sylvan.tools.base.Tool`` subclass instead. Extension files
        that define a Tool subclass are auto-discovered and registered.
        This decorator will be removed in a future version.

    Args:
        name: Tool name (must be unique across core + extensions).
        description: Tool description shown to the agent.
        schema: JSON Schema for the tool's input parameters.

    Returns:
        Decorator that registers the function as a tool handler.
    """
    import warnings

    warnings.warn(
        f"@register_tool('{name}') is deprecated. "
        "Define a sylvan.tools.base.Tool subclass instead - it will be "
        "auto-discovered when the extension file is imported.",
        DeprecationWarning,
        stacklevel=2,
    )

    def decorator(func: Callable) -> Callable:
        _registered_tools[name] = {
            "name": name,
            "description": description,
            "schema": schema,
            "handler": func,
        }
        return func

    return decorator


def register_content_handler(
    name: str,
    sniffer: Callable[[str, str], bool],
    handler: Callable,
    *,
    priority: int = 0,
) -> None:
    """Register a content handler that claims files by sniffing content.

    The sniffer is called with (file_path, content) and returns True if
    this handler should process the file. Handlers with higher priority
    run first. The first sniffer that returns True wins.

    The handler is called with (file_id, file_path, content, result, repo_name)
    and is responsible for storing symbols and/or imports. Symbol IDs must
    be prefixed with ``repo_name::`` for global uniqueness.

    Args:
        name: Handler name for logging.
        sniffer: Function(file_path, content) -> bool.
        handler: Async function(file_id, file_path, content, result, repo_name).
        priority: Higher runs first. Default 0.
    """
    _registered_content_handlers.append(
        {
            "name": name,
            "sniffer": sniffer,
            "handler": handler,
            "priority": priority,
        }
    )
    # Keep sorted by priority descending
    _registered_content_handlers.sort(key=lambda h: -h["priority"])


def get_content_handler(file_path: str, content: str) -> Callable | None:
    """Find the first content handler whose sniffer matches.

    Args:
        file_path: Relative file path.
        content: File content string.

    Returns:
        The handler function, or None if no sniffer matched.
    """
    for entry in _registered_content_handlers:
        try:
            if entry["sniffer"](file_path, content):
                return entry["handler"]
        except Exception:  # noqa: S112 -- sniffer failure should not block other handlers
            continue
    return None


def get_registered_tools() -> dict[str, dict[str, Any]]:
    """Return all tools registered by extensions."""
    return _registered_tools
