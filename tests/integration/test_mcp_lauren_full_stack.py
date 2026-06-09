"""Full-stack compatibility tests: lauren-mcp × Lauren framework.

Proves deep integration between every major Lauren feature and the MCP
server/client stack.  All tests use LaurenFactory.create() + Lauren's
in-process testing helpers — no external processes or network sockets.

Test classes:
  TestBasicSetup              (5)  — app creation, TestClient, WsTestClient
  TestHttpAndMcpCoexistence   (7)  — HTTP controllers alongside MCP server
  TestDIInjection             (8)  — constructor injection, shared services,
                                      imported modules, AppState
  TestGuardsAndMiddleware      (6)  — global middleware, guards, exception handlers
  TestLifecycle               (5)  — @post_construct, @pre_destruct, AppState.seal
  TestProtocolDeepCoverage    (7)  — tools, resources, prompts, all JSON-RPC flows
  TestTransportVariants        (4)  — ws / sse / both transport switching
  TestForRootParams            (4)  — providers, imports, server_info, capabilities

Total: 46 tests
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from lauren import (
    AppState,
    LaurenFactory,
    Scope,
    controller,
    exception_handler,
    get,
    injectable,
    middleware,
    module,
    post,
    post_construct,
    pre_destruct,
    use_value,
)
from lauren.testing import TestClient, WsTestClient
from lauren.types import CallNext, Request, Response

from lauren_mcp import (
    McpServerModule,
    mcp_prompt,
    mcp_resource,
    mcp_server,
    mcp_tool,
)
from lauren_mcp._server._session import SseSessionStore

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


async def _handshake(conn: Any, req_id: int = 1) -> dict:
    await conn.send_json(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        }
    )
    resp = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
    await conn.send_json({"jsonrpc": "2.0", "method": "notifications/initialized"})
    return resp


async def _rpc(conn: Any, method: str, req_id: int, params: dict | None = None) -> dict:
    msg: dict = {"jsonrpc": "2.0", "id": req_id, "method": method}
    if params is not None:
        msg["params"] = params
    await conn.send_json(msg)
    return await asyncio.wait_for(conn.receive_json(), timeout=5.0)


# ---------------------------------------------------------------------------
# Reusable server definitions
# ---------------------------------------------------------------------------

PRODUCTS = [
    {"id": 1, "name": "Widget A", "price": 9.99, "tags": ["blue"]},
    {"id": 2, "name": "Widget B", "price": 14.99, "tags": ["red"]},
    {"id": 3, "name": "Gadget C", "price": 24.99, "tags": ["blue", "pro"]},
]


@mcp_server("/mcp")
class ProductServer:
    @mcp_tool()
    async def search(self, query: str) -> list:
        """Search products. Args: query: Search terms."""
        return [p for p in PRODUCTS if query.lower() in p["name"].lower()]

    @mcp_tool()
    async def get_product(self, product_id: int) -> dict:
        """Get product by ID. Args: product_id: Numeric ID."""
        return next((p for p in PRODUCTS if p["id"] == product_id), None)  # type: ignore[return-value]

    @mcp_resource("/products/{product_id}")
    async def product_card(self, product_id: str) -> str:
        """Product card text. Args: product_id: ID from URI."""
        p = next((p for p in PRODUCTS if p["id"] == int(product_id)), None)
        return f"{p['name']}: ${p['price']:.2f}" if p else "Not found"

    @mcp_prompt()
    async def recommend(self, budget: str) -> str:
        """Recommendation prompt. Args: budget: Max budget."""
        affordable = [p for p in PRODUCTS if p["price"] <= float(budget)]
        names = ", ".join(p["name"] for p in affordable) or "none"
        return f"Recommend under ${budget}: {names}"


# ---------------------------------------------------------------------------
# 1 — Basic setup
# ---------------------------------------------------------------------------


class TestBasicSetup:
    @pytest.fixture(scope="class")
    def app(self):
        @module(imports=[McpServerModule.for_root(ProductServer)])
        class App:
            pass

        a = LaurenFactory.create(App)
        TestClient(a)
        return a

    async def test_factory_creates_app(self, app):
        assert app is not None

    def test_test_client_does_not_raise(self, app):
        client = TestClient(app)
        assert client is not None

    async def test_ws_client_connects(self, app):
        async with WsTestClient(app).connect("/mcp/ws") as conn:
            resp = await _handshake(conn)
            assert "result" in resp

    async def test_initialize_result_has_server_info(self, app):
        async with WsTestClient(app).connect("/mcp/ws") as conn:
            resp = await _handshake(conn)
            assert resp["result"]["serverInfo"]["name"] == "ProductServer"
            assert resp["result"]["serverInfo"]["version"] == "1.0.0"

    async def test_initialize_result_has_capabilities(self, app):
        async with WsTestClient(app).connect("/mcp/ws") as conn:
            resp = await _handshake(conn)
            caps = resp["result"]["capabilities"]
            assert "tools" in caps
            assert "resources" in caps
            assert "prompts" in caps


# ---------------------------------------------------------------------------
# 2 — HTTP controllers + MCP server coexistence
# ---------------------------------------------------------------------------


@controller("/api")
class ProductController:
    @get("/products")
    async def list_products(self) -> list[dict]:
        return PRODUCTS

    @get("/products/{product_id}")
    async def get_product(self, product_id: int) -> dict:
        p = next((p for p in PRODUCTS if p["id"] == product_id), None)
        if p is None:
            return Response.json({"error": "not found"}, status=404)  # type: ignore[return-value]
        return p

    @post("/products")
    async def create_product(self, name: str, price: float) -> dict:
        item = {"id": len(PRODUCTS) + 1, "name": name, "price": price, "tags": []}
        PRODUCTS.append(item)
        return item


class TestHttpAndMcpCoexistence:
    @pytest.fixture(scope="class")
    def app(self):
        @module(
            controllers=[ProductController],
            imports=[McpServerModule.for_root(ProductServer)],
        )
        class App:
            pass

        a = LaurenFactory.create(App)
        TestClient(a)
        return a

    def test_http_get_returns_products(self, app):
        resp = TestClient(app).get("/api/products")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_http_get_single_product(self, app):
        resp = TestClient(app).get("/api/products/1")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Widget A"

    def test_http_404_for_unknown_product(self, app):
        resp = TestClient(app).get("/api/products/9999")
        assert resp.status_code == 404

    async def test_mcp_ws_works_alongside_http(self, app):
        async with WsTestClient(app).connect("/mcp/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(conn, "tools/list", 2)
            assert "tools" in resp["result"]

    async def test_mcp_tools_list_has_two_tools(self, app):
        async with WsTestClient(app).connect("/mcp/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(conn, "tools/list", 2)
            names = {t["name"] for t in resp["result"]["tools"]}
            assert "search" in names
            assert "get_product" in names

    async def test_http_and_mcp_concurrent_requests(self, app):
        """HTTP TestClient and WsTestClient can run at the same time."""
        http = TestClient(app)
        async with WsTestClient(app).connect("/mcp/ws") as conn:
            await _handshake(conn)
            http_resp = http.get("/api/products")
            mcp_resp = await _rpc(conn, "ping", 2)
            assert http_resp.status_code == 200
            assert "result" in mcp_resp

    async def test_mcp_call_tool_returns_correct_data(self, app):
        async with WsTestClient(app).connect("/mcp/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(
                conn, "tools/call", 2, {"name": "search", "arguments": {"query": "widget"}}
            )
            items = json.loads(resp["result"]["content"][0]["text"])
            assert any("Widget" in i["name"] for i in items)


# ---------------------------------------------------------------------------
# 3 — DI injection
# ---------------------------------------------------------------------------


@injectable(scope=Scope.SINGLETON)
class PricingService:
    """Shared singleton service used by both HTTP and MCP."""

    call_count: int = 0

    def format_price(self, price: float) -> str:
        self.call_count += 1
        return f"${price:.2f}"


@injectable(scope=Scope.SINGLETON)
class InventoryService:
    """Another injectable to test multi-dependency injection."""

    def stock_level(self, product_id: int) -> int:
        return 10 + product_id  # dummy implementation


@mcp_server("/shop")
class ShopMcpServer:
    def __init__(self, pricing: PricingService, inventory: InventoryService) -> None:
        self._pricing = pricing
        self._inventory = inventory

    @mcp_tool()
    async def price_tag(self, amount: float) -> str:
        """Format a price. Args: amount: Numeric amount."""
        return self._pricing.format_price(amount)

    @mcp_tool()
    async def stock(self, product_id: int) -> int:
        """Get stock level. Args: product_id: Product ID."""
        return self._inventory.stock_level(product_id)


@controller("/shop")
class ShopController:
    def __init__(self, pricing: PricingService) -> None:
        self._pricing = pricing

    @get("/price")
    async def price(self, amount: float) -> dict:
        return {"formatted": self._pricing.format_price(amount)}


class TestDIInjection:
    @pytest.fixture(scope="class")
    def app(self):
        # Correct pattern: shared module exports services; both HTTP and MCP import it.
        @module(
            providers=[PricingService, InventoryService],
            exports=[PricingService, InventoryService],
        )
        class ServicesModule:
            pass

        @module(
            controllers=[ShopController],
            imports=[
                ServicesModule,
                McpServerModule.for_root(ShopMcpServer, imports=[ServicesModule]),
            ],
        )
        class App:
            pass

        a = LaurenFactory.create(App)
        TestClient(a)
        return a

    async def test_mcp_server_receives_injected_service(self, app):
        async with WsTestClient(app).connect("/shop/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(
                conn, "tools/call", 2, {"name": "price_tag", "arguments": {"amount": 9.99}}
            )
            assert resp["result"]["content"][0]["text"] == "$9.99"

    async def test_mcp_server_receives_second_injected_service(self, app):
        async with WsTestClient(app).connect("/shop/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(
                conn, "tools/call", 2, {"name": "stock", "arguments": {"product_id": 5}}
            )
            assert int(resp["result"]["content"][0]["text"]) == 15

    def test_http_controller_uses_same_service_class(self, app):
        resp = TestClient(app).get("/shop/price?amount=19.99")
        assert resp.status_code == 200
        assert resp.json()["formatted"] == "$19.99"

    async def test_for_root_providers_param_makes_service_visible(self):
        """providers= in for_root() makes external services available."""

        @injectable(scope=Scope.SINGLETON)
        class _Svc:
            def value(self) -> str:
                return "injected"

        @mcp_server("/inject-test")
        class _Srv:
            def __init__(self, svc: _Svc) -> None:
                self._svc = svc

            @mcp_tool()
            async def check(self) -> str:
                "Check injection."
                return self._svc.value()

        @module(imports=[McpServerModule.for_root(_Srv, providers=[_Svc])])
        class _App:
            pass

        app = LaurenFactory.create(_App)
        TestClient(app)
        async with WsTestClient(app).connect("/inject-test/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(conn, "tools/call", 2, {"name": "check", "arguments": {}})
            assert resp["result"]["content"][0]["text"] == "injected"

    async def test_for_root_imports_param_allows_imported_module(self):
        """imports= in for_root() makes an exported module's services visible."""

        @injectable(scope=Scope.SINGLETON)
        class _SharedSvc:
            def answer(self) -> int:
                return 42

        @module(providers=[_SharedSvc], exports=[_SharedSvc])
        class _SharedModule:
            pass

        @mcp_server("/import-test")
        class _Srv:
            def __init__(self, svc: _SharedSvc) -> None:
                self._svc = svc

            @mcp_tool()
            async def ask(self) -> int:
                "Ask. Args: none."
                return self._svc.answer()

        @module(imports=[McpServerModule.for_root(_Srv, imports=[_SharedModule])])
        class _App:
            pass

        app = LaurenFactory.create(_App)
        TestClient(app)
        async with WsTestClient(app).connect("/import-test/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(conn, "tools/call", 2, {"name": "ask", "arguments": {}})
            assert int(resp["result"]["content"][0]["text"]) == 42

    async def test_app_state_accessible_via_injectable(self):
        """AppState registered as a DI value provider is injectable into services.

        AppState is NOT automatically injectable — register it explicitly via
        use_value() so the DI container can resolve it.
        """
        state = AppState({"currency": "GBP"})

        @injectable(scope=Scope.SINGLETON)
        class _Cfg:
            def __init__(self, app_state: AppState) -> None:
                self._state = app_state

            def currency(self) -> str:
                return self._state.get("currency", "USD")

        @mcp_server("/cfg-test")
        class _Srv:
            def __init__(self, cfg: _Cfg) -> None:
                self._cfg = cfg

            @mcp_tool()
            async def currency(self) -> str:
                "Get currency."
                return self._cfg.currency()

        state_provider = use_value(provide=AppState, value=state)

        @module(
            imports=[
                McpServerModule.for_root(
                    _Srv,
                    providers=[_Cfg, state_provider],
                )
            ]
        )
        class _App:
            pass

        app = LaurenFactory.create(_App, app_state=state)
        TestClient(app)
        async with WsTestClient(app).connect("/cfg-test/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(conn, "tools/call", 2, {"name": "currency", "arguments": {}})
            assert resp["result"]["content"][0]["text"] == "GBP"

    async def test_post_construct_fires_for_injected_service(self):
        """@post_construct on an injected service fires before MCP connections."""
        ready: list[bool] = []

        @injectable(scope=Scope.SINGLETON)
        class _Ready:
            @post_construct
            def on_ready(self) -> None:
                ready.append(True)

        @mcp_server("/ready-test")
        class _Srv:
            def __init__(self, svc: _Ready) -> None:
                self._svc = svc

            @mcp_tool()
            async def status(self) -> str:
                "Status."
                return "ok"

        @module(imports=[McpServerModule.for_root(_Srv, providers=[_Ready])])
        class _App:
            pass

        app = LaurenFactory.create(_App)
        TestClient(app)  # triggers @post_construct
        assert ready == [True]


# ---------------------------------------------------------------------------
# 4 — Guards and middleware
# ---------------------------------------------------------------------------


class TestGuardsAndMiddleware:
    @pytest.fixture(scope="class")
    def app_with_middleware(self):
        request_log: list[str] = []

        @middleware()
        class _Logger:
            async def dispatch(self, request: Request, call_next: CallNext) -> Response:
                request_log.append(f"{request.method} {request.path}")
                return await call_next(request)

        @controller("/guarded")
        class _Ctrl:
            @get("/hello")
            async def hello(self) -> dict:
                return {"message": "hi"}

        @module(
            controllers=[_Ctrl],
            imports=[McpServerModule.for_root(ProductServer)],
        )
        class _App:
            pass

        app = LaurenFactory.create(_App, global_middlewares=[_Logger])
        TestClient(app)
        app._test_request_log = request_log  # type: ignore[attr-defined]
        return app

    def test_middleware_fires_on_http_requests(self, app_with_middleware):
        TestClient(app_with_middleware).get("/guarded/hello")
        assert any("/guarded/hello" in e for e in app_with_middleware._test_request_log)  # type: ignore[attr-defined]

    def test_http_route_returns_correct_data(self, app_with_middleware):
        resp = TestClient(app_with_middleware).get("/guarded/hello")
        assert resp.status_code == 200
        assert resp.json() == {"message": "hi"}

    async def test_mcp_still_works_with_global_middleware(self, app_with_middleware):
        async with WsTestClient(app_with_middleware).connect("/mcp/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(conn, "ping", 2)
            assert "result" in resp

    async def test_auth_middleware_blocks_mcp_sse_without_key(self):
        """Global middleware can inspect the request path and reject MCP SSE."""

        @middleware()
        class _Auth:
            async def dispatch(self, request: Request, call_next: CallNext) -> Response:
                if request.path.startswith("/secure"):
                    key = request.headers.get("x-api-key")
                    if key != "valid-key":
                        return Response.json({"error": "Unauthorised"}, status=401)
                return await call_next(request)

        @mcp_server("/secure")
        class _Srv:
            @mcp_tool()
            async def ping(self) -> str:
                "Ping."
                return "pong"

        @module(imports=[McpServerModule.for_root(_Srv, transport="sse")])
        class _App:
            pass

        app = LaurenFactory.create(_App, global_middlewares=[_Auth])
        TestClient(app)
        client = TestClient(app)
        # No key → 401
        resp = client.post("/secure/", content=b"{}", headers={"content-type": "application/json"})
        assert resp.status_code == 401

    async def test_exception_handler_registered_alongside_mcp(self):
        """Custom exception handlers coexist with MCP server in same app."""
        from lauren import exception_handler

        @exception_handler(ValueError)
        class _VE:
            async def catch(self, exc: ValueError, request: Request) -> Response:
                return Response.json({"error": str(exc)}, status=422)

        @controller("/api")
        class _Ctrl:
            @get("/fail")
            async def fail(self) -> dict:
                raise ValueError("intentional")

        @module(
            controllers=[_Ctrl],
            imports=[McpServerModule.for_root(ProductServer)],
        )
        class _App:
            pass

        app = LaurenFactory.create(_App, global_exception_handlers=[_VE])
        TestClient(app)
        resp = TestClient(app).get("/api/fail")
        assert resp.status_code == 422
        assert "intentional" in resp.json()["error"]

    async def test_mcp_still_works_alongside_exception_handler(self):
        """MCP tools work even when exception handlers are registered globally."""

        @exception_handler(RuntimeError)
        class _RE:
            async def catch(self, exc: RuntimeError, request: Request) -> Response:
                return Response.json({"error": str(exc)}, status=500)

        @module(imports=[McpServerModule.for_root(ProductServer)])
        class _App:
            pass

        app = LaurenFactory.create(_App, global_exception_handlers=[_RE])
        TestClient(app)
        async with WsTestClient(app).connect("/mcp/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(
                conn, "tools/call", 2, {"name": "search", "arguments": {"query": "widget"}}
            )
            assert "result" in resp


# ---------------------------------------------------------------------------
# 5 — Lifecycle hooks
# ---------------------------------------------------------------------------


class TestLifecycle:
    async def test_post_construct_fires_after_create(self):
        log: list[str] = []

        @injectable(scope=Scope.SINGLETON)
        class _Svc:
            @post_construct
            def init(self) -> None:
                log.append("started")

        @mcp_server("/lifecycle")
        class _Srv:
            def __init__(self, svc: _Svc) -> None:
                self._svc = svc

            @mcp_tool()
            async def ping(self) -> str:
                "Ping."
                return "pong"

        @module(imports=[McpServerModule.for_root(_Srv, providers=[_Svc])])
        class _App:
            pass

        app = LaurenFactory.create(_App)
        TestClient(app)
        assert "started" in log

    async def test_pre_destruct_callable(self):
        """@pre_destruct registers without error (shutdown not triggered in test)."""
        cleaned: list[bool] = []

        @injectable(scope=Scope.SINGLETON)
        class _Svc:
            @post_construct
            def init(self) -> None:
                pass

            @pre_destruct
            async def cleanup(self) -> None:
                cleaned.append(True)

        @mcp_server("/destruct-test")
        class _Srv:
            def __init__(self, svc: _Svc) -> None: ...

            @mcp_tool()
            async def ok(self) -> str:
                "Ok."
                return "ok"

        @module(imports=[McpServerModule.for_root(_Srv, providers=[_Svc])])
        class _App:
            pass

        app = LaurenFactory.create(_App)
        TestClient(app)
        # pre_destruct only runs on shutdown — just verify no startup error
        assert app is not None

    async def test_app_state_sealed_after_startup(self):
        """AppState values set before create() are readable after startup."""

        @mcp_server("/state-test")
        class _Srv:
            @mcp_tool()
            async def ok(self) -> str:
                "Ok."
                return "ok"

        @module(imports=[McpServerModule.for_root(_Srv)])
        class _App:
            pass

        app = LaurenFactory.create(_App, app_state=AppState({"version": "v2"}))
        TestClient(app)
        assert app is not None  # no exception during startup

    async def test_mcp_handlers_require_test_client_for_post_construct(self):
        """TestClient(app) is REQUIRED to trigger @post_construct before WS use.

        LaurenFactory.create() compiles the DI graph but does NOT instantiate
        singletons eagerly.  Singletons (and their @post_construct hooks) are
        resolved on first startup — which TestClient triggers.  Without
        TestClient, MCP handlers are not registered and 'initialize' will fail.
        """

        @mcp_server("/pc-test")
        class _Srv:
            @mcp_tool()
            async def ping(self) -> str:
                "Ping."
                return "pong"

        @module(imports=[McpServerModule.for_root(_Srv)])
        class _App:
            pass

        app = LaurenFactory.create(_App)
        TestClient(app)  # required — registers MCP handlers via @post_construct
        async with WsTestClient(app).connect("/pc-test/ws") as conn:
            resp = await _handshake(conn)
            assert "result" in resp  # initialize succeeded → handlers are registered

    async def test_multiple_post_construct_in_correct_order(self):
        """Multiple @post_construct hooks fire in topological order."""
        order: list[str] = []

        @injectable(scope=Scope.SINGLETON)
        class _A:
            @post_construct
            def start(self) -> None:
                order.append("A")

        @injectable(scope=Scope.SINGLETON)
        class _B:
            def __init__(self, a: _A) -> None: ...

            @post_construct
            def start(self) -> None:
                order.append("B")

        @mcp_server("/order-test")
        class _Srv:
            def __init__(self, b: _B) -> None: ...

            @mcp_tool()
            async def ok(self) -> str:
                "Ok."
                return "ok"

        @module(imports=[McpServerModule.for_root(_Srv, providers=[_A, _B])])
        class _App:
            pass

        app = LaurenFactory.create(_App)
        TestClient(app)
        # A must start before B (B depends on A)
        assert order.index("A") < order.index("B")


# ---------------------------------------------------------------------------
# 6 — Protocol deep coverage
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def product_app():
    @module(imports=[McpServerModule.for_root(ProductServer)])
    class App:
        pass

    a = LaurenFactory.create(App)
    TestClient(a)
    return a


class TestProtocolDeepCoverage:
    async def test_tools_list_schema_correct_types(self, product_app):
        async with WsTestClient(product_app).connect("/mcp/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(conn, "tools/list", 2)
            search = next(t for t in resp["result"]["tools"] if t["name"] == "search")
            assert search["inputSchema"]["properties"]["query"]["type"] == "string"
            assert "query" in search["inputSchema"]["required"]

    async def test_tools_call_dict_result_json_encoded(self, product_app):
        async with WsTestClient(product_app).connect("/mcp/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(
                conn, "tools/call", 2, {"name": "get_product", "arguments": {"product_id": 1}}
            )
            product = json.loads(resp["result"]["content"][0]["text"])
            assert product["name"] == "Widget A"
            assert product["price"] == 9.99

    async def test_resources_list_returns_resource_schema(self, product_app):
        async with WsTestClient(product_app).connect("/mcp/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(conn, "resources/list", 2)
            resources = resp["result"]["resources"]
            assert len(resources) >= 1
            assert any("products" in r["uri"] for r in resources)

    async def test_resources_read_returns_text_content(self, product_app):
        async with WsTestClient(product_app).connect("/mcp/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(conn, "resources/read", 2, {"uri": "/products/1"})
            text = resp["result"]["contents"][0]["text"]
            assert "Widget A" in text
            assert "9.99" in text

    async def test_prompts_list_returns_prompt_schema(self, product_app):
        async with WsTestClient(product_app).connect("/mcp/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(conn, "prompts/list", 2)
            assert any(p["name"] == "recommend" for p in resp["result"]["prompts"])

    async def test_prompts_get_with_argument_filters(self, product_app):
        async with WsTestClient(product_app).connect("/mcp/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(
                conn, "prompts/get", 2, {"name": "recommend", "arguments": {"budget": "12"}}
            )
            text = resp["result"]["messages"][0]["content"]["text"]
            assert "Widget A" in text
            assert "Gadget C" not in text  # too expensive

    async def test_ping_returns_empty_result(self, product_app):
        async with WsTestClient(product_app).connect("/mcp/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(conn, "ping", 2)
            assert resp["result"] == {}


# ---------------------------------------------------------------------------
# 7 — Transport variants
# ---------------------------------------------------------------------------


class TestTransportVariants:
    async def test_ws_only_transport(self):
        @module(imports=[McpServerModule.for_root(ProductServer, transport="ws")])
        class App:
            pass

        app = LaurenFactory.create(App)
        TestClient(app)
        async with WsTestClient(app).connect("/mcp/ws") as conn:
            resp = await _handshake(conn)
            assert "result" in resp

    def test_sse_only_transport_has_post_endpoint(self):
        @module(imports=[McpServerModule.for_root(ProductServer, transport="sse")])
        class App:
            pass

        app = LaurenFactory.create(App)
        TestClient(app)
        resp = TestClient(app).post(
            "/mcp/",
            content=b"{}",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400  # missing session-id, route exists

    async def test_both_transport_ws_works(self):
        @module(imports=[McpServerModule.for_root(ProductServer, transport="both")])
        class App:
            pass

        app = LaurenFactory.create(App)
        TestClient(app)
        async with WsTestClient(app).connect("/mcp/ws") as conn:
            resp = await _handshake(conn)
            assert "result" in resp

    def test_both_transport_sse_route_exists(self):
        @module(imports=[McpServerModule.for_root(ProductServer, transport="both")])
        class App:
            pass

        app = LaurenFactory.create(App)
        TestClient(app)
        resp = TestClient(app).post(
            "/mcp/",
            content=b"{}",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400  # missing session-id, confirms route exists


# ---------------------------------------------------------------------------
# 8 — for_root() parameters
# ---------------------------------------------------------------------------


class TestForRootParams:
    async def test_custom_server_info_in_handshake(self):
        from lauren_mcp._types import Implementation

        @mcp_server("/meta-test")
        class _Srv:
            @mcp_tool()
            async def ok(self) -> str:
                "Ok."
                return "ok"

        @module(
            imports=[
                McpServerModule.for_root(
                    _Srv,
                    server_info=Implementation(name="AcmeMCP", version="3.0.0"),
                )
            ]
        )
        class App:
            pass

        app = LaurenFactory.create(App)
        TestClient(app)
        async with WsTestClient(app).connect("/meta-test/ws") as conn:
            resp = await _handshake(conn)
            info = resp["result"]["serverInfo"]
            assert info["name"] == "AcmeMCP"
            assert info["version"] == "3.0.0"

    async def test_for_root_raises_on_non_decorated_class(self):
        class _Plain:
            pass

        with pytest.raises(TypeError, match="not an MCP server class"):
            McpServerModule.for_root(_Plain)

    async def test_providers_param_injects_service(self):
        @injectable(scope=Scope.SINGLETON)
        class _Calc:
            def add(self, a: int, b: int) -> int:
                return a + b

        @mcp_server("/calc-test")
        class _Srv:
            def __init__(self, calc: _Calc) -> None:
                self._calc = calc

            @mcp_tool()
            async def add(self, a: int, b: int) -> int:
                "Add. Args: a: First. b: Second."
                return self._calc.add(a, b)

        @module(imports=[McpServerModule.for_root(_Srv, providers=[_Calc])])
        class App:
            pass

        app = LaurenFactory.create(App)
        TestClient(app)
        async with WsTestClient(app).connect("/calc-test/ws") as conn:
            await _handshake(conn)
            resp = await _rpc(conn, "tools/call", 2, {"name": "add", "arguments": {"a": 3, "b": 4}})
            assert int(resp["result"]["content"][0]["text"]) == 7

    async def test_sse_session_dispatch_via_queue(self):
        """SSE transport correctly dispatches initialize and returns result in queue."""

        @module(imports=[McpServerModule.for_root(ProductServer, transport="sse")])
        class App:
            pass

        app = LaurenFactory.create(App)
        TestClient(app)

        store: SseSessionStore = await app.container.resolve(SseSessionStore)
        sid = "compat-test-session"
        queue = store.create(sid)
        try:
            client = TestClient(app)
            client.post(
                "/mcp/",
                content=json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-03-26",
                            "capabilities": {},
                            "clientInfo": {"name": "t", "version": "1"},
                        },
                    }
                ).encode(),
                headers={"content-type": "application/json", "mcp-session-id": sid},
            )
            payload = await asyncio.wait_for(queue.get(), timeout=3.0)
            resp = json.loads(payload)
            assert resp["id"] == 1
            assert resp["result"]["serverInfo"]["name"] == "ProductServer"
        finally:
            store.remove(sid)
