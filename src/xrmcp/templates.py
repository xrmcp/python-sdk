from __future__ import annotations

import re
from typing import Any

from xrmcp.jsonpath import resolve_jsonpath


class TemplateResolutionError(ValueError):
    pass


_TEMPLATE_RE = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_.-]*)\s*}}")


def render_template(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return _render_string(value, context)
    if isinstance(value, list):
        return [render_template(item, context) for item in value]
    if isinstance(value, dict):
        return {key: render_template(item, context) for key, item in value.items()}
    return value


def _render_string(template: str, context: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        path = match.group(1)
        resolved = _resolve_path(path, context)
        if resolved is None:
            raise TemplateResolutionError(f"Unresolved template variable: {path}")
        return str(resolved)

    return _TEMPLATE_RE.sub(replace, template)


def _resolve_path(path: str, context: dict[str, Any]) -> Any:
    parts = path.split(".")

    # secrets.X namespace — resolved via SecretStore
    if parts[0] == "secrets" and len(parts) == 2:
        store = context.get("secrets")
        if store is not None:
            return store.get(parts[1])
        return None

    # results.* namespace — resolved via jsonpath-ng against accumulated results
    if parts[0] == "results" and len(parts) >= 2:
        results = context.get("results")
        if not results:
            raise TemplateResolutionError(f"No prior execution results available for: {path}")
        tail = ".".join(parts[1:])
        jp_expr = re.sub(r"\.(\d+)", r"[\1]", tail)
        try:
            return resolve_jsonpath(results, f"$.{jp_expr}")
        except ValueError:
            raise TemplateResolutionError(f"results.{tail}")

    current: Any = context

    for index, part in enumerate(parts):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        if index == 0 and isinstance(context.get("input"), dict) and part in context["input"]:
            current = context["input"][part]
            continue
        return None

    return current
