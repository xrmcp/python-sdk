from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
import os
from pathlib import Path
from typing import Any


logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RegisteredTool:
    registration: dict[str, Any]
    registered_at: str

    @property
    def manifest(self) -> dict[str, Any]:
        return self.registration["tool"]

    @property
    def config(self) -> dict[str, Any]:
        return self.registration.get("config", {})


class ToolRegistry:
    def __init__(self, *, store_path: str | os.PathLike[str] | None = None) -> None:
        self._tools: dict[str, RegisteredTool] = {}
        default_path = Path("./xrmcp_store") / "tools.json"
        env_store_path = os.getenv("XRMCP_STORE_PATH")
        self._store_path = Path(store_path or env_store_path or default_path).expanduser()
        self._load_from_disk()

    def upsert(self, registration: dict[str, Any]) -> str:
        name = registration["tool"]["name"]
        status = "updated" if name in self._tools else "registered"
        self._tools[name] = RegisteredTool(
            registration=registration,
            registered_at=datetime.now(UTC).isoformat(),
        )
        self._persist_to_disk()
        return status

    def get(self, name: str) -> RegisteredTool | None:
        return self._tools.get(name)

    def delete(self, name: str) -> bool:
        if name not in self._tools:
            return False
        del self._tools[name]
        self._persist_to_disk()
        return True

    def list(self) -> list[RegisteredTool]:
        return list(self._tools.values())

    def _load_from_disk(self) -> None:
        if not self._store_path.exists():
            return

        try:
            raw = json.loads(self._store_path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("registry store root must be an object")

            loaded: dict[str, RegisteredTool] = {}
            for name, entry in raw.items():
                if not isinstance(name, str):
                    raise ValueError("tool name key must be a string")
                if not isinstance(entry, dict):
                    raise ValueError("tool entry must be an object")

                registration = entry.get("registration")
                registered_at = entry.get("registered_at")
                if not isinstance(registration, dict) or not isinstance(registered_at, str):
                    raise ValueError("tool entry requires registration object and registered_at string")

                loaded[name] = RegisteredTool(
                    registration=registration,
                    registered_at=registered_at,
                )

            self._tools = loaded
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            logger.warning(
                "Failed to load tool registry store at %s: %s. Starting with an empty registry.",
                self._store_path,
                exc,
            )
            self._tools = {}

    def _persist_to_disk(self) -> None:
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            name: {
                "registration": registered.registration,
                "registered_at": registered.registered_at,
            }
            for name, registered in self._tools.items()
        }

        temp_path = self._store_path.with_suffix(f"{self._store_path.suffix}.tmp")
        temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temp_path.replace(self._store_path)
