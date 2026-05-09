from __future__ import annotations

import base64
import json

import httpx
import pytest

from xrmcp.executors.api import ApiExecutor, ApiExecutorError
from xrmcp.executors.api.auth import apply_auth, get_auth_handler
from xrmcp.executors.api.request_builder import RequestBuilder


# ---------------------------------------------------------------------------
# RequestBuilder — URL, headers, body
# ---------------------------------------------------------------------------


class TestRequestBuilder:
    def setup_method(self):
        self.builder = RequestBuilder()
        self.ctx = {"input": {"ticketKey": "PROJ-1"}, "config": {"baseUrl": "https://api.example.com"}}

    def test_url_string(self):
        req = self.builder.build({"url": "https://api.example.com/foo"}, self.ctx)
        assert str(req.url) == "https://api.example.com/foo"

    def test_url_object_uses_raw(self):
        req = self.builder.build({"url": {"raw": "{{config.baseUrl}}/issues/{{ticketKey}}"}}, self.ctx)
        assert str(req.url) == "https://api.example.com/issues/PROJ-1"

    def test_method_default_get(self):
        req = self.builder.build({"url": "https://api.example.com/"}, self.ctx)
        assert req.method == "GET"

    def test_method_post(self):
        req = self.builder.build({"method": "POST", "url": "https://api.example.com/"}, self.ctx)
        assert req.method == "POST"

    def test_headers_list(self):
        spec = {
            "url": "https://api.example.com/",
            "header": [
                {"key": "X-Ticket", "value": "{{ticketKey}}"},
                {"key": "Accept", "value": "application/json"},
            ],
        }
        req = self.builder.build(spec, self.ctx)
        assert req.headers["X-Ticket"] == "PROJ-1"
        assert req.headers["Accept"] == "application/json"

    def test_headers_string(self):
        spec = {
            "url": "https://api.example.com/",
            "header": "Content-Type: application/json\nX-Custom: hello",
        }
        req = self.builder.build(spec, self.ctx)
        assert req.headers["Content-Type"] == "application/json"
        assert req.headers["X-Custom"] == "hello"

    def test_body_raw(self):
        spec = {
            "url": "https://api.example.com/",
            "method": "POST",
            "body": {"mode": "raw", "raw": '{"key":"{{ticketKey}}"}'},
        }
        req = self.builder.build(spec, self.ctx)
        assert req.content == b'{"key":"PROJ-1"}'

    def test_body_urlencoded(self):
        spec = {
            "url": "https://api.example.com/",
            "method": "POST",
            "body": {
                "mode": "urlencoded",
                "urlencoded": [{"key": "ticket", "value": "{{ticketKey}}"}],
            },
        }
        req = self.builder.build(spec, self.ctx)
        assert b"ticket=PROJ-1" in req.content

    def test_body_graphql(self):
        gql = {"query": "{ viewer { login } }"}
        spec = {
            "url": "https://api.example.com/graphql",
            "method": "POST",
            "body": {"mode": "graphql", "graphql": gql},
        }
        req = self.builder.build(spec, self.ctx)
        assert json.loads(req.content) == gql

    def test_body_absent(self):
        req = self.builder.build({"url": "https://api.example.com/"}, self.ctx)
        assert req.content == b""


# ---------------------------------------------------------------------------
# apply_auth
# ---------------------------------------------------------------------------


class TestApplyAuth:
    def _base_request(self):
        return httpx.Request("GET", "https://api.example.com/")

    def test_none_unchanged(self):
        req = self._base_request()
        result = apply_auth(req, None)
        assert result is req

    def test_noauth_unchanged(self):
        req = self._base_request()
        result = apply_auth(req, {"type": "noauth"})
        assert result is req

    def test_bearer(self):
        req = self._base_request()
        result = apply_auth(req, {
            "type": "bearer",
            "bearer": [{"key": "token", "value": "my-token"}],
        })
        assert result.headers["Authorization"] == "Bearer my-token"

    def test_basic(self):
        req = self._base_request()
        result = apply_auth(req, {
            "type": "basic",
            "basic": [
                {"key": "username", "value": "user"},
                {"key": "password", "value": "pass"},
            ],
        })
        expected = "Basic " + base64.b64encode(b"user:pass").decode()
        assert result.headers["Authorization"] == expected

    def test_apikey_header(self):
        req = self._base_request()
        result = apply_auth(req, {
            "type": "apikey",
            "apikey": [
                {"key": "in", "value": "header"},
                {"key": "key", "value": "X-API-Key"},
                {"key": "value", "value": "secret"},
            ],
        })
        assert result.headers["X-API-Key"] == "secret"

    def test_apikey_query(self):
        req = self._base_request()
        result = apply_auth(req, {
            "type": "apikey",
            "apikey": [
                {"key": "in", "value": "query"},
                {"key": "key", "value": "api_key"},
                {"key": "value", "value": "secret"},
            ],
        })
        assert "api_key=secret" in str(result.url)

    def test_does_not_mutate_original(self):
        req = self._base_request()
        apply_auth(req, {
            "type": "bearer",
            "bearer": [{"key": "token", "value": "tok"}],
        })
        assert "Authorization" not in req.headers

    def test_digest_returns_handler(self):
        handler = get_auth_handler({
            "type": "digest",
            "digest": [
                {"key": "username", "value": "user"},
                {"key": "password", "value": "pass"},
            ],
        })
        assert isinstance(handler, httpx.DigestAuth)

    def test_non_digest_returns_none_handler(self):
        assert get_auth_handler({"type": "bearer", "bearer": [{"key": "token", "value": "t"}]}) is None
        assert get_auth_handler(None) is None


# ---------------------------------------------------------------------------
# ApiExecutor — happy path and error handling
# ---------------------------------------------------------------------------


def _make_transport(json_body: dict | None = None, status: int = 200, text: str = ""):
    """Build an httpx MockTransport that returns a fixed response."""

    def handler(request):
        if json_body is not None:
            content = json.dumps(json_body).encode()
            headers = {"content-type": "application/json"}
        else:
            content = text.encode()
            headers = {"content-type": "text/plain"}
        return httpx.Response(status, content=content, headers=headers)

    return httpx.MockTransport(handler)


@pytest.mark.anyio
async def test_execute_returns_json():
    transport = _make_transport(json_body={"id": 42})
    client = httpx.AsyncClient(transport=transport)
    executor = ApiExecutor(http_client=client)

    execution = {"type": "api", "request": {"method": "GET", "url": "https://api.example.com/posts/1"}}
    result = await executor.execute(execution, {"input": {}, "config": {}})
    assert result == {"id": 42}


@pytest.mark.anyio
async def test_execute_returns_text():
    transport = _make_transport(text="hello world")
    client = httpx.AsyncClient(transport=transport)
    executor = ApiExecutor(http_client=client)

    execution = {"type": "api", "request": {"url": "https://api.example.com/ping"}}
    result = await executor.execute(execution, {"input": {}, "config": {}})
    assert result == "hello world"


@pytest.mark.anyio
async def test_execute_raises_on_http_error():
    def handler(request):
        return httpx.Response(404, content=b"not found", headers={"content-type": "text/plain"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    executor = ApiExecutor(http_client=client)

    execution = {"type": "api", "request": {"url": "https://api.example.com/missing"}}
    with pytest.raises(ApiExecutorError, match="404"):
        await executor.execute(execution, {"input": {}, "config": {}})


@pytest.mark.anyio
async def test_network_permission_blocks_disallowed_host():
    transport = _make_transport(json_body={})
    client = httpx.AsyncClient(transport=transport)
    executor = ApiExecutor(
        http_client=client,
        permissions={"network": ["allowed.example.com"]},
    )

    execution = {"type": "api", "request": {"url": "https://blocked.other.com/data"}}
    with pytest.raises(ApiExecutorError, match="allowlist"):
        await executor.execute(execution, {"input": {}, "config": {}})


@pytest.mark.anyio
async def test_network_permission_allows_listed_host():
    transport = _make_transport(json_body={"ok": True})
    client = httpx.AsyncClient(transport=transport)
    executor = ApiExecutor(
        http_client=client,
        permissions={"network": ["api.example.com"]},
    )

    execution = {"type": "api", "request": {"url": "https://api.example.com/data"}}
    result = await executor.execute(execution, {"input": {}, "config": {}})
    assert result == {"ok": True}
