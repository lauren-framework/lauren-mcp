# Multiple MCP Servers

`lauren-mcp` offers three ways to combine tools from multiple MCP servers into
a single endpoint:

1. **`mounts=`** — embed another `@mcp_server` class's tools directly in the
   same app, with a name prefix.
2. **`proxies=`** — forward calls to a remote MCP server at runtime, again
   with a prefix.
3. **Two separate apps** — the traditional approach; still valid when you
   genuinely need independent transport endpoints.

Tool names are namespaced with a prefix so names from different sources never
collide.  If two sources produce the same name after prefixing, the server
raises `McpToolNameCollision` at startup.

---

## 1. Mounting a sibling server with mounts=

`mounts=[(OtherServerCls, "prefix_")]` exposes another `@mcp_server` class's
tools (and resources/prompts) through the primary server.  Both classes are
wired into the same Lauren DI graph, so they share services and the same
transport endpoint.

```python
from __future__ import annotations

from lauren import LaurenFactory, module
from lauren_mcp import mcp_server, mcp_tool, McpServerModule

# --- Secondary server (its /mcp-secondary path is never mounted as a controller) ---

@mcp_server("/mcp-secondary")
class AnalyticsServer:
    @mcp_tool()
    async def stats(self) -> dict:
        """Return site statistics."""
        return {"users": 42, "sessions": 128}

    @mcp_tool()
    async def top_pages(self, limit: int = 5) -> list[dict]:
        """Return the top pages by view count.

        Args:
            limit: Maximum number of pages to return.
        """
        return [{"path": "/home", "views": 1000}]


# --- Primary server ---

@mcp_server("/mcp")
class PrimaryServer:
    @mcp_tool()
    async def search(self, query: str) -> list[dict]:
        """Search items.

        Args:
            query: Search terms.
        """
        return [{"name": query}]


@module(
    imports=[
        McpServerModule.for_root(
            PrimaryServer,
            transport="ws",
            mounts=[(AnalyticsServer, "analytics_")],
        )
    ]
)
class App:
    pass


app = LaurenFactory.create(App)
```

The client connecting at `ws://host/mcp/ws` sees three tools:

```
search
analytics_stats
analytics_top_pages
```

> **Tip**: The path on the mounted class (`"/mcp-secondary"`) is ignored when
> using `mounts=`.  Only the primary server's path is registered as a transport
> endpoint.

### Shared services between mounted servers

Because both servers live in the same DI graph, you can inject shared services
into both via `providers=`:

```python
@injectable(scope=Scope.SINGLETON)
class AnalyticsDB:
    async def query(self, sql: str) -> list[dict]: ...


@mcp_server("/mcp-secondary")
class AnalyticsServer:
    def __init__(self, db: AnalyticsDB) -> None:
        self._db = db

    @mcp_tool()
    async def stats(self) -> dict:
        """Return statistics."""
        return await self._db.query("SELECT COUNT(*) FROM events")


@mcp_server("/mcp")
class PrimaryServer:
    @mcp_tool()
    async def ping(self) -> str:
        "Ping."
        return "pong"


@module(
    imports=[
        McpServerModule.for_root(
            PrimaryServer,
            transport="streamable",
            providers=[AnalyticsDB],
            mounts=[(AnalyticsServer, "analytics_")],
        )
    ]
)
class App:
    pass
```

---

## 2. Proxying a remote server with proxies=

`proxies=[(client, "prefix_")]` connects a remote MCP server at startup,
fetches its tool catalogue, and registers each tool locally under
`{prefix}{name}`.  Calls to those tools are forwarded over the client
connection.  The connection is closed cleanly at shutdown.

```python
from __future__ import annotations

from lauren import LaurenFactory, module
from lauren_mcp import mcp_server, mcp_tool, McpServer, McpServerModule


@mcp_server("/mcp")
class LocalServer:
    @mcp_tool()
    async def local_search(self, query: str) -> list[dict]:
        """Search locally.

        Args:
            query: Search terms.
        """
        return [{"name": query}]


# Connect to a remote analytics MCP server
remote = McpServer.streamable_http("http://analytics.internal/mcp")

@module(
    imports=[
        McpServerModule.for_root(
            LocalServer,
            transport="all",   # WebSocket + Streamable HTTP
            proxies=[(remote, "remote_")],
        )
    ]
)
class App:
    pass


app = LaurenFactory.create(App)
```

At startup the proxy binder:
1. Calls `remote.connect()` and runs the MCP handshake.
2. Fetches the remote `tools/list` and registers each tool as
   `remote_{tool_name}`.
3. Logs the count: `MCP proxy[remote_]: registered 4 remote tools`.

At shutdown `remote.close()` is called automatically.

You can proxy any transport — stdio, WebSocket, HTTP+SSE, or Streamable HTTP:

```python
proxies=[
    (McpServer.stdio(["python", "analytics_server.py"]), "analytics_"),
    (McpServer.ws("ws://search.internal/mcp/ws"),        "search_"),
    (McpServer.streamable_http("http://ocr.internal/mcp"), "ocr_"),
]
```

### McpToolNameCollision

If two sources produce the same tool name after applying their prefixes, the
server raises `McpToolNameCollision` during the `@post_construct` startup phase:

```
McpToolNameCollision: Tool name 'analytics_stats' is already registered
```

Choose prefixes that are unique across all sources.

---

## 3. Combining mounts and proxies

`mounts=` and `proxies=` can be used together.  All names are checked for
collisions against the full combined catalogue:

```python
remote = McpServer.streamable_http("http://billing.internal/mcp")

@module(
    imports=[
        McpServerModule.for_root(
            PrimaryServer,
            mounts=[(AnalyticsServer, "analytics_")],
            proxies=[(remote, "billing_")],
        )
    ]
)
class App:
    pass
```

Tools visible to clients: `{primary_tools}`, `analytics_{...}`, `billing_{...}`.

---

## 4. OpenAPI import

`build_openapi_server_class` wraps an existing REST API as an MCP server by
reading its OpenAPI spec.  Pass the result to `for_root()` like any
hand-written server class.

```python
import httpx
from lauren import LaurenFactory, module
from lauren_mcp import McpServerModule
from lauren_mcp.server import build_openapi_server_class, RouteEntry

ApiServer = build_openapi_server_class(
    "openapi.json",                                          # path, dict, or YAML file
    http_client=httpx.AsyncClient(base_url="https://api.example.com"),
    server_path="/mcp-api",
    route_map=[
        RouteEntry(r"/admin",   expose_as="exclude"),        # hide admin endpoints
        RouteEntry(r"/v2/",     expose_as="exclude"),        # hide v2 routes
        RouteEntry(r"/items",   method="GET", name_override="list_items",
                   description_override="List all catalogue items."),
    ],
)


@module(imports=[McpServerModule.for_root(ApiServer, transport="streamable")])
class App:
    pass
```

`RouteEntry` rules are evaluated in order; the first match wins.  Operations
with no matching rule are exposed as tools.  Operations with `expose_as="exclude"`
are omitted entirely.

> **Caveat**: Tool names and descriptions generated from `operationId` strings
> are lower quality than hand-crafted ones.  LLMs use tool descriptions heavily
> when selecting tools.  Consider using `description_override` on important
> operations, or wrapping the generated server with `mounts=` to add
> hand-written tools alongside it.

You can mount an OpenAPI server alongside a hand-written one:

```python
remote_api = build_openapi_server_class(spec, http_client=..., server_path="/unused")

@module(
    imports=[
        McpServerModule.for_root(
            PrimaryServer,
            mounts=[(remote_api, "api_")],
        )
    ]
)
class App:
    pass
```

---

## 5. Two separate apps (traditional approach)

When you genuinely need two independent transport endpoints (different paths,
different auth, different transports), run two separate Lauren apps:

```python
# app_a.py
@module(imports=[McpServerModule.for_root(ServerA, transport="ws")])
class AppA: pass

# app_b.py
@module(imports=[McpServerModule.for_root(ServerB, transport="streamable")])
class AppB: pass
```

> **Warning**: A single Lauren app cannot import two `for_root()` modules that
> declare the same provider class.  Lauren raises `ModuleExportViolation`.
> Use two separate `LaurenFactory.create()` calls (two separate ASGI apps)
> rather than two `for_root()` imports in one `@module`.

---

## 6. McpToolBridge for agent workloads

When you are building an agent rather than a server, use `McpToolBridge` to
aggregate tools from multiple MCP servers under aliases.  The bridge manages
lifecycle (`connect_all` / `disconnect_all`) and namespaces tools as
`{alias}__{tool_name}`.

```python
import asyncio
from lauren_mcp import McpServer, McpToolBridge, McpServerConfig

bridge = McpToolBridge([
    McpServerConfig(
        alias="fs",
        client=McpServer.stdio(["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]),
    ),
    McpServerConfig(
        alias="search",
        client=McpServer.streamable_http("http://search.internal/mcp"),
    ),
])

async def main():
    await bridge.connect_all()
    # tools available as fs__read_file, search__search, ...
    await bridge.disconnect_all()

asyncio.run(main())
```

A server that fails to connect is logged at `ERROR` level; remaining servers
continue loading and their tools are available.

See **[MCP Agent Tools](mcp-agent-tools.md)** for the full agent integration
guide.

---

## Next steps

- **[MCP Agent Tools](mcp-agent-tools.md)** — wiring MCP servers into agent loops
- **[Testing](testing.md)** — test multi-server setups with mock clients
- **[Error handling](error-handling.md)** — retry, timeout, and failure patterns
