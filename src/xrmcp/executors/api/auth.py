from __future__ import annotations

import base64
from typing import Any

import httpx


def _attrs_to_dict(attrs: list[dict[str, Any]]) -> dict[str, Any]:
    """Convert a list of AuthAttribute objects into a plain key→value dict."""
    return {a["key"]: a.get("value") for a in attrs}


def apply_auth(request: httpx.Request, auth_spec: dict | None) -> httpx.Request:
    """Apply the Auth spec from #/$defs/Auth to an httpx.Request.

    Returns a new httpx.Request with authentication applied, or the original
    request unchanged when auth is absent or noauth.  The original request is
    never mutated.
    """
    if auth_spec is None:
        return request

    auth_type: str = auth_spec.get("type", "noauth")

    if auth_type == "noauth":
        return request

    raw_attrs: list[dict[str, Any]] = auth_spec.get(auth_type) or []
    attrs = _attrs_to_dict(raw_attrs)

    if auth_type == "bearer":
        token = attrs.get("token", "")
        return _with_header(request, "Authorization", f"Bearer {token}")

    if auth_type == "basic":
        username = attrs.get("username", "")
        password = attrs.get("password", "")
        encoded = base64.b64encode(f"{username}:{password}".encode()).decode()
        return _with_header(request, "Authorization", f"Basic {encoded}")

    if auth_type == "apikey":
        key_name = attrs.get("key", "")
        key_value = attrs.get("value", "")
        location = attrs.get("in", "header")
        if location == "query":
            # Rebuild the request with the extra query param appended to the URL
            url = request.url.copy_with(
                params={**dict(request.url.params), key_name: key_value}
            )
            return httpx.Request(
                method=request.method,
                url=url,
                headers=request.headers,
                content=request.content,
            )
        # Default: add as header
        return _with_header(request, key_name, key_value)

    # digest is handled at the client level via get_auth_handler — nothing to add to headers
    return request


def get_auth_handler(auth_spec: dict | None) -> httpx.Auth | None:
    """Return an httpx.Auth handler for auth types that require a client-level flow.

    Currently only digest is handled here.  Returns None for all other types
    (which are already applied as headers by apply_auth).
    """
    if not auth_spec:
        return None
    auth_type: str = auth_spec.get("type", "noauth")
    if auth_type == "digest":
        attrs = _attrs_to_dict(auth_spec.get("digest") or [])
        username = attrs.get("username", "")
        password = attrs.get("password", "")
        return httpx.DigestAuth(username, password)
    return None


def _with_header(request: httpx.Request, name: str, value: str) -> httpx.Request:
    """Return a new httpx.Request with an additional (or replaced) header."""
    merged = dict(request.headers)
    merged[name] = value
    return httpx.Request(
        method=request.method,
        url=request.url,
        headers=merged,
        content=request.content,
    )
