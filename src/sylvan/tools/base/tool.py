"""Tool base class with auto-discovery and framework-level response wrapping."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, ClassVar

from mcp.types import Tool as MCPTool

from sylvan.logging import get_logger
from sylvan.tools.base.params import ToolParams

if TYPE_CHECKING:
    from sylvan.tools.base.hints import HintBuilder

logger = get_logger(__name__)

_registry: dict[str, type[Tool]] = {}


class MeasureMethod:
    """Constants for token estimation methods used in ``_meta.token_efficiency``."""

    BYTE_ESTIMATE = "byte_estimate"
    TIKTOKEN_CL100K = "tiktoken_cl100k"


class Tool:
    """Base class for all sylvan MCP tools.

    Subclass this, set class attributes, define a ``Params`` inner class
    composed from traits, and implement ``handle()``. The framework handles
    schema generation, param validation, ``_meta`` envelope, timing,
    staleness checks, and token efficiency tracking.

    Token efficiency is automatic for tools that override ``measure()``.
    The base calls ``measure()`` after ``handle()`` returns, and if it
    returns non-zero values, attaches ``token_efficiency`` to ``_meta``.

    Example::

        from sylvan.tools.base import Tool, HasSymbol, HasDepth, ToolParams

        class GetBlastRadius(Tool):
            name = "what_breaks_if_i_change"
            category = "analysis"
            description = "Check what breaks if you change a symbol."

            class Params(HasSymbol, HasDepth, ToolParams):
                pass

            async def handle(self, p: Params) -> dict:
                svc = AnalysisService()
                return await svc.blast_radius(p.symbol_id, depth=p.depth)

            def measure(self, result: dict) -> tuple[int, int]:
                returned = _token_len(json.dumps(result.get("confirmed", [])))
                equivalent = sum(f.get("file_tokens", 0) for f in result.get("confirmed", []))
                return returned, equivalent

    Attributes:
        name: MCP tool name (snake_case, unique).
        category: One of "search", "retrieval", "analysis", "indexing", "meta".
        description: Agent-facing description shown in ``list_tools``.
    """

    name: ClassVar[str] = ""
    category: ClassVar[str] = "meta"
    description: ClassVar[str] = ""

    class Params(ToolParams):
        pass

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if cls.name:
            _registry[cls.name] = cls

    def to_mcp_tool(self) -> MCPTool:
        """Generate the MCP Tool definition from class metadata."""
        return MCPTool(
            name=self.name,
            description=self.description,
            inputSchema=self.Params.to_schema(),
        )

    async def execute(self, arguments: dict) -> dict:
        """Framework entry point - validates params, calls handle(), wraps response.

        Individual tools override ``handle()`` and optionally ``measure()``,
        never this method.
        """
        from sylvan.tools.base.meta import ToolMeta, _current_meta, get_meta, reset_meta, set_meta

        owns_meta = _current_meta.get() is None
        meta_token = set_meta(ToolMeta()) if owns_meta else None

        try:
            params = self.Params.from_dict(arguments)

            t0 = time.monotonic()
            result = await self.handle(params)
            elapsed = (time.monotonic() - t0) * 1000

            if isinstance(result, dict):
                tool_meta = get_meta()
                if not tool_meta._repo:
                    tool_meta.repo(getattr(params, "repo", None))

                returned, equivalent = self.measure(result)
                if returned > 0 or equivalent > 0:
                    tool_meta.token_efficiency(returned, equivalent, self.measure_method())

                built = tool_meta.build()
                built["timing_ms"] = round(elapsed, 1)

                existing = result.get("_meta", {})
                existing.update({k: v for k, v in built.items() if k not in existing or existing[k] is None})
                existing["timing_ms"] = built["timing_ms"]
                result["_meta"] = existing

                if "_version" not in result:
                    result["_version"] = "1.0"

                repo_name = existing.get("repo") or getattr(params, "repo", None)
                if repo_name and "_stale" not in result:
                    try:
                        from sylvan.tools.support.response import check_staleness

                        stale_msg = await check_staleness(repo_name)
                        if stale_msg:
                            result["_stale"] = stale_msg
                    except Exception:  # noqa: S110
                        pass

                try:
                    from sylvan.tools.support.discovery import get_engine

                    tags = self._build_discovery_tags(result)
                    await get_engine().enrich(result, self.name, tags=tags, repo=repo_name)
                except Exception:  # noqa: S110
                    pass
        finally:
            if meta_token is not None:
                reset_meta(meta_token)

        return result

    async def handle(self, p: Any) -> dict:
        """Tool implementation. Override this in subclasses.

        Args:
            p: Validated Params instance with typed fields.

        Returns:
            Tool response dict. No need to build ``_meta`` - the framework
            handles that. Just return your domain data.
        """
        raise NotImplementedError(f"{type(self).__name__} must implement handle()")

    def measure(self, result: dict) -> tuple[int, int]:
        """Measure token efficiency of the response.

        Override this to enable automatic ``token_efficiency`` in ``_meta``.
        Return ``(tokens_returned, tokens_equivalent)`` where:

        - ``tokens_returned``: tokens the agent will actually consume from
          this response.
        - ``tokens_equivalent``: tokens the agent would have consumed by
          reading the raw files instead (e.g., via Read tool).

        The base returns ``(0, 0)`` which means no tracking. Tools that
        return retrievable data (source code, outlines, search results)
        should override this.

        Args:
            result: The dict returned by ``handle()``.

        Returns:
            Tuple of (returned, equivalent). Both zero to skip tracking.
        """
        return 0, 0

    def hints(self) -> HintBuilder:
        """Create a new HintBuilder for this tool response.

        Usage in handle()::

            hints = self.hints()
            hints.for_symbol(symbol_id, file_path, line_start, line_end)
            hints.apply(result)
            return result
        """
        from sylvan.tools.base.hints import HintBuilder

        return HintBuilder()

    def measure_method(self) -> str:
        """Token estimation method for the ``_meta`` envelope.

        Override to change the method. Use ``MeasureMethod`` constants.
        Default is ``MeasureMethod.BYTE_ESTIMATE``.
        """
        return MeasureMethod.BYTE_ESTIMATE

    def _build_discovery_tags(self, result: dict) -> list[str]:
        """Derive discovery tags from the tool response."""
        tags: list[str] = []
        symbols = result.get("symbols")
        if isinstance(symbols, list) and len(symbols) == 0:
            tags.append("result_empty")
        if isinstance(symbols, list):
            for sym in symbols:
                if isinstance(sym, dict) and sym.get("kind") == "class":
                    tags.append("result_has_class")
                    break
        complexity = result.get("complexity")
        if isinstance(complexity, (int, float)) and complexity >= 8:
            tags.append("high_complexity")
            tags.append(f"complexity:{complexity}")
        if result.get("has_tests") is False:
            tags.append("untested")
        line_count = result.get("line_count")
        if isinstance(line_count, (int, float)) and line_count >= 60:
            tags.append("long_symbol")
        total = result.get("total")
        if isinstance(total, (int, float)) and total >= 10 and "importers" in result:
            tags.append("many_importers")
        return tags


def get_registry() -> dict[str, type[Tool]]:
    """Return the global tool registry (name -> class)."""
    return dict(_registry)


def get_tool(name: str) -> Tool | None:
    """Instantiate a registered tool by name."""
    cls = _registry.get(name)
    if cls is None:
        return None
    return cls()


def get_all_tools() -> list[Tool]:
    """Instantiate all registered tools."""
    return [cls() for cls in _registry.values()]
