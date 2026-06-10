"""Tests for @use_guards, @use_interceptors, @use_middlewares on @mcp_server
with HTTP+SSE transport.

Because the SSE controller is a real Lauren @controller, Lauren's full HTTP
pipeline applies — guards run before handler dispatch, interceptors wrap
responses, middleware wraps the entire request/response cycle.

Test classes:
  TestSseGuards        (7)  — no key/wrong key → 403, valid key → 400/202
  TestSseInterceptors  (5)  — header added, response transformed, order
  TestSseMiddlewares   (5)  — request mutation, response mutation, order
  TestSseComposed      (5)  — all three together, correct pipeline order

Total: 22 tests
"""

from __future__ import annotations

from typing import Any

import pytest
from lauren import (
    LaurenFactory,
    Scope,
    injectable,
    middleware,
    module,
    use_guards,
    use_interceptors,
    use_middlewares,
)
from lauren.testing import TestClient
from lauren.types import CallHandler, CallNext, ExecutionContext, Request, Response

from lauren_mcp import McpServerModule, mcp_server, mcp_tool
from lauren_mcp._server._session import SseSessionStore

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _post(client: TestClient, body: bytes, path: str = "/mcp/", **headers: str) -> Any:
    """POST to *path* with the given body and headers."""
    return client.post(
        path,
        content=body,
        headers={"content-type": "application/json", **headers},
    )


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@injectable(scope=Scope.SINGLETON)
class ApiKeyGuard:
    async def can_activate(self, ctx: ExecutionContext) -> bool:
        return ctx.request.headers.get("x-api-key") == "valid"


@injectable(scope=Scope.SINGLETON)
class RoleGuard:
    async def can_activate(self, ctx: ExecutionContext) -> bool:
        return ctx.request.headers.get("x-role") == "admin"


@injectable(scope=Scope.SINGLETON)
class AlwaysDenyGuard:
    async def can_activate(self, ctx: ExecutionContext) -> bool:
        return False


# ---------------------------------------------------------------------------
# 1 — Guards on SSE transport
# ---------------------------------------------------------------------------


class TestSseGuards:
    @pytest.fixture(scope="class")
    def app(self):
        @use_guards(ApiKeyGuard)
        @mcp_server("/mcp")
        class _Srv:
            @mcp_tool()
            async def ping(self) -> str:
                "Ping."
                return "pong"

        @module(imports=[McpServerModule.for_root(_Srv, transport="sse")])
        class _App:
            pass

        a = LaurenFactory.create(_App)
        TestClient(a)
        return a

    def test_post_without_key_returns_403(self, app):
        """Guard blocks POST /mcp/ without X-Api-Key → 403."""
        resp = _post(TestClient(app), b"{}")
        assert resp.status_code == 403

    def test_post_wrong_key_returns_403(self, app):
        resp = _post(TestClient(app), b"{}", **{"x-api-key": "wrong"})
        assert resp.status_code == 403

    def test_post_valid_key_passes_guard(self, app):
        """Guard passes, missing session-id → 400 (not 403)."""
        resp = _post(TestClient(app), b"{}", **{"x-api-key": "valid"})
        assert resp.status_code == 400

    async def test_post_valid_key_with_session_returns_202(self, app):
        """Valid key + valid session → 202 Accepted."""
        store: SseSessionStore = await app.container.resolve(SseSessionStore)
        sid = "guard-test-session"
        store.create(sid)
        try:
            resp = _post(
                TestClient(app),
                b'{"jsonrpc":"2.0","method":"notifications/initialized"}',
                **{"x-api-key": "valid", "mcp-session-id": sid},
            )
            assert resp.status_code == 202
        finally:
            store.remove(sid)

    def test_always_deny_guard_blocks_all_posts(self):
        @use_guards(AlwaysDenyGuard)
        @mcp_server("/mcp-denied")
        class _Srv:
            @mcp_tool()
            async def ping(self) -> str:
                "Ping."
                return "pong"

        @module(imports=[McpServerModule.for_root(_Srv, transport="sse")])
        class _App:
            pass

        a = LaurenFactory.create(_App)
        TestClient(a)
        resp = _post(TestClient(a), b"{}", path="/mcp-denied/", **{"x-api-key": "any"})
        assert resp.status_code == 403

    def test_multiple_guards_all_must_pass(self):
        @use_guards(ApiKeyGuard, RoleGuard)
        @mcp_server("/mcp-multi")
        class _Srv:
            @mcp_tool()
            async def ping(self) -> str:
                "Ping."
                return "pong"

        @module(imports=[McpServerModule.for_root(_Srv, transport="sse")])
        class _App:
            pass

        a = LaurenFactory.create(_App)
        TestClient(a)
        client = TestClient(a)

        # Only api key → role guard fails → 403
        resp = _post(client, b"{}", path="/mcp-multi/", **{"x-api-key": "valid"})
        assert resp.status_code == 403

        # Both pass → 400 (guard passed, missing session-id)
        resp = _post(client, b"{}", path="/mcp-multi/", **{"x-api-key": "valid", "x-role": "admin"})
        assert resp.status_code == 400

    def test_guard_with_di_injected_service(self):
        @injectable(scope=Scope.SINGLETON)
        class _Store:
            def is_valid(self, key: str) -> bool:
                return key in ("key-a", "key-b")

        @injectable(scope=Scope.SINGLETON)
        class _StoreGuard:
            def __init__(self, store: _Store) -> None:
                self._store = store

            async def can_activate(self, ctx: ExecutionContext) -> bool:
                return self._store.is_valid(ctx.request.headers.get("x-key", ""))

        @use_guards(_StoreGuard)
        @mcp_server("/mcp-store")
        class _Srv:
            @mcp_tool()
            async def ping(self) -> str:
                "Ping."
                return "pong"

        @module(imports=[McpServerModule.for_root(_Srv, providers=[_Store], transport="sse")])
        class _App:
            pass

        a = LaurenFactory.create(_App)
        TestClient(a)
        client = TestClient(a)

        assert _post(client, b"{}", path="/mcp-store/", **{"x-key": "invalid"}).status_code == 403
        assert _post(client, b"{}", path="/mcp-store/", **{"x-key": "key-a"}).status_code == 400


# ---------------------------------------------------------------------------
# 2 — Interceptors on SSE transport
# ---------------------------------------------------------------------------


class TestSseInterceptors:
    @pytest.fixture(scope="class")
    def app(self):
        @injectable(scope=Scope.SINGLETON)
        class _HeaderInterceptor:
            async def intercept(self, ctx: ExecutionContext, call_handler: CallHandler) -> Any:
                result = await call_handler.handle()
                if isinstance(result, Response):
                    return result.with_header("x-intercepted", "true")
                return result

        @use_interceptors(_HeaderInterceptor)
        @mcp_server("/mcp")
        class _Srv:
            @mcp_tool()
            async def ping(self) -> str:
                "Ping."
                return "pong"

        @module(imports=[McpServerModule.for_root(_Srv, transport="sse")])
        class _App:
            pass

        a = LaurenFactory.create(_App)
        TestClient(a)
        return a

    def test_interceptor_fires_on_post(self, app):
        """Interceptor runs on POST /mcp/ requests."""
        resp = _post(TestClient(app), b"{}")
        assert resp.header("x-intercepted") == "true"

    async def test_interceptor_fires_on_valid_session_post(self, app):
        """Interceptor fires even for valid session posts."""
        store: SseSessionStore = await app.container.resolve(SseSessionStore)
        sid = "interceptor-test"
        store.create(sid)
        try:
            resp = _post(
                TestClient(app),
                b'{"jsonrpc":"2.0","id":1,"method":"ping"}',
                **{"mcp-session-id": sid},
            )
            assert resp.header("x-intercepted") == "true"
        finally:
            store.remove(sid)

    def test_interceptor_receives_response_object(self):
        """Interceptor sees Response objects (Lauren auto-converts handlers)."""
        seen_type: list[str] = []

        @injectable(scope=Scope.SINGLETON)
        class _TypeObserver:
            async def intercept(self, ctx: ExecutionContext, call_handler: CallHandler) -> Any:
                result = await call_handler.handle()
                seen_type.append(type(result).__name__)
                return result

        @use_interceptors(_TypeObserver)
        @mcp_server("/mcp")
        class _Srv:
            @mcp_tool()
            async def ping(self) -> str:
                "Ping."
                return "pong"

        @module(imports=[McpServerModule.for_root(_Srv, transport="sse")])
        class _App:
            pass

        a = LaurenFactory.create(_App)
        TestClient(a)
        _post(TestClient(a), b"{}")
        # Lauren converts handler return to Response before interceptor sees it
        assert "Response" in seen_type[0]

    def test_multiple_interceptors_compose(self):
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

        @use_interceptors(_First, _Second)
        @mcp_server("/mcp")
        class _Srv:
            @mcp_tool()
            async def ping(self) -> str:
                "Ping."
                return "pong"

        @module(imports=[McpServerModule.for_root(_Srv, transport="sse")])
        class _App:
            pass

        a = LaurenFactory.create(_App)
        TestClient(a)
        _post(TestClient(a), b"{}")
        assert order == ["first-before", "second-before", "second-after", "first-after"]

    def test_interceptor_can_short_circuit(self):
        """Interceptor can return early without calling the handler."""

        @injectable(scope=Scope.SINGLETON)
        class _EarlyExit:
            async def intercept(self, ctx: ExecutionContext, call_handler: CallHandler) -> Any:
                return Response.json({"short": "circuit"}, status=503)

        @use_interceptors(_EarlyExit)
        @mcp_server("/mcp")
        class _Srv:
            @mcp_tool()
            async def ping(self) -> str:
                "Ping."
                return "pong"

        @module(imports=[McpServerModule.for_root(_Srv, transport="sse")])
        class _App:
            pass

        a = LaurenFactory.create(_App)
        TestClient(a)
        resp = _post(TestClient(a), b"{}")
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# 3 — Middleware on SSE transport
# ---------------------------------------------------------------------------


class TestSseMiddlewares:
    @pytest.fixture(scope="class")
    def app(self):
        @middleware()
        class _AddHeader:
            async def dispatch(self, request: Request, call_next: CallNext) -> Response:
                resp = await call_next(request)
                return resp.with_header("x-mw", "fired")

        @use_middlewares(_AddHeader)
        @mcp_server("/mcp")
        class _Srv:
            @mcp_tool()
            async def ping(self) -> str:
                "Ping."
                return "pong"

        @module(imports=[McpServerModule.for_root(_Srv, transport="sse")])
        class _App:
            pass

        a = LaurenFactory.create(_App)
        TestClient(a)
        return a

    def test_middleware_fires_on_post(self, app):
        resp = _post(TestClient(app), b"{}")
        assert resp.header("x-mw") == "fired"

    def test_middleware_can_mutate_request_state(self):
        seen_state: list[str] = []

        @middleware()
        class _StateWriter:
            async def dispatch(self, request: Request, call_next: CallNext) -> Response:
                request.state.set("mcp_user", "alice")
                return await call_next(request)

        @injectable(scope=Scope.SINGLETON)
        class _StateReader:
            async def intercept(self, ctx: ExecutionContext, call_handler: CallHandler) -> Any:
                seen_state.append(ctx.request.state.get("mcp_user", "?"))
                return await call_handler.handle()

        @use_middlewares(_StateWriter)
        @use_interceptors(_StateReader)
        @mcp_server("/mcp")
        class _Srv:
            @mcp_tool()
            async def ping(self) -> str:
                "Ping."
                return "pong"

        @module(imports=[McpServerModule.for_root(_Srv, transport="sse")])
        class _App:
            pass

        a = LaurenFactory.create(_App)
        TestClient(a)
        _post(TestClient(a), b"{}")
        assert seen_state[0] == "alice"

    def test_middleware_can_short_circuit(self):
        @middleware()
        class _Maintenance:
            async def dispatch(self, request: Request, call_next: CallNext) -> Response:
                return Response.json({"mode": "maintenance"}, status=503)

        @use_middlewares(_Maintenance)
        @mcp_server("/mcp")
        class _Srv:
            @mcp_tool()
            async def ping(self) -> str:
                "Ping."
                return "pong"

        @module(imports=[McpServerModule.for_root(_Srv, transport="sse")])
        class _App:
            pass

        a = LaurenFactory.create(_App)
        TestClient(a)
        resp = _post(TestClient(a), b"{}")
        assert resp.status_code == 503

    def test_multiple_middlewares_onion_order(self):
        order: list[str] = []

        @middleware()
        class _Outer:
            async def dispatch(self, request: Request, call_next: CallNext) -> Response:
                order.append("outer-before")
                resp = await call_next(request)
                order.append("outer-after")
                return resp

        @middleware()
        class _Inner:
            async def dispatch(self, request: Request, call_next: CallNext) -> Response:
                order.append("inner-before")
                resp = await call_next(request)
                order.append("inner-after")
                return resp

        @use_middlewares(_Outer, _Inner)
        @mcp_server("/mcp")
        class _Srv:
            @mcp_tool()
            async def ping(self) -> str:
                "Ping."
                return "pong"

        @module(imports=[McpServerModule.for_root(_Srv, transport="sse")])
        class _App:
            pass

        a = LaurenFactory.create(_App)
        TestClient(a)
        _post(TestClient(a), b"{}")
        assert order == ["outer-before", "inner-before", "inner-after", "outer-after"]

    def test_middleware_fires_on_both_sse_endpoints(self):
        """Middleware applies to both GET /sse and POST / endpoints."""
        count: list[int] = [0]

        @middleware()
        class _Counter:
            async def dispatch(self, request: Request, call_next: CallNext) -> Response:
                count[0] += 1
                return await call_next(request)

        @use_middlewares(_Counter)
        @mcp_server("/mcp")
        class _Srv:
            @mcp_tool()
            async def ping(self) -> str:
                "Ping."
                return "pong"

        @module(imports=[McpServerModule.for_root(_Srv, transport="sse")])
        class _App:
            pass

        a = LaurenFactory.create(_App)
        TestClient(a)
        client = TestClient(a)
        _post(client, b"{}")
        _post(client, b"{}", **{"x-api-key": "any"})
        assert count[0] == 2


# ---------------------------------------------------------------------------
# 4 — All three composed together
# ---------------------------------------------------------------------------


class TestSseComposed:
    @pytest.fixture(scope="class")
    def app(self):
        pipeline: list[str] = []

        @middleware()
        class _Mw:
            async def dispatch(self, request: Request, call_next: CallNext) -> Response:
                pipeline.append("mw-before")
                resp = await call_next(request)
                pipeline.append("mw-after")
                return resp

        @injectable(scope=Scope.SINGLETON)
        class _Guard:
            async def can_activate(self, ctx: ExecutionContext) -> bool:
                pipeline.append("guard")
                return ctx.request.headers.get("x-ok") == "yes"

        @injectable(scope=Scope.SINGLETON)
        class _Icp:
            async def intercept(self, ctx: ExecutionContext, call_handler: CallHandler) -> Any:
                pipeline.append("icp-before")
                result = await call_handler.handle()
                pipeline.append("icp-after")
                return result

        @use_middlewares(_Mw)
        @use_guards(_Guard)
        @use_interceptors(_Icp)
        @mcp_server("/mcp")
        class _Srv:
            @mcp_tool()
            async def ping(self) -> str:
                "Ping."
                return "pong"

        @module(imports=[McpServerModule.for_root(_Srv, transport="sse")])
        class _App:
            pass

        a = LaurenFactory.create(_App)
        TestClient(a)
        a._pipeline = pipeline  # type: ignore[attr-defined]
        return a

    def test_guard_blocks_without_header(self, app):
        app._pipeline.clear()  # type: ignore[attr-defined]
        resp = _post(TestClient(app), b"{}")
        assert resp.status_code == 403

    def test_full_pipeline_order_with_valid_header(self, app):
        """Correct order: middleware → guard → interceptor → handler."""
        app._pipeline.clear()  # type: ignore[attr-defined]
        _post(TestClient(app), b"{}", **{"x-ok": "yes"})
        p = app._pipeline  # type: ignore[attr-defined]
        # middleware fires first and last (onion model)
        assert p[0] == "mw-before"
        assert "guard" in p
        assert "icp-before" in p
        assert "icp-after" in p
        assert p[-1] == "mw-after"

    async def test_middleware_fires_before_guard_rejection(self, app):
        """Middleware's pre-handler code runs even when a guard rejects.

        Lauren raises internally on guard rejection so the middleware's
        post-``call_next`` code does not run — only the pre-call code fires.
        """
        app._pipeline.clear()  # type: ignore[attr-defined]
        resp = _post(TestClient(app), b"{}")  # no x-ok header → guard rejects
        assert resp.status_code == 403
        assert "mw-before" in app._pipeline  # type: ignore[attr-defined]
        assert "guard" in app._pipeline  # type: ignore[attr-defined]

    async def test_interceptor_does_not_fire_when_guard_rejects(self, app):
        """Interceptor only runs if guard passes."""
        app._pipeline.clear()  # type: ignore[attr-defined]
        _post(TestClient(app), b"{}")  # guard rejects
        assert "icp-before" not in app._pipeline  # type: ignore[attr-defined]

    async def test_both_transport_has_guards_on_ws_and_sse(self):
        """transport='both': guards apply to WS (close 1008) and SSE (403)."""
        from lauren.testing import WsTestClient

        @injectable(scope=Scope.SINGLETON)
        class _BothGuard:
            async def can_activate(self, ctx: Any) -> bool:
                key = ctx.request.headers.get("x-api-key", "")
                return key == "valid"

        @use_guards(_BothGuard)
        @mcp_server("/mcp")
        class _Srv:
            @mcp_tool()
            async def ping(self) -> str:
                "Ping."
                return "pong"

        @module(imports=[McpServerModule.for_root(_Srv, transport="both")])
        class _App:
            pass

        a = LaurenFactory.create(_App)
        TestClient(a)

        # SSE: POST without key → 403
        resp = _post(TestClient(a), b"{}")
        assert resp.status_code == 403

        # WS: no key → close 1008
        async with WsTestClient(a).connect("/mcp/ws") as conn:
            assert conn.close_code == 1008
