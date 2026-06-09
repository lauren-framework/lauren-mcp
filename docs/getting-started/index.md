# Getting Started with Lauren MCP

## What is MCP?

The **Model Context Protocol (MCP)** is an open standard that defines how AI assistants
(clients) discover and call tools hosted by external services (servers). It ships a
JSON-RPC 2.0 wire format layered over three transports:

| Transport | Use case |
|---|---|
| stdio | Local tools and subprocesses |
| WebSocket | Persistent, bidirectional connections |
| HTTP + SSE | Stateless or browser-friendly deployments |

MCP lets an AI client — such as Claude, a custom agent, or any MCP-aware application —
call your service's tools without knowing anything about its internal implementation.
The server advertises a schema for each tool (name, description, JSON Schema for
parameters) and the client calls them using a standard handshake.

## Why lauren-mcp?

Lauren is a lightweight Python web framework focused on type-safe routing, dependency
injection, and modular application composition. `lauren-mcp` extends it in two directions:

**As a server**: Any `@mcp_server` class becomes an MCP endpoint that AI clients can
connect to over WebSocket, HTTP+SSE, or stdio. You get automatic JSON Schema generation
from Python type annotations, DI-aware tool dispatch, and protocol lifecycle management
for free.

**As a client**: The `McpServer` factory and `McpServerConfig` dataclass let you wire
remote MCP servers into a Lauren `AgentModule` with a single list of config objects.
Each remote tool appears as a first-class callable prefixed with the server's alias,
so namespacing is always unambiguous.

## Two modes at a glance

### Server mode

You decorate a class with `@mcp_server("/path")` and individual methods with
`@mcp_tool()`. Lauren introspects the type annotations and docstrings to build a
valid MCP `tools/list` response. When an AI client calls a tool the framework dispatches
to the correct method, runs any DI resolvers, and returns the result as a valid MCP
content block.

```
AI client  ──── WebSocket/HTTP+SSE ────▶  Lauren app
                                           └─ @mcp_server("/mcp")
                                               ├─ @mcp_tool() search(...)
                                               ├─ @mcp_tool() add_item(...)
                                               └─ @mcp_resource("items://{id}") ...
```

### Client mode

You construct one or more `McpServerConfig` objects pointing at remote MCP servers
(stdio subprocesses, WebSocket URLs, or HTTP+SSE endpoints) and pass them to
`AgentModule.for_root(mcp_servers=[...])`. The module connects to each server at
startup, fetches its tool list, and makes every tool available to the agent under
a namespaced name: `alias__tool_name`.

```
Lauren app ──── stdio/WebSocket/HTTP ────▶  External MCP server
  AgentModule                                └─ tools: ["read_file", "write_file"]
    └─ agent sees: "fs__read_file", "fs__write_file"
```

## Next steps

- [Installation](installation.md) — pip, uv, and local dev setup
- [Quick Start](quick-start.md) — two complete working examples in under 50 lines
- [MCP Server guide](../guides/mcp-server.md) — full decorator API and DI integration
- [MCP Client guide](../guides/mcp-client.md) — all three transport modes
- [Agent Tools guide](../guides/mcp-agent-tools.md) — wiring tools into an AI agent
- [Testing guide](../guides/testing.md) — subprocess echo server, mocks, coverage
