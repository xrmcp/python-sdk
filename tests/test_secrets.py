from __future__ import annotations

import pytest

from xrmcp.schema_validation import SchemaValidator
from xrmcp.secrets import EnvSecretStore, SecretStore
from xrmcp.templates import TemplateResolutionError, render_template


# ---------------------------------------------------------------------------
# Minimal valid manifest builder
# ---------------------------------------------------------------------------


def _build_manifest(**overrides) -> dict:
    base = {
        "tool": {
            "schemaVersion": "xrmcp.v0.1.0",
            "name": "read_ticket",
            "description": "Read a ticket",
            "type": "api",
            "inputSchema": {"type": "object", "properties": {}, "required": []},
            "executions": [
                {
                    "type": "api",
                    "request": {"method": "GET", "url": "https://api.example.com/"},
                }
            ],
        }
    }
    base["tool"].update(overrides)
    return base


# ---------------------------------------------------------------------------
# EnvSecretStore
# ---------------------------------------------------------------------------


def test_env_secret_store_returns_value_when_set(monkeypatch):
    monkeypatch.setenv("MY_TOKEN", "super-secret")
    store = EnvSecretStore()
    assert store.get("MY_TOKEN") == "super-secret"


def test_env_secret_store_returns_none_when_not_set(monkeypatch):
    monkeypatch.delenv("MISSING_SECRET", raising=False)
    store = EnvSecretStore()
    assert store.get("MISSING_SECRET") is None


# ---------------------------------------------------------------------------
# render_template — secrets.* namespace
# ---------------------------------------------------------------------------


class _StaticStore(SecretStore):
    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    def get(self, name: str) -> str | None:
        return self._values.get(name)


def test_render_template_resolves_secret():
    store = _StaticStore({"MY_TOKEN": "abc123"})
    context = {"input": {}, "config": {}, "secrets": store}
    result = render_template("Bearer {{secrets.MY_TOKEN}}", context)
    assert result == "Bearer abc123"


def test_render_template_raises_when_secret_missing():
    store = _StaticStore({})
    context = {"input": {}, "config": {}, "secrets": store}
    with pytest.raises(TemplateResolutionError):
        render_template("{{secrets.MISSING}}", context)


# ---------------------------------------------------------------------------
# validate_registration — secret declaration check
# ---------------------------------------------------------------------------


def test_validate_rejects_undeclared_secret():
    validator = SchemaValidator()
    manifest = _build_manifest(
        executions=[{
            "type": "api",
            "request": {
                "method": "GET",
                "url": "https://api.example.com/",
                "auth": {
                    "type": "bearer",
                    "bearer": [{"key": "token", "value": "{{secrets.API_TOKEN}}"}],
                },
            },
        }],
        # permissions.secrets NOT declared
    )
    result = validator.validate_registration(manifest)
    assert not result.valid
    codes = [e["code"] for e in result.errors]
    assert "undeclared_secret" in codes


def test_validate_accepts_declared_secret():
    validator = SchemaValidator()
    manifest = _build_manifest(
        executions=[{
            "type": "api",
            "request": {
                "method": "GET",
                "url": "https://api.example.com/",
                "auth": {
                    "type": "bearer",
                    "bearer": [{"key": "token", "value": "{{secrets.API_TOKEN}}"}],
                },
            },
        }],
        permissions={"secrets": ["API_TOKEN"]},
    )
    result = validator.validate_registration(manifest)
    assert result.valid


def test_validate_accepts_manifest_with_no_secret_refs():
    validator = SchemaValidator()
    manifest = _build_manifest()
    result = validator.validate_registration(manifest)
    assert result.valid
