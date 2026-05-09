from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import httpx

from xrmcp.templates import render_template


class RequestBuilder:
    """Builds an httpx.Request from an xrMCP Request manifest and a context dict.

    The returned request is not yet sent — the caller is responsible for
    dispatching it via an AsyncClient.
    """

    def build(self, request_spec: dict[str, Any], context: dict[str, Any]) -> httpx.Request:
        method = (request_spec.get("method") or "GET").upper()
        url = self._resolve_url(request_spec.get("url"), context)
        headers = self._resolve_headers(request_spec.get("header"), context)
        kwargs: dict[str, Any] = {}
        self._apply_body(request_spec.get("body"), context, kwargs)

        # proxy and certificate are not implemented
        # TODO: apply ProxyConfig from request_spec.get("proxy")
        # TODO: apply Certificate from request_spec.get("certificate")

        return httpx.Request(method=method, url=url, headers=headers, **kwargs)

    # ------------------------------------------------------------------
    # URL
    # ------------------------------------------------------------------

    def _resolve_url(self, url_spec: Any, context: dict[str, Any]) -> str:
        if url_spec is None:
            return ""
        if isinstance(url_spec, str):
            return render_template(url_spec, context)
        # Url object — use the `raw` field as the canonical representation
        raw: str = url_spec.get("raw", "")
        return render_template(raw, context)

    # ------------------------------------------------------------------
    # Headers
    # ------------------------------------------------------------------

    def _resolve_headers(
        self, header_spec: Any, context: dict[str, Any]
    ) -> dict[str, str]:
        if not header_spec:
            return {}

        if isinstance(header_spec, str):
            # Parse "Key: Value\nKey2: Value2" lines
            result: dict[str, str] = {}
            for line in header_spec.splitlines():
                line = line.strip()
                if ":" in line:
                    key, _, value = line.partition(":")
                    result[key.strip()] = render_template(value.strip(), context)
            return result

        # HeaderList — array of {key, value} objects (schema: #/$defs/Header)
        return {
            h["key"]: render_template(h.get("value", ""), context)
            for h in header_spec
            if h.get("key")
        }

    # ------------------------------------------------------------------
    # Body
    # ------------------------------------------------------------------

    def _apply_body(
        self,
        body_spec: Any,
        context: dict[str, Any],
        kwargs: dict[str, Any],
    ) -> None:
        if not body_spec:
            return

        mode: str = body_spec.get("mode", "")

        if mode == "raw":
            raw_body = body_spec.get("raw", "")
            kwargs["content"] = render_template(raw_body, context)

        elif mode == "urlencoded":
            items = body_spec.get("urlencoded") or []
            kwargs["data"] = {
                item["key"]: render_template(item.get("value", ""), context)
                for item in items
                if item.get("key")
            }

        elif mode == "formdata":
            items = body_spec.get("formdata") or []
            data: dict[str, str] = {}
            files: dict[str, Any] = {}
            for item in items:
                key = item.get("key", "")
                if not key:
                    continue
                if item.get("type") == "file":
                    # src may be a path string, null, or array — left as a stub
                    # TODO: open file from item["src"] and add to files dict
                    pass
                else:
                    data[key] = render_template(item.get("value", ""), context)
            if data:
                kwargs["data"] = data
            if files:
                kwargs["files"] = files

        elif mode == "graphql":
            gql = body_spec.get("graphql") or {}
            kwargs["json"] = gql

        elif mode == "file":
            # TODO: file body mode — read file from disk
            pass
