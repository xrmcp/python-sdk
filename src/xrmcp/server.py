from __future__ import annotations

import json
import os
from typing import Any

import mcp.types as types
from jsonschema import ValidationError
from mcp.server.lowlevel import NotificationOptions, Server

from xrmcp.registry import ToolRegistry
from xrmcp.runner import ToolRunner, ToolRunnerError
from xrmcp.schema_validation import SchemaValidator
from xrmcp.secrets import SecretStore


class XRMCPRuntime:
    def __init__(
        self,
        *,
        name: str = "xrMCP Runtime",
        version: str = "0.1.0",
        validator: SchemaValidator | None = None,
        registry: ToolRegistry | None = None,
        registry_store_path: str | os.PathLike[str] | None = None,
        runner: ToolRunner | None = None,
        secret_store: SecretStore | None = None,
    ) -> None:
        self.validator = validator or SchemaValidator()
        self.registry = registry or ToolRegistry(store_path=registry_store_path)
        self.runner = runner or ToolRunner(secret_store=secret_store)
        self.server: Server[Any, Any] = Server(name, version=version)
        self.notification_options = NotificationOptions(tools_changed=False)
        self._register_handlers()

    def create_initialization_options(self):
        return self.server.create_initialization_options(self.notification_options, experimental_capabilities={})

    async def aclose(self) -> None:
        await self.runner.aclose()

    def register_tool(self, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        result = self.validator.validate_registration(payload)
        name = payload.get("tool", {}).get("name", "unknown")
        if not result.valid:
            return 422, {
                "name": name,
                "status": "rejected",
                "errors": result.errors,
            }

        assert result.normalized is not None
        status = self.registry.upsert(result.normalized)
        return 200, {
            "name": result.normalized["tool"]["name"],
            "status": status,
            "errors": [],
        }

    def unregister_tool(self, name: str) -> tuple[int, dict[str, Any] | None]:
        if self.registry.delete(name):
            return 204, None
        return 404, {"name": name, "status": "not_found"}

    async def list_mcp_tools(self) -> list[types.Tool]:
        tools: list[types.Tool] = []
        for registered in self.registry.list():
            manifest = registered.manifest
            tools.append(
                types.Tool(
                    name=manifest["name"],
                    description=manifest["description"],
                    inputSchema=manifest["inputSchema"],
                    outputSchema=manifest.get("outputSchema"),
                )
            )
        return tools

    async def invoke_tool(self, name: str, arguments: dict[str, Any] | None) -> dict[str, Any] | types.CallToolResult:
        registered = self.registry.get(name)
        if registered is None:
            return self._error_result(f"Unknown tool: {name}")

        manifest = registered.manifest
        arguments = arguments or {}

        try:
            self.validator.validate_tool_arguments(manifest, arguments)
            result = await self.runner.run(
                manifest=registered.manifest,
                config=registered.config,
                arguments=arguments,
            )
        except ValidationError as exc:
            return self._error_result(f"Input validation error: {exc.message}")
        except ToolRunnerError as exc:
            return self._error_result(str(exc))

        if isinstance(result, dict):
            return result
        return {
            "result": result,
        }

    def _register_handlers(self) -> None:
        @self.server.list_tools()
        async def list_tools() -> list[types.Tool]:
            return await self.list_mcp_tools()

        @self.server.call_tool(validate_input=False)
        async def call_tool(name: str, arguments: dict[str, Any] | None) -> dict[str, Any] | types.CallToolResult:
            return await self.invoke_tool(name, arguments)

    def _error_result(self, message: str) -> types.CallToolResult:
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=message)],
            isError=True,
        )

    def dump_installed_tools(self) -> list[dict[str, Any]]:
        installed: list[dict[str, Any]] = []
        for registered in self.registry.list():
            manifest = registered.manifest
            installed.append(
                {
                    "name": manifest["name"],
                    "type": manifest["type"],
                    "description": manifest.get("description"),
                    "registeredAt": registered.registered_at,
                    "metadata": manifest.get("metadata", {}),
                }
            )
        return installed

    def format_structured_result(self, data: dict[str, Any]) -> str:
        return json.dumps(data, indent=2)
