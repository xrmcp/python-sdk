from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from xrmcp.executors.api.auth import apply_auth, get_auth_handler
from xrmcp.executors.api.request_builder import RequestBuilder
from xrmcp.templates import render_template


class ApiExecutorError(RuntimeError):
    pass


class ApiExecutor:
    """Executes a single ApiExecution manifest entry.

    Parameters
    ----------
    http_client:
        Optional pre-built AsyncClient. When not provided the executor creates
        and owns its own client (closed via ``aclose``).
    permissions:
        The ``ToolManifest.permissions`` object (schema: ``#/$defs/Permissions``).
        Passed at construction time because it belongs to the manifest, not to
        an individual execution.  Pass ``None`` to allow all outbound hosts.
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        permissions: dict | None = None,
    ) -> None:
        self._owned_client = http_client is None
        self._http_client = http_client or httpx.AsyncClient()
        self._permissions = permissions
        self._builder = RequestBuilder()

    async def aclose(self) -> None:
        if self._owned_client:
            await self._http_client.aclose()

    async def execute(self, execution: dict, context: dict) -> Any:
        """Execute a single ApiExecution dict and return the raw response payload.

        Parameters
        ----------
        execution:
            A single entry from ``ToolManifest.executions`` (type == "api").
        context:
            ``{"input": {...}, "config": {...}}`` assembled by the caller.
        """
        request_spec = execution.get("request", {})
        request = self._builder.build(request_spec, context)

        auth_spec = render_template(request_spec.get("auth"), context)
        request = apply_auth(request, auth_spec)
        auth_handler = get_auth_handler(auth_spec)

        self._check_network_permission(request)

        try:
            response = await self._http_client.send(request, auth=auth_handler)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ApiExecutorError(
                f"HTTP {exc.response.status_code} from {request.url}"
            ) from exc
        except httpx.RequestError as exc:
            raise ApiExecutorError(f"Network error: {exc}") from exc

        content_type = response.headers.get("content-type", "")
        if "application/json" in content_type:
            return response.json()
        return response.text

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_network_permission(self, request: httpx.Request) -> None:
        """Raise ApiExecutorError if the target host is not in the allowlist.

        An empty or absent ``network`` list means all hosts are permitted.
        """
        if self._permissions is None:
            return
        allowlist: list[str] = self._permissions.get("network") or []
        if not allowlist:
            return

        host = request.url.host
        port = request.url.port
        host_with_port = f"{host}:{port}" if port else host

        for entry in allowlist:
            if self._host_matches(host, host_with_port, entry):
                return

        raise ApiExecutorError(
            f"Network destination '{host_with_port}' is not in the permissions allowlist"
        )

    @staticmethod
    def _host_matches(host: str, host_with_port: str, entry: str) -> bool:
        """Match a host against a NetworkPermission entry (hostname, host:port, or pattern)."""
        if entry == host or entry == host_with_port:
            return True
        # Simple wildcard prefix: *.example.com
        if entry.startswith("*."):
            suffix = entry[1:]  # ".example.com"
            return host.endswith(suffix) or host_with_port.endswith(suffix)
        return False
