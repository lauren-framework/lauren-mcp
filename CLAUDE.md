# CLAUDE.md — Development guide for lauren-mcp

## Project overview

`lauren-mcp` is a Model Context Protocol (MCP) server and client library for the
Lauren Python web framework.  It provides:

- **Server** — `@mcp_server`, `@mcp_tool`, `@mcp_resource`, `@mcp_prompt`,
  `@mcp_completion`, `@mcp_lifespan` decorators that expose any Lauren service as
  an MCP endpoint over WebSocket, HTTP+SSE, or Streamable HTTP.
- **Client** — `McpServer.stdio/ws/http/streamable` factories returning an
  `McpClientProtocol` that can connect to any MCP server.
- **Lauren integration** — `McpServerModule.for_root(server_cls)` builds a Lauren
  `@module` that wires handlers into the DI graph and mounts transport controllers.
- **CLI** — `lmcp` entry-point (Typer app) with `run`, `dev`, `inspect`, `call`,
  and `install` commands.

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
  __init__.py              Public __all__ (~73+ symbols); re-exports McpCallError,
                           McpExecutionContext, McpForbiddenError, McpCallHandler
  _types.py                Wire types (dataclasses): JsonRpc*, MCP types, parse_message
  _mcp_version.py          LATEST="2025-11-25", STABLE, SUPPORTED (4 versions)
  _bridge.py               McpServerConfig, McpToolBridge (lifecycle manager)

  server/                  Server-side decorator API
    _decorators.py         @mcp_server, @mcp_tool, @mcp_resource, @mcp_prompt,
                           @mcp_completion, @mcp_lifespan; _validate_tool_name,
                           _auto_output_schema
    _meta.py               McpServerMeta, McpToolMeta, McpResourceMeta, McpPromptMeta,
                           McpCompletionMeta, McpLifespanMeta; MCP_*_META constants;
                           structured_output/title/annotations fields on McpToolMeta
    _handlers.py           Handler factories: make_tools_list_handler,
                           make_tools_call_handler, make_completion_handler,
                           make_context_factory; title/annotations in list response
    _module.py             McpServerModule.for_root() + _McpHandlerRegistrar;
                           injects McpCatalogManager, ResourceSubscriptionManager;
                           @pre_destruct for @mcp_lifespan cleanup
    _schema.py             SchemaBuilder — recursive JSON Schema for Pydantic /
                           dataclass / TypedDict / msgspec
    _docstring.py          Google / Sphinx / NumPy docstring parser
    _uri.py                RFC 6570 URI template compiler ({+p}, {p*}, {?p1,p2})
    _builtin_resources.py  FileResource, HttpResource, DirectoryResource
    _composition.py        make_mount_binder, make_proxy_binder, McpToolNameCollision
    _openapi.py            build_openapi_server_class, RouteEntry

  _server/                 Transport layer (server side)
    _exec_context.py       McpExecutionContext (frozen dataclass passed to guards/interceptors);
                           McpForbiddenError, McpCallHandler
    _dispatcher.py         McpDispatcher (@injectable Singleton, body-based routing)
    _ws.py                 mcp_ws_controller() — Lauren @ws_controller factory
    _sse.py                mcp_http_sse_controller() — Lauren @controller factory
    _streamable.py         mcp_streamable_http_controller, StreamableSessionStore;
                           single-POST endpoint; JSON vs SSE based on Accept header;
                           mcp-session-id issued at initialize; GET push; DELETE teardown
    _session.py            SseSessionStore (@injectable Singleton, session→queue map)
    _handshake.py          negotiate_version(), build_initialize_result()
    _binding.py            CURRENT_BINDING ContextVar[TransportBinding | None];
                           TransportBinding dataclass (headers, session_id,
                           send_notification, client_rpc, client_capabilities)
    _catalog.py            McpCatalogManager (@injectable Singleton); holds live
                           tool/resource/prompt lists; mutations fire list_changed
    _registry.py           McpConnectionRegistry (@injectable Singleton); fan-out
                           broadcast to all live connections across all transports
    _context.py            McpToolContext (frozen dataclass), LogLevelState,
                           McpSamplingLoopError, build_elicitation_schema
    _subscriptions.py      ResourceSubscriptionManager — per-URI subscriber fan-out
    _event_store.py        EventStore ABC, InMemoryEventStore
    _transport_security.py TransportSecuritySettings, McpTransportSecurityGuard
                           (DNS rebinding protection)
    _otel.py               instrument_dispatcher — wraps each handler in an OTel span
    _propagate.py          Helper for propagating Lauren metadata onto controllers

  _client/                 Client transports
    _protocol.py           McpClientProtocol (ABC)
    _factory.py            McpServer static factory (stdio/ws/http/streamable)
    _stdio.py              McpStdioClient, McpCallError
    _base_remote.py        _McpBaseRemoteClient (shared handshake + mux logic)
    _features.py           _ClientFeaturesMixin (version negotiation, roots,
                           server-initiated request routing, list handlers)
    _ws.py                 McpWebSocketClient (requires [ws] extra)
    _sse.py                McpHttpSseClient (requires [http] extra)
    _streamable.py         McpStreamableHttpClient — MCP 2025-03-26 transport
                           (requires [http] extra)
    _oauth.py              ClientCredentialsProvider, InMemoryTokenStorage

  cli/
    __init__.py            Typer app "lmcp" (requires [cli] extra)
    _commands.py           run, dev, inspect, call, install commands
    _resolve.py            resolve_server_class — file-spec → @mcp_server class

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
in `providers=[...]` so the DI container instantiates it and calls its
`@post_construct` at startup.  It also has a `@pre_destruct` that closes the
`@mcp_lifespan` async generator at shutdown.

**Critical**: call `TestClient(app)` after `LaurenFactory.create(app)` to trigger
`@post_construct` hooks before connecting via WsTestClient.

### CURRENT_BINDING contextvar

`_server/_binding.py` holds `CURRENT_BINDING: ContextVar[TransportBinding | None]`.
Each transport sets it (via `CURRENT_BINDING.set(binding)`) before calling
`dispatcher.dispatch()`; because `contextvars` values propagate into tasks created
afterwards, handler tasks see the correct per-connection data (headers, session_id,
send_notification, client_rpc, client_capabilities) without any locking or threading.

**Warning**: the contextvar does NOT propagate into threads.  Do not use
`asyncio.to_thread` inside tool handlers without copying `CURRENT_BINDING.get()`
before entering the thread.

### McpCatalogManager + McpConnectionRegistry

`McpCatalogManager` (SINGLETON) holds the live tool/resource/prompt catalogue.  It
is seeded from decorator metadata at startup (silently — broadcast fn not yet
attached), then `catalog.set_broadcast_fn(registry.broadcast_method)` is called so
subsequent mutations fire `notifications/*/list_changed` automatically.

`McpConnectionRegistry` (SINGLETON) maps connection keys to send functions.  WS,
SSE, and Streamable controllers each register on connect and unregister on close.
`broadcast_method(method)` fans a parameter-less notification to all live connections.

### Context factory pattern

`make_context_factory(metadata, lifespan_getter, log_level_state)` builds a callable
that reads `CURRENT_BINDING.get()` and constructs a frozen `McpToolContext` per call.
`make_tools_call_handler(..., context_factory=..., dispatcher=...)` injects it for
each invocation and registers cancel events.

### McpToolContext

`frozen=True` dataclass injected into `@mcp_tool` parameters annotated
`McpToolContext`.  Excluded from JSON schema automatically (via `_is_context_annotation`
which handles string annotations under `from __future__ import annotations`).

Key methods: `report_progress(progress, total, message)`, `log/debug/info/warning/
error/notice/critical(msg, data)`, `sample(messages, *, tools=, ...)`,
`elicit(msg, response_type)`, `elicit_url(msg, url)`, `cancel_requested` property.

New private fields on the frozen dataclass must use `object.__setattr__` (as done
for `_cancel_event` lazy init).

### WebSocket transport

`mcp_ws_controller(path)` mounts at `{path}/ws`.  `handle_connect` calls
`await ws.accept()` explicitly (Lauren auto-accepts only after `@on_connect` returns,
but our message loop never returns) then `await self._message_loop(ws)`.

### SSE transport

Two endpoints at `base_path`:
- `GET {path}/sse` — opens SSE stream, yields `endpoint` event with `session_id`
- `POST {path}/` — receives JSON-RPC; response pushed to the session's queue

`SseSessionStore` maps `session_id → asyncio.Queue[str]`.

### Streamable HTTP transport

Single `POST {path}/` endpoint.  Response is JSON or SSE depending on the client's
`Accept` header.  `mcp-session-id` header issued at `initialize` and required on all
subsequent requests.  `StreamableSessionStore` maps session_id to `StreamableSession`.
`GET {path}/` opens a push channel.  `DELETE {path}/` tears down the session.

### Protocol versions

`LATEST = "2025-11-25"`, `SUPPORTED = {"2024-11-05", "2025-03-26", "2025-06-18",
"2025-11-25"}`.  Client defaults to `LATEST`.  `negotiate_version()` in `_handshake.py`
picks the best overlap.

### Per-method `@use_*(...)` decorators

`@mcp_tool`, `@mcp_resource`, and `@mcp_prompt` methods accept the standard Lauren
cross-cutting decorators (`@use_guards`, `@use_interceptors`, `@use_exception_handlers`,
`@set_metadata`) applied **inside** (closer to the `async def`) the `@mcp_tool()` call.

**Decorator ordering rule — critical:** Python applies decorators inside-out.
`@mcp_tool()` must be the **outermost** decorator so that it sees the Lauren attributes
already set by the inner decorators.  Correct order:

```python
@set_metadata("required_role", "admin")   # innermost — applied first
@use_guards(AdminGuard)
@mcp_tool()                               # outermost — applied last, reads attrs
async def delete_all(self, ctx: McpToolContext) -> dict: ...
```

**Why metadata is re-read at `for_root()` time:** `_read_method_decorators()` runs at
`@mcp_tool()` decoration time, before inner decorators have attached their attributes.
`McpServerModule.for_root()` re-reads the fully-decorated method attributes at startup
so guards, interceptors, and exception handler classes are discovered correctly.

**`McpExecutionContext`** (`frozen=True`) is passed to guards and interceptors.  Fields:
`tool_name`, `method_name`, `server_class`, `headers`, `execution_context`, `session_id`,
`metadata`, `tool_use_id`; method `get_metadata(key)`.

**`McpForbiddenError`** — raised by the dispatcher when a guard's `can_activate()`
returns `False`; serialised as `INTERNAL_ERROR` with `data.type = "FORBIDDEN"`.

**`McpCallHandler`** — passed to interceptors; `await call_handler.handle() -> dict`
invokes the next step in the chain (or the actual tool).

**DI resolution:** Guard, interceptor, and exception-handler classes referenced in
per-method decorators are automatically registered as DI providers by
`_McpHandlerRegistrar` at `@post_construct` time and resolved via the Lauren container.

**`@use_middlewares` is disallowed** on individual `@mcp_tool` methods — the dispatcher
raises `TypeError` at decoration time (middlewares operate at the HTTP/WS transport
level, not at the per-tool dispatch level).

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
- CLI tests that import `typer` should guard with `pytest.importorskip("typer")`.

## Common pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| `McpCallError: Method not found: 'initialize'` | `@post_construct` didn't fire | Call `TestClient(app)` after `LaurenFactory.create()` |
| WsTestClient deadlocks | `handle_connect` doesn't call `ws.accept()` first | Already fixed in `_ws.py` — don't revert |
| `ModuleExportViolation: McpDispatcher declared in two modules` | Two `for_root()` in same app | Use two separate Lauren apps |
| `MissingProviderError: No provider for server_cls` | `from __future__ import annotations` stringifies annotation | Fixed via `__annotations__["server_instance"] = server_cls` after class definition |
| `prek` fails: `git write-tree: insufficient permission` | Root-owned `.git/objects` dirs | noxfile uses `prek run --all-files` to skip git stash |
| Subprocess test hangs 30 s | server script crashes, client retries | Set `max_retries=0` on `McpServer.stdio` in tests |
| `McpToolContext` param excluded from schema | `_is_context_annotation` checks string annotations | Correct behaviour — no fix needed |
| Tool context not visible in `asyncio.to_thread` | CURRENT_BINDING doesn't cross thread boundary | Copy `binding = CURRENT_BINDING.get()` before entering thread |
| `@mcp_lifespan` cleanup not called | Lauren doesn't support async `@pre_destruct` in older versions | Requires lauren>=1.6.0 |
| CLI test fails with `ModuleNotFoundError: typer` | typer is an optional dep | Add `pytest.importorskip("typer")` at top of test file |
| `@use_guards` silently ignored / guard never runs | Decorator ordering wrong | `@mcp_tool()` must be the **outermost** decorator; `@use_guards` goes inside |
| `McpForbiddenError` not raised even though guard returns `False` | Guard class not discovered by DI | Ensure guard is `@injectable()` and listed in `@use_guards`; registrar auto-adds it as provider at startup |
| `@use_middlewares` on `@mcp_tool` method | Middlewares not meaningful at per-tool level | Remove it; `TypeError` is raised at decoration time by design |
