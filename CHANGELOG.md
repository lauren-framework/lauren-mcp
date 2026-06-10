# Changelog

All notable changes to `lauren-mcp` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased] — 2026-06-10

### Added — Transports

- Streamable HTTP transport (MCP 2025-03-26): single POST endpoint, JSON/SSE response body
  negotiated via `Accept` header, `mcp-session-id` session management, GET push channel,
  DELETE session teardown
- Protocol versions 2025-06-18 and 2025-11-25 added to `SUPPORTED`; `LATEST` updated to
  `"2025-11-25"`
- `McpServer.streamable_http()` client factory for the Streamable HTTP transport
- DNS rebinding protection: `TransportSecuritySettings` and `McpTransportSecurityGuard`
- SSE event store: `EventStore` ABC, `InMemoryEventStore`, Last-Event-ID replay for
  resumable connections
- Stateless HTTP mode: `stateless=True` on `mcp_streamable_http_controller`
- OAuth discovery endpoints (`.well-known/`) on the Streamable HTTP transport
- `transport="streamable"` and `transport="all"` options on `McpServerModule.for_root()`

### Added — Schema generation

- `SchemaBuilder`: recursive JSON Schema generation from Pydantic `BaseModel`,
  `msgspec.Struct`, `@dataclass`, `TypedDict`, `Literal[...]`, `Annotated[T, Field(...)]`,
  `list[T]`, `dict[K, V]`, `UUID`, `datetime`, and other standard types
- Per-parameter descriptions auto-extracted from Google, Sphinx, and NumPy docstrings
- `pydantic` and `msgspec` optional extras for schema generation

### Added — Tool features

- `McpToolContext` injection: declare `ctx: McpToolContext` in a `@mcp_tool` signature;
  the parameter is excluded from the generated JSON Schema
- `ctx.report_progress(progress, total, message)` — sends `notifications/progress`
- `ctx.log/debug/info/notice/warning/error/critical()` — sends `notifications/message`;
  8-level severity
- `ctx.sample()` with `tools=`, `tool_choice=`, `max_tool_iterations=` — agentic
  sampling loop
- `ctx.elicit()` accepting `list[str]`, `@dataclass`, `TypedDict`, or Pydantic model —
  structured user input
- `ctx.elicit_url()` — URL-based elicitation for OAuth flows
- `ctx.cancel_requested` — `asyncio.Event` set on `$/cancelRequest`
- `ctx.lifespan_context` — dict yielded by `@mcp_lifespan`
- `@mcp_lifespan` decorator for startup/shutdown lifecycle hooks with context propagation
- `@mcp_tool(title=, annotations=ToolAnnotations(...), timeout=, tags=, meta=,
  output_schema=, structured_output=)`
- `ToolAnnotations(readOnlyHint, destructiveHint, idempotentHint, openWorldHint)`
- SEP-986 tool name validation: 1–128 characters, `[A-Za-z0-9_\-.]` only,
  raises `McpToolNameCollision` on duplicate registration
- Auto-detect output schema from return type annotation when `structured_output=True`

### Added — Resource features

- Binary blob resources: `bytes` return value auto-encoded as base64 blob; `BlobResource`,
  `ResourceResult`
- RFC 6570 URI template extensions: `{+param}`, `{param*}`, `{?p1,p2}` with type coercion
- `@mcp_resource(title=, annotations=ResourceAnnotations(audience, priority))`
- Resource subscriptions: `resources/subscribe`, `resources/unsubscribe`,
  `notifications/resources/updated`
- `ResourceSubscriptionManager` singleton for fan-out update notifications
- Built-in resource types: `FileResource`, `HttpResource`, `DirectoryResource`

### Added — Prompt and completion

- `@mcp_prompt(title=)`
- `@mcp_completion(target, argument)` decorator and `completion/complete` handler
- `client.complete(ref, argument)` method
- `CompletionResult` wire type
- `ServerCapabilities.completions` field

### Added — Dynamic catalog

- `McpCatalogManager`: register/unregister tools, resources, and prompts at runtime with
  automatic `list_changed` notifications
- `McpConnectionRegistry`: fan-out notifications to all currently connected clients
- `listChanged: True` advertised by default in server capabilities

### Added — Server composition

- `McpServerModule.for_root(mounts=[(Cls, "prefix_")], proxies=[(client, "prefix_")])`
- `make_mount_binder` and `make_proxy_binder` helpers
- `McpToolNameCollision` exception raised on duplicate tool name registration

### Added — OpenAPI import

- `build_openapi_server_class(spec, http_client=..., route_entries=...)` generates an
  `@mcp_server` class from an OpenAPI 3.x specification
- `RouteEntry` for custom route mapping rules

### Added — Client features

- `McpServer.streamable_http()` factory
- All client factories now accept: `protocol_version=`, `roots=`, `progress_handler=`,
  `log_handler=`, `list_changed_handler=`, `resource_updated_handler=`,
  `sampling_handler=`, `elicitation_handler=`, `sampling_tools=`
- `client.protocol_version` property available after `connect()`
- `client.on_progress/on_log/on_list_changed/on_resource_updated()` return an unsubscribe
  callable
- `client.subscribe_resource(uri)` and `client.unsubscribe_resource(uri)`
- `client.set_logging_level(level)` — 8 severity levels
- `client.complete(ref, argument)`
- `ClientCredentialsProvider` and `InMemoryTokenStorage` for OAuth client credentials flow
- `client.notify_roots_changed()`

### Added — Wire types

- `AudioContent`, `ResourceLink` content block types
- `ToolUseContent`, `ToolResultContent` for agentic sampling messages
- `ResourceAnnotations`, `Role`
- `UrlElicitResult`, `McpUrlElicitationNotAvailable`
- `CompletionResult`
- `validate_sampling_messages()` helper
- `ToolSchema.title`, `ResourceSchema.title`, `PromptSchema.title`
- `ToolSchema.outputSchema`, `ToolSchema.annotations`
- `ToolResult.structuredContent`
- `ServerCapabilities.completions`

### Added — Observability and CLI

- OpenTelemetry tracing: `instrument_otel=True` on `for_root()`,
  `instrument_dispatcher()` standalone helper; requires `[otel]` extra
- `lmcp` CLI: `run`, `dev`, `inspect`, `call`, `install` commands; requires `[cli]` extra

### Added — Per-method cross-cutting decorators

- `@use_guards` on individual `@mcp_tool` / `@mcp_resource` / `@mcp_prompt` methods;
  guard runs per-call and receives `McpExecutionContext`
- `@use_interceptors` on individual methods; `McpCallHandler` abstraction wraps the
  next step in the chain (`await call_handler.handle() -> dict`)
- `@use_exception_handlers` on individual methods; maps domain exceptions to
  `isError: True` tool results
- `@set_metadata(key, value)` on individual methods; merged into `McpToolContext.metadata`
  at call time; method-level value wins over class-level value for the same key
- `@use_middlewares` on `@mcp_tool` / `@mcp_resource` / `@mcp_prompt` methods raises
  `TypeError` at decoration time (correct — middlewares are not meaningful at the
  per-tool dispatch level)
- `McpExecutionContext` frozen dataclass passed to guards and interceptors; fields:
  `tool_name`, `method_name`, `server_class`, `headers`, `execution_context`,
  `session_id`, `metadata`, `tool_use_id`; method `get_metadata(key)`
- `McpForbiddenError(guard_name)` exception raised by the dispatcher when a guard's
  `can_activate()` returns `False`; serialised as `INTERNAL_ERROR` with
  `data.type = "FORBIDDEN"`
- `McpCallHandler` class for interceptor chains; `await handle() -> dict`
- Guard, interceptor, and exception-handler classes referenced in per-method decorators
  are auto-registered as DI providers by `_McpHandlerRegistrar` at `@post_construct` time
- `guards`, `interceptors`, `exception_handlers`, `tool_metadata` fields added to
  `McpToolMeta`, `McpResourceMeta`, and `McpPromptMeta`
- New file `src/lauren_mcp/_server/_exec_context.py` — `McpExecutionContext`,
  `McpForbiddenError`, `McpCallHandler`
- Tests: `tests/unit/test_per_tool_*.py`, `tests/integration/test_per_tool_*.py`,
  `tests/end_to_end/test_per_tool_*.py`

### Changed

- `LATEST` protocol version updated: `"2025-03-26"` → `"2025-11-25"`
- Client defaults to `LATEST` during the `initialize` handshake
- `McpServerModule.for_root()` now accepts: `log_level=`, `mounts=`, `proxies=`,
  `instrument_otel=`, `event_store=`, `stateless_http=`
- `make_tools_call_handler()` accepts `context_factory=` and `dispatcher=` parameters
- `McpDispatcher.cancel()` now also sets the `cancel_requested` `asyncio.Event` in
  addition to cancelling the asyncio task
- `listChanged` advertised as `True` by default (was `False`)
- All client factories accept `**feature_kwargs` for handlers, roots, and version

---

## Historical phases

### Phase 7 — Native WS guard/interceptor support + reflect API

- **`lauren>=1.6.0` minimum** — `@use_guards` and `@use_interceptors` now work natively
  on `@ws_controller` (and therefore on `@mcp_server`) classes; the framework's WS
  runtime reads and enforces them before `@on_connect` fires. No workarounds needed in
  extension packages.
- **`McpServerModule.for_root()` simplified** — the manual
  `server_cls.__dict__.get("__lauren_use_guards__", ())` reads replaced with the stable
  public API: `reflect_guards(server_cls)`, `reflect_interceptors(server_cls)`,
  `reflect_middlewares(server_cls)` from `lauren.reflect`.
- **`docs/comparisons.md`** — new page comparing `lauren-mcp` with FastMCP and the
  official Anthropic `mcp` SDK.

### Phase 6 — Documentation and developer experience

- Full MkDocs Material documentation site
- Guides: MCP Server, MCP Client, Agent Tools, Testing
- API reference for all public symbols
- `llms.txt` and `llms-full.txt` for AI assistant consumption
- Skills: `using-mcp-server`, `using-mcp-client`, `mcp-agent-tools`, `mcp-testing`,
  `mcp-transport-internals`
- `scripts/check_llms_full.py` — CI check that `llms-full.txt` covers `__all__`
- `scripts/generate_api_docs.py` — generate `docs/generated-reference/` pages

### Phase 5 — Testing infrastructure

- Echo server fixture at `tests/fixtures/echo_server.py`
- Unit test suite for all wire types, schema generation, and dispatcher routing
- Integration test suite using the echo server subprocess
- `pytest.mark.eval` for live-network tests
- Coverage reporting with 80% minimum threshold

### Phase 4 — Agent integration

- `AgentModule.for_root(mcp_servers=[...])` accepting a list of `McpServerConfig`
- Automatic tool namespacing: `{alias}__{tool_name}`
- System prompt injection with tool catalogue
- `tool_filter` support to whitelist tool subsets
- Startup log output listing all registered MCP tools

### Phase 3 — Client transports

- `McpServer.stdio(command)` — subprocess stdin/stdout transport (no extra deps)
- `McpServer.ws(url)` — WebSocket transport (`[ws]` extra, `websockets>=12`)
- `McpServer.http(url)` — HTTP+SSE transport (`[http]` extra, `httpx>=0.27`)
- `_McpBaseRemoteClient` shared base with pending-request registry and timeout handling
- Exponential backoff reconnect for WebSocket client
- `McpServerConfig` dataclass with alias, client, description, tool_filter fields
- `McpToolBridge` adapter for registering and calling remote tools

### Phase 2 — Server decorators

- `@mcp_server(path)` class decorator with name, version, description parameters
- `@mcp_tool()` method decorator with automatic JSON Schema generation from type hints
- `@mcp_resource(uri)` method decorator with URI template variable extraction
- `@mcp_prompt()` method decorator for parameterised prompt templates
- `McpServerModule.for_root()` Lauren module that mounts all `@mcp_server` classes
- `McpDispatcher` body-based JSON-RPC routing engine
- `SseSessionStore` for HTTP+SSE session lifecycle management
- WebSocket handler (`_ws.py`) and SSE handler (`_sse.py`)
- MCP handshake implementation in `_handshake.py`

### Phase 1 — Foundation

- Initial package skeleton: `pyproject.toml`, `noxfile.py`, GitHub Actions workflows
- `src/lauren_mcp/` package structure with `__init__.py`, `_version.py`, `_types.py`
- Wire types: `JsonRpcRequest`, `JsonRpcNotification`, `JsonRpcResponse`,
  `JsonRpcErrorResponse`, `McpErrorCode`, `parse_message`, `build_error_response`
- MCP message types: `ToolSchema`, `ResourceSchema`, `PromptSchema`, `TextContent`,
  `ImageContent`, `EmbeddedResource`, `PromptArgument`, `PromptMessage`,
  `InitializeParams`, `InitializeResult`, `ClientCapabilities`, `ServerCapabilities`,
  `Implementation`, `ToolCallParams`, `ToolResult`, `ReadResourceParams`,
  `ReadResourceResult`, `GetPromptParams`, `GetPromptResult`
- Version constants: `LATEST`, `STABLE`, `SUPPORTED`

[Unreleased]: https://github.com/lauren-framework/lauren-mcp/compare/HEAD...HEAD
