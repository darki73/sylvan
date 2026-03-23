"""MCP transport runners -- stdio, SSE, and streamable HTTP."""

import anyio

from sylvan.logging import get_logger

logger = get_logger(__name__)


async def run_stdio(server: object) -> None:
    """Run the MCP server over stdio.

    Args:
        server: The MCP ``Server`` instance to run.
    """
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


async def run_sse(server: object, host: str = "127.0.0.1", port: int = 8420) -> None:
    """Run the MCP server over HTTP + Server-Sent Events.

    Clients connect via ``GET /sse`` then POST messages to ``/messages/``.

    Args:
        server: The MCP ``Server`` instance to run.
        host: Network interface to bind to.
        port: TCP port to listen on.
    """
    import uvicorn
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.responses import Response
    from starlette.routing import Mount, Route

    sse = SseServerTransport("/messages/")

    async def handle_sse(request: object) -> Response:
        """Handle an incoming SSE connection request.

        Args:
            request: The Starlette request object.

        Returns:
            An empty HTTP response after the SSE session ends.
        """
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await server.run(streams[0], streams[1], server.create_initialization_options())
        return Response()

    app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse, methods=["GET"]),
            Mount("/messages/", app=sse.handle_post_message),
        ],
    )

    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    uv_server = uvicorn.Server(config)
    logger.info("sse_server_starting", host=host, port=port, url=f"http://{host}:{port}/sse")
    await uv_server.serve()


async def run_streamable_http(server: object, host: str = "127.0.0.1", port: int = 8420) -> None:
    """Run the MCP server over streamable HTTP.

    Clients POST JSON-RPC messages to ``/mcp`` and receive SSE-streamed
    responses.

    Args:
        server: The MCP ``Server`` instance to run.
        host: Network interface to bind to.
        port: TCP port to listen on.
    """
    from uuid import uuid4

    import uvicorn
    from mcp.server.streamable_http import StreamableHTTPServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Mount

    session_id = uuid4().hex
    transport = StreamableHTTPServerTransport(mcp_session_id=session_id)

    async def handle_mcp(scope: dict, receive: object, send: object) -> None:
        """Forward an ASGI request to the streamable-HTTP transport.

        Args:
            scope: ASGI connection scope.
            receive: ASGI receive callable.
            send: ASGI send callable.
        """
        await transport.handle_request(scope, receive, send)

    app = Starlette(routes=[Mount("/mcp", app=handle_mcp)])

    async def serve_with_transport() -> None:
        """Start uvicorn and the MCP session concurrently.
        """
        config = uvicorn.Config(app, host=host, port=port, log_level="info")
        uv_server = uvicorn.Server(config)

        async with transport.connect() as (read_stream, write_stream), anyio.create_task_group() as tg:
            async def run_mcp() -> None:
                """Run the MCP server on the transport streams.
                    """
                await server.run(
                    read_stream, write_stream, server.create_initialization_options(),
                )

            logger.info(
                "http_server_starting", host=host, port=port,
                url=f"http://{host}:{port}/mcp",
            )
            tg.start_soon(run_mcp)
            await uv_server.serve()
            tg.cancel_scope.cancel()

    await serve_with_transport()
