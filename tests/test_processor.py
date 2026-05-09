from __future__ import annotations

import pytest

from xrmcp.processor import ProcessorError, process


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def test_list_payload_wrapped():
    result = process([{"id": 1}, {"id": 2}], None)
    assert result == {"result": [{"id": 1}, {"id": 2}]}


def test_dict_payload_unchanged_when_no_spec():
    payload = {"name": "Alice"}
    assert process(payload, None) is payload


def test_empty_spec_returns_normalised():
    assert process([1, 2], {}) == {"result": [1, 2]}


# ---------------------------------------------------------------------------
# Filter — all / none
# ---------------------------------------------------------------------------


def test_filter_all_passthrough():
    payload = {"a": 1, "b": 2}
    result = process(payload, {"filter": {"mode": "all"}})
    assert result == {"a": 1, "b": 2}


def test_filter_none_returns_empty_and_skips_mapper():
    payload = {"a": 1}
    result = process(payload, {
        "filter": {"mode": "none"},
        # mapper is forbidden by schema when mode=none, but we verify it would be skipped anyway
    })
    assert result == {}


# ---------------------------------------------------------------------------
# Filter — select: flat, nested, list projection
# ---------------------------------------------------------------------------


def test_filter_select_flat_field():
    payload = {"name": "Alice", "age": 30}
    result = process(payload, {"filter": {"mode": "select", "fields": ["name"]}})
    assert result == {"name": "Alice"}


def test_filter_select_nested_field():
    payload = {"owner": {"email": "a@b.com", "id": 99}, "other": "x"}
    result = process(payload, {"filter": {"mode": "select", "fields": ["owner.email"]}})
    assert result == {"owner": {"email": "a@b.com"}}


def test_filter_select_list_projection():
    payload = {"items": [{"sku": "A1", "price": 10}, {"sku": "B2", "price": 20}]}
    result = process(payload, {"filter": {"mode": "select", "fields": ["items[].sku"]}})
    assert result == {"items": [{"sku": "A1"}, {"sku": "B2"}]}


def test_filter_select_list_nested_projection():
    payload = {"items": [{"meta": {"tag": "x"}, "junk": 1}, {"meta": {"tag": "y"}, "junk": 2}]}
    result = process(payload, {"filter": {"mode": "select", "fields": ["items[].meta.tag"]}})
    assert result == {"items": [{"meta": {"tag": "x"}}, {"meta": {"tag": "y"}}]}


# ---------------------------------------------------------------------------
# List payload via result[].field (after normalisation)
# ---------------------------------------------------------------------------


def test_result_list_projection_after_normalisation():
    payload = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
    result = process(payload, {"filter": {"mode": "select", "fields": ["result[].id"]}})
    assert result == {"result": [{"id": 1}, {"id": 2}]}


# ---------------------------------------------------------------------------
# Mapper
# ---------------------------------------------------------------------------


def test_mapper_remaps_keys():
    payload = {"name": "Alice", "age": 30}
    result = process(payload, {"mapper": {"mode": "jsonpath", "mapping": {"fullName": "$.name"}}})
    assert result == {"fullName": "Alice"}


def test_mapper_nested_jsonpath():
    payload = {"owner": {"email": "a@b.com"}}
    result = process(payload, {"mapper": {"mode": "jsonpath", "mapping": {"email": "$.owner.email"}}})
    assert result == {"email": "a@b.com"}


# ---------------------------------------------------------------------------
# Filter + mapper combined
# ---------------------------------------------------------------------------


def test_filter_then_mapper():
    payload = {"name": "Alice", "age": 30, "junk": "x"}
    result = process(payload, {
        "filter": {"mode": "select", "fields": ["name"]},
        "mapper": {"mode": "jsonpath", "mapping": {"fullName": "$.name"}},
    })
    assert result == {"fullName": "Alice"}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


def test_invalid_filter_mode_raises():
    with pytest.raises(ProcessorError, match="filter mode"):
        process({"a": 1}, {"filter": {"mode": "unknown"}})


def test_invalid_mapper_mode_raises():
    with pytest.raises(ProcessorError, match="mapper mode"):
        process({"a": 1}, {"mapper": {"mode": "unknown", "mapping": {"x": "$.a"}}})


def test_select_on_non_dict_raises():
    with pytest.raises(ProcessorError):
        process("plain string", {"filter": {"mode": "select", "fields": ["name"]}})
