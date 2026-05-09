from __future__ import annotations

from typing import Any

from jsonpath_ng.ext import parse


def resolve_jsonpath(data: Any, expr: str) -> Any:
    """Resolve a JSONPath expression against *data* using jsonpath-ng.

    Returns the matched value when the expression matches exactly one node.
    Returns a list when the expression matches multiple nodes.
    Raises ValueError for parse errors or when no nodes match.
    """
    try:
        matches = parse(expr).find(data)
    except Exception as exc:
        raise ValueError(f"Invalid JSONPath expression {expr!r}: {exc}") from exc

    if not matches:
        raise ValueError(f"JSONPath {expr!r} matched nothing in the data")

    if len(matches) == 1:
        return matches[0].value

    return [m.value for m in matches]
