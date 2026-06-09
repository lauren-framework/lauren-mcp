# Guides

Practical, task-oriented guides for every major feature of `lauren-mcp`.

## Beginner

| Guide | Description |
|---|---|
| [Your First Server](first-server.md) | Step-by-step: build a server with tools, resources, and prompts; deploy with Lauren |
| [Your First Client](first-client.md) | Connect, discover, and call tools from any MCP server |

## Decorators and features

| Guide | Description |
|---|---|
| [Decorators in Depth](decorators.md) | All options for `@mcp_tool`, `@mcp_resource`, `@mcp_prompt`, and `@mcp_server` |
| [Multiple Servers](multiple-servers.md) | Connect several MCP servers simultaneously; tool namespacing |
| [Error Handling](error-handling.md) | Timeouts, `McpCallError`, not-found resources, and retry patterns |

## Testing

| Guide | Description |
|---|---|
| [Testing](testing.md) | Unit tests (direct method calls), subprocess E2E, mock clients, `WsTestClient` |

## Full API reference

| Guide | Description |
|---|---|
| [MCP Server API](mcp-server.md) | Complete `@mcp_server`, `@mcp_tool`, `@mcp_resource`, `@mcp_prompt`, and `McpServerModule` reference |
| [MCP Client API](mcp-client.md) | Complete `McpServer.stdio/ws/http` and `McpClientProtocol` method reference |
| [Agent Tools](mcp-agent-tools.md) | Wire MCP server tools into a Lauren AI `AgentModule` |
