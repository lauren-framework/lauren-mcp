# Installation

## Extras overview

`lauren-mcp` ships a small core (JSON-RPC wire types + server decorators + DI hooks)
with optional transport extras:

| Command | Installs | When to use |
|---|---|---|
| `pip install lauren-mcp` | Core only | Server-only deployments; write your own transport |
| `pip install "lauren-mcp[ws]"` | Core + `websockets` | WebSocket client transport |
| `pip install "lauren-mcp[http]"` | Core + `httpx` + `httpx-sse` | HTTP + SSE client transport |
| `pip install "lauren-mcp[all]"` | Core + WS + HTTP | All transports |

## pip

```bash
# Core (server decorators, JSON-RPC types, stdio client)
pip install lauren-mcp

# WebSocket client
pip install "lauren-mcp[ws]"

# HTTP + SSE client
pip install "lauren-mcp[http]"

# Everything
pip install "lauren-mcp[all]"
```

## uv

```bash
uv add lauren-mcp
uv add "lauren-mcp[ws]"
uv add "lauren-mcp[http]"
uv add "lauren-mcp[all]"
```

## Local development setup

If you are contributing to `lauren-mcp` itself or want to develop against a local
checkout of both `lauren-mcp` and `lauren-framework`:

1. Clone the repositories side by side:

```bash
git clone https://github.com/lauren-framework/lauren-mcp
git clone https://github.com/lauren-framework/lauren-framework
```

Your directory layout should look like:

```
my-projects/
├── lauren-framework/   # the core framework
└── lauren-mcp/         # this package
```

2. The `pyproject.toml` already contains a `[tool.uv.sources]` stanza:

```toml
[tool.uv.sources]
lauren = { path = "../lauren-framework", editable = true }
```

This tells `uv` to install `lauren` from the sibling directory as an editable install,
so changes to the framework are immediately reflected without reinstalling.

3. Install the development environment:

```bash
cd lauren-mcp
uv sync --extra all --extra dev --active
```

4. Run the test suite to verify everything works:

```bash
uv run pytest tests/unit -q
```

## Verify your installation

```bash
python -c "import lauren_mcp; print(lauren_mcp.__version__)"
```

You should see the current version string (e.g. `0.1.0`). If you installed from a local
checkout without a git tag, you will see something like `0.0.0+unknown` or
`0.0.0.post1+d20250601` — that is expected and harmless for development.

## Runtime requirements

- Python **3.11** or later
- `lauren >= 1.5.0`
- `anyio >= 4.0`

Optional:
- `websockets >= 12` (for `[ws]` extra)
- `httpx >= 0.27` and `httpx-sse >= 0.4` (for `[http]` extra)
