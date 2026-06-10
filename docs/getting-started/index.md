# Getting Started with Lauren MCP

## What is MCP?

The **Model Context Protocol (MCP)** is an open standard that defines how AI assistants
(clients) discover and call tools hosted by external services (servers). It ships a
JSON-RPC 2.0 wire format layered over several transports:

| Transport | Protocol version | Use case |
|---|---|---|
| stdio | any | Local tools and subprocesses |
| WebSocket | any | Persistent, bidirectional connections |
| HTTP + SSE (legacy) | MCP 2024-11-05 | Stateless or browser-friendly deployments |
| Streamable HTTP | MCP 2025-03-26 | Modern HTTP, single-endpoint, streaming |

MCP lets an AI client — such as Claude, a custom agent, or any MCP-aware application —
call your service's tools without knowing anything about its internal implementation.
The server advertises a schema for each tool (name, description, JSON Schema for
parameters) and the client calls them using a standard handshake.

## Why lauren-mcp?

Lauren is a lightweight Python web framework focused on type-safe routing, dependency
injection, and modular application composition. `lauren-mcp` extends it in two directions:

**As a server**: Any `@mcp_server` class becomes an MCP endpoint that AI clients can
connect to over WebSocket, Streamable HTTP, legacy HTTP+SSE, or stdio. You get automatic
JSON Schema generation from Python type annotations, DI-aware tool dispatch, per-call
context injection, server lifecycle hooks, and full protocol lifecycle management — all
without boilerplate.

**As a client**: The `McpServer` factory returns an `McpClientProtocol` that connects
to any MCP server. Use it standalone, wire multiple clients into a Lauren agent module,
or compose remote tools into a local server via `McpServerModule.for_root(proxies=[...])`.

## Two modes at a glance

### Server mode

You decorate a class with `@mcp_server("/path")` and individual methods with
`@mcp_tool()`. Lauren introspects the type annotations and docstrings to build a
valid MCP `tools/list` response. When an AI client calls a tool the framework dispatches
to the correct method, runs any DI resolvers, and returns the result as a valid MCP
content block.

```
AI client  ──── WebSocket / Streamable HTTP / SSE ────▶  Lauren app
                                                           └─ @mcp_server("/mcp")
                                                               ├─ @mcp_lifespan    (startup/shutdown)
                                                               ├─ @mcp_tool()      search(...)
                                                               ├─ @mcp_tool()      add_item(...)
                                                               └─ @mcp_resource()  items://{id}
```

The transport is selected by passing `transport=` to `@mcp_server` or to
`McpServerModule.for_root()`. The default is `"ws"` (WebSocket). Use `"streamable"`
for the 2025-03-26 Streamable HTTP transport, `"all"` for both WebSocket and Streamable
HTTP simultaneously, or `"sse"` / `"both"` for legacy deployments.

### Client mode

You construct a client via the `McpServer` factory and call it directly or wire it
into a Lauren agent module. Every factory method accepts optional handlers for progress
notifications, server log messages, tool-list changes, sampling requests, and elicitation
requests.

```
Lauren app ──── stdio / WebSocket / Streamable HTTP ────▶  External MCP server
  AgentModule                                               └─ tools: ["read_file", "write_file"]
    └─ agent sees: "fs__read_file", "fs__write_file"
```

After `connect()` you can inspect `client.protocol_version` to see which MCP version
was negotiated, subscribe to notifications with `client.on_progress()` /
`client.on_log()` / `client.on_list_changed()`, and call `client.notify_roots_changed()`
when your client-side file-system roots change.

## Key concepts

### JSON Schema generation

`@mcp_tool` builds the `inputSchema` advertised in `tools/list` directly from the
method's Python type annotations. Standard types (`str`, `int`, `float`, `bool`,
`list[str]`, `dict[str, int]`) map to their JSON Schema equivalents. With the optional
`[pydantic]` or `[msgspec]` extras you also get full schema generation from Pydantic
`BaseModel`, `msgspec.Struct`, `@dataclass`, and `TypedDict` parameters — including
nested models, discriminated unions, and `Annotated[T, Field(...)]` constraints.

### McpToolContext

Declare a parameter annotated as `McpToolContext` in any `@mcp_tool` method and the
framework injects a per-call context object. It is excluded from the advertised JSON
Schema — clients never see it or need to supply it.

```python
@mcp_tool()
async def process(self, data: str, ctx: McpToolContext) -> str:
    await ctx.report_progress(0, 100)
    await ctx.info("Starting processing")
    result = heavy_work(data)
    await ctx.report_progress(100, 100)
    return result
```

### Lifespan

`@mcp_lifespan` on an async generator method runs once at server startup and once at
shutdown. The dict the generator yields is available as `ctx.lifespan_context` inside
every tool call — a clean pattern for sharing database connections, HTTP clients, or
any other startup-time resource.

### Server composition

`McpServerModule.for_root()` accepts `mounts=` (merge tools from sibling `@mcp_server`
classes) and `proxies=` (forward to remote MCP clients). Combined, this lets you
aggregate many logical servers behind one endpoint with name-prefixed namespacing and
collision detection at startup.

## Next steps

- [Installation](installation.md) — pip, uv, extras, and local dev setup
- [Quick Start](quick-start.md) — two complete working examples in under 60 lines
- [MCP Server guide](../guides/mcp-server.md) — full decorator API and DI integration
- [MCP Client guide](../guides/mcp-client.md) — all four transport modes
- [Testing guide](../guides/testing.md) — subprocess echo server, mocks, coverage
