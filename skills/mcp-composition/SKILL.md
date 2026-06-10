---
skill: mcp-composition
version: 1.0.0
tags: [mcp, composition, mount, proxy, openapi, McpToolNameCollision, lauren-mcp]
summary: Combine multiple MCP servers via in-process mounting, remote proxying, and OpenAPI import.
---

# Skill: MCP Server Composition

## When to use this skill

Use this skill when you need to:
- Expose another `@mcp_server` class's tools/resources/prompts through a primary server
- Forward calls to a remote MCP server with local name prefixing
- Convert an OpenAPI 3.x spec into a set of `@mcp_tool` methods
- Understand `McpToolNameCollision` and how to avoid it

## Overview

`McpServerModule.for_root()` accepts two composition parameters:

- `mounts=[(OtherServerCls, "prefix_"), ...]` — in-process: expose another
  `@mcp_server` class's catalog entries with a name prefix applied
- `proxies=[(client, "prefix_"), ...]` — remote: connect a
  `McpClientProtocol`, fetch its tool catalog, and re-expose the tools locally

Both can be combined in a single `for_root()` call.

---

## `mounts=` — in-process server mounting

The mounted class's tools, resources, and prompts are registered in the
primary server's catalog with the given prefix prepended to every name.
Calls are dispatched to the DI-resolved instance of the mounted class.

```python
from __future__ import annotations
from lauren import LaurenFactory, module
from lauren_mcp import McpServerModule, mcp_server, mcp_tool

@mcp_server("/inventory")
class InventoryServer:
    @mcp_tool()
    async def check_stock(self, sku: str) -> int:
        """Check stock level for a SKU.

        Args:
            sku: Product SKU code.
        """
        return 42

    @mcp_tool()
    async def reserve(self, sku: str, qty: int) -> bool:
        """Reserve stock."""
        return True


@mcp_server("/mcp", transport="streamable")
class GatewayServer:
    @mcp_tool()
    async def ping(self) -> str:
        return "pong"


@module(imports=[
    McpServerModule.for_root(
        GatewayServer,
        transport="streamable",
        mounts=[
            (InventoryServer, "inv_"),   # exposes inv_check_stock, inv_reserve
        ],
    )
])
class AppModule:
    pass

app = LaurenFactory.create(AppModule)
```

Clients connecting to the gateway see: `ping`, `inv_check_stock`, `inv_reserve`.

**How it works internally:**
`make_mount_binder(mounted_cls, prefix)` returns an `@injectable(Singleton)`
that, at startup, clones each tool/resource/prompt meta with the prefix
applied, binds the meta to the DI-resolved instance of `mounted_cls`, and
calls `catalog.register_tool(meta, on_conflict="error")`.

---

## `proxies=` — remote server proxying

Connect a `McpClientProtocol` at startup, fetch its tool catalog, and
register each tool locally under `{prefix}{name}`. Calls are forwarded over
the client. The connection is closed at shutdown.

```python
from lauren_mcp import McpServer, McpServerModule, mcp_server, mcp_tool

@mcp_server("/mcp", transport="streamable")
class AggregatorServer:
    @mcp_tool()
    async def local_ping(self) -> str:
        return "local pong"


@module(imports=[
    McpServerModule.for_root(
        AggregatorServer,
        transport="streamable",
        proxies=[
            (McpServer.streamable_http("https://search.internal/mcp"), "search_"),
            (McpServer.streamable_http("https://analytics.internal/mcp"), "stats_"),
        ],
    )
])
class AppModule:
    pass
```

Clients see: `local_ping`, `search_<tool>`, `stats_<tool>`.

**How it works internally:**
`make_proxy_binder(client, prefix)` returns an `@injectable(Singleton)` that,
at startup, calls `client.connect()`, fetches `list_tools()`, and creates a
`McpToolMeta` for each remote tool bound to a `_RemoteToolTarget` adapter
that forwards `call_tool()` over the client.

---

## Combining mounts and proxies

```python
McpServerModule.for_root(
    GatewayServer,
    mounts=[
        (InventoryServer, "inv_"),
        (BillingServer, "bill_"),
    ],
    proxies=[
        (McpServer.streamable_http("https://search.internal/mcp"), "search_"),
        (McpServer.ws("ws://legacy.internal/mcp/ws"), "legacy_"),
    ],
)
```

All sources are merged into the same `McpCatalogManager`. Name collisions
across any combination of sources raise `McpToolNameCollision` at startup.

---

## `McpToolNameCollision`

Raised at startup when two composition sources produce the same prefixed
tool name. Fix it by choosing non-overlapping prefixes.

```python
from lauren_mcp import McpToolNameCollision

# This raises McpToolNameCollision if InventoryServer and BillingServer
# both have a tool named "status" and the same prefix is used:
try:
    McpServerModule.for_root(
        GatewayServer,
        mounts=[(InventoryServer, "svc_"), (BillingServer, "svc_")],
    )
except McpToolNameCollision as exc:
    print(f"Name conflict: {exc}")
    # Fix: use distinct prefixes like "inv_" and "bill_"
```

---

## `make_mount_binder` / `make_proxy_binder` — DI-native setup

Use these directly when you need fine-grained control over the DI graph
(e.g. when adding a mount to an existing module without calling `for_root`
again):

```python
from lauren_mcp.server._composition import make_mount_binder, make_proxy_binder
from lauren_mcp import McpServer

# In-process mount
mount_binder = make_mount_binder(InventoryServer, "inv_")

# Remote proxy
proxy_binder = make_proxy_binder(
    McpServer.streamable_http("https://search.internal/mcp"),
    "search_",
)

# Add both classes to providers= in your @module
@module(providers=[InventoryServer, mount_binder, proxy_binder])
class MyExtraModule:
    pass
```

`make_mount_binder(cls, prefix)` requires `cls` to be decorated with
`@mcp_server`, or raises `TypeError`.

---

## `build_openapi_server_class` — OpenAPI import

Convert an OpenAPI 3.x spec into an `@mcp_server` class whose tools call the
backing REST API. Intended for prototyping; hand-written tool descriptions
perform better with LLMs.

```python
import httpx
from lauren_mcp import build_openapi_server_class, McpServerModule, RouteEntry

http_client = httpx.AsyncClient(base_url="https://api.example.com")

ServerCls = build_openapi_server_class(
    "openapi.json",             # path, or a parsed dict
    http_client=http_client,
    base_url="",                # base_url already in client
    server_path="/mcp",
    route_map=[
        # Exclude health-check endpoint
        RouteEntry(pattern=r"/health", expose_as="exclude"),
        # Override name for a specific operation
        RouteEntry(pattern=r"/v2/search", method="GET",
                   name_override="search_v2",
                   description_override="Search with v2 syntax"),
    ],
    class_name="ExampleApiServer",
)

@module(imports=[McpServerModule.for_root(ServerCls)])
class AppModule:
    pass
```

**`RouteEntry` fields:**

```python
@dataclass
class RouteEntry:
    pattern: str               # regex matched against the path
    method: str | None = None  # "GET", "POST", ... or None for all methods
    expose_as: Literal["tool", "exclude"] = "tool"
    name_override: str | None = None
    description_override: str | None = None
```

The first matching rule wins. Operations with no matching entry default to
being exposed as tools.

**Tool names:** derived from `operationId` if present; otherwise
`{method}_{path}` with non-alphanumeric characters replaced by `_`.

**`from_lauren()` pattern** — import from a running Lauren app's own OpenAPI spec:

```python
import httpx
from lauren_mcp import build_openapi_server_class

# The Lauren app exposes /openapi.json automatically
async def build_from_lauren(app_url: str) -> type:
    async with httpx.AsyncClient(base_url=app_url) as hc:
        resp = await hc.get("/openapi.json")
        spec = resp.json()
    return build_openapi_server_class(spec, http_client=httpx.AsyncClient(base_url=app_url))
```

---

## Quick reference

| Approach | Latency | Shared DI | Use when |
|---|---|---|---|
| `mounts=` | ~0 (in-process) | Yes | Both servers in the same Lauren app |
| `proxies=` | network round-trip | No | Remote server; stable tool catalog |
| `build_openapi_server_class` | network round-trip | No | Wrapping a REST API |
