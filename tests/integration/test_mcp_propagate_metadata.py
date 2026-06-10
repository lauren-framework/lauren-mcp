"""Runtime verification that @use_* metadata on @mcp_server is propagated and
enforced by Lauren's pipeline for both WS and SSE transports.

Tests verify:
  - @use_guards        → WS: rejected before @on_connect; SSE: 403 per-request
  - @use_interceptors  → SSE: wraps handlers, fires timing/logging logic
  - @use_middlewares   → SSE: middleware chain runs around every request
  - @use_encoder       → SSE: custom encoder used for all responses
  - @set_metadata      → readable by guards via ctx.get_metadata()
  - All of the above combined on one server class
"""

from __future__ import annotations

from typing import Any

import pytest
from lauren import (
    LaurenFactory,
    Scope,
    injectable,
    interceptor,
    middleware,
    module,
    set_metadata,
    use_encoder,
    use_guards,
    use_interceptors,
    use_middlewares,
)
from lauren.serialization import StdlibJSONEncoder
from lauren.testing import TestClient, WsTestClient
from lauren.types import ExecutionContext, Request, Response

from lauren_mcp import McpServerModule, mcp_server, mcp_tool

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_app(server_cls: type, transport: str = "ws") -> Any:
    @module(imports=[McpServerModule.for_root(server_cls, transport=transport)])
    class _App:
        pass

    return LaurenFactory.create(_App)


async def _handshake(conn: Any) -> None:
    await conn.send_json(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        }
    )
    msg = await conn.receive_json()
    assert msg.get("result") or msg.get("id") == 1
    await conn.send_json({"jsonrpc": "2.0", "method": "notifications/initialized"})


# ---------------------------------------------------------------------------
# WS — @use_guards
# ---------------------------------------------------------------------------


@injectable(scope=Scope.SINGLETON)
class _WsApiKeyGuard:
    async def can_activate(self, ctx: Any) -> bool:
        return ctx.request.headers.get("x-key") == "ws-secret"


@use_guards(_WsApiKeyGuard)
@mcp_server("/ws-guard-test")
class _WsGuardedServer:
    @mcp_tool()
    async def echo(self, msg: str) -> str:
        "Echo."
        return msg


class TestWsGuardPropagated:
    @pytest.fixture(scope="class")
    def app(self):
        return _make_app(_WsGuardedServer, transport="ws")

    async def test_rejected_without_key(self, app):
        async with WsTestClient(app).connect("/ws-guard-test/ws") as conn:
            assert conn.close_code == 1008

    async def test_allowed_with_key(self, app):
        async with WsTestClient(app).connect(
            "/ws-guard-test/ws", headers={"x-key": "ws-secret"}
        ) as conn:
            assert conn.close_code is None  # accepted


# ---------------------------------------------------------------------------
# WS — @set_metadata readable by guard
# ---------------------------------------------------------------------------


@injectable(scope=Scope.SINGLETON)
class _MetadataGuard:
    """Guard that checks a custom threshold stored via @set_metadata."""

    async def can_activate(self, ctx: Any) -> bool:
        # ctx.get_metadata works for both WsConnectionContext and ExecutionContext
        required = ctx.get_metadata("required_role", "user")
        return ctx.request.headers.get("x-role") == required


@set_metadata("required_role", "admin")
@use_guards(_MetadataGuard)
@mcp_server("/metadata-test")
class _MetadataServer:
    @mcp_tool()
    async def ping(self) -> str:
        "Ping."
        return "pong"


class TestWsSetMetadataPropagated:
    @pytest.fixture(scope="class")
    def app(self):
        return _make_app(_MetadataServer, transport="ws")

    async def test_rejected_without_admin_role(self, app):
        async with WsTestClient(app).connect(
            "/metadata-test/ws", headers={"x-role": "user"}
        ) as conn:
            assert conn.close_code == 1008

    async def test_allowed_with_admin_role(self, app):
        async with WsTestClient(app).connect(
            "/metadata-test/ws", headers={"x-role": "admin"}
        ) as conn:
            assert conn.close_code is None  # accepted


# ---------------------------------------------------------------------------
# SSE — @use_guards
# ---------------------------------------------------------------------------


@injectable(scope=Scope.SINGLETON)
class _SseApiKeyGuard:
    async def can_activate(self, ctx: ExecutionContext) -> bool:
        return ctx.request.headers.get("x-sse-key") == "sse-secret"


@use_guards(_SseApiKeyGuard)
@mcp_server("/sse-guard-test")
class _SseGuardedServer:
    @mcp_tool()
    async def greet(self, name: str) -> str:
        "Greet."
        return f"Hello, {name}"


class TestSseGuardPropagated:
    @pytest.fixture(scope="class")
    def app(self):
        return _make_app(_SseGuardedServer, transport="sse")

    def test_post_without_key_returns_403(self, app):
        client = TestClient(app)
        r = client.post("/sse-guard-test/", content=b"{}")
        assert r.status_code == 403

    def test_post_with_key_passes_guard(self, app):
        client = TestClient(app)
        # 400 because no session-id header, but guard passed (not 403)
        r = client.post(
            "/sse-guard-test/",
            content=b"{}",
            headers={"x-sse-key": "sse-secret"},
        )
        assert r.status_code != 403

    def test_post_wrong_key_returns_403(self, app):
        client = TestClient(app)
        r = client.post(
            "/sse-guard-test/",
            content=b"{}",
            headers={"x-sse-key": "wrong"},
        )
        assert r.status_code == 403

    def test_guard_applies_to_all_routes_on_controller(self, app):
        """Guard is controller-level, so it covers all SSE endpoints."""
        from lauren.reflect import get_all_routes

        routes = [r for r in get_all_routes(app) if "sse-guard-test" in r.full_path]
        assert len(routes) == 2  # GET /sse and POST /
        # All routes belong to the guarded controller
        ctrl_classes = {r.handler.__qualname__.rsplit(".", 1)[0] for r in routes}
        assert ctrl_classes  # at least one controller found
        for (_, path), ch in app._handlers.items():
            if "sse-guard-test" in path:
                assert len(ch.guards) > 0, f"No guards on {path}"


# ---------------------------------------------------------------------------
# SSE — @use_middlewares
# ---------------------------------------------------------------------------


_mw_calls: list[str] = []


@middleware()
class _TraceMiddleware:
    async def dispatch(self, request: Request, call_next: Any) -> Response:
        _mw_calls.append("before")
        response = await call_next(request)
        _mw_calls.append("after")
        return response


@use_middlewares(_TraceMiddleware)
@mcp_server("/mw-test")
class _MiddlewareServer:
    @mcp_tool()
    async def ping(self) -> str:
        "Ping."
        return "pong"


class TestSseMiddlewarePropagated:
    @pytest.fixture(scope="class")
    def app(self):
        _mw_calls.clear()
        return _make_app(_MiddlewareServer, transport="sse")

    def test_middleware_fires_on_sse_post(self, app):
        _mw_calls.clear()
        client = TestClient(app)
        client.post("/mw-test/", content=b"{}")
        assert "before" in _mw_calls
        assert "after" in _mw_calls

    def test_middleware_fires_on_second_post(self, app):
        _mw_calls.clear()
        client = TestClient(app)
        client.post("/mw-test/", content=b"{}")
        count = _mw_calls.count("before")
        assert count >= 1  # at least one before/after pair per request


# ---------------------------------------------------------------------------
# SSE — @use_interceptors
# ---------------------------------------------------------------------------


_interceptor_calls: list[str] = []


@interceptor()
class _LoggingInterceptor:
    async def intercept(self, ctx: Any, call_handler: Any) -> Any:
        _interceptor_calls.append("enter")
        result = await call_handler.handle()
        _interceptor_calls.append("exit")
        return result


@use_interceptors(_LoggingInterceptor)
@mcp_server("/icp-test")
class _InterceptorServer:
    @mcp_tool()
    async def ping(self) -> str:
        "Ping."
        return "pong"


class TestSseInterceptorPropagated:
    @pytest.fixture(scope="class")
    def app(self):
        _interceptor_calls.clear()
        return _make_app(_InterceptorServer, transport="sse")

    def test_interceptor_fires_on_post(self, app):
        _interceptor_calls.clear()
        client = TestClient(app)
        client.post("/icp-test/", content=b"{}")
        assert "enter" in _interceptor_calls
        assert "exit" in _interceptor_calls


# ---------------------------------------------------------------------------
# SSE — @use_encoder
# ---------------------------------------------------------------------------


class _RecordingEncoder(StdlibJSONEncoder):
    """Encoder that records every call for test assertions."""

    calls: list[str] = []

    def encode(self, obj: Any) -> bytes:
        _RecordingEncoder.calls.append("encode")
        return super().encode(obj)


@use_encoder(_RecordingEncoder())
@mcp_server("/encoder-test")
class _EncoderServer:
    @mcp_tool()
    async def ping(self) -> str:
        "Ping."
        return "pong"


class TestSseEncoderPropagated:
    @pytest.fixture(scope="class")
    def app(self):
        _RecordingEncoder.calls.clear()
        _app = _make_app(_EncoderServer, transport="sse")
        TestClient(_app)  # trigger startup so _handlers is populated
        return _app

    def test_encoder_is_propagated_to_sse_controller(self, app):
        # After startup, compiled handlers carry the propagated encoder.
        encoder_paths = []
        for (method, path), ch in app._handlers.items():
            if "encoder-test" in path:
                encoder_paths.append(path)
                assert isinstance(ch.encoder, _RecordingEncoder), (
                    f"Expected _RecordingEncoder on {method} {path}, got {ch.encoder!r}"
                )
        assert encoder_paths, "No /encoder-test routes in compiled handlers"

    def test_encoder_does_not_affect_other_endpoints(self, app):
        # Other apps/controllers should still use the default encoder
        for (_, path), ch in app._handlers.items():
            if "encoder-test" not in path:
                # Encoder may be None (uses app-level default) — that's correct
                assert not isinstance(ch.encoder, _RecordingEncoder)


# ---------------------------------------------------------------------------
# Combined — all metadata on one server
# ---------------------------------------------------------------------------


_combined_mw_calls: list[str] = []
_combined_icp_calls: list[str] = []


@injectable(scope=Scope.SINGLETON)
class _CombinedGuard:
    async def can_activate(self, ctx: Any) -> bool:
        return ctx.request.headers.get("x-combined") == "yes"


@middleware()
class _CombinedMiddleware:
    async def dispatch(self, req: Request, call_next: Any) -> Response:
        _combined_mw_calls.append("mw")
        return await call_next(req)


@interceptor()
class _CombinedInterceptor:
    async def intercept(self, ctx: Any, ch: Any) -> Any:
        _combined_icp_calls.append("icp")
        return await ch.handle()


@set_metadata("server_type", "combined")
@use_guards(_CombinedGuard)
@use_middlewares(_CombinedMiddleware)
@use_interceptors(_CombinedInterceptor)
@mcp_server("/combined-test")
class _CombinedServer:
    @mcp_tool()
    async def status(self) -> str:
        "Status."
        return "ok"


class TestCombinedPropagation:
    @pytest.fixture(scope="class")
    def app(self):
        _combined_mw_calls.clear()
        _combined_icp_calls.clear()
        return _make_app(_CombinedServer, transport="sse")

    def test_guard_rejects_without_header(self, app):
        client = TestClient(app)
        r = client.post("/combined-test/", content=b"{}")
        assert r.status_code == 403

    def test_guard_allows_with_header_on_post(self, app):
        client = TestClient(app)
        r = client.post(
            "/combined-test/",
            content=b"{}",
            headers={"x-combined": "yes"},
        )
        assert r.status_code != 403

    def test_middleware_fires_with_valid_header(self, app):
        _combined_mw_calls.clear()
        client = TestClient(app)
        client.post(
            "/combined-test/",
            content=b"{}",
            headers={"x-combined": "yes"},
        )
        assert "mw" in _combined_mw_calls

    def test_interceptor_fires_with_valid_header(self, app):
        _combined_icp_calls.clear()
        client = TestClient(app)
        client.post(
            "/combined-test/",
            content=b"{}",
            headers={"x-combined": "yes"},
        )
        assert "icp" in _combined_icp_calls

    def test_set_metadata_propagated_to_transport_controller(self, app):
        from lauren.reflect import get_all_routes, reflect_user_metadata

        routes = get_all_routes(app)
        combined_routes = [r for r in routes if "combined-test" in r.full_path]
        assert combined_routes, "No /combined-test routes found"
        # All routes on the controller share the controller-level metadata
        # The controller class carries the metadata — not individual handlers
        # Verify via class-level check using controller_cls from compiled handler
        from lauren._asgi import LaurenApp  # noqa: PLC0415

        assert isinstance(app, LaurenApp)
        for (_, path), ch in app._handlers.items():
            if "combined-test" in path:
                meta = reflect_user_metadata(ch.controller_cls)
                assert meta.get("server_type") == "combined"
                return
        pytest.fail("combined-test controller not found in compiled handlers")
