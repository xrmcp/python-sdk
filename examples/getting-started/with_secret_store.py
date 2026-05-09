from xrmcp import XRMCPRuntime, ToolRunner, SecretStore, EnvSecretStore, create_app

import uvicorn

# Custom secret store
class VaultSecretStore(SecretStore):
    def get(self, name: str) -> str | None:
        ...

runtime = XRMCPRuntime(
    runner=ToolRunner(secret_store=VaultSecretStore()),
)

app = create_app(runtime=runtime)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=7373)
