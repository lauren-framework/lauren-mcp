# Lauren MCP

> Model Context Protocol server and client for the Lauren web framework.

`lauren-mcp` adds two capabilities to any Lauren application:

**Server** — expose any Lauren service as an MCP server that AI clients can discover and call,
with automatic JSON Schema generation, DI-aware dispatch, and full protocol lifecycle management:

```python
from lauren_mcp import mcp_server, mcp_tool, mcp_lifespan, McpServerModule
from lauren_mcp import ToolAnnotations, McpToolContext

@mcp_server("/mcp")
class SearchServer:
    @mcp_lifespan
    async def lifespan(self):
        db = await connect_db()
        try:
            yield {"db": db}
        finally:
            await db.close()

    @mcp_tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def search(self, query: str, limit: int = 10, ctx: McpToolContext = None) -> list[dict]:
        """Search the catalogue.

        Args:
            query: Search terms to match against item names and tags.
            limit: Maximum number of results to return.
        """
        await ctx.report_progress(0, 1)
        results = await ctx.lifespan_context["db"].search(query, limit=limit)
        await ctx.report_progress(1, 1)
        return results
```

**Client** — connect to any MCP server over stdio, WebSocket, or HTTP and consume its tools:

```python
from lauren_mcp import McpServer

# Streamable HTTP (MCP 2025-03-26)
client = McpServer.streamable_http("http://localhost:8000/mcp")
await client.connect()
tools = await client.list_tools()
result = await client.call_tool("search", {"query": "widget"})
await client.close()
```

## Installation

| Command | What you get |
|---|---|
| `pip install lauren-mcp` | Core: server decorators + stdio client |
| `pip install "lauren-mcp[ws]"` | + WebSocket client (`websockets`) |
| `pip install "lauren-mcp[http]"` | + HTTP+SSE and Streamable HTTP clients (`httpx`) |
| `pip install "lauren-mcp[pydantic]"` | + rich JSON Schema generation for Pydantic models |
| `pip install "lauren-mcp[msgspec]"` | + rich JSON Schema generation for `msgspec.Struct` |
| `pip install "lauren-mcp[all]"` | All transports + pydantic + msgspec |

## What's included

### Server

- `@mcp_server(path, transport=...)` — marks a class as an MCP server; registers it with Lauren DI
- `@mcp_tool(...)` — exposes a method as a callable tool with full JSON Schema generation
- `@mcp_resource(uri_template)` — exposes a method as a readable MCP resource
- `@mcp_prompt(name)` — exposes a method as an MCP prompt template
- `@mcp_lifespan` — async generator hook for startup/shutdown lifecycle
- `McpServerModule.for_root(cls)` — builds a Lauren `@module` that mounts the transport controllers

#### Transports

| Value | Description | Protocol |
|---|---|---|
| `"ws"` (default) | WebSocket | any |
| `"sse"` | Legacy HTTP+SSE | MCP 2024-11-05 |
| `"streamable"` | Streamable HTTP | MCP 2025-03-26 |
| `"both"` | WebSocket + legacy SSE | — |
| `"all"` | WebSocket + Streamable HTTP | — |

#### Tool features

- **Rich type annotations** — `BaseModel`, `msgspec.Struct`, `@dataclass`, `TypedDict`,
  `Literal[...]`, `Annotated[T, Field(ge=0)]`, `list[str]`, `dict[str, int]` all produce
  proper JSON Schema in `tools/list`
- **Docstring extraction** — Google, Sphinx, and NumPy docstring styles are parsed for
  per-parameter descriptions
- **`McpToolContext`** — inject a context parameter to access `ctx.headers`,
  `ctx.session_id`, `ctx.lifespan_context`, send progress reports, emit structured logs,
  make server-initiated LLM calls (`ctx.sample()`), and elicit user input (`ctx.elicit()`)
- **`ToolAnnotations`** — `readOnlyHint`, `destructiveHint`, `idempotentHint`,
  `openWorldHint` transmitted to clients in `tools/list`
- **`output_schema`** — advertise the structured JSON output schema alongside regular content

### Client

- `McpServer.stdio(command)` — launch a subprocess MCP server
- `McpServer.ws(url)` — connect over WebSocket
- `McpServer.http(url)` — connect via legacy HTTP+SSE (MCP 2024-11-05)
- `McpServer.streamable_http(url)` — connect via Streamable HTTP (MCP 2025-03-26)
- `client.protocol_version` — the negotiated protocol version (available after `connect()`)
- `client.on_progress()` / `client.on_log()` / `client.on_list_changed()` — subscribe to
  server notifications; each returns an unsubscribe callable
- `client.notify_roots_changed()` — push updated roots to the server

### Server composition

`McpServerModule.for_root(Cls, mounts=[(OtherCls, "prefix_")], proxies=[(client, "prefix_")])`
lets you merge multiple MCP servers — local or remote — under a single endpoint with
name-prefixed tool namespacing.

### OpenAPI import

```python
from lauren_mcp.server import build_openapi_server_class, RouteEntry
```

Generates an `@mcp_server` class from an OpenAPI spec so any REST API becomes an MCP server
without manual decoration.

## Quick links

- [Getting Started](getting-started/index.md)
- [MCP Server guide](guides/mcp-server.md)
- [MCP Client guide](guides/mcp-client.md)
- [API Reference](reference/index.md)
