from __future__ import annotations

import contextlib
import os

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from xrmcp.server import XRMCPRuntime


class MCPStreamableHTTPApp:
    def __init__(self, session_manager: StreamableHTTPSessionManager) -> None:
        self.session_manager = session_manager

    async def __call__(self, scope, receive, send) -> None:
        await self.session_manager.handle_request(scope, receive, send)


def create_app(runtime: XRMCPRuntime | None = None) -> Starlette:
    runtime = runtime or XRMCPRuntime(registry_store_path=os.getenv("XRMCP_STORE_PATH"))
    session_manager = StreamableHTTPSessionManager(
        runtime.server,
        json_response=True,
        stateless=True,
    )

    @contextlib.asynccontextmanager
    async def lifespan(_: Starlette):
        async with session_manager.run():
            try:
                yield
            finally:
                await runtime.aclose()

    async def register_tool(request: Request) -> Response:
        payload = await request.json()
        status_code, body = runtime.register_tool(payload)
        return JSONResponse(body, status_code=status_code)

    async def list_installed(_: Request) -> Response:
        return JSONResponse({"tools": runtime.dump_installed_tools()})

    async def unregister_tool(request: Request) -> Response:
        name = request.path_params["name"]
        status_code, body = runtime.unregister_tool(name)
        if body is None:
            return Response(status_code=status_code)
        return JSONResponse(body, status_code=status_code)

    return Starlette(
        routes=[
            Route("/tools/register", endpoint=register_tool, methods=["POST"]),
            Route("/tools/list-installed", endpoint=list_installed, methods=["GET"]),
            Route("/tools/{name}", endpoint=unregister_tool, methods=["DELETE"]),
            Mount("/mcp", app=MCPStreamableHTTPApp(session_manager)),
        ],
        lifespan=lifespan,
    )
