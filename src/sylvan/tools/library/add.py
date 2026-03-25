"""MCP tool: add_library -- index a third-party library's source code."""

from sylvan.tools.support.response import MetaBuilder, log_tool_call, wrap_response


@log_tool_call
async def add_library(package: str) -> dict:
    """Index a third-party library's source code for precise API lookup.

    Fetches the real source at a specific version -- more reliable than
    docs.  The agent can then search the library's actual implementation.

    Args:
        package: Package spec like ``"pip/django@4.2"``, ``"npm/react"``,
            or ``"go/github.com/gin-gonic/gin@v1.9.1"``.

    Returns:
        Tool response dict with library status and ``_meta`` envelope.
    """
    meta = MetaBuilder()

    try:
        from sylvan.libraries.manager import async_add_library

        result = await async_add_library(package)
        meta.set("status", result.get("status", ""))
        return wrap_response(result, meta.build())
    except ValueError as e:
        return wrap_response({"error": str(e)}, meta.build())
    except Exception as e:
        return wrap_response({"error": f"Failed to add library: {e}"}, meta.build())
