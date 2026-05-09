from __future__ import annotations

import os
from typing import Any

import httpx
from jsonschema import Draft202012Validator, ValidationError

from xrmcp.executors.api.executor import ApiExecutor, ApiExecutorError
from xrmcp.output_mapper import apply_output_mapper
from xrmcp.processor import process
from xrmcp.secrets import EnvSecretStore, SecretStore
from xrmcp.templates import TemplateResolutionError


class ToolRunnerError(RuntimeError):
    pass


class ToolRunner:
    """Orchestrates a full tool invocation: sort → dispatch → process → assemble → validate.

    A single ``httpx.AsyncClient`` is shared across all ``run`` calls for
    connection pooling.  ``ApiExecutor`` instances are created per ``run``
    so they pick up the manifest-scoped ``permissions``.
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient | None = None,
        secret_store: SecretStore | None = None,
    ) -> None:
        self._owned_client = http_client is None
        self._http_client = http_client or httpx.AsyncClient(
            verify=self._build_verify_config()
        )
        self._secret_store = secret_store

    async def aclose(self) -> None:
        if self._owned_client:
            await self._http_client.aclose()

    @staticmethod
    def _build_verify_config() -> bool | str:
        insecure = os.getenv("XRMCP_TLS_INSECURE", "").strip().lower()
        if insecure in {"1", "true", "yes", "on"}:
            return False
        ca_bundle = os.getenv("XRMCP_CA_BUNDLE", "").strip()
        if ca_bundle:
            return ca_bundle
        return True

    async def run(self, manifest: dict, config: dict, arguments: dict) -> Any:
        """Execute all executions in *manifest*, process outputs, and return the final result.

        Parameters
        ----------
        manifest:
            A ``ToolManifest`` dict, already schema-validated by the caller.
        config:
            Install-time config values (``ToolRegistration.config``).
        arguments:
            MCP tool call input, already validated against ``inputSchema`` by the caller.
        """
        context: dict[str, Any] = {
            "input": arguments,
            "config": config,
            "secrets": self._secret_store or EnvSecretStore(),
        }

        executions: list[dict] = manifest.get("executions", [])

        # Sort by (order ?? +inf, original list position) for deterministic sequencing.
        sorted_executions = sorted(
            enumerate(executions),
            key=lambda t: (t[1].get("order", float("inf")), t[0]),
        )

        # Build executor registry for this run.
        # Permissions are manifest-scoped, so ApiExecutor is created per run
        # but shares the long-lived HTTP client for connection reuse.
        permissions = manifest.get("permissions")
        api_executor = ApiExecutor(
            http_client=self._http_client,
            permissions=permissions,
        )
        _executors: dict[str, Any] = {
            "api": api_executor,
        }

        results: dict[str, Any] = {}
        ordered_ids: list[str] = []

        for list_pos, execution in sorted_executions:
            exec_type = execution.get("type")
            executor = _executors.get(exec_type)
            if executor is None:
                raise ToolRunnerError(
                    f"Unsupported execution type: {exec_type!r}. "
                    f"Supported types: {sorted(_executors)}"
                )

            exec_id = execution.get("id") or f"_{list_pos}"

            try:
                raw = await executor.execute(execution, context)
            except (ApiExecutorError, TemplateResolutionError) as exc:
                raise ToolRunnerError(str(exc)) from exc
            processed = process(raw, execution.get("processor"))

            results[exec_id] = processed
            context["results"] = results
            ordered_ids.append(exec_id)

        final = apply_output_mapper(results, manifest.get("outputMapper"), ordered_ids)

        output_schema = manifest.get("outputSchema")
        if output_schema is not None:
            try:
                Draft202012Validator(output_schema).validate(final)
            except ValidationError as exc:
                raise ToolRunnerError(
                    f"Output validation error: {exc.message}"
                ) from exc

        return final
