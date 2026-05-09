from __future__ import annotations

import os


class SecretStore:
    """Base class for secret resolution. Subclass to provide custom stores."""

    def get(self, name: str) -> str | None:
        """Return the secret value for *name*, or None if not set."""
        raise NotImplementedError


class EnvSecretStore(SecretStore):
    """Resolves secrets from environment variables."""

    def get(self, name: str) -> str | None:
        return os.environ.get(name)
