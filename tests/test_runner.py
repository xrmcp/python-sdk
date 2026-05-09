from __future__ import annotations

import json

import httpx
import pytest

from xrmcp.runner import ToolRunner, ToolRunnerError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_transport(*responses: dict | str, status: int = 200):
    """Return a MockTransport that cycles through the given responses in order."""
    queue = list(responses)
    idx = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        item = queue[idx[0] % len(queue)]
        idx[0] += 1
        if isinstance(item, (dict, list)):
            return httpx.Response(
                status,
                content=json.dumps(item).encode(),
                headers={"content-type": "application/json"},
            )
        return httpx.Response(
            status,
            content=str(item).encode(),
            headers={"content-type": "text/plain"},
        )

    return httpx.MockTransport(handler)


def _runner(*responses: dict | str, status: int = 200) -> ToolRunner:
    transport = _make_transport(*responses, status=status)
    client = httpx.AsyncClient(transport=transport)
    return ToolRunner(http_client=client)


_BASE_EXECUTION = {
    "type": "api",
    "request": {"method": "GET", "url": "https://api.example.com/items"},
}

_BASE_MANIFEST = {
    "executions": [_BASE_EXECUTION],
}


# ---------------------------------------------------------------------------
# Single execution — no processor, no outputMapper
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_single_execution_returns_raw_response():
    runner = _runner({"id": 1, "name": "Alice"})
    result = await runner.run(_BASE_MANIFEST, config={}, arguments={})
    assert result == {"id": 1, "name": "Alice"}
    await runner.aclose()


@pytest.mark.anyio
async def test_single_execution_list_normalised():
    """A list response is normalised to {"result": [...]} by the processor."""
    runner = _runner([{"id": 1}, {"id": 2}])
    result = await runner.run(_BASE_MANIFEST, config={}, arguments={})
    assert result == {"result": [{"id": 1}, {"id": 2}]}
    await runner.aclose()


# ---------------------------------------------------------------------------
# Single execution — with processor
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_single_execution_with_select_filter():
    manifest = {
        "executions": [
            {
                **_BASE_EXECUTION,
                "processor": {
                    "filter": {"mode": "select", "fields": ["id", "name"]},
                },
            }
        ]
    }
    runner = _runner({"id": 1, "name": "Alice", "secret": "x"})
    result = await runner.run(manifest, config={}, arguments={})
    assert result == {"id": 1, "name": "Alice"}
    await runner.aclose()


@pytest.mark.anyio
async def test_single_execution_with_none_filter():
    manifest = {
        "executions": [
            {
                **_BASE_EXECUTION,
                "processor": {"filter": {"mode": "none"}},
            }
        ]
    }
    runner = _runner({"id": 1})
    result = await runner.run(manifest, config={}, arguments={})
    assert result == {}
    await runner.aclose()


# ---------------------------------------------------------------------------
# Multi-execution — outputMapper mode=merge
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_multi_execution_merge():
    manifest = {
        "executions": [
            {"type": "api", "id": "first", "request": {"method": "GET", "url": "https://api.example.com/a"}},
            {"type": "api", "id": "second", "request": {"method": "GET", "url": "https://api.example.com/b"}},
        ],
        "outputMapper": {"mode": "merge"},
    }
    runner = _runner({"x": 1}, {"y": 2})
    result = await runner.run(manifest, config={}, arguments={})
    assert result == {"x": 1, "y": 2}
    await runner.aclose()


@pytest.mark.anyio
async def test_multi_execution_last_is_default():
    """Default outputMapper mode is 'last' — returns the last execution's result."""
    manifest = {
        "executions": [
            {"type": "api", "id": "first", "request": {"method": "GET", "url": "https://api.example.com/a"}},
            {"type": "api", "id": "second", "request": {"method": "GET", "url": "https://api.example.com/b"}},
        ],
    }
    runner = _runner({"x": 1}, {"y": 2})
    result = await runner.run(manifest, config={}, arguments={})
    assert result == {"y": 2}
    await runner.aclose()


@pytest.mark.anyio
async def test_execution_order_respected():
    """Executions are run in ascending order value, not list position."""
    manifest = {
        "executions": [
            {"type": "api", "order": 2, "id": "second", "request": {"method": "GET", "url": "https://api.example.com/b"}},
            {"type": "api", "order": 1, "id": "first", "request": {"method": "GET", "url": "https://api.example.com/a"}},
        ],
        "outputMapper": {"mode": "last"},
    }
    # Transport returns {"first": true} then {"second": true} in call order.
    runner = _runner({"first": True}, {"second": True})
    result = await runner.run(manifest, config={}, arguments={})
    # Sorted order: order=1 (id=first) then order=2 (id=second).
    # "last" returns the result stored under "second" id.
    assert result == {"second": True}
    await runner.aclose()


# ---------------------------------------------------------------------------
# Unknown execution type → ToolRunnerError
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_unknown_execution_type_raises():
    manifest = {
        "executions": [
            {"type": "grpc", "request": {}},
        ]
    }
    runner = _runner({})
    with pytest.raises(ToolRunnerError, match="Unsupported execution type: 'grpc'"):
        await runner.run(manifest, config={}, arguments={})
    await runner.aclose()


# ---------------------------------------------------------------------------
# outputSchema validation → ToolRunnerError
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_output_schema_violation_raises():
    manifest = {
        "executions": [_BASE_EXECUTION],
        "outputSchema": {
            "type": "object",
            "required": ["id"],
            "properties": {"id": {"type": "integer"}},
        },
    }
    runner = _runner({"name": "no id here"})
    with pytest.raises(ToolRunnerError, match="Output validation error"):
        await runner.run(manifest, config={}, arguments={})
    await runner.aclose()


@pytest.mark.anyio
async def test_output_schema_valid_passes():
    manifest = {
        "executions": [_BASE_EXECUTION],
        "outputSchema": {
            "type": "object",
            "required": ["id"],
            "properties": {"id": {"type": "integer"}},
        },
    }
    runner = _runner({"id": 99})
    result = await runner.run(manifest, config={}, arguments={})
    assert result == {"id": 99}
    await runner.aclose()


# ---------------------------------------------------------------------------
# Positional IDs (no explicit id)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_positional_ids_used_when_no_id():
    manifest = {
        "executions": [
            {"type": "api", "request": {"method": "GET", "url": "https://api.example.com/a"}},
            {"type": "api", "request": {"method": "GET", "url": "https://api.example.com/b"}},
        ],
        "outputMapper": {
            "mode": "map",
            "mapping": {
                "a_val": {"from": "_0", "path": "$.value"},
                "b_val": {"from": "_1", "path": "$.value"},
            },
        },
    }
    runner = _runner({"value": 10}, {"value": 20})
    result = await runner.run(manifest, config={}, arguments={})
    assert result == {"a_val": 10, "b_val": 20}
    await runner.aclose()


# ---------------------------------------------------------------------------
# Execution chaining — {{results.*}} references
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_chained_executions_url_resolved_from_prior_result():
    """Execution 2 URL uses {{results.exec1.id}} resolved from exec1's response."""
    captured_urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_urls.append(str(request.url))
        if str(request.url).endswith("/items"):
            body = {"id": "msg-abc"}
        else:
            body = {"detail": "fetched"}
        return httpx.Response(
            200,
            content=__import__("json").dumps(body).encode(),
            headers={"content-type": "application/json"},
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    runner = ToolRunner(http_client=client)

    manifest = {
        "executions": [
            {
                "id": "exec1",
                "order": 1,
                "type": "api",
                "request": {"method": "GET", "url": "https://api.example.com/items"},
            },
            {
                "id": "exec2",
                "order": 2,
                "type": "api",
                "request": {"method": "GET", "url": "https://api.example.com/items/{{results.exec1.id}}"},
            },
        ],
        "outputMapper": {"mode": "last"},
    }

    result = await runner.run(manifest, config={}, arguments={})
    assert result == {"detail": "fetched"}
    assert captured_urls[1] == "https://api.example.com/items/msg-abc"
    await runner.aclose()


@pytest.mark.anyio
async def test_chained_executions_missing_key_raises():
    """Referencing a key absent from a prior result raises ToolRunnerError."""
    runner = _runner({"id": "msg-abc"}, {"detail": "fetched"})

    manifest = {
        "executions": [
            {
                "id": "exec1",
                "order": 1,
                "type": "api",
                "request": {"method": "GET", "url": "https://api.example.com/items"},
            },
            {
                "id": "exec2",
                "order": 2,
                "type": "api",
                "request": {"method": "GET", "url": "https://api.example.com/items/{{results.exec1.no_such_key}}"},
            },
        ],
    }

    with pytest.raises(ToolRunnerError):
        await runner.run(manifest, config={}, arguments={})
    await runner.aclose()
