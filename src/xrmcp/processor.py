from __future__ import annotations

from typing import Any

from xrmcp.jsonpath import resolve_jsonpath


class ProcessorError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def process(payload: Any, processor_spec: dict | None) -> Any:
    """Apply ResponseProcessor spec to a raw API payload.

    Normalises list payloads to {"result": [...]}, then runs the optional
    filter and mapper stages defined in #/$defs/ResponseProcessor.
    """
    # Normalise: list → {"result": list}
    if isinstance(payload, list):
        payload = {"result": payload}

    if not processor_spec:
        return payload

    result = payload

    # Stage 1: filter
    filter_spec = processor_spec.get("filter")
    if filter_spec is not None:
        result = _apply_filter(result, filter_spec)
        if filter_spec.get("mode") == "none":
            return result  # mapper is skipped per schema constraint

    # Stage 2: mapper
    mapper_spec = processor_spec.get("mapper")
    if mapper_spec is not None:
        result = _apply_mapper(result, mapper_spec)

    return result


# ---------------------------------------------------------------------------
# Filter stage
# ---------------------------------------------------------------------------


def _apply_filter(payload: Any, filter_spec: dict) -> Any:
    mode = filter_spec.get("mode")

    if mode == "all":
        return payload

    if mode == "none":
        return {}

    if mode == "select":
        fields = filter_spec.get("fields", [])
        return _select_fields(payload, fields)

    raise ProcessorError(f"Unsupported filter mode: {mode!r}")


def _select_fields(payload: Any, selectors: list[str]) -> Any:
    if not isinstance(payload, dict):
        raise ProcessorError("filter.mode=select requires an object payload")

    result: dict[str, Any] = {}

    # Group selectors by their list-field name to avoid overwriting
    list_groups: dict[str, list[str]] = {}  # field_name -> [sub-selectors per item]

    for selector in selectors:
        parts = _parse_selector(selector)
        list_idx = next((i for i, p in enumerate(parts) if p.is_list), None)

        if list_idx is not None:
            list_field = parts[list_idx].name
            remaining = parts[list_idx + 1 :]
            sub_sel = ".".join(p.name for p in remaining)
            list_groups.setdefault(list_field, [])
            if sub_sel:
                list_groups[list_field].append(sub_sel)
        else:
            value = _extract_path(payload, parts)
            if value is not _MISSING:
                _set_path(result, parts, value)

    for list_field, sub_sels in list_groups.items():
        if list_field not in payload:
            continue
        list_value = payload[list_field]
        if not isinstance(list_value, list):
            raise ProcessorError(
                f"Selector '{list_field}[]' targets a non-list field"
            )
        items = []
        for item in list_value:
            if not isinstance(item, dict):
                continue
            item_obj: dict[str, Any] = {}
            for sub_sel in sub_sels:
                sub_parts = _parse_selector(sub_sel)
                val = _extract_path(item, sub_parts)
                if val is not _MISSING:
                    _set_path(item_obj, sub_parts, val)
            if item_obj or not sub_sels:
                items.append(item_obj if sub_sels else item)
        result[list_field] = items

    return result


# ---------------------------------------------------------------------------
# Mapper stage
# ---------------------------------------------------------------------------


def _apply_mapper(payload: Any, mapper_spec: dict) -> Any:
    mode = mapper_spec.get("mode")
    if mode != "jsonpath":
        raise ProcessorError(f"Unsupported mapper mode: {mode!r}")

    # allow_missing defaults to True (schema default): missing paths → null instead of error.
    allow_missing: bool = mapper_spec.get("allow_missing", True)
    mapping: dict[str, str] = mapper_spec.get("mapping", {})

    result: dict[str, Any] = {}
    for key, expr in mapping.items():
        try:
            result[key] = resolve_jsonpath(payload, expr)
        except ValueError:
            if not allow_missing:
                raise ProcessorError(
                    f"JSONPath {expr!r} matched nothing and allow_missing is false"
                )
            result[key] = None
    return result


# ---------------------------------------------------------------------------
# Selector parsing helpers
# ---------------------------------------------------------------------------


class _Part:
    __slots__ = ("name", "is_list")

    def __init__(self, name: str, is_list: bool = False) -> None:
        self.name = name
        self.is_list = is_list


_MISSING = object()


def _parse_selector(selector: str) -> list[_Part]:
    """Parse a selector like 'items[].meta.tag' into _Part objects."""
    parts: list[_Part] = []
    # Split on dots, but keep [] attached to the preceding name
    for segment in selector.split("."):
        if segment.endswith("[]"):
            parts.append(_Part(segment[:-2], is_list=True))
        else:
            parts.append(_Part(segment, is_list=False))
    return parts


def _extract_path(obj: Any, parts: list[_Part]) -> Any:
    current = obj
    for part in parts:
        if not isinstance(current, dict) or part.name not in current:
            return _MISSING
        current = current[part.name]
    return current


def _set_path(target: dict, parts: list[_Part], value: Any) -> None:
    """Write value into target following the (non-list) parts path."""
    for part in parts[:-1]:
        target = target.setdefault(part.name, {})
    target[parts[-1].name] = value
