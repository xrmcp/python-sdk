from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError

_SECRET_RE = re.compile(r"{{\s*secrets\.([A-Za-z_][A-Za-z0-9_.-]*)\s*}}")


def _extract_secret_refs(value: Any) -> set[str]:
    """Recursively collect all {{secrets.X}} names from strings in value."""
    if isinstance(value, str):
        return set(_SECRET_RE.findall(value))
    if isinstance(value, list):
        result: set[str] = set()
        for item in value:
            result |= _extract_secret_refs(item)
        return result
    if isinstance(value, dict):
        result = set()
        for v in value.values():
            result |= _extract_secret_refs(v)
        return result
    return set()


@dataclass(slots=True)
class RegistrationValidationResult:
    valid: bool
    errors: list[dict[str, str]]
    normalized: dict[str, Any] | None = None


class SchemaValidator:
    def __init__(self, schema_path: Path | None = None) -> None:
        self.schema_path = schema_path or self._default_schema_path()
        self.schema = self._load_schema(self.schema_path)
        self.registration_validator = Draft202012Validator(
            {
                "$schema": self.schema["$schema"],
                "$ref": "#/$defs/ToolRegistration",
                "$defs": self.schema["$defs"],
            }
        )

    def validate_registration(self, payload: dict[str, Any]) -> RegistrationValidationResult:
        errors = [self._format_error(err) for err in self.registration_validator.iter_errors(payload)]
        if errors:
            return RegistrationValidationResult(valid=False, errors=errors)

        manifest = payload["tool"]
        config = payload.get("config", {})

        schema_errors = self._validate_embedded_schemas(manifest)
        if schema_errors:
            return RegistrationValidationResult(valid=False, errors=schema_errors)

        config_schema = manifest.get("configSchema")
        if config_schema is not None:
            config_errors = [self._format_error(err) for err in Draft202012Validator(config_schema).iter_errors(config)]
            if config_errors:
                return RegistrationValidationResult(valid=False, errors=config_errors)

        # Check that every {{secrets.X}} reference is declared in permissions.secrets
        declared_secrets: set[str] = set(manifest.get("permissions", {}).get("secrets", []))
        referenced_secrets = _extract_secret_refs(manifest)
        undeclared = referenced_secrets - declared_secrets
        if undeclared:
            return RegistrationValidationResult(
                valid=False,
                errors=[
                    {"code": "undeclared_secret", "message": f"Secret '{name}' is used in a template but not listed in permissions.secrets — add \"{name}\" to the permissions.secrets array to allow it"}
                    for name in sorted(undeclared)
                ],
            )

        input_schema = manifest["inputSchema"]
        schema_type = input_schema.get("type")
        if schema_type != "object":
            return RegistrationValidationResult(
                valid=False,
                errors=[{"code": "invalid_input_schema", "message": "tool.inputSchema must be a JSON object schema for MCP tool arguments"}],
            )

        normalized = {
            "tool": manifest,
            "config": config,
        }
        return RegistrationValidationResult(valid=True, errors=[], normalized=normalized)

    def validate_tool_arguments(self, manifest: dict[str, Any], arguments: dict[str, Any]) -> None:
        Draft202012Validator(manifest["inputSchema"]).validate(arguments)

    def _validate_embedded_schemas(self, manifest: dict[str, Any]) -> list[dict[str, str]]:
        errors: list[dict[str, str]] = []
        for key in ("inputSchema", "outputSchema", "configSchema"):
            schema = manifest.get(key)
            if schema is None:
                continue
            try:
                Draft202012Validator.check_schema(schema)
            except SchemaError as exc:
                errors.append({"code": "invalid_schema", "message": f"{key}: {exc.message}"})
        return errors

    def _format_error(self, error: ValidationError) -> dict[str, str]:
        path = ".".join(str(part) for part in error.absolute_path)
        message = error.message if not path else f"{path}: {error.message}"
        return {
            "code": "validation_error",
            "message": message,
        }

    def _load_schema(self, schema_path: Path) -> dict[str, Any]:
        import json

        with schema_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _default_schema_path(self) -> Path:
        return Path(__file__).resolve().parents[2] / "specification" / "v0.1.0" / "schema.json"
