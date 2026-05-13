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
  -H 'authorization: Bearer my-secret-token' \
  -H 'content-type: application/json' \
  -d @examples/getting-started/registry/jsonph/list_posts.xrmcp.json

# Using the CLI
XRMCP_API_TOKEN=my-secret-token xrmcp tool install examples/getting-started/registry/jsonph/list_posts.xrmcp.json
```

Tool manifests follow [`specification/v0.1.0/schema.json`](specification/v0.1.0/schema.json).

## REST API auth

The management endpoints:

- `POST /tools/register`
- `GET /tools/list-installed`
- `DELETE /tools/{name}`

support these environment variables:

- `XRMCP_API_AUTH_MODE` — `none` or `bearer` (default: `none`)
- `XRMCP_API_TOKEN` — required when `XRMCP_API_AUTH_MODE=bearer`

When bearer auth is enabled, clients must send:

```http
Authorization: Bearer <token>
```

If neither auth variable is set, app creation logs a warning that the REST API is running in development mode without auth.

Example:

```bash
export XRMCP_API_AUTH_MODE=bearer
export XRMCP_API_TOKEN=my-secret-token
uvicorn xrmcp.app:create_app --factory --host 127.0.0.1 --port 7373
```

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
