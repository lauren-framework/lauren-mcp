# Guides

Practical, task-oriented guides for every major feature of `lauren-mcp`.

## Beginner

| Guide | Description |
|---|---|
| [Your First Server](first-server.md) | Step-by-step: build a server with tools, resources, and prompts; add context injection and a lifespan hook; deploy with WebSocket and Streamable HTTP |
| [Your First Client](first-client.md) | Connect with WebSocket or Streamable HTTP, discover and call tools, handle server notifications |
| [Using with Lauren](using-with-lauren.md) | End-to-end guide: HTTP controllers, DI injection, guards, interceptors, middleware, SSE |

## Decorators and features

| Guide | Description |
|---|---|
| [Decorators in Depth](decorators.md) | Complete reference for `@mcp_server`, `@mcp_tool`, `@mcp_resource`, `@mcp_prompt`, and `@mcp_lifespan`; `McpToolContext`; `ToolAnnotations`; rich type schemas; `BlobResource`/`ToolOutput` |
| [Multiple Servers](multiple-servers.md) | Connect several MCP servers simultaneously; tool namespacing |
| [Error Handling](error-handling.md) | Timeouts, `McpCallError`, not-found resources, and retry patterns |

## Examples

| Guide | Description |
|---|---|
| [Filesystem Example](../../examples/filesystem/README.md) | Production-quality MCP server exposing a sandboxed filesystem, plus an interactive Poolside CLI client built with Rich |

## Testing

| Guide | Description |
|---|---|
| [Testing](testing.md) | Unit tests (direct method calls), subprocess E2E, mock clients, `WsTestClient` |

## Full API reference

| Guide | Description |
|---|---|
| [MCP Server API](mcp-server.md) | Complete `@mcp_server`, `@mcp_tool`, `@mcp_resource`, `@mcp_prompt`, and `McpServerModule` reference |
| [MCP Client API](mcp-client.md) | Complete `McpServer.stdio/ws/http/streamable_http` and `McpClientProtocol` method reference |
| [Agent Tools](mcp-agent-tools.md) | Wire MCP server tools into a Lauren AI `AgentModule` |
