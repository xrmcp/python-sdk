# xrMCP Python SDK

Python runtime for [xrMCP](https://github.com/xrmcp/xrmcp) — install AI tools from JSON manifests without deploying hardcoded MCP servers.

## What it does

The SDK exposes a Starlette app you embed in your own host application. It provides:

- `POST /tools/register` — register a tool from a `.xrmcp.json` manifest at runtime
- `GET /tools/list-installed` — list currently installed tools
- `DELETE /tools/{name}` — uninstall a tool
- `/mcp` — MCP Streamable HTTP endpoint for your agent

## Quick start

```bash
pip install xrmcp
pip install "uvicorn>=0.30"
```

See [`examples/getting-started/`](examples/getting-started/) for a minimal host server.

## Register a tool

```bash
# Using curl
curl -X POST http://127.0.0.1:7373/tools/register \
  -H 'content-type: application/json' \
  -d @examples/getting-started/registry/jsonph/list_posts.xrmcp.json

# Using the CLI
xrmcp tool install examples/getting-started/registry/jsonph/list_posts.xrmcp.json
```

Tool manifests follow [`specification/v0.1.0/schema.json`](specification/v0.1.0/schema.json).

## Current scope

- `api` execution type only
- registry persists to disk (`XRMCP_STORE_PATH` or `./xrmcp_store/tools.json` by default)
- manifest-native tool exposure through the official MCP Python SDK
- minimal permission enforcement

## Secrets

Secrets referenced in manifests (e.g. `{{secrets.MY_TOKEN}}`) are resolved via a `SecretStore`. The default store reads from environment variables. Pass a custom store to use any backend:

```python
from xrmcp import XRMCPRuntime, SecretStore

class VaultSecretStore(SecretStore):
    def get(self, name: str) -> str | None:
        return vault_client.read(name)

runtime = XRMCPRuntime(secret_store=VaultSecretStore())
```

## Limitations

- `permissions.network` uses a minimal allowlist check
- REST endpoints (`/tools/*`) are unauthenticated — authentication coming soon
