# Contributing to lauren-mcp

Thank you for considering a contribution to `lauren-mcp`! This page covers everything
you need to go from a fresh clone to a merged PR.

---

## Setup

1. Fork and clone the repository:

```bash
git clone https://github.com/YOUR_USERNAME/lauren-mcp
cd lauren-mcp
```

2. Clone the framework side by side (required for editable install):

```bash
git clone https://github.com/lauren-framework/lauren-framework ../lauren-framework
```

3. Install all dev dependencies:

```bash
uv sync --dev --active
```

4. Verify the setup:

```bash
uv run --no-sync pytest tests/unit -q
```

---

## Running tests

All commands use `uv run --no-sync` so they use the already-synced `.venv` without
re-resolving dependencies.

```bash
# Full test suite across all supported Python versions (3.11 – 3.14)
uv run --no-sync nox

# A specific nox session
uv run --no-sync nox -s tests-3.12
uv run --no-sync nox -s lint
uv run --no-sync nox -s typecheck
uv run --no-sync nox -s prek       # pre-release checks (uses --all-files)

# Run tests directly — faster, skips nox overhead
uv run --no-sync pytest tests/unit -q
uv run --no-sync pytest tests/integration -q
uv run --no-sync pytest tests/end_to_end -q
uv run --no-sync pytest tests/docs -q

# Type-check source only
uv run --no-sync mypy src/lauren_mcp

# Check llms-full.txt coverage
uv run --no-sync nox -s llms_check
```

### Nox sessions reference

| Session | What it does |
|---|---|
| `tests` | Full suite parametrised over Python 3.11 – 3.14 |
| `tests_unit` | Unit tests only, Python 3.12 |
| `tests_integration` | Integration tests only, Python 3.12 (installs `all` extra) |
| `tests_extras` | Verifies import guards work for bare / ws / http / all installs |
| `coverage` | Full suite with `--cov` and HTML / XML reports |
| `lint` | `ruff check --fix` over `src/`, `noxfile.py`, `scripts/` (tests and examples excluded via `[tool.ruff]`) |
| `format` | `ruff format` over the same paths |
| `typecheck` | `mypy src/lauren_mcp` with `strict = true` |
| `llms_check` | Verifies `llms-full.txt` covers all public symbols |
| `prek` | Pre-release checks via `prek run --all-files` |
| `docs` | `mkdocs build --strict` |
| `docs_serve` | `mkdocs serve` for local preview |
| `build` | Wipes `dist/` and builds wheel + sdist |
| `build_check` | `twine check dist/*` |

---

## Repository layout

```
src/lauren_mcp/
  __init__.py              Public re-exports + McpCallError export
  _types.py                Wire types (dataclasses): JsonRpc*, MCP types, parse_message
  _mcp_version.py          Protocol version constants (LATEST, STABLE, SUPPORTED)

  server/                  Server-side decorator API
    _decorators.py         @mcp_server, @mcp_tool, @mcp_resource, @mcp_prompt, @mcp_lifespan
    _meta.py               McpServerMeta, McpToolMeta, McpResourceMeta, McpPromptMeta, McpLifespanMeta
    _handlers.py           Handler factories (make_tools_list_handler etc.)
    _module.py             McpServerModule.for_root() + _McpHandlerRegistrar
    _schema.py             SchemaBuilder — JSON Schema from Python type annotations
    _docstring.py          Docstring parser (Google / Sphinx / NumPy styles)
    _composition.py        make_mount_binder(), make_proxy_binder() for mounts= and proxies=
    _openapi.py            build_openapi_server_class() — import an OpenAPI spec as tools
    _uri.py                compile_uri_template() — RFC 6570 subset for @mcp_resource

  _server/                 Transport layer (server side)
    _dispatcher.py         McpDispatcher (@injectable Singleton, method-based routing)
    _ws.py                 mcp_ws_controller() — Lauren @ws_controller factory
    _sse.py                mcp_http_sse_controller() — Lauren @controller factory (legacy SSE)
    _streamable.py         mcp_streamable_http_controller() — Streamable HTTP (2025-03-26)
    _session.py            SseSessionStore (@injectable Singleton, legacy SSE session→queue map)
    _binding.py            TransportBinding dataclass + CURRENT_BINDING ContextVar
    _catalog.py            McpCatalogManager — live tool/resource/prompt catalogue
    _registry.py           McpConnectionRegistry — fan-out channel for server-push notifications
    _context.py            McpToolContext — per-call context object injected into @mcp_tool methods
    _handshake.py          negotiate_version(), build_initialize_result()
    _propagate.py          _apply_server_metadata() — copies @use_* from @mcp_server to controllers

  _client/                 Client transports
    _protocol.py           McpClientProtocol (ABC)
    _factory.py            McpServer static factory (stdio / ws / http / streamable)
    _features.py           _ClientFeaturesMixin — notification handlers, roots, protocol state
    _stdio.py              McpStdioClient, McpCallError
    _base_remote.py        _McpBaseRemoteClient (shared handshake + multiplexing logic)
    _ws.py                 McpWebSocketClient (requires [ws] extra)
    _sse.py                McpHttpSseClient (requires [http] extra)
    _streamable.py         McpStreamableHttpClient (requires [http] extra)

tests/
  unit/                    Pure unit tests — no subprocess, no network
  integration/             In-process tests — Lauren DI, WsTestClient, TestClient
  end_to_end/              Real subprocess MCP server + McpStdioClient
  docs/                    E2E tests for every code example in docs/
```

---

## Architecture decisions

### Lauren DI + `@post_construct`

`McpServerModule.for_root(server_cls)` returns a `@module` class.  All handler
registration lives inside `_McpHandlerRegistrar` — an `@injectable(Singleton)` listed
in `providers=[...]` so the DI container instantiates it and calls its `@post_construct`
at startup.

`@post_construct` fires when `TestClient(app)` (or a real ASGI server) first starts the
app.  Unit tests that skip `TestClient` must call `_register_handlers()` manually or
the dispatcher will reject every request with `Method not found: 'initialize'`.

**Critical**: always call `TestClient(app)` *after* `LaurenFactory.create(app)` — only
the combination triggers `@post_construct` hooks before you connect via `WsTestClient`.

### `CURRENT_BINDING` — per-call transport context

`McpDispatcher` is a **SINGLETON** shared across all connections, but each connection
(or each HTTP request in the case of Streamable HTTP and legacy SSE) needs its own
notification channel, session id, and client capability set.

Transports solve this with `CURRENT_BINDING`, a `contextvars.ContextVar[TransportBinding | None]`:

1. The transport sets `CURRENT_BINDING` before calling `dispatcher.dispatch()`.
2. `dispatch()` creates a task for the handler; `ContextVar` values propagate
   automatically into tasks created in the same context.
3. The handler reads `CURRENT_BINDING.get()` to obtain the correct `TransportBinding`
   for its connection — no locking, no re-registration.

```python
# _binding.py
CURRENT_BINDING: ContextVar[TransportBinding | None] = ContextVar(
    "mcp_transport_binding", default=None
)

# Transport (e.g. _ws.py) before dispatching a frame:
token = CURRENT_BINDING.set(binding)
try:
    response = await self._dispatcher.dispatch(msg)
finally:
    CURRENT_BINDING.reset(token)
```

`TransportBinding` carries: request headers, an `ExecutionContext`, a `session_id`,
a `send_notification` callable, a `client_rpc` callable (for sampling / elicitation),
and the negotiated `ClientCapabilities`.

### `McpCatalogManager` + `McpConnectionRegistry`

Two SINGLETON services manage the live catalogue and connected clients:

**`McpCatalogManager`** holds the mutable dictionaries of tools, resources, and
prompts.  It is seeded from decorator metadata at startup (silently — no
notifications fire before the broadcast function is attached) and can be mutated
at runtime via `register_tool` / `unregister_tool` etc.  Every post-startup mutation
fires a `notifications/*/list_changed` broadcast through the registered
`BroadcastFn`.

**`McpConnectionRegistry`** maps connection keys to `SendFn` callables — one entry
per live WebSocket or SSE stream.  When the catalog manager calls `broadcast_method`,
the registry fans the notification out to every open connection using
`asyncio.gather`, logging and skipping individual failures so one dead socket cannot
stall the others.

The two services are wired together in `_McpHandlerRegistrar._register_handlers`:

```python
catalog.set_broadcast_fn(self._registry.broadcast_method)
```

### WebSocket transport

`mcp_ws_controller(path)` mounts at `{path}/ws`.  `handle_connect` calls
`await ws.accept()` explicitly (Lauren auto-accepts only after `@on_connect` returns,
but MCP's message loop never returns) then enters `_message_loop`.  This keeps
Lauren's built-in routing loop from starting — MCP uses raw JSON-RPC frames, not
Lauren's `event`-keyed dispatch format.

Server-initiated requests (sampling, elicitation) work over WebSocket: the transport
issues a `"srv-{n}"` request frame and parks an `asyncio.Future` in
`_pending_client_rpcs`; when the client sends back a matching response frame the
future resolves and `ctx.sample()` / `ctx.elicit()` returns.

### Legacy HTTP+SSE transport (MCP 2024-11-05)

`mcp_http_sse_controller(base_path)` exposes two endpoints:

- `GET {path}/sse` — opens the SSE stream, generates a `session_id`, emits an
  `endpoint` event carrying it, then blocks on the session queue.
- `POST {path}/` — receives JSON-RPC; looks up the session queue by
  `mcp-session-id` header, dispatches the request, and puts the serialised response
  on the queue so the SSE stream delivers it.

`SseSessionStore` maps `session_id → asyncio.Queue[str]`.  Sessions are created on
`GET /sse` and cleaned up in the generator's `finally` block.

**Limitation**: legacy SSE cannot carry server-to-client requests, so `ctx.sample()`
and `ctx.elicit()` raise `McpSamplingNotAvailable` / `McpElicitationNotAvailable`
on this transport.

### Streamable HTTP transport (MCP 2025-03-26)

`mcp_streamable_http_controller(base_path)` exposes a single MCP endpoint:

- `POST {path}/` — handles `initialize` (creates a session and returns
  `mcp-session-id`) and all subsequent requests.  When the client sends
  `Accept: text/event-stream`, notifications generated during the call stream onto
  the response body as SSE events before the final JSON-RPC response.  Plain JSON
  mode returns the response directly.  Client response frames (for server-initiated
  RPCs) are also delivered via `POST`.
- `GET {path}/` — optional server-push channel; an SSE stream delivering
  notifications and server-initiated requests for the session.
- `DELETE {path}/` — explicit session teardown.

`StreamableSessionStore` manages `StreamableSession` objects — one per live client.
Each session has a `push_queue` (feeding the GET channel) and a
`pending_client_rpcs` dict (for sampling / elicitation futures).

### Server metadata propagation

`@mcp_server` is a regular Python class decorator; it does not know about Lauren
transports at decoration time.  When `for_root()` creates the transport controllers
it calls `_apply_server_metadata(server_cls, controller_cls)`, which reads every
Lauren `@use_*` annotation from the server class (guards, interceptors, middlewares,
exception handlers, encoder, user metadata) and replays them onto the controller
class.  The Lauren runtime then enforces them natively — guards run before
`@on_connect` (WS) or per-request (HTTP), interceptors wrap handlers, etc.

### `_ClientFeaturesMixin`

`McpStdioClient`, `McpWebSocketClient`, `McpHttpSseClient`, and
`McpStreamableHttpClient` all inherit `_ClientFeaturesMixin` from `_client/_features.py`.
The mixin provides:

- Protocol version negotiation state (`_requested_protocol_version` /
  `_negotiated_protocol_version`).
- Handler registration: `on_progress()`, `on_log()`, `on_list_changed()` — each
  returns an unsubscribe callable.
- Roots support: a static list or a callable provider; `notify_roots_changed()` fires
  `notifications/roots/list_changed`.
- Server-initiated request handling: `sampling/createMessage`,
  `elicitation/create`, `roots/list`, and `ping` are answered in background tasks
  so they cannot block the receive loop.

---

## Design philosophy

1. **Zero magic at import time.** Decorators register metadata; they do not run IO,
   open connections, or start threads.  All side effects happen at application startup
   via `McpServerModule.for_root()` or on the first `async with client`.

2. **Type annotations are the source of truth.** JSON Schemas for tools, resources,
   and prompts are derived automatically from Python type annotations — including
   Pydantic models, `msgspec.Struct`, `@dataclass`, and `TypedDict`.  Manually
   authored schemas are a last resort, not the default.

3. **Transports are interchangeable.** The same `@mcp_server` class works over
   WebSocket, HTTP+SSE, Streamable HTTP, and stdio without any code changes.  The
   transport choice is a deployment detail, not an application concern.

4. **Optional deps stay optional.** The `websockets` and `httpx` packages are never
   imported at module level.  Import guards raise a clear `ImportError` with an
   install hint when a transport is used without its extra.

5. **Tests must not require a running server by default.** Unit tests mock the
   `McpClientProtocol`; integration tests use `WsTestClient` or `TestClient`
   in-process.  Live-network tests are `@pytest.mark.eval` and excluded from default
   pytest runs.

---

## Branching strategy

| Branch | Purpose |
|---|---|
| `main` | Stable, always releasable |
| `dev` | Integration branch for in-progress features |
| `feat/<name>` | Feature branches (from `dev`) |
| `fix/<name>` | Bug fix branches (from `main` for hotfixes, `dev` otherwise) |
| `docs/<name>` | Documentation-only changes |

Open PRs against `dev` for features and against `main` for critical hotfixes.

---

## Commit message format

```
<type>(<scope>): <short summary>

<optional longer description>

Refs: #<issue>
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `chore`, `ci`

Examples:

```
feat(server): add @mcp_resource decorator with URI template support
fix(client): handle reconnect during in-flight call_tool
docs(guides): add authentication headers section to client guide
```

---

## How to add a new MCP primitive

Use this checklist when implementing a new MCP primitive (e.g. a new decorator or
message type):

1. **Add wire types** in `src/lauren_mcp/_types.py` — dataclasses matching the MCP spec.
2. **Add to `__all__`** in `src/lauren_mcp/__init__.py`.
3. **Write unit tests** in `tests/unit/` covering serialisation, schema generation,
   and dispatch — no subprocesses, no network.
4. **Implement the server-side handler** in `src/lauren_mcp/_server/` and register
   it in `_dispatcher.py`.
5. **Implement the client-side method** on `McpClientProtocol` and all transport
   implementations.
6. **Update the echo server fixture** at `tests/fixtures/echo_server.py` to exercise
   the new primitive.
7. **Write an integration test** in `tests/integration/` using the echo server.
8. **Update docs**: add a section to the relevant guide, update
   `reference/types.md` or `reference/server.md` / `reference/client.md`, update
   `llms-full.txt`, and run `nox -s llms_check` to verify coverage.

---

## Common pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| `McpCallError: Method not found: 'initialize'` | `@post_construct` didn't fire | Call `TestClient(app)` after `LaurenFactory.create()` |
| `WsTestClient` deadlocks | `handle_connect` doesn't call `ws.accept()` first | Already fixed in `_ws.py` — do not revert |
| `ModuleExportViolation: McpDispatcher declared in two modules` | Two `for_root()` in the same Lauren app | Use two separate Lauren apps |
| `MissingProviderError: No provider for server_cls` | `from __future__ import annotations` stringifies the annotation | Fixed via `__annotations__["server_instance"] = server_cls` after class definition |
| `prek` fails: `git write-tree: insufficient permission` | Root-owned `.git/objects` dirs | `noxfile` passes `--all-files` to skip the git stash step |
| Subprocess test hangs 30 s | Server script crashes; client retries | Set `max_retries=0` on `McpServer.stdio` in tests |
| `ctx.sample()` raises `McpSamplingNotAvailable` | Using the legacy SSE transport | Switch to WebSocket or Streamable HTTP, which support server-to-client RPCs |

---

## Test requirements

- All new code must have unit tests.
- Coverage must not drop below 90% (`nox -s coverage`).
- Integration tests must pass locally before opening a PR.
- `pytest.mark.eval` tests are optional for contributors but required for
  maintainers before a release.

---

## Docs requirements

- Every public symbol must have a docstring.
- New guides must be linked from `docs/guides/index.md`.
- Run `nox -s docs` locally to ensure the docs build without warnings.

---

## Definition of done

A PR is ready to merge when:

- [ ] All unit and integration tests pass (`nox -s tests tests_integration`)
- [ ] Coverage is ≥ 90% (`nox -s coverage`)
- [ ] Lint and format pass (`nox -s lint format`)
- [ ] Type check passes (`nox -s typecheck`)
- [ ] `llms-full.txt` is up to date (`nox -s llms_check`)
- [ ] Docs build without warnings (`nox -s docs`)
- [ ] `CHANGELOG.md` has an entry in `[Unreleased]`
- [ ] PR description explains the *why*, not just the *what*
