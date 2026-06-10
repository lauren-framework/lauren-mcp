# Using lauren-mcp with Lauren

This guide shows step-by-step how to build a production-grade application that
combines Lauren's HTTP controllers, DI container, guards, middleware, and SSE
with `lauren-mcp`'s MCP server and client support.

---

## Prerequisites

```bash
pip install "lauren-mcp[ws]" uvicorn
```

Import paths used throughout this guide:

```python
from lauren import (
    LaurenFactory, module, injectable, Scope,
    controller, get, post,
    ws_controller, on_connect, on_disconnect,
    AppState,
)
from lauren.testing import TestClient, WsTestClient
from lauren_mcp import (
    mcp_server, mcp_tool, mcp_resource, mcp_prompt,
    mcp_lifespan, McpServerModule, McpToolContext,
)
```

---

## 1. Minimal app: @module + LaurenFactory

The recommended pattern for production apps:

```python
# app.py
from __future__ import annotations

from lauren import LaurenFactory, module
from lauren_mcp import mcp_server, mcp_tool, McpServerModule

ITEMS = [
    {"id": 1, "name": "Widget A", "price": 9.99},
    {"id": 2, "name": "Widget B", "price": 14.99},
]


@mcp_server("/mcp")
class CatalogueServer:

    @mcp_tool()
    async def search(self, query: str) -> list[dict]:
        """Search items by name.

        Args:
            query: Search terms.
        """
        return [i for i in ITEMS if query.lower() in i["name"].lower()]

    @mcp_tool()
    async def get_item(self, item_id: int) -> dict | None:
        """Get an item by ID.

        Args:
            item_id: Numeric item ID.
        """
        return next((i for i in ITEMS if i["id"] == item_id), None)


@module(imports=[McpServerModule.for_root(CatalogueServer)])
class AppModule:
    pass


app = LaurenFactory.create(AppModule)
```

```bash
uvicorn app:app --port 8000
```

Clients connect at `ws://localhost:8000/mcp/ws`.

---

## 2. Choosing a transport

```python
# WebSocket only (default)
McpServerModule.for_root(MyServer, transport="ws")

# Streamable HTTP only (MCP 2025-03-26 — recommended for HTTP clients)
McpServerModule.for_root(MyServer, transport="streamable")

# Legacy HTTP + SSE only (MCP 2024-11-05)
McpServerModule.for_root(MyServer, transport="sse")

# WebSocket + legacy HTTP+SSE simultaneously
McpServerModule.for_root(MyServer, transport="both")

# WebSocket + Streamable HTTP simultaneously
McpServerModule.for_root(MyServer, transport="all")
```

| Transport | Client connects at |
|---|---|
| `"ws"` | `ws://host/mcp/ws` |
| `"streamable"` | `http://host/mcp/` (POST / GET / DELETE) |
| `"sse"` | `http://host/mcp/` (POST) + `http://host/mcp/sse` (GET SSE) |

> **Note**: Legacy SSE and Streamable HTTP both use `POST /` so they cannot be
> mounted on the same path. Use `"all"` (WebSocket + Streamable) rather than
> mixing SSE and Streamable.

---

## 3. Managing resources with @mcp_lifespan

`@mcp_lifespan` is the preferred way to set up resources that need to exist
for the lifetime of the server (database connections, HTTP client sessions,
caches, etc.).  The async generator runs once at startup; the dict it yields
becomes `McpToolContext.lifespan_context` for every tool call.  Cleanup code
in the `finally` block runs at shutdown.

```python
from __future__ import annotations

import asyncpg
from lauren import LaurenFactory, module
from lauren_mcp import mcp_server, mcp_tool, mcp_lifespan, McpServerModule, McpToolContext

DATABASE_URL = "postgresql://user:pass@localhost/shop"


@mcp_server("/mcp")
class CatalogueServer:

    @mcp_lifespan
    async def lifespan(self):
        # Connect once at startup; the pool is shared across all tool calls.
        pool = await asyncpg.create_pool(DATABASE_URL)
        try:
            yield {"db": pool}
        finally:
            await pool.close()

    @mcp_tool()
    async def search(self, query: str, ctx: McpToolContext) -> list[dict]:
        """Search items by name.

        Args:
            query: Search terms.
        """
        db = ctx.lifespan_context["db"]
        rows = await db.fetch(
            "SELECT id, name, price FROM items WHERE name ILIKE $1",
            f"%{query}%",
        )
        return [dict(r) for r in rows]

    @mcp_tool()
    async def get_item(self, item_id: int, ctx: McpToolContext) -> dict | None:
        """Fetch one item by ID.

        Args:
            item_id: Numeric item ID.
        """
        db = ctx.lifespan_context["db"]
        row = await db.fetchrow("SELECT * FROM items WHERE id = $1", item_id)
        return dict(row) if row else None


@module(imports=[McpServerModule.for_root(CatalogueServer)])
class AppModule:
    pass

app = LaurenFactory.create(AppModule)
```

> **Important**: `@mcp_lifespan` must be an async generator (a coroutine containing
> exactly one `yield`).  The framework raises `TypeError` if the method is a plain
> coroutine.  Each server class may have at most one `@mcp_lifespan` method.

---

## 4. McpToolContext injection

Declare a parameter typed `McpToolContext` on any `@mcp_tool` method to receive
the per-call context.  The framework detects the annotation and injects the
object automatically — it is not included in the tool's input schema.

```python
from lauren_mcp import McpToolContext

@mcp_tool()
async def process(self, payload: str, ctx: McpToolContext) -> str:
    """Process a payload.

    Args:
        payload: Data to process.
    """
    # Transport identity
    session_id   = ctx.session_id        # str | None
    headers      = ctx.headers           # lauren.types.Headers | None
    exec_ctx     = ctx.execution_context # lauren.types.ExecutionContext | None

    # Metadata set by guards / interceptors via @set_metadata
    tenant_id = ctx.get_metadata("tenant_id")   # or ctx.metadata["tenant_id"]

    # Shared resources from @mcp_lifespan
    db = ctx.lifespan_context.get("db")

    return payload.upper()
```

### Progress notifications

Send incremental progress to the client while a long-running tool is working.
The client must have supplied a `progressToken` in its `tools/call` request;
`report_progress` is a no-op when no token is present.

```python
@mcp_tool()
async def index_documents(self, paths: list[str], ctx: McpToolContext) -> dict:
    """Index a list of documents.

    Args:
        paths: File paths to index.
    """
    total = len(paths)
    for i, path in enumerate(paths, 1):
        await _index_one(path)
        await ctx.report_progress(i, total)
    return {"indexed": total}
```

### Log notifications

Send structured log entries to the client in real time.  Entries below the
server's configured `log_level` are dropped silently.

```python
@mcp_tool()
async def run_pipeline(self, job_id: str, ctx: McpToolContext) -> dict:
    """Run a data pipeline job.

    Args:
        job_id: Job identifier.
    """
    await ctx.info("Pipeline started", {"job_id": job_id})
    try:
        result = await _execute(job_id)
        await ctx.info("Pipeline complete", {"rows": result["rows"]})
        return result
    except Exception as exc:
        await ctx.error("Pipeline failed", {"error": str(exc)})
        raise
```

Convenience methods: `ctx.debug()`, `ctx.info()`, `ctx.warning()`, `ctx.error()`.
All call `ctx.log(level, message, data)` internally.

---

## 5. Controlling log level

The `log_level` parameter on `for_root()` sets the minimum severity for
client-bound log notifications (default: `"debug"`).  Valid values are
`"debug"`, `"info"`, `"warning"`, and `"error"`.

```python
McpServerModule.for_root(
    MyServer,
    transport="streamable",
    log_level="info",   # suppress debug-level log notifications
)
```

Clients may raise the threshold at runtime by sending `logging/setLevel`.

---

## 6. HTTP controllers + MCP server in the same app

HTTP routes and MCP endpoints share the same DI container and app lifecycle:

```python
from lauren import LaurenFactory, module, controller, get

@controller("/api")
class CatalogueController:
    """REST API alongside the MCP server."""

    @get("/items")
    async def list_items(self) -> list[dict]:
        return ITEMS

    @get("/items/{item_id}")
    async def get_item(self, item_id: int) -> dict:
        item = next((i for i in ITEMS if i["id"] == item_id), None)
        if item is None:
            from lauren.types import Response
            return Response.json({"error": "not found"}, status=404)
        return item


@module(
    controllers=[CatalogueController],
    imports=[McpServerModule.for_root(CatalogueServer)],
)
class AppModule:
    pass


app = LaurenFactory.create(AppModule)
```

- `GET /api/items` → JSON list of all items
- `GET /api/items/1` → single item
- `ws://host/mcp/ws` → MCP WebSocket endpoint

---

## 7. Dependency injection into @mcp_server

Pass your service classes via `providers=` so the DI container injects them
into your `@mcp_server` class constructor:

```python
from lauren import injectable, Scope

@injectable(scope=Scope.SINGLETON)
class PricingService:
    def apply_discount(self, price: float, pct: float) -> float:
        return round(price * (1 - pct / 100), 2)


@mcp_server("/mcp")
class ShopServer:
    # Lauren injects PricingService automatically
    def __init__(self, pricing: PricingService) -> None:
        self._pricing = pricing

    @mcp_tool()
    async def discounted_price(self, price: float, discount_pct: float) -> float:
        """Apply a discount and return the new price.

        Args:
            price: Original price.
            discount_pct: Discount percentage (0–100).
        """
        return self._pricing.apply_discount(price, discount_pct)


@module(
    imports=[
        McpServerModule.for_root(
            ShopServer,
            providers=[PricingService],   # make PricingService visible
        )
    ]
)
class AppModule:
    pass
```

To share a service between HTTP controllers and the MCP server, export it from
a dedicated module and import it on both sides:

```python
@module(providers=[PricingService], exports=[PricingService])
class PricingModule:
    pass


@module(
    controllers=[PriceController],
    imports=[
        PricingModule,                                                  # HTTP side
        McpServerModule.for_root(ShopServer, imports=[PricingModule]), # MCP side
    ],
)
class AppModule:
    pass
```

> **Lauren module encapsulation rule**: a provider may only be declared in one
> module.  If both the outer `AppModule` and `for_root(providers=[...])` declare
> `PricingService`, Lauren raises `ModuleExportViolation`.  Declare a shared
> service in exactly one `@module(exports=[...])` module and import it everywhere
> else.

---

## 8. The @set_metadata → ctx.get_metadata() flow

Guards and interceptors can attach metadata to a connection using
`@set_metadata`.  Tools receive this metadata through `McpToolContext.metadata`
(or the convenience method `ctx.get_metadata(key)`).

```python
from lauren import injectable, Scope, use_guards, set_metadata

@injectable(scope=Scope.SINGLETON)
class TenantGuard:
    async def can_activate(self, ctx) -> bool:
        tenant = ctx.request.headers.get("x-tenant-id")
        if not tenant:
            return False
        # Store tenant for tools to read
        ctx.state.set("tenant_id", tenant)
        return True


@use_guards(TenantGuard)
@set_metadata("require_tenant", True)
@mcp_server("/mcp")
class TenantServer:
    @mcp_tool()
    async def get_data(self, ctx: McpToolContext) -> dict:
        """Fetch tenant-scoped data."""
        tenant_id = ctx.get_metadata("tenant_id")
        return {"tenant": tenant_id, "data": [...]}
```

The `@set_metadata` values set on the class are available as
`ctx.metadata["require_tenant"]`; values set dynamically via `ctx.state` in a
guard arrive via the `execution_context` on the binding.

---

## 9. Guards

### @use_guards directly on @mcp_server

Stack `@use_guards(...)` directly on your `@mcp_server` class — no middleware,
no extra wiring.  Guards are checked **at connection time** (before the MCP
handshake); rejected clients receive close code `1008` (Policy Violation) for
WebSocket, or `403` for HTTP transports.

```python
from lauren import injectable, Scope, use_guards
from lauren_mcp import mcp_server, mcp_tool, McpServerModule

@injectable(scope=Scope.SINGLETON)
class ApiKeyGuard:
    async def can_activate(self, ctx) -> bool:
        # ctx.request.headers holds the WS upgrade or HTTP request headers
        return ctx.request.headers.get("x-api-key") == "secret-key"


@use_guards(ApiKeyGuard)          # stacked directly on @mcp_server
@mcp_server("/mcp")
class SecureServer:
    @mcp_tool()
    async def secret(self) -> str:
        "Run a secured action."
        return "classified"


@module(imports=[McpServerModule.for_root(SecureServer)])
class AppModule:
    pass

app = LaurenFactory.create(AppModule)
TestClient(app)  # triggers @post_construct
```

`ApiKeyGuard` is injected automatically — no need to add it to `providers=`.

**Multiple guards:**

```python
@use_guards(ApiKeyGuard, RateLimitGuard)
@mcp_server("/mcp")
class SecureServer: ...
```

All guards are checked in order; the first rejection closes the connection.

### Guards with DI dependencies

Guards are resolved from Lauren's DI container.  If a guard needs a service,
inject it via the constructor:

```python
@injectable(scope=Scope.SINGLETON)
class TokenAuthGuard:
    def __init__(self, token_store: TokenStore) -> None:
        self._store = token_store

    async def can_activate(self, ctx) -> bool:
        token = ctx.request.headers.get("authorization", "")
        return await self._store.is_valid(token)


@use_guards(TokenAuthGuard)
@mcp_server("/mcp")
class SecureServer: ...


@module(
    imports=[McpServerModule.for_root(SecureServer, providers=[TokenStore])]
)
class AppModule: ...
```

### Global guard on HTTP routes only

Global guards apply to HTTP routes only, not to WebSocket connections.  Use
`@use_guards` on the server class for MCP, and `global_guards=` for HTTP:

```python
app = LaurenFactory.create(AppModule, global_guards=[SomeHttpGuard])
```

---

## 10. Middleware

Middleware wraps every HTTP request/response in an onion model.

### Global middleware (logging)

```python
import logging, time
from lauren import middleware
from lauren.types import Request, Response, CallNext

logger = logging.getLogger(__name__)

@middleware()
class LoggingMiddleware:
    async def dispatch(self, request: Request, call_next: CallNext) -> Response:
        t0 = time.monotonic()
        response = await call_next(request)
        logger.info(
            "%s %s → %d (%.0fms)",
            request.method, request.path, response.status_code,
            (time.monotonic() - t0) * 1000,
        )
        return response


app = LaurenFactory.create(AppModule, global_middlewares=[LoggingMiddleware])
```

### Class-level middleware

```python
from lauren import use_middlewares

@use_middlewares(CachingMiddleware)
@controller("/api/v1")
class CachedController:
    @get("/items")
    async def items(self) -> list[dict]:
        return ITEMS
```

---

## 11. Interceptors

Interceptors wrap the handler call and can transform responses.  They run
after guards but before the handler, and receive the handler's return value.

> **Important**: By the time an interceptor's `call_handler.handle()` returns,
> Lauren has already converted the handler's dict/model return value to a
> `Response` object.  Interceptors should check `isinstance(result, Response)`.

### Global interceptor

```python
from lauren import injectable, Scope
from lauren.types import ExecutionContext, CallHandler, Response

@injectable(scope=Scope.SINGLETON)
class TimingInterceptor:
    async def intercept(self, ctx: ExecutionContext, call_handler: CallHandler) -> Any:
        import time
        t0 = time.monotonic()
        result = await call_handler.handle()
        elapsed_ms = (time.monotonic() - t0) * 1000
        if isinstance(result, Response):
            return result.with_header("x-elapsed-ms", f"{elapsed_ms:.1f}")
        return result


app = LaurenFactory.create(AppModule, global_interceptors=[TimingInterceptor])
```

---

## 12. Using AppState for shared read-only config

`AppState` is set before startup and read-only after.  Both HTTP controllers
and MCP server methods can access it via a service:

```python
from lauren import AppState, injectable, Scope

@injectable(scope=Scope.SINGLETON)
class AppConfig:
    def __init__(self, state: AppState) -> None:
        self._state = state

    @property
    def currency(self) -> str:
        return self._state.get("currency", "USD")


@mcp_server("/mcp")
class PricingServer:
    def __init__(self, config: AppConfig) -> None:
        self._config = config

    @mcp_tool()
    async def format_price(self, amount: float) -> str:
        """Format a price with the app currency.

        Args:
            amount: Numeric amount.
        """
        return f"{amount:.2f} {self._config.currency}"


app = LaurenFactory.create(
    AppModule,
    app_state=AppState({"currency": "GBP"}),
)
```

---

## 13. Custom server metadata

```python
from lauren_mcp._types import Implementation, ServerCapabilities

McpServerModule.for_root(
    MyServer,
    server_info=Implementation(name="My Service", version="2.0.0"),
    capabilities=ServerCapabilities(
        tools={"listChanged": False},
        resources={"listChanged": False},
    ),
)
```

---

## 14. Testing

### In-process WS testing (fastest)

```python
import asyncio, json, pytest
from lauren import LaurenFactory, module
from lauren.testing import TestClient, WsTestClient
from lauren_mcp import mcp_server, mcp_tool, McpServerModule

@mcp_server("/mcp")
class EchoServer:
    @mcp_tool()
    async def echo(self, text: str) -> str:
        "Echo. Args: text: Input."
        return text

@pytest.fixture(scope="module")
def app():
    @module(imports=[McpServerModule.for_root(EchoServer)])
    class App: pass
    a = LaurenFactory.create(App)
    TestClient(a)   # triggers @post_construct — REQUIRED
    return a

async def test_echo(app):
    async with WsTestClient(app).connect("/mcp/ws") as ws:
        # Handshake
        await ws.send_json({"jsonrpc":"2.0","id":1,"method":"initialize",
                            "params":{"protocolVersion":"2025-03-26","capabilities":{},
                                      "clientInfo":{"name":"test","version":"1"}}})
        await asyncio.wait_for(ws.receive_json(), timeout=3.0)
        await ws.send_json({"jsonrpc":"2.0","method":"notifications/initialized"})
        # Call tool
        await ws.send_json({"jsonrpc":"2.0","id":2,"method":"tools/call",
                            "params":{"name":"echo","arguments":{"text":"hello"}}})
        resp = await asyncio.wait_for(ws.receive_json(), timeout=3.0)
        assert resp["result"]["content"][0]["text"] == "hello"
```

> **Critical**: call `TestClient(app)` after `LaurenFactory.create(app)` to
> trigger `@post_construct` hooks before connecting via `WsTestClient`.  Without
> this step the `initialize` handler is not registered and every call returns
> `Method not found`.

---

## 15. Inspecting MCP server metadata with lauren.reflect

`lauren>=1.6.0` ships a full metadata introspection API.  You can read guard,
interceptor, and metadata annotations from any `@mcp_server` class without
touching internal `__dict__` attributes:

```python
from lauren.reflect import (
    reflect_guards,
    reflect_interceptors,
    reflect_user_metadata,
    reflect_all,
    get_all_routes,
    get_all_ws_gateways,
)

@use_guards(ApiKeyGuard, RateLimitGuard)
@set_metadata("rate_limit", 100)
@mcp_server("/mcp")
class MyServer: ...

reflect_guards(MyServer)             # (ApiKeyGuard, RateLimitGuard)
reflect_user_metadata(MyServer)      # {"rate_limit": 100}
meta = reflect_all(MyServer)         # ReflectedMeta(guards=…, interceptors=…, middlewares=…)
```

After the app has started, query the compiled dispatch table:

```python
app = LaurenFactory.create(AppModule)
TestClient(app)  # triggers startup

for gw in get_all_ws_gateways(app):
    print(gw.path_template, gw.guards)   # "/mcp/ws"  (ApiKeyGuard, RateLimitGuard)

for route in get_all_routes(app):
    print(route.method, route.full_path)  # POST /mcp/  GET /mcp/  ...
```

### Propagating guards with @propagate_metadata

When multiple MCP servers share the same auth policy, use `@propagate_metadata`
to avoid repeating `@use_guards` on every class:

```python
from lauren import propagate_metadata

@use_guards(ApiKeyGuard)
@set_metadata("require_auth", True)
class _AuthPolicy:
    pass

@propagate_metadata(_AuthPolicy)
@mcp_server("/catalogue")
class CatalogueServer: ...

@propagate_metadata(_AuthPolicy)
@mcp_server("/inventory")
class InventoryServer: ...
```

---

## 16. Full production app example

```python
# main.py — production app combining HTTP, MCP, DI, lifespan, middleware
from __future__ import annotations

import asyncpg
from lauren import (
    LaurenFactory, module, controller, get, post,
    injectable, Scope, middleware,
)
from lauren.types import Request, Response, CallNext
from lauren_mcp import (
    mcp_server, mcp_tool, mcp_resource, mcp_lifespan,
    McpServerModule, McpToolContext,
)

DATABASE_URL = "postgresql://user:pass@localhost/shop"


@injectable(scope=Scope.SINGLETON)
class ItemStore:
    """Shared in-memory item store used by both HTTP and MCP."""

    def __init__(self) -> None:
        self._items: list[dict] = [
            {"id": 1, "name": "Widget A", "price": 9.99},
            {"id": 2, "name": "Widget B", "price": 14.99},
        ]

    def search(self, query: str) -> list[dict]:
        q = query.lower()
        return [i for i in self._items if q in i["name"].lower()]

    def get(self, item_id: int) -> dict | None:
        return next((i for i in self._items if i["id"] == item_id), None)

    def add(self, name: str, price: float) -> dict:
        item = {"id": len(self._items) + 1, "name": name, "price": price}
        self._items.append(item)
        return item


@controller("/api/v1")
class ItemController:
    """REST API for item management."""

    def __init__(self, store: ItemStore) -> None:
        self._store = store

    @get("/items")
    async def list_items(self, q: str = "") -> list[dict]:
        return self._store.search(q) if q else self._store._items

    @post("/items")
    async def create_item(self, name: str, price: float) -> dict:
        return self._store.add(name, price)


@mcp_server("/mcp", transport="all")   # WebSocket + Streamable HTTP
class ItemMcpServer:
    """MCP server exposing the item store to AI clients."""

    def __init__(self, store: ItemStore) -> None:
        self._store = store

    @mcp_lifespan
    async def lifespan(self):
        # Example: open a read-only analytics connection at startup.
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=3)
        try:
            yield {"analytics_db": pool}
        finally:
            await pool.close()

    @mcp_tool()
    async def search_items(self, query: str, ctx: McpToolContext) -> list[dict]:
        """Search items by name. Args: query: Search terms."""
        await ctx.info("Searching", {"query": query})
        return self._store.search(query)

    @mcp_tool()
    async def analytics_summary(self, ctx: McpToolContext) -> dict:
        """Return a summary from the analytics DB."""
        db = ctx.lifespan_context["analytics_db"]
        count = await db.fetchval("SELECT COUNT(*) FROM events")
        return {"total_events": count}

    @mcp_resource("/items/{item_id}")
    async def item_card(self, item_id: str) -> str:
        """Item as plain text. Args: item_id: Numeric ID."""
        item = self._store.get(int(item_id))
        return f"{item['name']} — ${item['price']:.2f}" if item else "Not found"


@middleware()
class RequestLogger:
    async def dispatch(self, request: Request, call_next: CallNext) -> Response:
        print(f"→ {request.method} {request.path}")
        return await call_next(request)


@module(
    controllers=[ItemController],
    providers=[ItemStore],
    imports=[
        McpServerModule.for_root(
            ItemMcpServer,
            providers=[ItemStore],
            log_level="info",
        )
    ],
)
class AppModule:
    pass


app = LaurenFactory.create(AppModule, global_middlewares=[RequestLogger])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

> **Note**: `ItemStore` is declared in both the outer module and the MCP
> sub-module's `providers=`.  Lauren resolves each independently as a
> SINGLETON within its own module scope.  If you need the SAME instance,
> use a shared module with `exports=[ItemStore]` and `imports=[SharedModule]`.

---

## Next steps

- **[Decorators in depth](decorators.md)** — full `@mcp_tool`/`@mcp_resource`/`@mcp_prompt` reference
- **[Multiple servers](multiple-servers.md)** — composition, proxies, and OpenAPI import
- **[Error handling](error-handling.md)** — `McpCallError`, retry patterns
- **[Testing](testing.md)** — subprocess e2e, WsTestClient, mock clients
- **[MCP Server API](mcp-server.md)** — complete reference
