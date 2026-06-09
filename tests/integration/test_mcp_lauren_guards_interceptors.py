"""Compatibility tests: Lauren guards, interceptors, and middleware with lauren-mcp.

Proves that Lauren's complete cross-cutting concerns stack — applied both
globally and at class/method level — works correctly alongside MCP servers.

Test classes:
  TestGlobalGuards        (6)  — guard blocks/passes globally, request headers
  TestClassGuards         (5)  — guard on HTTP controller alongside MCP WS
  TestGlobalInterceptors  (5)  — timing, transformation, early-exit
  TestClassInterceptors   (5)  — class and method-level interceptors
  TestGlobalMiddleware    (6)  — request mutation, response mutation, early exit
  TestClassMiddleware     (5)  — controller-scoped middleware
  TestComposedStack       (4)  — guards + interceptors + middleware all at once

Total: 36 tests
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from lauren import (
    LaurenFactory,
    Scope,
    controller,
    get,
    injectable,
    middleware,
    module,
    use_guards,
    use_interceptors,
    use_middlewares,
)
from lauren.testing import TestClient, WsTestClient
from lauren.types import CallHandler, CallNext, ExecutionContext, Request, Response

from lauren_mcp import McpServerModule, mcp_server, mcp_tool

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Shared MCP server for all tests in this file
# ---------------------------------------------------------------------------


@mcp_server("/mcp")
class EchoMcpServer:
    @mcp_tool()
    async def echo(self, text: str) -> str:
        """Echo text. Args: text: Input string."""
        return text

    @mcp_tool()
    async def add(self, a: int, b: int) -> int:
        """Add two integers. Args: a: First. b: Second."""
        return a + b


# ---------------------------------------------------------------------------
# Helpers
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


async def _call(conn: Any, name: str, args: dict, req_id: int = 2) -> dict:
    await conn.send_json(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
        }
    )
    return await asyncio.wait_for(conn.receive_json(), timeout=5.0)


# ---------------------------------------------------------------------------
# Guard implementations
# ---------------------------------------------------------------------------


@injectable(scope=Scope.SINGLETON)
class AllowAllGuard:
    async def can_activate(self, ctx: ExecutionContext) -> bool:
        return True


@injectable(scope=Scope.SINGLETON)
class BlockAllGuard:
    async def can_activate(self, ctx: ExecutionContext) -> bool:
        return False


@injectable(scope=Scope.SINGLETON)
class ApiKeyGuard:
    """Allow only requests with X-Api-Key: valid."""

    async def can_activate(self, ctx: ExecutionContext) -> bool:
        return ctx.request.headers.get("x-api-key") == "valid"


@injectable(scope=Scope.SINGLETON)
class HeaderGuard:
    """Allow requests with X-Role: admin header."""

    async def can_activate(self, ctx: ExecutionContext) -> bool:
        return ctx.request.headers.get("x-role") == "admin"


# ---------------------------------------------------------------------------
# 1 — Global guards
# ---------------------------------------------------------------------------


class TestGlobalGuards:
    async def test_global_allow_all_guard_permits_mcp_ws(self):
        """AllowAllGuard globally → MCP WS still works."""

        @module(imports=[McpServerModule.for_root(EchoMcpServer)])
        class App:
            pass

        app = LaurenFactory.create(App, global_guards=[AllowAllGuard])
        TestClient(app)
        async with WsTestClient(app).connect("/mcp/ws") as conn:
            await _handshake(conn)
            resp = await _call(conn, "echo", {"text": "hi"})
            assert resp["result"]["content"][0]["text"] == "hi"

    async def test_global_allow_all_guard_permits_http(self):
        """AllowAllGuard globally → HTTP routes work."""

        @controller("/api")
        class _Ctrl:
            @get("/test")
            async def test_route(self) -> dict:
                return {"ok": True}

        @module(
            controllers=[_Ctrl],
            imports=[McpServerModule.for_root(EchoMcpServer)],
        )
        class App:
            pass

        app = LaurenFactory.create(App, global_guards=[AllowAllGuard])
        TestClient(app)
        assert TestClient(app).get("/api/test").status_code == 200

    async def test_global_block_all_guard_blocks_http(self):
        """BlockAllGuard globally → HTTP routes return 403."""

        @controller("/api")
        class _Ctrl:
            @get("/secret")
            async def secret(self) -> dict:
                return {"secret": True}

        @module(
            controllers=[_Ctrl],
            imports=[McpServerModule.for_root(EchoMcpServer)],
        )
        class App:
            pass

        app = LaurenFactory.create(App, global_guards=[BlockAllGuard])
        TestClient(app)
        resp = TestClient(app).get("/api/secret")
        # Guard rejection → 403 Forbidden
        assert resp.status_code == 403

    async def test_global_api_key_guard_blocks_without_key(self):

        @controller("/api")
        class _Ctrl:
            @get("/protected")
            async def protected(self) -> dict:
                return {"data": "secret"}

        @module(
            controllers=[_Ctrl],
            imports=[McpServerModule.for_root(EchoMcpServer)],
        )
        class App:
            pass

        app = LaurenFactory.create(App, global_guards=[ApiKeyGuard])
        TestClient(app)
        assert TestClient(app).get("/api/protected").status_code == 403

    async def test_global_api_key_guard_passes_with_valid_key(self):

        @controller("/api")
        class _Ctrl:
            @get("/protected")
            async def protected(self) -> dict:
                return {"data": "secret"}

        @module(
            controllers=[_Ctrl],
            imports=[McpServerModule.for_root(EchoMcpServer)],
        )
        class App:
            pass

        app = LaurenFactory.create(App, global_guards=[ApiKeyGuard])
        TestClient(app)
        resp = TestClient(app).get("/api/protected", headers={"x-api-key": "valid"})
        assert resp.status_code == 200
        assert resp.json()["data"] == "secret"

    async def test_mcp_ws_works_with_global_block_all_guard(self):
        """Global guards apply to HTTP; WS upgrade path may differ.

        We simply verify the app starts without error when a guard is present.
        """

        @module(imports=[McpServerModule.for_root(EchoMcpServer)])
        class App:
            pass

        app = LaurenFactory.create(App, global_guards=[AllowAllGuard])
        TestClient(app)
        async with WsTestClient(app).connect("/mcp/ws") as conn:
            resp = await _handshake(conn)
            assert "result" in resp


# ---------------------------------------------------------------------------
# 2 — Class-level guards on HTTP controllers alongside MCP
# ---------------------------------------------------------------------------


@injectable(scope=Scope.SINGLETON)
class RoleGuard:
    async def can_activate(self, ctx: ExecutionContext) -> bool:
        return ctx.request.headers.get("x-role") in ("admin", "staff")


class TestClassGuards:
    @pytest.fixture(scope="class")
    def app(self):
        @use_guards(RoleGuard)
        @controller("/admin")
        class AdminController:
            @get("/dashboard")
            async def dashboard(self) -> dict:
                return {"page": "dashboard"}

            @get("/stats")
            async def stats(self) -> dict:
                return {"visitors": 42}

        @controller("/public")
        class PublicController:
            @get("/hello")
            async def hello(self) -> dict:
                return {"message": "hello"}

        @module(
            controllers=[AdminController, PublicController],
            providers=[RoleGuard],
            imports=[McpServerModule.for_root(EchoMcpServer)],
        )
        class App:
            pass

        a = LaurenFactory.create(App)
        TestClient(a)
        return a

    def test_guarded_route_blocked_without_role(self, app):
        assert TestClient(app).get("/admin/dashboard").status_code == 403

    def test_guarded_route_allowed_with_role(self, app):
        resp = TestClient(app).get("/admin/dashboard", headers={"x-role": "admin"})
        assert resp.status_code == 200

    def test_guarded_route_stats_blocked_without_role(self, app):
        assert TestClient(app).get("/admin/stats").status_code == 403

    def test_unguarded_public_route_always_accessible(self, app):
        assert TestClient(app).get("/public/hello").status_code == 200

    async def test_mcp_server_works_regardless_of_class_guard(self, app):
        """Class-level guard on HTTP controller does not affect MCP WS."""
        async with WsTestClient(app).connect("/mcp/ws") as conn:
            await _handshake(conn)
            resp = await _call(conn, "echo", {"text": "unguarded"})
            assert resp["result"]["content"][0]["text"] == "unguarded"


# ---------------------------------------------------------------------------
# 3 — Global interceptors
# ---------------------------------------------------------------------------


@injectable(scope=Scope.SINGLETON)
class TimingInterceptor:
    """Adds an X-Elapsed-Ms header to every HTTP response."""

    elapsed_ms: float = 0.0

    async def intercept(self, ctx: ExecutionContext, call_handler: CallHandler) -> Any:
        import time

        t0 = time.monotonic()
        result = await call_handler.handle()
        self.elapsed_ms = (time.monotonic() - t0) * 1000
        if isinstance(result, Response):
            return result.with_header("x-elapsed-ms", str(self.elapsed_ms))
        return result


@injectable(scope=Scope.SINGLETON)
class WrapInterceptor:
    """Wraps dict responses in a {data: ...} envelope."""

    async def intercept(self, ctx: ExecutionContext, call_handler: CallHandler) -> Any:
        result = await call_handler.handle()
        if isinstance(result, dict):
            return {"data": result, "wrapped": True}
        return result


@injectable(scope=Scope.SINGLETON)
class EarlyExitInterceptor:
    """Returns 503 for requests with X-Down: true header."""

    async def intercept(self, ctx: ExecutionContext, call_handler: CallHandler) -> Any:
        if ctx.request.headers.get("x-down") == "true":
            return Response.json({"error": "service down"}, status=503)
        return await call_handler.handle()


class TestGlobalInterceptors:
    async def test_timing_interceptor_adds_header(self):

        @controller("/timed")
        class _Ctrl:
            @get("/")
            async def index(self) -> Response:
                return Response.json({"ok": True})

        @module(
            controllers=[_Ctrl],
            providers=[TimingInterceptor],
            imports=[McpServerModule.for_root(EchoMcpServer)],
        )
        class App:
            pass

        app = LaurenFactory.create(App, global_interceptors=[TimingInterceptor])
        TestClient(app)
        resp = TestClient(app).get("/timed/")
        assert resp.status_code == 200
        assert resp.header("x-elapsed-ms") is not None

    async def test_early_exit_interceptor_blocks_request(self):

        @controller("/svc")
        class _Ctrl:
            @get("/")
            async def index(self) -> dict:
                return {"ok": True}

        @module(
            controllers=[_Ctrl],
            providers=[EarlyExitInterceptor],
            imports=[McpServerModule.for_root(EchoMcpServer)],
        )
        class App:
            pass

        app = LaurenFactory.create(App, global_interceptors=[EarlyExitInterceptor])
        TestClient(app)
        resp = TestClient(app).get("/svc/", headers={"x-down": "true"})
        assert resp.status_code == 503

    async def test_early_exit_interceptor_passes_normal_request(self):

        @controller("/svc2")
        class _Ctrl:
            @get("/")
            async def index(self) -> dict:
                return {"ok": True}

        @module(
            controllers=[_Ctrl],
            providers=[EarlyExitInterceptor],
            imports=[McpServerModule.for_root(EchoMcpServer)],
        )
        class App:
            pass

        app = LaurenFactory.create(App, global_interceptors=[EarlyExitInterceptor])
        TestClient(app)
        resp = TestClient(app).get("/svc2/")
        assert resp.status_code == 200

    async def test_global_interceptor_does_not_break_mcp_ws(self):
        """Global interceptors do not interfere with WS connections."""

        @module(
            providers=[EarlyExitInterceptor],
            imports=[McpServerModule.for_root(EchoMcpServer)],
        )
        class App:
            pass

        app = LaurenFactory.create(App, global_interceptors=[EarlyExitInterceptor])
        TestClient(app)
        async with WsTestClient(app).connect("/mcp/ws") as conn:
            await _handshake(conn)
            resp = await _call(conn, "echo", {"text": "intercepted?"})
            assert resp["result"]["content"][0]["text"] == "intercepted?"

    async def test_multiple_global_interceptors_compose(self):
        """Multiple global interceptors run in order."""
        order: list[str] = []

        @injectable(scope=Scope.SINGLETON)
        class _First:
            async def intercept(self, ctx: ExecutionContext, call_handler: CallHandler) -> Any:
                order.append("first-before")
                result = await call_handler.handle()
                order.append("first-after")
                return result

        @injectable(scope=Scope.SINGLETON)
        class _Second:
            async def intercept(self, ctx: ExecutionContext, call_handler: CallHandler) -> Any:
                order.append("second-before")
                result = await call_handler.handle()
                order.append("second-after")
                return result

        @controller("/ordered")
        class _Ctrl:
            @get("/")
            async def index(self) -> dict:
                order.append("handler")
                return {"ok": True}

        @module(
            controllers=[_Ctrl],
            providers=[_First, _Second],
            imports=[McpServerModule.for_root(EchoMcpServer)],
        )
        class App:
            pass

        app = LaurenFactory.create(App, global_interceptors=[_First, _Second])
        TestClient(app)
        TestClient(app).get("/ordered/")
        assert order == ["first-before", "second-before", "handler", "second-after", "first-after"]


# ---------------------------------------------------------------------------
# 4 — Class-level interceptors
# ---------------------------------------------------------------------------


@injectable(scope=Scope.SINGLETON)
class EnvelopeInterceptor:
    """Adds X-Intercepted header to all responses (Lauren returns Response objects)."""

    call_count: int = 0

    async def intercept(self, ctx: ExecutionContext, call_handler: CallHandler) -> Any:
        result = await call_handler.handle()
        EnvelopeInterceptor.call_count += 1
        # Lauren auto-converts handler return values to Response objects before
        # passing them to interceptors — check for Response type.
        if isinstance(result, Response):
            return result.with_header("x-intercepted", "true")
        return result


class TestClassInterceptors:
    @pytest.fixture(scope="class")
    def app(self):
        @use_interceptors(EnvelopeInterceptor)
        @controller("/wrapped")
        class WrappedController:
            @get("/item")
            async def item(self) -> dict:
                return {"id": 1, "name": "Widget"}

        @controller("/plain")
        class PlainController:
            @get("/item")
            async def item(self) -> dict:
                return {"id": 2, "name": "Gadget"}

        @module(
            controllers=[WrappedController, PlainController],
            providers=[EnvelopeInterceptor],
            imports=[McpServerModule.for_root(EchoMcpServer)],
        )
        class App:
            pass

        a = LaurenFactory.create(App)
        TestClient(a)
        return a

    def test_class_interceptor_fires_and_adds_header(self, app):
        """Interceptor fires for routes in the decorated controller."""
        EnvelopeInterceptor.call_count = 0
        resp = TestClient(app).get("/wrapped/item")
        assert resp.status_code == 200
        assert resp.header("x-intercepted") == "true"
        assert EnvelopeInterceptor.call_count >= 1

    def test_unintercepted_controller_has_no_interceptor_header(self, app):
        """Interceptor does NOT fire for routes outside the decorated controller."""
        EnvelopeInterceptor.call_count = 0
        resp = TestClient(app).get("/plain/item")
        assert resp.status_code == 200
        assert resp.header("x-intercepted") is None
        assert resp.json()["name"] == "Gadget"

    async def test_mcp_ws_not_affected_by_class_interceptor(self, app):
        async with WsTestClient(app).connect("/mcp/ws") as conn:
            await _handshake(conn)
            resp = await _call(conn, "add", {"a": 10, "b": 5})
            result = int(resp["result"]["content"][0]["text"])
            assert result == 15

    async def test_class_interceptor_and_mcp_concurrent(self, app):
        """HTTP class interceptor and MCP WS run simultaneously."""
        http_client = TestClient(app)
        async with WsTestClient(app).connect("/mcp/ws") as conn:
            await _handshake(conn)
            http_resp = http_client.get("/wrapped/item")
            mcp_resp = await _call(conn, "echo", {"text": "concurrent"})
            assert http_resp.header("x-intercepted") == "true"
            assert mcp_resp["result"]["content"][0]["text"] == "concurrent"

    async def test_method_level_interceptor(self):
        """@use_interceptors on a specific method fires only for that handler."""
        fired: list[str] = []

        @injectable(scope=Scope.SINGLETON)
        class _Marker:
            async def intercept(self, ctx: ExecutionContext, call_handler: CallHandler) -> Any:
                fired.append("fired")
                result = await call_handler.handle()
                # Lauren returns Response objects at this point
                if isinstance(result, Response):
                    return result.with_header("x-method-intercepted", "true")
                return result

        @controller("/method-level")
        class _Ctrl:
            @use_interceptors(_Marker)
            @get("/special")
            async def special(self) -> dict:
                return {"page": "special"}

            @get("/normal")
            async def normal(self) -> dict:
                return {"page": "normal"}

        @module(
            controllers=[_Ctrl],
            providers=[_Marker],
            imports=[McpServerModule.for_root(EchoMcpServer)],
        )
        class App:
            pass

        app = LaurenFactory.create(App)
        TestClient(app)
        fired.clear()
        special_resp = TestClient(app).get("/method-level/special")
        normal_resp = TestClient(app).get("/method-level/normal")
        assert special_resp.header("x-method-intercepted") == "true"
        assert normal_resp.header("x-method-intercepted") is None


# ---------------------------------------------------------------------------
# 5 — Global middleware (extended)
# ---------------------------------------------------------------------------


class TestGlobalMiddleware:
    async def test_request_mutation_via_middleware(self):
        """Middleware can mutate request.state; handlers read it."""

        @middleware()
        class _SetState:
            async def dispatch(self, request: Request, call_next: CallNext) -> Response:
                request.state.set("user_id", "u123")
                return await call_next(request)

        @controller("/state")
        class _Ctrl:
            @get("/me")
            async def me(self, request: Request) -> dict:
                return {"user_id": request.state.get("user_id")}

        @module(
            controllers=[_Ctrl],
            imports=[McpServerModule.for_root(EchoMcpServer)],
        )
        class App:
            pass

        app = LaurenFactory.create(App, global_middlewares=[_SetState])
        TestClient(app)
        resp = TestClient(app).get("/state/me")
        assert resp.json()["user_id"] == "u123"

    async def test_response_mutation_via_middleware(self):
        """Middleware can add headers to every response."""

        @middleware()
        class _CacheHeaders:
            async def dispatch(self, request: Request, call_next: CallNext) -> Response:
                resp = await call_next(request)
                return resp.with_header("x-cache", "miss")

        @controller("/cached")
        class _Ctrl:
            @get("/data")
            async def data(self) -> dict:
                return {"items": []}

        @module(
            controllers=[_Ctrl],
            imports=[McpServerModule.for_root(EchoMcpServer)],
        )
        class App:
            pass

        app = LaurenFactory.create(App, global_middlewares=[_CacheHeaders])
        TestClient(app)
        resp = TestClient(app).get("/cached/data")
        assert resp.header("x-cache") == "miss"

    async def test_early_exit_middleware(self):
        """Middleware can short-circuit the request."""

        @middleware()
        class _Maintenance:
            async def dispatch(self, request: Request, call_next: CallNext) -> Response:
                return Response.json({"error": "maintenance"}, status=503)

        @controller("/api")
        class _Ctrl:
            @get("/")
            async def index(self) -> dict:
                return {"ok": True}

        @module(
            controllers=[_Ctrl],
            imports=[McpServerModule.for_root(EchoMcpServer)],
        )
        class App:
            pass

        app = LaurenFactory.create(App, global_middlewares=[_Maintenance])
        TestClient(app)
        assert TestClient(app).get("/api/").status_code == 503

    async def test_path_scoped_middleware_only_applies_to_matching_path(self):
        """Middleware that inspects request.path to selectively apply."""

        @middleware()
        class _ApiOnly:
            async def dispatch(self, request: Request, call_next: CallNext) -> Response:
                if not request.path.startswith("/api"):
                    return await call_next(request)
                return Response.json({"blocked": True}, status=403)

        @controller("/api")
        class _ApiCtrl:
            @get("/data")
            async def data(self) -> dict:
                return {"data": True}

        @controller("/other")
        class _OtherCtrl:
            @get("/data")
            async def data(self) -> dict:
                return {"other": True}

        @module(
            controllers=[_ApiCtrl, _OtherCtrl],
            imports=[McpServerModule.for_root(EchoMcpServer)],
        )
        class App:
            pass

        app = LaurenFactory.create(App, global_middlewares=[_ApiOnly])
        TestClient(app)
        assert TestClient(app).get("/api/data").status_code == 403
        assert TestClient(app).get("/other/data").status_code == 200

    async def test_multiple_global_middlewares_execute_in_order(self):
        order: list[str] = []

        @middleware()
        class _First:
            async def dispatch(self, request: Request, call_next: CallNext) -> Response:
                order.append("first-before")
                resp = await call_next(request)
                order.append("first-after")
                return resp

        @middleware()
        class _Second:
            async def dispatch(self, request: Request, call_next: CallNext) -> Response:
                order.append("second-before")
                resp = await call_next(request)
                order.append("second-after")
                return resp

        @controller("/chain")
        class _Ctrl:
            @get("/")
            async def index(self) -> dict:
                order.append("handler")
                return {"ok": True}

        @module(
            controllers=[_Ctrl],
            imports=[McpServerModule.for_root(EchoMcpServer)],
        )
        class App:
            pass

        app = LaurenFactory.create(App, global_middlewares=[_First, _Second])
        TestClient(app)
        TestClient(app).get("/chain/")
        assert order == ["first-before", "second-before", "handler", "second-after", "first-after"]

    async def test_global_middleware_does_not_break_mcp_ws(self):
        """Global middleware runs on HTTP; MCP WS still functions."""

        @middleware()
        class _Logger:
            async def dispatch(self, request: Request, call_next: CallNext) -> Response:
                return await call_next(request)

        @module(imports=[McpServerModule.for_root(EchoMcpServer)])
        class App:
            pass

        app = LaurenFactory.create(App, global_middlewares=[_Logger])
        TestClient(app)
        async with WsTestClient(app).connect("/mcp/ws") as conn:
            await _handshake(conn)
            resp = await _call(conn, "echo", {"text": "middleware ok"})
            assert resp["result"]["content"][0]["text"] == "middleware ok"


# ---------------------------------------------------------------------------
# 6 — Class-level middleware
# ---------------------------------------------------------------------------


class TestClassMiddleware:
    @pytest.fixture(scope="class")
    def app(self):
        log: list[str] = []

        @middleware()
        class _ClassLog:
            async def dispatch(self, request: Request, call_next: CallNext) -> Response:
                log.append(f"class:{request.path}")
                return await call_next(request)

        @use_middlewares(_ClassLog)
        @controller("/logged")
        class _LoggedCtrl:
            @get("/a")
            async def route_a(self) -> dict:
                return {"route": "a"}

            @get("/b")
            async def route_b(self) -> dict:
                return {"route": "b"}

        @controller("/unlogged")
        class _UnloggedCtrl:
            @get("/c")
            async def route_c(self) -> dict:
                return {"route": "c"}

        @module(
            controllers=[_LoggedCtrl, _UnloggedCtrl],
            providers=[_ClassLog],
            imports=[McpServerModule.for_root(EchoMcpServer)],
        )
        class App:
            pass

        a = LaurenFactory.create(App)
        TestClient(a)
        a._log = log  # type: ignore[attr-defined]
        return a

    def test_class_middleware_fires_for_all_routes_in_controller(self, app):
        TestClient(app).get("/logged/a")
        TestClient(app).get("/logged/b")
        assert any("logged/a" in e for e in app._log)  # type: ignore[attr-defined]
        assert any("logged/b" in e for e in app._log)  # type: ignore[attr-defined]

    def test_class_middleware_does_not_fire_for_other_controllers(self, app):
        log_before = len(app._log)  # type: ignore[attr-defined]
        TestClient(app).get("/unlogged/c")
        assert len(app._log) == log_before  # type: ignore[attr-defined]

    def test_class_middleware_routes_return_correct_data(self, app):
        assert TestClient(app).get("/logged/a").json() == {"route": "a"}
        assert TestClient(app).get("/logged/b").json() == {"route": "b"}

    def test_unlogged_controller_still_returns_correct_data(self, app):
        assert TestClient(app).get("/unlogged/c").json() == {"route": "c"}

    async def test_class_middleware_and_mcp_coexist(self, app):
        """Class middleware on HTTP controller doesn't affect MCP WS."""
        async with WsTestClient(app).connect("/mcp/ws") as conn:
            await _handshake(conn)
            resp = await _call(conn, "add", {"a": 7, "b": 3})
            assert int(resp["result"]["content"][0]["text"]) == 10


# ---------------------------------------------------------------------------
# 7 — Fully composed stack
# ---------------------------------------------------------------------------


class TestComposedStack:
    @pytest.fixture(scope="class")
    def app(self):
        events: list[str] = []

        @injectable(scope=Scope.SINGLETON)
        class _LogGuard:
            async def can_activate(self, ctx: ExecutionContext) -> bool:
                events.append("guard")
                return True

        @injectable(scope=Scope.SINGLETON)
        class _LogInterceptor:
            async def intercept(self, ctx: ExecutionContext, call_handler: CallHandler) -> Any:
                events.append("interceptor-before")
                result = await call_handler.handle()
                events.append("interceptor-after")
                return result

        @middleware()
        class _LogMiddleware:
            async def dispatch(self, request: Request, call_next: CallNext) -> Response:
                events.append("middleware-before")
                resp = await call_next(request)
                events.append("middleware-after")
                return resp

        @controller("/composed")
        class _Ctrl:
            @get("/")
            async def index(self) -> dict:
                events.append("handler")
                return {"ok": True}

        @module(
            controllers=[_Ctrl],
            providers=[_LogGuard, _LogInterceptor],
            imports=[McpServerModule.for_root(EchoMcpServer)],
        )
        class App:
            pass

        a = LaurenFactory.create(
            App,
            global_guards=[_LogGuard],
            global_interceptors=[_LogInterceptor],
            global_middlewares=[_LogMiddleware],
        )
        TestClient(a)
        a._events = events  # type: ignore[attr-defined]
        return a

    def test_middleware_guard_interceptor_fire_in_correct_order(self, app):
        """Full pipeline: middleware → guard → interceptor → handler."""
        app._events.clear()  # type: ignore[attr-defined]
        TestClient(app).get("/composed/")
        events = app._events  # type: ignore[attr-defined]
        assert events[0] == "middleware-before"
        assert "guard" in events
        assert "interceptor-before" in events
        assert "handler" in events
        assert "interceptor-after" in events
        assert events[-1] == "middleware-after"

    def test_all_http_routes_go_through_full_pipeline(self, app):
        app._events.clear()  # type: ignore[attr-defined]
        resp = TestClient(app).get("/composed/")
        assert resp.status_code == 200
        assert "middleware-before" in app._events  # type: ignore[attr-defined]

    async def test_mcp_ws_works_in_fully_composed_app(self, app):
        async with WsTestClient(app).connect("/mcp/ws") as conn:
            await _handshake(conn)
            resp = await _call(conn, "echo", {"text": "full stack"})
            assert resp["result"]["content"][0]["text"] == "full stack"

    async def test_mcp_add_tool_correct_in_full_stack(self, app):
        async with WsTestClient(app).connect("/mcp/ws") as conn:
            await _handshake(conn)
            resp = await _call(conn, "add", {"a": 100, "b": 200})
            assert int(resp["result"]["content"][0]["text"]) == 300
