# Comparisons

> How `lauren-mcp` stacks up against the other Python MCP libraries.

---

## FastMCP

[FastMCP](https://github.com/jlowin/fastmcp) is the most widely-used standalone
Python MCP library. It ships its own minimal ASGI-like server and is designed to
be picked up quickly without any existing framework.

### At a glance

| Capability | `lauren-mcp` | FastMCP |
|---|---|---|
| **Decorator API** | `@mcp_server`, `@mcp_tool`, `@mcp_resource`, `@mcp_prompt` | `@mcp.tool`, `@mcp.resource`, `@mcp.prompt` |
| **Transport** | WebSocket + SSE (both built-in) | SSE + stdio (WebSocket via plugin) |
| **DI container** | Lauren's full DI (SINGLETON / REQUEST / TRANSIENT, Protocol binding, lifecycle hooks) | None — plain function injection |
| **Auth / Guards** | `@use_guards` on `@mcp_server`; same guard class works for HTTP + WS | Manual middleware / context variables |
| **Interceptors** | `@use_interceptors` — wraps `@on_connect`, timing, caching | Not supported |
| **Testing** | `WsTestClient` in-process, no subprocess needed | `fastmcp.testing.Client` (subprocess or in-process) |
| **Type schema** | Inferred from type annotations; Pydantic, dataclass, TypedDict, `msgspec.Struct` all work | Pydantic-first; `BaseModel` recommended |
| **Multi-server** | Multiple `@mcp_server` classes in one Lauren app, each at its own path | One `FastMCP` instance per process by default |
| **HTTP routes alongside MCP** | First-class — Lauren controllers and MCP servers share one `LaurenFactory.create()` | Not supported (MCP only) |
| **Client** | `McpStdioClient`, `McpSseClient` included | Built-in client |
| **Existing framework required** | Yes — requires `lauren>=1.6.0` | No — standalone |

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

### When to choose FastMCP

- You want the fastest possible path from zero to a working MCP server.
- Your project has no existing HTTP API and you do not expect one.
- You prefer a standalone package with no framework dependency.
- Your tooling needs are simple (no DI, no auth pipeline, no interceptors).

### When to choose lauren-mcp

- You are building or already have a Lauren application and want MCP as another
  transport alongside your REST / WebSocket / SSE routes.
- You need production auth — `@use_guards` on `@mcp_server` lets the same
  `ApiKeyGuard` or `JwtBearerGuard` protect both HTTP and MCP endpoints without
  duplicating logic.
- You need DI — tools and resources can declare `__init__` dependencies that
  Lauren resolves from the container (databases, caches, config, loggers).
- You need multi-server — multiple `@mcp_server` classes can coexist in one
  process at different paths, each with its own tool set.
- You want in-process testing with `WsTestClient` rather than subprocess stdio.

---

## mcp (Anthropic's official Python SDK)

The [official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
(`pip install mcp`) is the reference implementation maintained by Anthropic.

### At a glance

| Capability | `lauren-mcp` | `mcp` SDK |
|---|---|---|
| **API style** | Decorator-driven, class-based | Low-level `Server` object + handler registration |
| **Transport** | WebSocket + SSE | stdio + SSE (WebSocket experimental) |
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

### When to choose lauren-mcp

- You want ergonomic decorators and automatic schema inference instead of
  manually constructing `Tool` and `TextContent` objects.
- You are integrating MCP into an existing Lauren service.

---

## mcpx / other wrappers

Several community wrappers exist (`mcpx`, `mcp-framework`, etc.). They vary in
maturity and transport support. The comparison dimensions are the same as above:

| Question | lauren-mcp answer |
|---|---|
| Does it integrate with my web framework? | Yes — it *is* a Lauren package |
| Does it support DI? | Yes — full Lauren container |
| Does it support WebSocket transport? | Yes — built-in |
| Does it support SSE transport? | Yes — built-in |
| Can I share auth guards with my HTTP routes? | Yes — `@use_guards` works on `@mcp_server` |
| Can I test without a subprocess? | Yes — `WsTestClient` in-process |

---

## Summary

`lauren-mcp` is the right choice when MCP is one capability of a larger Lauren
service — auth, DI, HTTP routes, and MCP all share the same app, the same
container, and the same guard pipeline.

For greenfield, framework-free MCP servers, **FastMCP** is the fastest start.
For raw protocol control or tooling work, use the **official `mcp` SDK** directly.
