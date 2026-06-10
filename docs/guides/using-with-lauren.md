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
    post_construct, pre_destruct,
    AppState,
)
from lauren.testing import TestClient, WsTestClient
from lauren_mcp import mcp_server, mcp_tool, mcp_resource, mcp_prompt, McpServerModule
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

## 2. HTTP controllers + MCP server in the same app

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

## 3. Dependency injection into @mcp_server

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
            providers=[PricingService],   # ← make PricingService visible
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
        PricingModule,                                             # HTTP side
        McpServerModule.for_root(ShopServer, imports=[PricingModule]),  # MCP side
    ],
)
class AppModule:
    pass
```

Alternatively, export a service FROM `for_root()` so the parent module can see it:

```python
@module(
    imports=[
        McpServerModule.for_root(
            ShopServer,
            providers=[PricingService],
            exports=[PricingService],   # PricingService is visible to AppModule
        )
    ]
)
class AppModule:
    pass
```

> **Lauren module encapsulation rule**: a provider may only be declared in one module.
> If both the outer `AppModule` and `for_root(providers=[...])` declare `PricingService`,
> Lauren raises `ModuleExportViolation`.  Declare a shared service in exactly one
> `@module(exports=[...])` module and import it everywhere else.

---

## 4. Using AppState for shared read-only config

`AppState` is set before startup and read-only after. Both HTTP controllers
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

## 5. Guards

### `@use_guards` directly on `@mcp_server` ✅

Stack `@use_guards(...)` directly on your `@mcp_server` class — no middleware,
no extra wiring.  Guards are checked **at connection time** (before the MCP
handshake); rejected clients receive close code `1008` (Policy Violation).

```python
from lauren import injectable, Scope, use_guards
from lauren_mcp import mcp_server, mcp_tool, McpServerModule

@injectable(scope=Scope.SINGLETON)
class ApiKeyGuard:
    async def can_activate(self, ctx) -> bool:
        # ctx.request.headers holds the WS upgrade request headers
        return ctx.request.headers.get("x-api-key") == "secret-key"


@use_guards(ApiKeyGuard)          # ← stacked directly on @mcp_server
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

**Connection flow:**

```
Client → WS upgrade (X-Api-Key: secret-key)
           ↓
        ApiKeyGuard.can_activate(ctx)  →  True  →  ws.accept()  →  MCP handshake
                                        →  False →  ws.close(1008)
```

**Multiple guards:**

```python
@use_guards(ApiKeyGuard, RateLimitGuard)
@mcp_server("/mcp")
class SecureServer: ...
```

All guards are checked in order; the first rejection closes the connection.

**Guard context:** Inside `can_activate(ctx)`, access the WS upgrade headers:

```python
@injectable(scope=Scope.SINGLETON)
class BearerGuard:
    async def can_activate(self, ctx) -> bool:
        auth = ctx.request.headers.get("authorization", "")
        if not auth.startswith("Bearer "):
            return False
        token = auth[len("Bearer "):]
        return await self._verify(token)  # async verify OK
```

### `@use_guards` on `@mcp_server` with DI dependencies

Guards are resolved from Lauren's DI container per-connection (REQUEST scope).
If a guard needs a service, inject it via the constructor:

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

Global guards apply to HTTP routes only, not to WS connections.  Use
`@use_guards` on the server class for MCP, and `global_guards=` for HTTP:

```python
app = LaurenFactory.create(AppModule, global_guards=[SomeHttpGuard])
```

### Class-level guard on an HTTP controller

```python
from lauren import controller, get, use_guards

@use_guards(RoleGuard)
@controller("/admin")
class AdminController:
    @get("/dashboard")
    async def dashboard(self) -> dict:
        return {"page": "dashboard"}
```

---

## 6. Middleware

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

Only routes in `CachedController` pass through `CachingMiddleware`.

### Request mutation via middleware

```python
@middleware()
class AuthMiddleware:
    async def dispatch(self, request: Request, call_next: CallNext) -> Response:
        token = request.headers.get("authorization", "")
        request.state.set("user_id", _decode_token(token))
        return await call_next(request)

# In your handler:
@get("/me")
async def me(self, request: Request) -> dict:
    return {"user_id": request.state.get("user_id")}
```

---

## 6b. Interceptors

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

### Class-level interceptor

```python
from lauren import use_interceptors

@use_interceptors(TimingInterceptor)
@controller("/api")
class TimedController:
    @get("/data")
    async def data(self) -> dict:
        return {"items": []}
```

### Method-level interceptor

```python
@controller("/api")
class MixedController:
    @use_interceptors(TimingInterceptor)   # only this route is timed
    @get("/slow")
    async def slow(self) -> dict:
        return {"ok": True}

    @get("/fast")
    async def fast(self) -> dict:
        return {"ok": True}
```

### Multiple interceptors

Interceptors compose in order: `[A, B]` runs `A-before → B-before → handler
→ B-after → A-after`.

```python
app = LaurenFactory.create(
    AppModule,
    global_interceptors=[AuthInterceptor, TimingInterceptor],
)
```

---

## 7. Choosing a transport

```python
# WebSocket only (default)
McpServerModule.for_root(MyServer, transport="ws")

# HTTP + SSE only
McpServerModule.for_root(MyServer, transport="sse")

# Both simultaneously
McpServerModule.for_root(MyServer, transport="both")
```

| Transport | Client connects at |
|---|---|
| `"ws"` | `ws://host/mcp/ws` |
| `"sse"` | `http://host/mcp/` (POST) + `http://host/mcp/sse` (GET SSE) |

---

## 8. Custom server metadata

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

## 9. @post_construct and @pre_destruct hooks

Both `@post_construct` and `@pre_destruct` work on any injectable in the module:

```python
from lauren import injectable, Scope, post_construct, pre_destruct

@injectable(scope=Scope.SINGLETON)
class DatabasePool:
    @post_construct
    async def open(self) -> None:
        self._pool = await create_pool(...)

    @pre_destruct
    async def close(self) -> None:
        await self._pool.close()


@mcp_server("/mcp")
class DataServer:
    def __init__(self, db: DatabasePool) -> None:
        self._db = db

    @mcp_tool()
    async def query(self, sql: str) -> list[dict]:
        """Run a SQL query. Args: sql: SQL statement."""
        return await self._db.execute(sql)


@module(
    imports=[McpServerModule.for_root(DataServer, providers=[DatabasePool])]
)
class AppModule:
    pass
```

`DatabasePool.open()` runs at startup; `DatabasePool.close()` runs at shutdown.

---

## 10. Testing

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

### Testing HTTP routes alongside MCP

```python
def test_rest_and_mcp(app):
    client = TestClient(app)
    # HTTP endpoint
    resp = client.get("/api/items")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

async def test_mcp_ws(app):
    async with WsTestClient(app).connect("/mcp/ws") as ws:
        # ... MCP protocol
```

### Subprocess E2E (tests the real Lauren app boot)

```python
import sys, os, tempfile, textwrap
from lauren_mcp import McpServer

_APP_SCRIPT = textwrap.dedent("""
    from lauren import LaurenFactory, module
    from lauren_mcp import mcp_server, mcp_tool, McpServerModule
    import sys, json, asyncio

    @mcp_server("/mcp")
    class S:
        @mcp_tool()
        async def ping(self) -> str:
            "Ping."
            return "pong"

    @module(imports=[McpServerModule.for_root(S, transport="ws")])
    class App: pass
    # ... stdio runner (see tests/end_to_end/)
""")
```

---

## 11. Full production app example

```python
# main.py — production app combining HTTP, MCP, DI, middleware
from __future__ import annotations

from lauren import (
    LaurenFactory, module, controller, get, post,
    injectable, Scope, middleware,
)
from lauren.types import Request, Response, CallNext
from lauren_mcp import mcp_server, mcp_tool, mcp_resource, McpServerModule


@injectable(scope=Scope.SINGLETON)
class ItemStore:
    """Shared data store used by both HTTP and MCP."""

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


@mcp_server("/mcp")
class ItemMcpServer:
    """MCP server exposing the same item store to AI clients."""

    def __init__(self, store: ItemStore) -> None:
        self._store = store

    @mcp_tool()
    async def search_items(self, query: str) -> list[dict]:
        """Search items by name. Args: query: Search terms."""
        return self._store.search(query)

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
            imports=[],
            providers=[ItemStore],  # shared from same pool via DI
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
- **[Error handling](error-handling.md)** — `McpCallError`, retry patterns
- **[Testing](testing.md)** — subprocess e2e, WsTestClient, mock clients
- **[MCP Server API](mcp-server.md)** — complete reference
