from __future__ import annotations

import pytest

from xrmcp.output_mapper import OutputMapperError, apply_output_mapper


RESULTS = {
    "exec_a": {"name": "Alice", "role": "admin"},
    "exec_b": {"role": "user", "active": True},
    "exec_c": {"summary": "done"},
}
ORDERED = ["exec_a", "exec_b", "exec_c"]


# ---------------------------------------------------------------------------
# Default / mode=last
# ---------------------------------------------------------------------------


def test_no_spec_returns_last():
    result = apply_output_mapper(RESULTS, None, ORDERED)
    assert result == {"summary": "done"}


def test_mode_last_returns_last():
    result = apply_output_mapper(RESULTS, {"mode": "last"}, ORDERED)
    assert result == {"summary": "done"}


def test_mode_last_single_execution():
    result = apply_output_mapper({"_0": {"x": 1}}, {"mode": "last"}, ["_0"])
    assert result == {"x": 1}


# ---------------------------------------------------------------------------
# mode=merge
# ---------------------------------------------------------------------------


def test_mode_merge_combines_keys():
    result = apply_output_mapper(RESULTS, {"mode": "merge"}, ORDERED)
    # exec_b.role overwrites exec_a.role; exec_c adds summary
    assert result == {"name": "Alice", "role": "user", "active": True, "summary": "done"}


def test_mode_merge_later_overwrites_earlier():
    results = {"a": {"x": 1, "y": 2}, "b": {"x": 99}}
    result = apply_output_mapper(results, {"mode": "merge"}, ["a", "b"])
    assert result["x"] == 99
    assert result["y"] == 2


def test_mode_merge_non_dict_raises():
    results = {"a": {"x": 1}, "b": "plain string"}
    with pytest.raises(OutputMapperError, match="objects"):
        apply_output_mapper(results, {"mode": "merge"}, ["a", "b"])


# ---------------------------------------------------------------------------
# mode=map
# ---------------------------------------------------------------------------


def test_mode_map_extracts_keys():
    result = apply_output_mapper(
        RESULTS,
        {
            "mode": "map",
            "mapping": {
                "userName": {"from": "exec_a", "path": "$.name"},
                "isActive": {"from": "exec_b", "path": "$.active"},
            },
        },
        ORDERED,
    )
    assert result == {"userName": "Alice", "isActive": True}


def test_mode_map_full_output_with_dollar():
    result = apply_output_mapper(
        RESULTS,
        {
            "mode": "map",
            "mapping": {
                "summary": {"from": "exec_c", "path": "$"},
            },
        },
        ORDERED,
    )
    assert result == {"summary": {"summary": "done"}}


def test_mode_map_unknown_from_raises():
    with pytest.raises(OutputMapperError, match="exec_missing"):
        apply_output_mapper(
            RESULTS,
            {
                "mode": "map",
                "mapping": {
                    "x": {"from": "exec_missing", "path": "$.name"},
                },
            },
            ORDERED,
        )
