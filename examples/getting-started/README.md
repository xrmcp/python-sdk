# xrMCP Example Server

This folder contains a minimal host-app server that uses the xrMCP Python SDK as a dependency.

## Files

- `server.py` — basic server exposing `/tools/register`, `/tools/list-installed`, and `/mcp`
- `with_secret_store.py` — same with a secret store example
- `registry/jsonph/` — example tool manifests (JSONPlaceholder)

## Run

From this directory:

```bash
pip install -e "../../"
pip install "uvicorn>=0.30"
python server.py
```

`server.py` auto-loads `.env` if present.

## Register a tool

Using curl:

```bash
curl -X POST http://127.0.0.1:7373/tools/register \
  -H 'content-type: application/json' \
  -d @registry/jsonph/list_posts.xrmcp.json

curl http://127.0.0.1:7373/tools/list-installed
```

Using the CLI (add `--url http://127.0.0.1:<port>` if not using the default port `7373`):

```bash
xrmcp tool install registry/jsonph/list_posts.xrmcp.json
xrmcp tool ls
```
