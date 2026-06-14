# AGENTS.md — Agent guidance for lauren-mcp

## File ownership

| Path | Owns what |
|---|---|
| `src/lauren_mcp/_types.py` | All MCP wire types; `parse_message`; `build_error_response` |
| `src/lauren_mcp/__init__.py` | Public `__all__` (~73+ symbols); re-exports including `McpCallError`, `McpExecutionContext`, `McpForbiddenError`, `McpCallHandler` |
| `src/lauren_mcp/_mcp_version.py` | `LATEST`, `STABLE`, `SUPPORTED` protocol version constants |
| `src/lauren_mcp/_bridge.py` | `McpServerConfig`, `McpToolBridge` (lifecycle manager) |
| `src/lauren_mcp/server/_decorators.py` | `@mcp_server`, `@mcp_tool`, `@mcp_resource`, `@mcp_prompt`, `@mcp_completion`, `@mcp_lifespan`; name validation; auto output schema |
| `src/lauren_mcp/server/_meta.py` | `McpServerMeta`, `McpToolMeta`, `McpResourceMeta`, `McpPromptMeta`, `McpCompletionMeta`, `McpLifespanMeta`; `MCP_*_META` attribute constants; `guards`, `interceptors`, `exception_handlers`, `tool_metadata` fields on all meta classes |
| `src/lauren_mcp/server/_handlers.py` | Handler factory functions; `make_context_factory`; `make_completion_handler` |
| `src/lauren_mcp/server/_module.py` | `McpServerModule.for_root()`, `_McpHandlerRegistrar` (DI wiring, lifespan, catalog seeding) |
| `src/lauren_mcp/server/_schema.py` | `SchemaBuilder` — recursive JSON Schema for Pydantic/dataclass/TypedDict/msgspec |
| `src/lauren_mcp/server/_docstring.py` | Google/Sphinx/NumPy docstring parser |
| `src/lauren_mcp/server/_uri.py` | RFC 6570 URI template compiler |
| `src/lauren_mcp/server/_builtin_resources.py` | `FileResource`, `HttpResource`, `DirectoryResource` |
| `src/lauren_mcp/server/_composition.py` | `make_mount_binder`, `make_proxy_binder`, `McpToolNameCollision` |
| `src/lauren_mcp/server/_openapi.py` | `build_openapi_server_class`, `RouteEntry` |
| `src/lauren_mcp/_server/_exec_context.py` | `McpExecutionContext` (frozen dataclass for guards/interceptors); `McpForbiddenError`, `McpCallHandler` |
| `src/lauren_mcp/_server/_dispatcher.py` | `McpDispatcher` (routes method → handler; enforces per-tool guards/interceptors) |
| `src/lauren_mcp/_server/_ws.py` | `mcp_ws_controller()` (Lauren WS gateway) |
| `src/lauren_mcp/_server/_sse.py` | `mcp_http_sse_controller()` (Lauren HTTP+SSE gateway) |
| `src/lauren_mcp/_server/_streamable.py` | `mcp_streamable_http_controller`, `StreamableSessionStore` |
| `src/lauren_mcp/_server/_session.py` | `SseSessionStore` |
| `src/lauren_mcp/_server/_handshake.py` | `negotiate_version()`, `build_initialize_result()` |
| `src/lauren_mcp/_server/_binding.py` | `CURRENT_BINDING` ContextVar, `TransportBinding` dataclass |
| `src/lauren_mcp/_server/_catalog.py` | `McpCatalogManager` (dynamic catalog + list_changed notifications) |
| `src/lauren_mcp/_server/_registry.py` | `McpConnectionRegistry` (fan-out broadcast to all live connections) |
| `src/lauren_mcp/_server/_context.py` | `McpToolContext`, `LogLevelState`, `McpSamplingLoopError`, `build_elicitation_schema` |
| `src/lauren_mcp/_server/_subscriptions.py` | `ResourceSubscriptionManager` |
| `src/lauren_mcp/_server/_event_store.py` | `EventStore` ABC, `InMemoryEventStore` |
| `src/lauren_mcp/_server/_transport_security.py` | `TransportSecuritySettings`, `McpTransportSecurityGuard` (DNS rebinding guard) |
| `src/lauren_mcp/_server/_otel.py` | `instrument_dispatcher` (OTel span wrapping) |
| `src/lauren_mcp/_client/_protocol.py` | `McpClientProtocol` ABC |
| `src/lauren_mcp/_client/_factory.py` | `McpServer` static factory |
| `src/lauren_mcp/_client/_stdio.py` | `McpStdioClient`, `McpCallError` |
| `src/lauren_mcp/_client/_base_remote.py` | `_McpBaseRemoteClient` (shared WS+SSE+Streamable logic) |
| `src/lauren_mcp/_client/_features.py` | `_ClientFeaturesMixin` (version negotiation, roots, server-request routing) |
| `src/lauren_mcp/_client/_ws.py` | `McpWebSocketClient` (requires `[ws]` extra) |
| `src/lauren_mcp/_client/_sse.py` | `McpHttpSseClient` (requires `[http]` extra) |
| `src/lauren_mcp/_client/_streamable.py` | `McpStreamableHttpClient` — MCP 2025-03-26 (requires `[http]` extra) |
| `src/lauren_mcp/_client/_oauth.py` | `ClientCredentialsProvider`, `InMemoryTokenStorage` |
| `src/lauren_mcp/cli/__init__.py` | Typer `app` ("lmcp" entry-point, requires `[cli]` extra) |
| `src/lauren_mcp/cli/_commands.py` | `run`, `dev`, `inspect`, `call`, `install` commands |
| `src/lauren_mcp/cli/_resolve.py` | `resolve_server_class` — file-spec → `@mcp_server` class |
| `llms-full.txt` | Full API reference for LLMs — must stay in sync with `__all__` |
| `llms.txt` | Short overview — update when public API changes |
| `docs/` | User-facing documentation |
| `skills/` | Agent skill packs |
| `tests/docs/` | E2E tests for every doc code example |
| `tests/integration/test_mcp_lauren_*.py` | Lauren DI + WsTestClient + TestClient integration |
| `tests/unit/test_cli_commands_coverage.py` | Unit tests for CLI command logic (`run`, `dev`, `inspect`, `call`, `install`) |
| `tests/unit/test_client_transports_coverage.py` | Unit tests for client transport classes (stdio, WS, SSE, Streamable) |
| `tests/unit/test_decorators_coverage.py` | Decorator coverage tests (part 1) |
| `tests/unit/test_decorators_coverage2.py` | Decorator coverage tests (part 2) |
| `tests/unit/test_handlers_coverage.py` | Handler factory coverage tests (part 1) |
| `tests/unit/test_handlers_coverage2.py` | Handler factory coverage tests (part 2) |
| `tests/unit/test_handlers_coverage3.py` | Handler factory coverage tests (part 3) |
| `tests/unit/test_handlers_coverage4.py` | Handler factory coverage tests (part 4) |
| `tests/unit/test_openapi_coverage.py` | Unit tests for `build_openapi_server_class` / `RouteEntry` |
| `tests/unit/test_schema_coverage.py` | `SchemaBuilder` coverage tests (part 1) |
| `tests/unit/test_schema_coverage2.py` | `SchemaBuilder` coverage tests (part 2) |
| `tests/unit/test_schema_coverage3.py` | `SchemaBuilder` coverage tests (part 3) |
| `tests/unit/test_server_transport_coverage.py` | Unit tests for server transport internals (WS, SSE, Streamable) |
| `tests/unit/conftest.py` | Shared pytest fixtures for the unit test suite |
| `tests/integration/test_cli_commands_integration.py` | Integration tests for CLI commands against a real Lauren app |
| `tests/integration/test_composition_coverage.py` | Integration tests for `make_mount_binder` / `make_proxy_binder` composition |
| `tests/integration/test_server_sse_streamable_coverage.py` | Integration tests for SSE and Streamable HTTP transports |
| `examples/filesystem/client.py` | Poolside API CLI client example using Rich |
| `examples/filesystem/pyproject.toml` | Standalone `pyproject.toml` for the filesystem example |
| `examples/filesystem/.env.example` | Example environment variable config for the filesystem example |

## By-task lookup

### Adding a new public symbol
1. Add to `src/lauren_mcp/__init__.py` imports and `__all__`
2. Add a `### SymbolName` section to `llms-full.txt`
3. Run `uv run --no-sync nox -s llms_check` — must pass with 0 missing symbols

### Adding a new `@mcp_*` decorator option
1. Update `server/_decorators.py` and `server/_meta.py`
2. Update `server/_handlers.py` if dispatch or schema logic changes
3. Update `docs/guides/decorators.md` and `docs/reference/server.md`
4. Add test in `tests/docs/test_decorators.py` (subprocess e2e)

### Adding a new context method to McpToolContext
1. Edit `_server/_context.py` only
2. `McpToolContext` is `frozen=True` — new private fields must use
   `object.__setattr__` (see `_cancel_event` for the pattern)
3. Add capability guard if the method requires a client capability

### Adding a new transport
1. Create `_server/_newtransport.py`; register/unregister with `McpConnectionRegistry`
2. Set `CURRENT_BINDING` before each `dispatcher.dispatch()` call
3. Add controller to `_module.py`'s `controllers` list and to the `_TRANSPORTS` set
4. Add `McpServer.newtransport()` factory in `_client/_factory.py` if there is a
   matching client transport
5. Document in `docs/reference/transports.md`

### Adding a new client transport
1. Create `_client/_newtransport.py` extending `_McpBaseRemoteClient` (or
   `_ClientFeaturesMixin` for feature sharing)
2. Add `McpServer.newtransport()` factory in `_client/_factory.py`
3. Add optional-dep guard (`try: import ...; _AVAIL = True except ImportError: ...`)
4. Add extra to `pyproject.toml` and document in `docs/reference/client.md`

### Adding per-tool guards

1. Decorate the method with `@use_guards(GuardClass)` **inside** `@mcp_tool()`:
   ```python
   @use_guards(AdminGuard)   # inner
   @mcp_tool()               # outer — must be outermost
   async def my_tool(self, ctx: McpToolContext) -> dict: ...
   ```
2. `GuardClass` must be `@injectable()` and implement `async can_activate(ctx: McpExecutionContext) -> bool`.
3. `_McpHandlerRegistrar` auto-registers `GuardClass` as a DI provider at `@post_construct` time — no manual provider registration needed.
4. When `can_activate` returns `False` the dispatcher raises `McpForbiddenError`, which the client sees as `INTERNAL_ERROR` with `data.type="FORBIDDEN"`.
5. Test with `WsTestClient`: set or omit the triggering header and assert the error code.
6. Add to `tests/unit/test_per_tool_guards.py` (sync guard logic) and `tests/integration/test_per_tool_guards.py` (full DI).

### Adding per-tool interceptors

1. Decorate with `@use_interceptors(InterceptorClass)` inside `@mcp_tool()` (same ordering rule as guards).
2. `InterceptorClass` must be `@interceptor()` and implement:
   ```python
   async def intercept(self, ctx: McpExecutionContext, handler: McpCallHandler) -> dict:
       # pre-processing ...
       result = await handler.handle()
       # post-processing ...
       return result
   ```
3. `McpCallHandler.handle()` calls the next interceptor in the chain or the actual tool.
4. `_McpHandlerRegistrar` auto-registers the interceptor class as a DI provider.
5. Test by asserting the result is transformed as expected via `WsTestClient`.

### Dynamic catalog mutation at runtime
1. Inject `McpCatalogManager` into your service
2. Call `catalog.register_tool(meta)` / `catalog.unregister_tool(name)`
3. `list_changed` notifications fire automatically — no manual broadcast needed

### Adding resource subscriptions
1. `ResourceSubscriptionManager` is already wired into `_McpHandlerRegistrar`
2. Inject it where needed and call `sub_mgr.notify_updated(uri)` to push
   `notifications/resources/updated` to all subscribers for that URI

### Changing McpServerModule.for_root()
- The handler registrar must be an `@injectable(Singleton)` in `providers=[...]`
- After creating the registrar class, set
  `__init__.__annotations__["server_instance"] = server_cls` to work around
  `from __future__ import annotations` stringification
- `_McpModule._handler_registrar_cls = _McpHandlerRegistrar` exposes it for direct testing
- `build_wired_dispatcher` takes 4 args: `(dispatcher, registry, catalog, server_instance)`

### Testing Lauren integration
- Always call `TestClient(app)` after `LaurenFactory.create()` to trigger `@post_construct`
- Two `McpServerModule.for_root()` in the same `@module` will raise
  `ModuleExportViolation` (McpDispatcher can only be in one module) — use separate apps
- CLI tests: add `pytest.importorskip("typer")` at the top of the file

## Common errors

| Error | Cause | Fix |
|---|---|---|
| `Method not found: 'initialize'` | `_register_handlers` `@post_construct` didn't run | Call `TestClient(app)` to trigger lifecycle |
| `UnresolvableParameterError: 'ws'` | `handle_connect` used `ws: Any` | Use `ws: WebSocket` from `from lauren import WebSocket` |
| `websocket_validation_error: frame missing 'event' field` | Lauren's routing loop consumed message | `handle_connect` must `await ws.accept()` then `await _message_loop(ws)` |
| `ModuleExportViolation: McpDispatcher declared in both…` | Two `for_root()` in same app | Use two separate `LaurenFactory.create()` apps |
| `MissingProviderError: No provider for server_cls` | PEP 563 stringifies `server_cls` annotation | Patch annotation at runtime (already done in `_module.py`) |
| Subprocess test hangs 30 s | `max_retries > 0` causes reconnects on crash | Set `max_retries=0` in all test fixtures |
| `prek run` fails: `git write-tree: insufficient permission` | Root-owned `.git/objects` dirs | `noxfile.py` runs `prek run --all-files`; also rewrite root-owned files with `python3 -c "import shutil; ..."` |
| `McpToolContext` param included in JSON schema | `_is_context_annotation` failed to match | Ensure the annotation string or type resolves to `McpToolContext`; check `from __future__ import annotations` is present |
| Tool gets wrong transport context | `asyncio.to_thread` doesn't copy ContextVar | Copy `binding = CURRENT_BINDING.get()` before the thread call |
| `ImportError: typer` in CLI test | `[cli]` extra not installed | Add `pytest.importorskip("typer")` at top of test file |
| `@use_guards` ignored / guard never runs | Decorator ordering wrong — `@use_guards` is outermost | Move `@mcp_tool()` to be the outermost decorator and `@use_guards` inside |
| Guard registered but `can_activate` not called | Guard class not discovered as provider | Confirm class is `@injectable()` and passed to `@use_guards`; registrar discovers it at `@post_construct` |

## Definition of done

A change is complete when ALL of the following pass:

```bash
uv run --no-sync nox -s lint          # ruff: 0 errors (src only; tests/examples excluded)
uv run --no-sync nox -s typecheck     # mypy: 0 errors
uv run --no-sync nox -s llms_check    # all 73+ public symbols documented
uv run --no-sync nox -s prek          # pre-release hooks pass
uv run --dev pytest tests/ -q         # all tests pass
```

If you add a public symbol, `llms_check` will fail — add a `### SymbolName` section
to `llms-full.txt` to fix it.

If you change an API signature, update:
1. `docs/reference/server.md` or `docs/reference/client.md`
2. The corresponding `skills/*/SKILL.md`
3. `llms-full.txt` (same section)
4. Any `tests/docs/` tests that check the old signature

## Key invariants

- `McpStdioClient._message_loop` uses `await process.stdout.readline()` — no competing
  `asyncio.create_task` loop because `handle_connect` awaits `_message_loop` directly.
- `ws.accept()` is called explicitly in `handle_connect` before the loop — Lauren
  only auto-accepts after `@on_connect` returns, but our loop never returns.
- `McpCallError` is the only exception raised by client methods on server-side errors.
  It is exported from the top-level `lauren_mcp` package.
- `McpCatalogManager.set_broadcast_fn` is called *after* seeding from decorator
  metadata so startup registration does not broadcast spurious `list_changed` events.
- `CURRENT_BINDING` propagates into asyncio Tasks but NOT into threads.
- `McpToolContext` is `frozen=True`; new lazy private fields use `object.__setattr__`.
- `McpServerConfig` has exactly two fields: `alias: str` and `client: Any`.
- `call_tool()` / `read_resource()` / `get_prompt()` all return raw `dict` (the
  JSON-RPC `result` field), not typed dataclasses.
- Protocol versions: `LATEST = "2025-11-25"`, `SUPPORTED = {"2024-11-05",
  "2025-03-26", "2025-06-18", "2025-11-25"}`.
