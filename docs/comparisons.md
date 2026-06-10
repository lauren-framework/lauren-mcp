# Comparisons

> How `lauren-mcp` stacks up against the other Python MCP libraries.

---

## FastMCP

[FastMCP](https://github.com/jlowin/fastmcp) is the most widely-used standalone
Python MCP library. It ships its own minimal ASGI-like server and is designed to
be picked up quickly without any existing framework.

### Feature comparison

| Feature | `lauren-mcp` | FastMCP |
|---|---|---|
| WebSocket transport | ✅ Native | ❌ Not supported |
| Legacy HTTP+SSE (2024-11-05) | ✅ | ✅ |
| Streamable HTTP (2025-03-26) | ✅ | ✅ Default |
| stdio transport | ✅ | ✅ |
| Protocol version negotiation | ✅ | ✅ |
| DI-native server instantiation | ✅ Lauren DI | ❌ |
| Guard / interceptor / middleware auth | ✅ Native Lauren pipeline | ❌ (custom `Depends`) |
| Tool annotations | ✅ | ✅ |
| Tool timeout | ✅ `timeout=` | ✅ |
| Tool tags | ✅ | ✅ |
| Tool structured output | ✅ `ToolOutput` | ✅ |
| Progress notifications | ✅ `ctx.report_progress()` | ✅ `ctx.report_progress()` |
| Structured logging to client | ✅ `ctx.log()` | ✅ `ctx.log()` |
| Sampling | ✅ `ctx.sample()` | ✅ `ctx.sample()` |
| Elicitation | ✅ `ctx.elicit()` | ✅ `ctx.elicit()` |
| Pydantic model schemas | ✅ (optional dep) | ✅ |
| `msgspec.Struct` schemas | ✅ (optional dep) | ❌ |
| `@dataclass` schemas | ✅ | ❌ |
| `TypedDict` schemas | ✅ | ❌ |
| Docstring param descriptions | ✅ Google / Sphinx / NumPy | ✅ Google / NumPy / Sphinx |
| Binary blob resources | ✅ `bytes` / `BlobResource` | ✅ |
| URI template extensions | ✅ RFC 6570 subset | ✅ RFC 6570 |
| Per-resource subscriptions | ❌ | ❌ (also missing) |
| Server composition / mount | ✅ `mounts=` | ✅ `mount()` |
| Remote server proxy | ✅ `proxies=` | ✅ `create_proxy()` |
| OpenAPI import | ✅ `build_openapi_server_class()` | ✅ `from_openapi()` |
| Lifespan hooks | ✅ `@mcp_lifespan` | ✅ `@lifespan` |
| Dynamic catalog notifications | ✅ `listChanged: True` | ✅ |
| Client notification handlers | ✅ `on_progress` / `on_log` / `on_list_changed` | ✅ |
| Client roots support | ✅ `roots=[Root(...)]` | ✅ |
| Sampling handler (client) | ✅ `sampling_handler=` | ✅ |
| Elicitation handler (client) | ✅ `elicitation_handler=` | ✅ |
| OAuth 2.1 auth | ❌ (use Lauren guards) | ✅ Built-in |
| CLI tools | ❌ | ✅ `fastmcp run/install` |
| OpenTelemetry | ❌ | ✅ |
| Background tasks | ❌ | ✅ Docket integration |
| Session state | ❌ | ✅ `ctx.get_state()` |
| Argument autocompletion | ❌ | ❌ (also missing server-side) |

### Remaining gaps

The following features are present in FastMCP but not yet implemented in `lauren-mcp`:

- **OAuth 2.1 built-in auth server** — Lauren guards cover the same use-case for
  framework users, but there is no drop-in OAuth provider.
- **CLI tooling** — no `lauren-mcp run` or `lauren-mcp install` equivalent.
- **OpenTelemetry instrumentation** — no built-in span/trace/metric export.
- **Background task workers** — no Docket-style async job queue integration.
- **Per-resource content-change subscriptions** — `resources/subscribe` is
  unimplemented on both sides.
- **Argument autocompletion** — server-side `completion/complete` is not yet
  implemented by either library.

### Code comparison

**FastMCP**

```python
from fastmcp import FastMCP

mcp = FastMCP("catalogue")

@mcp.tool()
def search(query: str) -> list[dict]:
    """Search the product catalogue."""
    return [{"name": "Widget A"}, {"name": "Widget B"}]

if __name__ == "__main__":
    mcp.run()
```

**lauren-mcp**

```python
from lauren import LaurenFactory, module
from lauren_mcp import McpServerModule, mcp_server, mcp_tool

@mcp_server("/catalogue")
class CatalogueServer:
    @mcp_tool()
    async def search(self, query: str) -> list[dict]:
        """Search the product catalogue."""
        return [{"name": "Widget A"}, {"name": "Widget B"}]

@module(imports=[McpServerModule.for_root(CatalogueServer)])
class AppModule:
    pass

app = LaurenFactory.create(AppModule)
# uvicorn app:app
```

### When to choose `lauren-mcp`

- Your app is already built on Lauren — shared DI container, guards, interceptors,
  and HTTP routes all live in the same process without extra glue.
- You need WebSocket transport.
- You want `msgspec.Struct`, `@dataclass`, or `TypedDict` schemas without Pydantic.
- You prefer Lauren's DI-native authentication patterns over a built-in OAuth server.
- You need in-process testing with `WsTestClient` rather than subprocess stdio.
- You need multi-server — multiple `@mcp_server` classes can coexist in one process
  at different paths, each with its own tool set, guards, and lifecycle.

### When to choose FastMCP

- You want the fastest possible path from zero to a working MCP server with no
  framework dependency.
- You want OAuth 2.1 built-in without writing a custom guard.
- You want CLI tooling (`fastmcp run`, `fastmcp install`).
- You need OpenTelemetry instrumentation.
- You are not using the Lauren framework.

---

## mcp (Anthropic's official Python SDK)

The [official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
(`pip install mcp`) is the reference implementation maintained by Anthropic.

### At a glance

| Capability | `lauren-mcp` | `mcp` SDK |
|---|---|---|
| **API style** | Decorator-driven, class-based | Low-level `Server` object + handler registration |
| **Transport** | WebSocket + SSE + Streamable HTTP + stdio | stdio + SSE + Streamable HTTP |
| **DI** | Full Lauren DI | None |
| **Auth** | `@use_guards` integrated | Manual, transport-level |
| **Protocol compliance** | Builds on top of the SDK wire types | Reference implementation |
| **Abstraction level** | High — decorators handle routing, serialisation, error mapping | Low — full control, more boilerplate |
| **Existing framework required** | Yes — `lauren>=1.6.0` | No |

### Code comparison

**`mcp` SDK (low-level)**

```python
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

server = Server("catalogue")

@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [types.Tool(name="search", description="Search catalogue",
                       inputSchema={"type": "object", "properties": {"query": {"type": "string"}}})]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    if name == "search":
        return [types.TextContent(type="text", text=str([{"name": "Widget A"}]))]
    raise ValueError(f"Unknown tool: {name}")

async def main():
    async with stdio_server() as streams:
        await server.run(*streams, server.create_initialization_options())
```

**lauren-mcp (high-level)**

```python
@mcp_server("/catalogue")
class CatalogueServer:
    @mcp_tool()
    async def search(self, query: str) -> list[dict]:
        """Search the product catalogue."""
        return [{"name": "Widget A"}]
```

### When to choose the official SDK

- You need maximum protocol flexibility or are implementing a non-standard
  MCP extension.
- You are building tooling *around* MCP (inspectors, proxies, test harnesses)
  rather than MCP servers.
- You want zero framework dependency.

### When to choose `lauren-mcp`

- You want ergonomic decorators and automatic schema inference instead of
  manually constructing `Tool` and `TextContent` objects.
- You are integrating MCP into an existing Lauren service.

---

## mcpx / other wrappers

Several community wrappers exist (`mcpx`, `mcp-framework`, etc.). They vary in
maturity and transport support. The comparison dimensions are the same as above:

| Question | `lauren-mcp` answer |
|---|---|
| Does it integrate with my web framework? | Yes — it *is* a Lauren package |
| Does it support DI? | Yes — full Lauren container |
| Does it support WebSocket transport? | Yes — built-in |
| Does it support SSE transport? | Yes — both legacy and Streamable HTTP built-in |
| Does it support `msgspec` / `dataclass` / `TypedDict` schemas? | Yes — all three |
| Can I share auth guards with my HTTP routes? | Yes — `@use_guards` works on `@mcp_server` |
| Can I test without a subprocess? | Yes — `WsTestClient` in-process |

---

## Summary

`lauren-mcp` is the right choice when MCP is one capability of a larger Lauren
service — auth, DI, HTTP routes, and MCP all share the same app, the same
container, and the same guard pipeline.  It now covers nearly the full FastMCP
feature surface, adding WebSocket transport, non-Pydantic schema types, and
first-class DI in return for the Lauren framework dependency.

For greenfield, framework-free MCP servers, **FastMCP** is the fastest start.
For raw protocol control or tooling work, use the **official `mcp` SDK** directly.
