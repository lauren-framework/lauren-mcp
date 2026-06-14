# Installation

## Extras overview

`lauren-mcp` ships a small core (JSON-RPC wire types, server decorators, DI hooks, and
the stdio client) with optional extras for additional transports and richer schema
generation:

| Command | Installs | When to use |
|---|---|---|
| `pip install lauren-mcp` | Core only | Server-only; stdio client; write your own transport |
| `pip install "lauren-mcp[ws]"` | Core + `websockets` | WebSocket client transport |
| `pip install "lauren-mcp[http]"` | Core + `httpx` + `httpx-sse` | HTTP+SSE client (legacy 2024-11-05) **and** Streamable HTTP client (2025-03-26) |
| `pip install "lauren-mcp[pydantic]"` | Core + `pydantic>=2` | Rich JSON Schema generation for Pydantic `BaseModel` parameters |
| `pip install "lauren-mcp[msgspec]"` | Core + `msgspec>=0.18` | Rich JSON Schema generation for `msgspec.Struct` parameters |
| `pip install "lauren-mcp[all]"` | Core + WS + HTTP + pydantic + msgspec | Everything |

!!! note "HTTP extras cover both SSE transports"
    The `[http]` extra installs `httpx` and `httpx-sse`, which are used by both
    `McpServer.http()` (legacy HTTP+SSE, MCP 2024-11-05) and
    `McpServer.streamable_http()` (Streamable HTTP, MCP 2025-03-26). You do not
    need a separate extra for the newer transport.

!!! tip "Schema extras are optional for servers too"
    Without `[pydantic]` or `[msgspec]`, tool parameters of those types still work —
    they just emit a minimal `{}` schema in `tools/list` rather than a fully typed one.
    Install the matching extra when you want clients to see parameter types and
    constraints.

## pip

```bash
# Core (server decorators, JSON-RPC types, stdio client)
pip install lauren-mcp

# WebSocket client
pip install "lauren-mcp[ws]"

# HTTP+SSE client (legacy) and Streamable HTTP client (2025-03-26)
pip install "lauren-mcp[http]"

# Rich schema generation for Pydantic models
pip install "lauren-mcp[pydantic]"

# Rich schema generation for msgspec.Struct
pip install "lauren-mcp[msgspec]"

# Everything
pip install "lauren-mcp[all]"
```

## uv

```bash
uv add lauren-mcp
uv add "lauren-mcp[ws]"
uv add "lauren-mcp[http]"
uv add "lauren-mcp[pydantic]"
uv add "lauren-mcp[msgspec]"
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
uv sync --dev --active
```

4. Run the test suite to verify everything works:

```bash
uv run pytest tests/unit -q
```

## Verify your installation

```bash
python -c "import lauren_mcp; print(lauren_mcp.__version__)"
```

You should see the current version string (e.g. `0.2.0`). If you installed from a local
checkout without a git tag, you will see something like `0.0.0+unknown` or
`0.0.0.post1+d20260610` — that is expected and harmless for development.

## Runtime requirements

- Python **3.11** or later
- `lauren >= 1.6.0`
- `anyio >= 4.0`

Optional:

- `websockets >= 12` (for `[ws]` extra)
- `httpx >= 0.27` and `httpx-sse >= 0.4` (for `[http]` extra)
- `pydantic >= 2.0` (for `[pydantic]` extra)
- `msgspec >= 0.18` (for `[msgspec]` extra)
