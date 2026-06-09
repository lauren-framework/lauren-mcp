# CLAUDE.md — Development guide for lauren-mcp

## Project overview

`lauren-mcp` is a Model Context Protocol (MCP) server and client library for the
Lauren Python web framework.  It provides:

- **Server** — `@mcp_server`, `@mcp_tool`, `@mcp_resource`, `@mcp_prompt` decorators
  that expose any Lauren service as an MCP endpoint over WebSocket or HTTP+SSE.
- **Client** — `McpServer.stdio/ws/http` factories returning an `McpClientProtocol`
  that can connect to any MCP server.
- **Lauren integration** — `McpServerModule.for_root(server_cls)` builds a Lauren
  `@module` that wires handlers into the DI graph and mounts transport controllers.

## Essential commands

```bash
# Run full test suite (all Python versions)
uv run --no-sync nox

# Run a specific session
uv run --no-sync nox -s tests-3.12
uv run --no-sync nox -s lint
uv run --no-sync nox -s typecheck
uv run --no-sync nox -s prek            # pre-release checks (uses --all-files)

# Run tests directly (faster, no nox overhead)
uv run --no-sync pytest tests/unit -q
uv run --no-sync pytest tests/integration -q
uv run --no-sync pytest tests/end_to_end -q
uv run --no-sync pytest tests/docs -q
uv run --no-sync pytest tests/integration/test_mcp_lauren_ws_integration.py -v

# Type-check source
uv run --no-sync mypy src/lauren_mcp

# Check llms-full.txt coverage
uv run --no-sync nox -s llms_check
```

## Repository layout

```
src/lauren_mcp/
  __init__.py              Public re-exports + McpCallError export
  _types.py                Wire types (dataclasses): JsonRpc*, MCP types, parse_message
  _version.py              LATEST / STABLE / SUPPORTED constants (from _mcp_version.py)
  _mcp_version.py          Protocol version constants
  _bridge.py               McpServerConfig, McpToolBridge (lifecycle manager)

  server/                  Server-side decorator API
    _decorators.py         @mcp_server, @mcp_tool, @mcp_resource, @mcp_prompt
    _meta.py               McpServerMeta, McpToolMeta, McpResourceMeta, McpPromptMeta
    _handlers.py           Handler factories (make_tools_list_handler etc.)
    _module.py             McpServerModule.for_root() + _McpHandlerRegistrar

  _server/                 Transport layer (server side)
    _dispatcher.py         McpDispatcher (@injectable Singleton, body-based routing)
    _ws.py                 mcp_ws_controller() — Lauren @ws_controller factory
    _sse.py                mcp_http_sse_controller() — Lauren @controller factory
    _session.py            SseSessionStore (@injectable Singleton, session→queue map)
    _handshake.py          negotiate_version(), build_initialize_result()

  _client/                 Client transports
    _protocol.py           McpClientProtocol (ABC)
    _factory.py            McpServer static factory
    _stdio.py              McpStdioClient, McpCallError
    _base_remote.py        _McpBaseRemoteClient (shared handshake + mux logic)
    _ws.py                 McpWebSocketClient (requires [ws] extra)
    _sse.py                McpHttpSseClient (requires [http] extra)

tests/
  unit/                    Pure unit tests (no subprocess, no network)
  integration/             In-process tests — Lauren DI, WsTestClient, TestClient
  end_to_end/              Real subprocess MCP server + McpStdioClient
  docs/                    E2E tests for every code example in docs/
```

## Architecture decisions

### Lauren DI + @post_construct

`McpServerModule.for_root(server_cls)` returns a `@module` class.  The handler
registration logic lives in `_McpHandlerRegistrar` — an `@injectable(Singleton)`
that is in `providers=[...]` so the DI container instantiates it and calls its
`@post_construct` at startup.

**Critical**: call `TestClient(app)` after `LaurenFactory.create(app)` to trigger
`@post_construct` hooks before connecting via WsTestClient.

### WebSocket transport

`mcp_ws_controller(path)` mounts at `{path}/ws`.  `handle_connect` calls
`await ws.accept()` explicitly (Lauren auto-accepts only after `@on_connect` returns,
but our message loop never returns) then `await self._message_loop(ws)`.
This keeps Lauren's routing loop from starting — MCP uses raw JSON-RPC, not Lauren's
event-keyed dispatch.

### SSE transport

Two endpoints at `base_path`:
- `GET {path}/sse` — opens SSE stream, yields `endpoint` event with `session_id`
- `POST {path}/` — receives JSON-RPC; response is pushed to the session's queue

`SseSessionStore` maps `session_id → asyncio.Queue[str]`.  Sessions are created per
GET connection and cleaned up in the generator's `finally` block.

### McpCallError

Raised by client methods when the server returns a JSON-RPC error response.  Exported
from `lauren_mcp` directly: `from lauren_mcp import McpCallError`.

## Conventions

- Type annotations: strict mypy (`strict = true`), all source files annotated.
- `from __future__ import annotations` on every source file.
- `ruff` for linting + formatting (`line-length = 100`).
- `asyncio_mode = "auto"` in pytest — every `async def test_*` is awaited.
- Subprocess server scripts in e2e tests use single-quoted docstrings to avoid
  terminating the outer `'''...'''` string literal.
- `max_retries=0` on all `McpServer.stdio` calls in tests to prevent 30 s hangs on
  subprocess errors.

## Common pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| `McpCallError: Method not found: 'initialize'` | `@post_construct` didn't fire | Call `TestClient(app)` after `LaurenFactory.create()` |
| WsTestClient deadlocks | `handle_connect` doesn't call `ws.accept()` first | Already fixed in `_ws.py` — don't revert |
| `ModuleExportViolation: McpDispatcher declared in two modules` | Two `for_root()` in same app | Use two separate Lauren apps |
| `MissingProviderError: No provider for server_cls` | `from __future__ import annotations` stringifies annotation | Fixed via `__annotations__["server_instance"] = server_cls` after class definition |
| `prek` fails: `git write-tree: insufficient permission` | Root-owned `.git/objects` dirs | noxfile uses `prek run --all-files` to skip git stash |
| Subprocess test hangs 30 s | server script crashes, client retries | Set `max_retries=0` on `McpServer.stdio` in tests |
