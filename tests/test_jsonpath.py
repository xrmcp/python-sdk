from __future__ import annotations

import pytest

from xrmcp.jsonpath import resolve_jsonpath


def test_single_match_returns_value_directly():
    data = {"name": "Alice", "age": 30}
    assert resolve_jsonpath(data, "$.name") == "Alice"


def test_multi_match_returns_list():
    data = {"items": [{"id": 1}, {"id": 2}, {"id": 3}]}
    result = resolve_jsonpath(data, "$.items[*].id")
    assert result == [1, 2, 3]


def test_no_match_raises_value_error():
    data = {"name": "Alice"}
    with pytest.raises(ValueError, match="matched nothing"):
        resolve_jsonpath(data, "$.missing")


def test_invalid_expression_raises_value_error():
    with pytest.raises(ValueError):
        resolve_jsonpath({}, "not-a-jsonpath")
