from __future__ import annotations

import logging

import httpx
import pytest
from starlette.testclient import TestClient

from xrmcp.app import create_app
from xrmcp.registry import ToolRegistry
from xrmcp.runner import ToolRunner
from xrmcp.server import XRMCPRuntime


@pytest.fixture(autouse=True)
def isolate_registry_store(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("XRMCP_STORE_PATH", str(tmp_path / "tools.json"))


def build_registration() -> dict:
    return {
        "tool": {
            "schemaVersion": "xrmcp.v0.1.0",
            "name": "read_ticket",
            "description": "Read a ticket by key",
            "type": "api",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "ticketKey": {"type": "string"},
                },
                "required": ["ticketKey"],
            },
            "outputSchema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "status": {"type": "string"},
                },
                "required": ["title", "status"],
            },
            "configSchema": {
                "type": "object",
                "properties": {
                    "baseUrl": {"type": "string"},
                },
                "required": ["baseUrl"],
            },
            "executions": [
                {
                    "type": "api",
                    "request": {
                        "method": "GET",
                        "url": "https://jira.example.com/issues/{{input.ticketKey}}",
                    },
                    "processor": {
                        "mapper": {
                            "mode": "jsonpath",
                            "mapping": {
                                "title": "$.fields.summary",
                                "status": "$.fields.status.name",
                            },
                        },
                    },
                }
            ],
            "permissions": {
                "network": ["jira.example.com"],
            },
        },
        "config": {
            "baseUrl": "jira.example.com",
        },
    }


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_valid_registration_appears_in_tool_listing() -> None:
    runtime = XRMCPRuntime()
    status_code, body = runtime.register_tool(build_registration())

    assert status_code == 200
    assert body["status"] == "registered"

    tools = await runtime.list_mcp_tools()
    assert [tool.name for tool in tools] == ["read_ticket"]


def test_invalid_registration_is_rejected() -> None:
    runtime = XRMCPRuntime()
    payload = build_registration()
    del payload["tool"]["executions"]

    status_code, body = runtime.register_tool(payload)

    assert status_code == 422
    assert body["status"] == "rejected"
    assert body["errors"]


# ---------------------------------------------------------------------------
# Invocation
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_registered_tool_can_be_invoked_by_name() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "https://jira.example.com/issues/ABC-123"
        return httpx.Response(
            200,
            json={"fields": {"summary": "Broken build", "status": {"name": "Open"}}},
        )

    runtime = XRMCPRuntime(
        runner=ToolRunner(http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    )
    runtime.register_tool(build_registration())

    result = await runtime.invoke_tool("read_ticket", {"ticketKey": "ABC-123"})

    assert result == {"title": "Broken build", "status": "Open"}


@pytest.mark.anyio
async def test_input_schema_validation_failure_returns_tool_error() -> None:
    runtime = XRMCPRuntime()
    runtime.register_tool(build_registration())

    result = await runtime.invoke_tool("read_ticket", {})

    assert result.isError is True
    assert "Input validation error" in result.content[0].text


@pytest.mark.anyio
async def test_invoke_unknown_tool_returns_error() -> None:
    runtime = XRMCPRuntime()

    result = await runtime.invoke_tool("no_such_tool", {"ticketKey": "X"})

    assert result.isError is True
    assert "Unknown tool" in result.content[0].text


@pytest.mark.anyio
async def test_execution_error_propagates_as_tool_error() -> None:
    """Any ToolRunnerError (network failure, bad response, etc.) surfaces as isError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    runtime = XRMCPRuntime(
        runner=ToolRunner(http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    )
    runtime.register_tool(build_registration())

    result = await runtime.invoke_tool("read_ticket", {"ticketKey": "ABC-123"})

    assert result.isError is True


@pytest.mark.anyio
async def test_jsonpath_response_mapping() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"fields": {"summary": "Ticket title", "status": {"name": "Closed"}}},
        )

    runtime = XRMCPRuntime(
        runner=ToolRunner(http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    )
    runtime.register_tool(build_registration())

    result = await runtime.invoke_tool("read_ticket", {"ticketKey": "ABC-123"})

    assert result["title"] == "Ticket title"
    assert result["status"] == "Closed"


# ---------------------------------------------------------------------------
# HTTP endpoint
# ---------------------------------------------------------------------------


def test_register_endpoint() -> None:
    runtime = XRMCPRuntime()
    app = create_app(runtime)

    with TestClient(app) as client:
        response = client.post("/tools/register", json=build_registration())

    assert response.status_code == 200
    assert response.json()["name"] == "read_ticket"


# ---------------------------------------------------------------------------
# Registry persistence
# ---------------------------------------------------------------------------


def test_registry_persists_and_reloads_tools(tmp_path) -> None:
    store_path = tmp_path / "tools.json"
    registry = ToolRegistry(store_path=store_path)

    status = registry.upsert(build_registration())
    assert status == "registered"
    assert store_path.exists()

    reloaded_registry = ToolRegistry(store_path=store_path)
    reloaded_tool = reloaded_registry.get("read_ticket")

    assert reloaded_tool is not None
    assert reloaded_tool.manifest["name"] == "read_ticket"


def test_registry_missing_store_file_starts_empty(tmp_path) -> None:
    missing_store = tmp_path / "missing" / "tools.json"
    registry = ToolRegistry(store_path=missing_store)

    assert registry.list() == []


def test_registry_corrupt_store_file_starts_empty_and_warns(tmp_path, caplog) -> None:
    corrupt_store = tmp_path / "tools.json"
    corrupt_store.write_text("{not valid json", encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        registry = ToolRegistry(store_path=corrupt_store)

    assert registry.list() == []
    assert "Failed to load tool registry store" in caplog.text
