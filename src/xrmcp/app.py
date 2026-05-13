from __future__ import annotations

import contextlib
import logging
import os

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from xrmcp.server import XRMCPRuntime

logger = logging.getLogger(__name__)


def load_api_auth_config_from_env() -> tuple[str, str]:
    mode = os.getenv("XRMCP_API_AUTH_MODE", "").strip().lower() or "none"
    token = os.getenv("XRMCP_API_TOKEN", "")

    if mode not in {"none", "bearer"}:
        raise RuntimeError(f'unsupported XRMCP_API_AUTH_MODE "{mode}"')
    if mode == "bearer" and not token.strip():
        raise RuntimeError("XRMCP_API_TOKEN is required when XRMCP_API_AUTH_MODE=bearer")
    if mode == "none" and not os.getenv("XRMCP_API_AUTH_MODE") and not os.getenv("XRMCP_API_TOKEN"):
        logger.warning(
            "xrMCP REST management API is running in development mode with no auth. "
            "To enable auth set XRMCP_API_AUTH_MODE=bearer and XRMCP_API_TOKEN=<token>"
        )
    return mode, token


class MCPStreamableHTTPApp:
    def __init__(self, session_manager: StreamableHTTPSessionManager) -> None:
        self.session_manager = session_manager

    async def __call__(self, scope, receive, send) -> None:
        await self.session_manager.handle_request(scope, receive, send)


def create_app(runtime: XRMCPRuntime | None = None) -> Starlette:
    auth_mode, auth_token = load_api_auth_config_from_env()
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

    def require_admin_auth(request: Request) -> Response | None:
        if auth_mode != "bearer":
            return None

        header = request.headers.get("authorization", "").strip()
        prefix = "Bearer "
        if not header.startswith(prefix):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if header.removeprefix(prefix).strip() != auth_token:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return None

    async def register_tool(request: Request) -> Response:
        unauthorized = require_admin_auth(request)
        if unauthorized is not None:
            return unauthorized
        payload = await request.json()
        status_code, body = runtime.register_tool(payload)
        return JSONResponse(body, status_code=status_code)

    async def list_installed(request: Request) -> Response:
        unauthorized = require_admin_auth(request)
        if unauthorized is not None:
            return unauthorized
        return JSONResponse({"tools": runtime.dump_installed_tools()})

    async def unregister_tool(request: Request) -> Response:
        unauthorized = require_admin_auth(request)
        if unauthorized is not None:
            return unauthorized
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
