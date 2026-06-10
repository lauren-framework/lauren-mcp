# Changelog

All notable changes to `lauren-mcp` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

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

### Phase 3 — Client transports

- `McpServer.stdio(command)` — subprocess stdin/stdout transport (no extra deps)
- `McpServer.ws(url)` — WebSocket transport (`[ws]` extra, `websockets>=12`)
- `McpServer.http(url)` — HTTP+SSE transport (`[http]` extra, `httpx>=0.27`)
- `_McpBaseRemoteClient` shared base with pending-request registry and timeout handling
- Exponential backoff reconnect for WebSocket client
- `McpServerConfig` dataclass with alias, client, description, tool_filter fields
- `McpToolBridge` adapter for registering and calling remote tools

### Phase 4 — Agent integration

- `AgentModule.for_root(mcp_servers=[...])` accepting a list of `McpServerConfig`
- Automatic tool namespacing: `{alias}__{tool_name}`
- System prompt injection with tool catalogue
- `tool_filter` support to whitelist tool subsets
- Startup log output listing all registered MCP tools

### Phase 5 — Testing infrastructure

- Echo server fixture at `tests/fixtures/echo_server.py`
- Unit test suite for all wire types, schema generation, and dispatcher routing
- Integration test suite using the echo server subprocess
- `pytest.mark.eval` for live-network tests
- Coverage reporting with 80% minimum threshold

### Phase 6 — Documentation and developer experience

- Full MkDocs Material documentation site
- Guides: MCP Server, MCP Client, Agent Tools, Testing
- API reference for all public symbols
- `llms.txt` and `llms-full.txt` for AI assistant consumption
- Skills: `using-mcp-server`, `using-mcp-client`, `mcp-agent-tools`, `mcp-testing`,
  `mcp-transport-internals`
- `scripts/check_llms_full.py` — CI check that `llms-full.txt` covers `__all__`
- `scripts/generate_api_docs.py` — generate `docs/generated-reference/` pages

### Phase 7 — Native WS guard/interceptor support + reflect API

- **`lauren>=1.6.0` minimum** — `@use_guards` and `@use_interceptors` now work
  natively on `@ws_controller` (and therefore on `@mcp_server`) classes; the
  framework's WS runtime reads and enforces them before `@on_connect` fires.
  No workarounds needed in extension packages.
- **`McpServerModule.for_root()` simplified** — the manual
  `server_cls.__dict__.get("__lauren_use_guards__", ())` reads in
  `server/_module.py` replaced with the stable public API:
  `reflect_guards(server_cls)`, `reflect_interceptors(server_cls)`,
  `reflect_middlewares(server_cls)` from `lauren.reflect`.
- **`docs/comparisons.md`** — new page comparing `lauren-mcp` with FastMCP and
  the official Anthropic `mcp` SDK.

[Unreleased]: https://github.com/lauren-framework/lauren-mcp/compare/HEAD...HEAD
