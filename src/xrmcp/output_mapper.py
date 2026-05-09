from __future__ import annotations

# Positional ID convention for executions without an explicit `id`:
# The caller assigns keys "_0", "_1", … by position in the `executions` array
# (not by `order`).  Executions with an `id` use that id as-is.
# `ordered_ids` must list the keys in execution order (sorted by ApiExecution.order,
# with list position as tiebreak), which may mix positional and named keys.

from typing import Any

from xrmcp.jsonpath import resolve_jsonpath


class OutputMapperError(RuntimeError):
    pass


def apply_output_mapper(
    results: dict[str, Any],
    mapper_spec: dict | None,
    ordered_ids: list[str],
) -> Any:
    """Assemble the final tool output from individual execution outputs.

    Parameters
    ----------
    results:
        ``{execution_id: processed_output}`` for every execution.
    mapper_spec:
        The ``outputMapper`` field from ``ToolManifest``, or ``None``.
    ordered_ids:
        Execution ids sorted by ``ApiExecution.order`` (then list position).
        Used by ``mode="last"`` and ``mode="merge"``.
    """
    if not mapper_spec:
        return _mode_last(results, ordered_ids)

    mode = mapper_spec.get("mode")

    if mode == "last":
        return _mode_last(results, ordered_ids)

    if mode == "merge":
        return _mode_merge(results, ordered_ids)

    if mode == "map":
        return _mode_map(results, mapper_spec.get("mapping", {}))

    raise OutputMapperError(f"Unsupported outputMapper mode: {mode!r}")


# ---------------------------------------------------------------------------
# Mode implementations
# ---------------------------------------------------------------------------


def _mode_last(results: dict[str, Any], ordered_ids: list[str]) -> Any:
    if not ordered_ids:
        raise OutputMapperError("ordered_ids is empty — cannot determine last execution")
    return results[ordered_ids[-1]]


def _mode_merge(results: dict[str, Any], ordered_ids: list[str]) -> Any:
    final: dict[str, Any] = {}
    for exec_id in ordered_ids:
        output = results[exec_id]
        if not isinstance(output, dict):
            raise OutputMapperError(
                f"mode=merge requires all execution outputs to be objects, "
                f"but execution {exec_id!r} returned {type(output).__name__}"
            )
        final.update(output)
    return final


def _mode_map(results: dict[str, Any], mapping: dict[str, Any]) -> Any:
    output: dict[str, Any] = {}
    for key, entry in mapping.items():
        from_id: str = entry["from"]
        path: str = entry["path"]
        if from_id not in results:
            raise OutputMapperError(
                f"mode=map references execution id {from_id!r} which is not in results"
            )
        output[key] = resolve_jsonpath(results[from_id], path)
    return output
