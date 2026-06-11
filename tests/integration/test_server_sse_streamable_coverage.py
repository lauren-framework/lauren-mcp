"""Integration tests to improve coverage for _sse.py and _streamable.py.

Targets the following uncovered regions:
  _sse.py:
    111-137  — open_stream SSE generator (session cleanup, registry, queue drain)
    184-192  — body read error path in handle_rpc
    206      — notification handling in handle_rpc
    229-233  — unexpected response frame warning path
    249-254  — legacy guard_classes / interceptor_classes / middleware_classes args
    258-265  — transport_security guard wiring

  _streamable.py:
    84-85    — StreamableSessionStore.remove with pending_client_rpcs cancellation
    177-181  — body read/parse error returning 400
    190-203  — client response frame (server-initiated RPC reply) handling
    209      — notifications/initialized sets session.initialized
    212-215  — $/cancelRequest notification dispatches dispatcher.cancel
    229-230  — unsupported message type returns 400
    243      — stateless notification returns 202
    246-249  — stateless client-response frame returns 202
    255      — stateless unsupported message returns 400
    258      — stateless JSON mode (no SSE) dispatch
    283-313  — stateless SSE mode generator
    357-361  — handle_get stateless returns 405
    364-378  — handle_get non-SSE and missing-session branches
    439-440  — event_store path in push generator
    445      — event_store.replay_events_after call
    448-450  — event_store event emission
    472-516  — handle_delete stateless 405, missing-session 400, success 204
    535      — oauth_authorization_server with metadata
    578-586  — transport_security guard wiring on streamable controller
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from lauren import LaurenFactory, module
from lauren.testing import TestClient

from lauren_mcp import McpServerModule, mcp_server, mcp_tool
from lauren_mcp._server._dispatcher import McpDispatcher
from lauren_mcp._server._registry import McpConnectionRegistry
from lauren_mcp._server._streamable import (
    StreamableSessionStore,
    mcp_streamable_http_controller,
)

pytestmark = pytest.mark.asyncio

_SESSION_HEADER = "mcp-session-id"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sse_app(server_cls: type) -> Any:
    @module(imports=[McpServerModule.for_root(server_cls, transport="sse")])
    class _App:
        pass

    app = LaurenFactory.create(_App)
    TestClient(app)  # trigger @post_construct
    return app


def _make_streamable_app(server_cls: type) -> Any:
    @module(imports=[McpServerModule.for_root(server_cls, transport="streamable")])
    class _App:
        pass

    app = LaurenFactory.create(_App)
    TestClient(app)
    return app


def _rpc(client: TestClient, body: dict[str, Any], path: str = "/mcp/", **headers: str) -> Any:
    return client.post(
        path,
        content=json.dumps(body).encode(),
        headers={"content-type": "application/json", **headers},
    )


def _initialize_streamable(client: TestClient, path: str = "/mcp/") -> tuple[str, dict[str, Any]]:
    resp = _rpc(
        client,
        {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"},
            },
        },
        path=path,
    )
    assert resp.status_code == 200
    session_id = resp.header(_SESSION_HEADER)
    assert session_id
    payload = resp.json()
    notif = _rpc(
        client,
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        path=path,
        **{_SESSION_HEADER: session_id},
    )
    assert notif.status_code == 202
    return session_id, payload


def _make_raw_streamable_ctrl(path: str, **kwargs: Any) -> Any:
    """Build a streamable controller instance with a real dispatcher (no DI)."""
    ctrl_cls = mcp_streamable_http_controller(path, **kwargs)

    dispatcher = McpDispatcher()

    # Register a minimal initialize handler so stateless calls work
    async def _init(params: Any) -> dict:  # type: ignore[return]
        return {
            "protocolVersion": "2025-03-26",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "test", "version": "0"},
        }

    dispatcher.register("initialize", _init)

    sessions = StreamableSessionStore()
    registry = McpConnectionRegistry()

    ctrl = object.__new__(ctrl_cls)
    ctrl._dispatcher = dispatcher
    ctrl._sessions = sessions
    ctrl._registry = registry
    return ctrl


def _make_mock_request(body: bytes = b"", headers: dict[str, str] | None = None) -> MagicMock:
    req = MagicMock()
    req.headers = headers or {}
    req.body = AsyncMock(return_value=body)
    return req


def _make_mock_ec(request: Any = None) -> MagicMock:
    ec = MagicMock()
    ec.request = request or MagicMock()
    ec.metadata = {}
    return ec


# ---------------------------------------------------------------------------
# SSE Servers
# ---------------------------------------------------------------------------


@mcp_server("/sse-cov")
class _SseCovServer:
    @mcp_tool()
    async def echo(self, msg: str) -> str:
        """Echo a message."""
        return msg


# ---------------------------------------------------------------------------
# Streamable HTTP server
# ---------------------------------------------------------------------------


@mcp_server("/stream-cov")
class _StreamCovServer:
    @mcp_tool()
    async def add(self, a: int, b: int) -> int:
        """Add two numbers."""
        return a + b


# ---------------------------------------------------------------------------
# SSE: missing session header returns 400
# ---------------------------------------------------------------------------


class TestSseMissingSessionHeader:
    @pytest.fixture(scope="class")
    def sse_app(self):
        return _make_sse_app(_SseCovServer)

    def test_post_without_session_returns_400(self, sse_app: Any) -> None:
        """POST with no mcp-session-id header returns 400."""
        client = TestClient(sse_app)
        resp = client.post(
            "/sse-cov/",
            content=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode(),
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400

    def test_post_with_unknown_session_returns_404(self, sse_app: Any) -> None:
        """POST with unknown session_id returns 404."""
        client = TestClient(sse_app)
        resp = client.post(
            "/sse-cov/",
            content=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode(),
            headers={"content-type": "application/json", _SESSION_HEADER: "bogus"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# SSE: notification handling in handle_rpc (line 206)
# ---------------------------------------------------------------------------


class TestSseNotificationHandling:
    @pytest.fixture(scope="class")
    def sse_app(self):
        return _make_sse_app(_SseCovServer)

    async def test_notification_with_valid_session_returns_202(self, sse_app: Any) -> None:
        """Notification to a live session returns 202 (line 206 path)."""
        from lauren_mcp._server._session import SseSessionStore

        client = TestClient(sse_app)
        sessions: SseSessionStore = await sse_app.container.resolve(SseSessionStore)
        session_id = "notif-session-001"
        sessions.create(session_id)

        resp = client.post(
            "/sse-cov/",
            content=json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode(),
            headers={"content-type": "application/json", _SESSION_HEADER: session_id},
        )
        assert resp.status_code == 202


# ---------------------------------------------------------------------------
# SSE: parse error path (lines 184-192)
# ---------------------------------------------------------------------------


class TestSseParseError:
    @pytest.fixture(scope="class")
    def sse_app(self):
        return _make_sse_app(_SseCovServer)

    async def test_malformed_json_with_session_returns_202(self, sse_app: Any) -> None:
        """Malformed JSON body → parse error put on queue, returns 202."""
        from lauren_mcp._server._session import SseSessionStore

        client = TestClient(sse_app)
        sessions: SseSessionStore = await sse_app.container.resolve(SseSessionStore)
        session_id = "parse-err-session"
        sessions.create(session_id)

        resp = client.post(
            "/sse-cov/",
            content=b"not-json!!",
            headers={"content-type": "application/json", _SESSION_HEADER: session_id},
        )
        assert resp.status_code == 202


# ---------------------------------------------------------------------------
# SSE: unexpected response frame (lines 229-233)
# ---------------------------------------------------------------------------


class TestSseResponseFrame:
    @pytest.fixture(scope="class")
    def sse_app(self):
        return _make_sse_app(_SseCovServer)

    async def test_response_frame_with_session_returns_202(self, sse_app: Any) -> None:
        """Client sending a JsonRpcResponse frame is silently accepted (202)."""
        from lauren_mcp._server._session import SseSessionStore

        client = TestClient(sse_app)
        sessions: SseSessionStore = await sse_app.container.resolve(SseSessionStore)
        session_id = "resp-frame-session"
        sessions.create(session_id)

        # A JsonRpcResponse frame from the client — unexpected in SSE
        resp = client.post(
            "/sse-cov/",
            content=json.dumps({"jsonrpc": "2.0", "id": 42, "result": {"ok": True}}).encode(),
            headers={"content-type": "application/json", _SESSION_HEADER: session_id},
        )
        assert resp.status_code == 202


# ---------------------------------------------------------------------------
# SSE: open_stream generator path (lines 111-137)
# ---------------------------------------------------------------------------


class TestSseOpenStream:
    async def test_open_stream_returns_event_stream(self) -> None:
        """open_stream creates a session and returns EventStream (lines 111-137)."""
        from lauren.sse import EventStream
        from lauren.types import Request as LaurenRequest

        from lauren_mcp._server._dispatcher import McpDispatcher
        from lauren_mcp._server._registry import McpConnectionRegistry
        from lauren_mcp._server._session import SseSessionStore
        from lauren_mcp._server._sse import mcp_http_sse_controller

        ctrl_cls = mcp_http_sse_controller("/sse-direct")
        dispatcher = McpDispatcher()
        sessions = SseSessionStore()
        registry = McpConnectionRegistry()

        ctrl = object.__new__(ctrl_cls)
        ctrl._dispatcher = dispatcher
        ctrl._sessions = sessions
        ctrl._registry = registry

        mock_request = MagicMock(spec=LaurenRequest)
        mock_request.headers = {}

        result = await ctrl.open_stream(mock_request)
        assert isinstance(result, EventStream)

    async def test_open_stream_generator_yields_endpoint_and_messages(self) -> None:
        """open_stream generator yields endpoint event, then message events, then exits on sentinel."""
        from lauren.sse import EventStream

        from lauren_mcp._server._dispatcher import McpDispatcher
        from lauren_mcp._server._registry import McpConnectionRegistry
        from lauren_mcp._server._session import SseSessionStore
        from lauren_mcp._server._sse import mcp_http_sse_controller

        ctrl_cls = mcp_http_sse_controller("/sse-gen")
        dispatcher = McpDispatcher()
        sessions = SseSessionStore()
        registry = McpConnectionRegistry()

        ctrl = object.__new__(ctrl_cls)
        ctrl._dispatcher = dispatcher
        ctrl._sessions = sessions
        ctrl._registry = registry

        mock_request = MagicMock()
        mock_request.headers = {}

        result = await ctrl.open_stream(mock_request)
        assert isinstance(result, EventStream)

        # Drain the generator
        events = []
        gen = result._source.__aiter__()

        # First event should be the endpoint event
        first_event = await gen.__anext__()
        events.append(first_event)
        assert first_event.event == "endpoint"

        # Find the session that was created by looking at sessions store
        session_ids = list(sessions._sessions.keys())
        assert session_ids
        session_id = session_ids[-1]
        queue = sessions.get(session_id)

        # Put a message on the queue, then sentinel
        assert queue is not None
        await queue.put('{"jsonrpc":"2.0","method":"ping"}')
        await queue.put(None)  # sentinel to stop

        # Read next event (the message)
        msg_event = await gen.__anext__()
        events.append(msg_event)
        assert msg_event.event == "message"

        # Consume until StopAsyncIteration
        try:
            await gen.__anext__()
        except StopAsyncIteration:
            pass

        assert len(events) == 2


# ---------------------------------------------------------------------------
# SSE: JsonRpcRequest dispatch path (lines 205-226)
# ---------------------------------------------------------------------------


class TestSseRequestDispatch:
    async def test_rpc_request_dispatched_to_queue(self) -> None:
        """A JsonRpcRequest is dispatched and response put on the queue (lines 205-226)."""
        from lauren_mcp._server._dispatcher import McpDispatcher
        from lauren_mcp._server._registry import McpConnectionRegistry
        from lauren_mcp._server._session import SseSessionStore
        from lauren_mcp._server._sse import mcp_http_sse_controller
        from lauren.types import ExecutionContext

        ctrl_cls = mcp_http_sse_controller("/sse-req-dispatch")
        dispatcher = McpDispatcher()

        # Register a simple tools/list handler
        async def _tools_list(params: Any) -> dict:
            return {"tools": []}

        dispatcher.register("tools/list", _tools_list)

        sessions = SseSessionStore()
        registry = McpConnectionRegistry()

        ctrl = object.__new__(ctrl_cls)
        ctrl._dispatcher = dispatcher
        ctrl._sessions = sessions
        ctrl._registry = registry

        session_id = "rpc-dispatch-sess"
        queue = sessions.create(session_id)

        mock_request = MagicMock()
        mock_request.headers = {_SESSION_HEADER: session_id}
        body = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
            }
        ).encode()
        mock_request.body = AsyncMock(return_value=body)

        mock_ec = MagicMock(spec=ExecutionContext)
        mock_ec.request = mock_request
        mock_ec.metadata = {}

        result = await ctrl.handle_rpc(mock_request, mock_ec)
        assert result.status == 202

        # The response should be on the queue
        response_json = queue.get_nowait()
        parsed = json.loads(response_json)
        assert "result" in parsed


async def test_sse_handle_rpc_body_read_exception() -> None:
    """Non-parse exception during body() triggers lines 184-192."""
    from lauren_mcp._server._dispatcher import McpDispatcher
    from lauren_mcp._server._registry import McpConnectionRegistry
    from lauren_mcp._server._session import SseSessionStore
    from lauren_mcp._server._sse import mcp_http_sse_controller
    from lauren.types import ExecutionContext

    ctrl_cls = mcp_http_sse_controller("/sse-body-err")
    dispatcher = McpDispatcher()
    sessions = SseSessionStore()
    registry = McpConnectionRegistry()

    ctrl = object.__new__(ctrl_cls)
    ctrl._dispatcher = dispatcher
    ctrl._sessions = sessions
    ctrl._registry = registry

    session_id = "body-err-sess"
    queue = sessions.create(session_id)

    mock_request = MagicMock()
    mock_request.headers = {_SESSION_HEADER: session_id}
    # Simulate a non-parse error in request.body()
    mock_request.body = AsyncMock(side_effect=RuntimeError("IO error reading body"))

    mock_ec = MagicMock(spec=ExecutionContext)
    mock_ec.request = mock_request
    mock_ec.metadata = {}

    result = await ctrl.handle_rpc(mock_request, mock_ec)
    assert result.status == 202

    # An internal error response should be on the queue
    error_json = queue.get_nowait()
    parsed = json.loads(error_json)
    assert "error" in parsed


# ---------------------------------------------------------------------------
# SSE: legacy explicit guard_classes / interceptor_classes / middleware_classes
# ---------------------------------------------------------------------------


class TestSseLegacyExplicitParams:
    """Test the guard_classes / interceptor_classes / middleware_classes fallback paths (lines 249-254)."""

    def test_explicit_guard_classes_applied(self) -> None:
        from lauren_mcp._server._sse import mcp_http_sse_controller

        class _AlwaysDenyGuard:
            async def can_activate(self, ctx: Any) -> bool:
                return False

        ctrl_cls = mcp_http_sse_controller(
            "/test-explicit-guard",
            source=None,
            guard_classes=(_AlwaysDenyGuard,),
        )
        assert isinstance(ctrl_cls, type)

    def test_explicit_interceptor_classes_applied(self) -> None:
        from lauren_mcp._server._sse import mcp_http_sse_controller

        class _FakeInterceptor:
            async def intercept(self, ctx: Any, handler: Any) -> Any:
                return await handler.handle()

        ctrl_cls = mcp_http_sse_controller(
            "/test-explicit-icp",
            source=None,
            interceptor_classes=(_FakeInterceptor,),
        )
        assert isinstance(ctrl_cls, type)

    def test_explicit_middleware_classes_applied(self) -> None:
        from lauren_mcp._server._sse import mcp_http_sse_controller

        class _FakeMiddleware:
            async def dispatch(self, request: Any, call_next: Any) -> Any:
                return await call_next(request)

        ctrl_cls = mcp_http_sse_controller(
            "/test-explicit-mw",
            source=None,
            middleware_classes=(_FakeMiddleware,),
        )
        assert isinstance(ctrl_cls, type)


# ---------------------------------------------------------------------------
# SSE: transport_security guard wiring (lines 258-265)
# ---------------------------------------------------------------------------


class TestSseTransportSecurity:
    def test_transport_security_guard_is_applied(self) -> None:
        from lauren_mcp._server._sse import mcp_http_sse_controller
        from lauren_mcp._server._transport_security import TransportSecuritySettings

        settings = TransportSecuritySettings(allowed_origins=["https://example.com"])
        ctrl_cls = mcp_http_sse_controller(
            "/test-ts-guard",
            transport_security=settings,
        )
        assert isinstance(ctrl_cls, type)

    async def test_transport_security_guard_can_activate_called(self) -> None:
        """The _BoundSseTransportSecurityGuard.can_activate is called (line 263)."""
        from lauren.reflect import reflect_guards

        from lauren_mcp._server._sse import mcp_http_sse_controller
        from lauren_mcp._server._transport_security import TransportSecuritySettings

        settings = TransportSecuritySettings(allowed_hosts=["allowed.com"])
        ctrl_cls = mcp_http_sse_controller("/test-ts-invoke", transport_security=settings)

        guards = reflect_guards(ctrl_cls)
        assert guards, "Expected transport security guard"

        # The last guard is the _BoundSseTransportSecurityGuard
        guard_instance = guards[-1]()

        mock_request = MagicMock()
        mock_request.headers = {"host": "allowed.com"}
        mock_request.method = "GET"

        mock_ctx = MagicMock()
        mock_ctx.request = mock_request

        result = await guard_instance.can_activate(mock_ctx)
        assert result is True

        mock_request.headers = {"host": "evil.com"}
        result2 = await guard_instance.can_activate(mock_ctx)
        assert result2 is False


# ---------------------------------------------------------------------------
# Streamable HTTP: StreamableSessionStore.remove (lines 84-85)
# ---------------------------------------------------------------------------


class TestStreamableSessionStoreRemove:
    def test_remove_cancels_pending_rpcs(self) -> None:
        """StreamableSessionStore.remove cancels pending client RPC futures."""
        store = StreamableSessionStore()
        session = store.create("2025-03-26")

        loop = asyncio.new_event_loop()
        try:
            fut = loop.create_future()
            session.pending_client_rpcs["srv-0"] = fut
            store.remove(session.session_id)
            assert fut.done()
            assert isinstance(fut.exception(), RuntimeError)
        finally:
            loop.close()

    def test_remove_sends_sentinel_to_push_queue(self) -> None:
        """StreamableSessionStore.remove puts None sentinel on push_queue."""
        store = StreamableSessionStore()
        session = store.create("2025-03-26")
        store.remove(session.session_id)
        assert not session.push_queue.empty()
        assert session.push_queue.get_nowait() is None

    def test_remove_nonexistent_session_is_noop(self) -> None:
        """Removing a session that doesn't exist doesn't raise."""
        store = StreamableSessionStore()
        store.remove("nonexistent-session")  # should not raise


# ---------------------------------------------------------------------------
# Streamable HTTP: body parse error (lines 177-181)
# ---------------------------------------------------------------------------


async def test_streamable_body_parse_error_returns_400() -> None:
    """Malformed JSON body on POST returns 400 (McpParseError path)."""
    ctrl = _make_raw_streamable_ctrl("/parse-err-sl")
    req = _make_mock_request(b"not-json")
    result = await ctrl.handle_post(req, _make_mock_ec(req))
    assert result.status == 400


async def test_streamable_body_read_general_exception_returns_400() -> None:
    """Non-parse exception reading body returns 400 (lines 177-181)."""
    ctrl = _make_raw_streamable_ctrl("/body-exc-sl")
    req = _make_mock_request()
    req.body = AsyncMock(side_effect=RuntimeError("IO error"))
    result = await ctrl.handle_post(req, _make_mock_ec(req))
    assert result.status == 400
    parsed = json.loads(result.body)
    assert "error" in parsed
    assert parsed["error"]["code"] == -32603  # INTERNAL_ERROR


# ---------------------------------------------------------------------------
# Streamable HTTP: client response frame handling (lines 190-203)
# ---------------------------------------------------------------------------


async def test_streamable_client_response_frame_no_session_returns_400() -> None:
    """JsonRpcResponse without session header → 400 from _require_session."""
    ctrl = _make_raw_streamable_ctrl("/resp-frame-sl")
    body = json.dumps({"jsonrpc": "2.0", "id": "srv-0", "result": {"ok": True}}).encode()
    req = _make_mock_request(body)
    result = await ctrl.handle_post(req, _make_mock_ec(req))
    assert result.status == 400


async def test_streamable_client_response_frame_valid_session_returns_202() -> None:
    """JsonRpcResponse with valid session → 202 (pending RPC resolution)."""
    ctrl = _make_raw_streamable_ctrl("/resp-frame-sl2")

    # Create a session first
    session = ctrl._sessions.create("2025-03-26")
    body = json.dumps({"jsonrpc": "2.0", "id": "srv-0", "result": {"ok": True}}).encode()
    req = _make_mock_request(body, headers={_SESSION_HEADER: session.session_id})
    result = await ctrl.handle_post(req, _make_mock_ec(req))
    assert result.status == 202


async def test_streamable_client_error_response_frame_valid_session_returns_202() -> None:
    """JsonRpcErrorResponse with valid session → 202."""
    ctrl = _make_raw_streamable_ctrl("/resp-frame-sl3")

    session = ctrl._sessions.create("2025-03-26")
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": "srv-0",
            "error": {"code": -32603, "message": "err"},
        }
    ).encode()
    req = _make_mock_request(body, headers={_SESSION_HEADER: session.session_id})
    result = await ctrl.handle_post(req, _make_mock_ec(req))
    assert result.status == 202


async def test_streamable_client_response_resolves_pending_rpc() -> None:
    """Client response resolves a pending server-initiated RPC future."""
    ctrl = _make_raw_streamable_ctrl("/resp-frame-sl4")

    loop = asyncio.get_event_loop()
    session = ctrl._sessions.create("2025-03-26")
    fut = loop.create_future()
    session.pending_client_rpcs["srv-0"] = fut

    body = json.dumps({"jsonrpc": "2.0", "id": "srv-0", "result": {"x": 42}}).encode()
    req = _make_mock_request(body, headers={_SESSION_HEADER: session.session_id})
    result = await ctrl.handle_post(req, _make_mock_ec(req))
    assert result.status == 202
    assert fut.done()
    assert fut.result() == {"x": 42}


async def test_streamable_client_error_response_rejects_pending_rpc() -> None:
    """Client error response rejects a pending server-initiated RPC future."""
    ctrl = _make_raw_streamable_ctrl("/resp-frame-sl5")

    loop = asyncio.get_event_loop()
    session = ctrl._sessions.create("2025-03-26")
    fut = loop.create_future()
    session.pending_client_rpcs["srv-0"] = fut

    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": "srv-0",
            "error": {"code": -32603, "message": "client error"},
        }
    ).encode()
    req = _make_mock_request(body, headers={_SESSION_HEADER: session.session_id})
    result = await ctrl.handle_post(req, _make_mock_ec(req))
    assert result.status == 202
    assert fut.done()
    assert isinstance(fut.exception(), RuntimeError)


# ---------------------------------------------------------------------------
# Streamable HTTP: notification handling (lines 209, 212-215)
# ---------------------------------------------------------------------------


async def test_streamable_notifications_initialized_sets_session_flag() -> None:
    """notifications/initialized sets session.initialized = True (line 209)."""
    ctrl = _make_raw_streamable_ctrl("/notif-init-sl")

    session = ctrl._sessions.create("2025-03-26")
    assert not session.initialized

    body = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode()
    req = _make_mock_request(body, headers={_SESSION_HEADER: session.session_id})
    result = await ctrl.handle_post(req, _make_mock_ec(req))
    assert result.status == 202
    assert session.initialized is True


async def test_streamable_cancel_request_notification(monkeypatch: Any) -> None:
    """$/cancelRequest notification calls dispatcher.cancel (lines 212-215)."""
    ctrl = _make_raw_streamable_ctrl("/cancel-notif-sl")

    session = ctrl._sessions.create("2025-03-26")
    cancelled_ids: list[Any] = []
    original_cancel = ctrl._dispatcher.cancel

    def _fake_cancel(req_id: Any) -> bool:
        cancelled_ids.append(req_id)
        return False

    ctrl._dispatcher.cancel = _fake_cancel  # type: ignore[method-assign]

    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "$/cancelRequest",
            "params": {"id": "req-to-cancel-123"},
        }
    ).encode()
    req = _make_mock_request(body, headers={_SESSION_HEADER: session.session_id})
    result = await ctrl.handle_post(req, _make_mock_ec(req))
    assert result.status == 202
    assert "req-to-cancel-123" in cancelled_ids


async def test_streamable_other_notification_returns_202() -> None:
    """Unrecognized notifications return 202."""
    ctrl = _make_raw_streamable_ctrl("/other-notif-sl")
    session = ctrl._sessions.create("2025-03-26")

    body = json.dumps({"jsonrpc": "2.0", "method": "notifications/toolsListChanged"}).encode()
    req = _make_mock_request(body, headers={_SESSION_HEADER: session.session_id})
    result = await ctrl.handle_post(req, _make_mock_ec(req))
    assert result.status == 202


# ---------------------------------------------------------------------------
# Streamable HTTP: unsupported message type path (lines 229-230)
# ---------------------------------------------------------------------------


async def test_streamable_unsupported_message_returns_400() -> None:
    """An empty {} JSON object is not recognized → 400."""
    ctrl = _make_raw_streamable_ctrl("/unsupported-sl")
    # {} body → McpParseError on parse_message → 400 via parse error path
    req = _make_mock_request(b"{}")
    result = await ctrl.handle_post(req, _make_mock_ec(req))
    assert result.status == 400


async def test_streamable_handle_post_unsupported_message_path() -> None:
    """Patch parse_message to return a weird type → lines 229-230 covered."""
    from unittest.mock import patch

    ctrl = _make_raw_streamable_ctrl("/unsupported-patch")
    session = ctrl._sessions.create("2025-03-26")

    body = b'{"jsonrpc":"2.0","id":1,"method":"test"}'
    req = _make_mock_request(body, headers={_SESSION_HEADER: session.session_id})

    # Patch parse_message to return an unexpected type
    class _WeirdMessage:
        pass

    with patch("lauren_mcp._server._streamable.parse_message", return_value=_WeirdMessage()):
        result = await ctrl.handle_post(req, _make_mock_ec(req))
    assert result.status == 400


async def test_streamable_handle_stateless_unsupported_message_path() -> None:
    """Patch parse_message in stateless mode to return a weird type → lines 246-249 covered."""
    from unittest.mock import patch

    ctrl = _make_raw_streamable_ctrl("/unsupported-sl-patch", stateless=True)
    body = b'{"jsonrpc":"2.0","id":1,"method":"test"}'
    req = _make_mock_request(body)

    class _WeirdMessage:
        pass

    with patch("lauren_mcp._server._streamable.parse_message", return_value=_WeirdMessage()):
        result = await ctrl.handle_post(req, _make_mock_ec(req))
    assert result.status == 400


# ---------------------------------------------------------------------------
# Streamable HTTP: stateless mode (lines 243, 246-249, 255, 258, 283-313)
# ---------------------------------------------------------------------------


async def test_stateless_notification_returns_202() -> None:
    """Stateless: notification → 202."""
    ctrl = _make_raw_streamable_ctrl("/sl-notif", stateless=True)
    body = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}).encode()
    req = _make_mock_request(body)
    result = await ctrl.handle_post(req, _make_mock_ec(req))
    assert result.status == 202


async def test_stateless_sse_dispatch_with_notification_covers_closure_lines() -> None:
    """Stateless SSE: tool emits notification to cover _send_notification closure (line 255)."""
    from lauren_mcp._server._binding import CURRENT_BINDING

    ctrl = _make_raw_streamable_ctrl("/sl-notif-sse", stateless=True)

    # Override dispatcher to emit a notification before returning
    notification_count = [0]
    original_dispatch = ctrl._dispatcher.dispatch

    async def _dispatch_with_notification(request: Any) -> Any:
        binding = CURRENT_BINDING.get()
        if binding and binding.send_notification:
            await binding.send_notification(
                {"jsonrpc": "2.0", "method": "notifications/progress", "params": {"progress": 50}}
            )
            notification_count[0] += 1
        return await original_dispatch(request)

    ctrl._dispatcher.dispatch = _dispatch_with_notification  # type: ignore[method-assign]

    # Register an initialize handler
    async def _init(params: Any) -> dict:
        return {
            "protocolVersion": "2025-03-26",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "test", "version": "0"},
        }

    ctrl._dispatcher.register("initialize", _init)

    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"},
            },
        }
    ).encode()
    req = _make_mock_request(body, headers={"accept": "text/event-stream"})
    result = await ctrl.handle_post(req, _make_mock_ec(req))

    from lauren.sse import EventStream

    assert isinstance(result, EventStream)

    # Drain the generator to execute the closure body (line 255)
    events = []
    async for event in result._source:
        events.append(event)

    assert notification_count[0] > 0
    assert len(events) >= 1


async def test_stateless_client_response_returns_202() -> None:
    """Stateless: client response frame → 202."""
    ctrl = _make_raw_streamable_ctrl("/sl-resp", stateless=True)
    body = json.dumps({"jsonrpc": "2.0", "id": "srv-0", "result": {"ok": True}}).encode()
    req = _make_mock_request(body)
    result = await ctrl.handle_post(req, _make_mock_ec(req))
    assert result.status == 202


async def test_stateless_invalid_message_returns_400() -> None:
    """Stateless: non-request/notification → 400."""
    ctrl = _make_raw_streamable_ctrl("/sl-invalid", stateless=True)
    # {} is not a valid JSON-RPC message
    req = _make_mock_request(b"{}")
    result = await ctrl.handle_post(req, _make_mock_ec(req))
    assert result.status == 400


async def test_stateless_request_returns_json_response() -> None:
    """Stateless: initialize request returns JSON directly (line 258 path — no SSE)."""
    ctrl = _make_raw_streamable_ctrl("/sl-init", stateless=True)
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"},
            },
        }
    ).encode()
    req = _make_mock_request(body)
    result = await ctrl.handle_post(req, _make_mock_ec(req))
    assert result.status == 200
    parsed = json.loads(result.body)
    assert "result" in parsed


async def test_stateless_request_with_sse_accept_returns_event_stream() -> None:
    """Stateless: initialize with Accept: text/event-stream returns EventStream (lines 283-313)."""
    from lauren.sse import EventStream

    ctrl = _make_raw_streamable_ctrl("/sl-sse", stateless=True)
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"},
            },
        }
    ).encode()
    req = _make_mock_request(body, headers={"accept": "text/event-stream"})
    result = await ctrl.handle_post(req, _make_mock_ec(req))
    assert isinstance(result, EventStream)

    # Drain the SSE generator to cover the _stateless_generator function body
    events = []
    async for event in result._source:
        events.append(event)
    # Should have at least one event (the final response)
    assert events
    assert events[-1].event == "message"


# ---------------------------------------------------------------------------
# Streamable HTTP: GET push channel (lines 357-380)
# ---------------------------------------------------------------------------


async def test_streamable_get_stateless_returns_405() -> None:
    """GET in stateless mode returns 405 (lines 357-361)."""
    ctrl = _make_raw_streamable_ctrl("/get-sl", stateless=True)
    req = _make_mock_request(headers={"accept": "text/event-stream"})
    result = await ctrl.handle_get(req)
    assert result.status == 405


async def test_streamable_get_non_sse_returns_405() -> None:
    """GET without Accept: text/event-stream returns 405 (line 364)."""
    ctrl = _make_raw_streamable_ctrl("/get-nosse")
    req = _make_mock_request()
    result = await ctrl.handle_get(req)
    assert result.status == 405


async def test_streamable_get_missing_session_returns_400() -> None:
    """GET with SSE accept but no session header returns 400 (lines 366-373)."""
    ctrl = _make_raw_streamable_ctrl("/get-nosess")
    req = _make_mock_request(headers={"accept": "text/event-stream"})
    result = await ctrl.handle_get(req)
    assert result.status == 400


async def test_streamable_get_unknown_session_returns_404() -> None:
    """GET with unknown session returns 404 (lines 374-378)."""
    ctrl = _make_raw_streamable_ctrl("/get-unk")
    req = _make_mock_request(
        headers={
            "accept": "text/event-stream",
            _SESSION_HEADER: "totally-bogus",
        }
    )
    result = await ctrl.handle_get(req)
    assert result.status == 404


async def test_streamable_get_valid_session_returns_event_stream() -> None:
    """GET with valid session and SSE accept opens the push channel (EventStream)."""
    from lauren.sse import EventStream

    ctrl = _make_raw_streamable_ctrl("/get-valid")
    session = ctrl._sessions.create("2025-03-26")

    # Put sentinel immediately so the generator exits fast
    session.push_queue.put_nowait(None)

    req = _make_mock_request(
        headers={
            "accept": "text/event-stream",
            _SESSION_HEADER: session.session_id,
        }
    )
    result = await ctrl.handle_get(req)
    assert isinstance(result, EventStream)


# ---------------------------------------------------------------------------
# Streamable HTTP: event_store in GET push channel (lines 439-450)
# ---------------------------------------------------------------------------


async def test_streamable_get_with_event_store_assigns_event_ids() -> None:
    """GET push channel with event_store assigns id: to each event (lines 439-450)."""
    from lauren.sse import EventStream

    from lauren_mcp._server._event_store import InMemoryEventStore

    store = InMemoryEventStore()
    ctrl = _make_raw_streamable_ctrl("/get-evtstore", event_store=store)
    session = ctrl._sessions.create("2025-03-26")

    # Put one message and then sentinel
    session.push_queue.put_nowait('{"test": "event"}')
    session.push_queue.put_nowait(None)

    req = _make_mock_request(
        headers={
            "accept": "text/event-stream",
            _SESSION_HEADER: session.session_id,
        }
    )
    result = await ctrl.handle_get(req)
    assert isinstance(result, EventStream)

    # Drain the generator to trigger the event_store.store_event path
    events = []
    async for event in result._source:
        events.append(event)

    # Should have one event with an id
    assert events
    # EventStore path sets id on events
    assert any(hasattr(e, "id") and e.id is not None for e in events)


async def test_streamable_get_with_event_store_replays_events() -> None:
    """GET push channel replays missed events from event_store (lines 445, 448-450)."""
    from lauren.sse import EventStream

    from lauren_mcp._server._event_store import InMemoryEventStore

    store = InMemoryEventStore()
    ctrl = _make_raw_streamable_ctrl("/get-replay", event_store=store)
    session = ctrl._sessions.create("2025-03-26")

    # Pre-store an event
    await store.store_event(session.session_id, f"{session.session_id}:0", '{"replayed":true}')

    # Put sentinel to end stream immediately
    session.push_queue.put_nowait(None)

    req = _make_mock_request(
        headers={
            "accept": "text/event-stream",
            _SESSION_HEADER: session.session_id,
            "last-event-id": f"{session.session_id}:-1",
        }
    )
    result = await ctrl.handle_get(req)
    assert isinstance(result, EventStream)

    events = []
    async for event in result._source:
        events.append(event)

    # First event should be the replayed one
    assert events
    assert any("replayed" in e.data for e in events)


async def test_streamable_get_with_event_store_and_new_message() -> None:
    """GET push channel: new message + event_store assigns ids (lines 439-440, 448-450)."""
    from lauren.sse import EventStream

    from lauren_mcp._server._event_store import InMemoryEventStore

    store = InMemoryEventStore()
    ctrl = _make_raw_streamable_ctrl("/get-evtstore2", event_store=store)
    session = ctrl._sessions.create("2025-03-26")

    # Put a real message + sentinel (no last-event-id, so no replay)
    session.push_queue.put_nowait('{"jsonrpc":"2.0","method":"test"}')
    session.push_queue.put_nowait(None)

    req = _make_mock_request(
        headers={
            "accept": "text/event-stream",
            _SESSION_HEADER: session.session_id,
        }
    )
    result = await ctrl.handle_get(req)
    assert isinstance(result, EventStream)

    events = []
    async for event in result._source:
        events.append(event)

    # Should have one event with id (event_store path)
    assert events
    # With event_store, id should be set
    evt_with_id = [e for e in events if hasattr(e, "id") and e.id is not None]
    assert evt_with_id


# ---------------------------------------------------------------------------
# Streamable HTTP: DELETE teardown (lines 472-516)
# ---------------------------------------------------------------------------


async def test_streamable_delete_stateless_returns_405() -> None:
    """DELETE in stateless mode returns 405 (lines 472-477)."""
    ctrl = _make_raw_streamable_ctrl("/del-sl", stateless=True)
    req = _make_mock_request()
    result = await ctrl.handle_delete(req)
    assert result.status == 405


async def test_streamable_delete_missing_session_header_returns_400() -> None:
    """DELETE without session header returns 400 (lines 479-483)."""
    ctrl = _make_raw_streamable_ctrl("/del-nosess")
    req = _make_mock_request()
    result = await ctrl.handle_delete(req)
    assert result.status == 400


async def test_streamable_delete_valid_session_returns_204() -> None:
    """DELETE valid session returns 204 (lines 484-486)."""
    ctrl = _make_raw_streamable_ctrl("/del-valid")
    session = ctrl._sessions.create("2025-03-26")

    req = _make_mock_request(headers={_SESSION_HEADER: session.session_id})
    result = await ctrl.handle_delete(req)
    assert result.status == 204


async def test_streamable_delete_nonexistent_session_returns_204() -> None:
    """DELETE a session that doesn't exist → store.remove is idempotent, returns 204."""
    ctrl = _make_raw_streamable_ctrl("/del-noexist")
    req = _make_mock_request(headers={_SESSION_HEADER: "nonexistent-session"})
    result = await ctrl.handle_delete(req)
    assert result.status == 204


# ---------------------------------------------------------------------------
# Streamable HTTP: OAuth discovery (line 535)
# ---------------------------------------------------------------------------


class _MockAuthServerMeta:
    def to_dict(self) -> dict[str, Any]:
        return {"issuer": "https://auth.example.com"}


class _MockProtectedResourceMeta:
    def to_dict(self) -> dict[str, Any]:
        return {"resource": "https://api.example.com/mcp"}


class _MockOAuthSettings:
    authorization_server_metadata = _MockAuthServerMeta()
    protected_resource_metadata = _MockProtectedResourceMeta()


class _MockOAuthSettingsNoAS:
    authorization_server_metadata = None
    protected_resource_metadata = _MockProtectedResourceMeta()


async def test_oauth_authorization_server_returns_metadata() -> None:
    """OAuth AS discovery endpoint returns metadata (line 535)."""
    ctrl = _make_raw_streamable_ctrl("/oauth-as", oauth_settings=_MockOAuthSettings())
    req = _make_mock_request()
    result = await ctrl.oauth_authorization_server(req)
    assert result.status == 200
    body = json.loads(result.body)
    assert body["issuer"] == "https://auth.example.com"


async def test_oauth_protected_resource_returns_metadata() -> None:
    """OAuth protected resource endpoint returns metadata."""
    ctrl = _make_raw_streamable_ctrl("/oauth-pr", oauth_settings=_MockOAuthSettings())
    req = _make_mock_request()
    result = await ctrl.oauth_protected_resource(req)
    assert result.status == 200
    body = json.loads(result.body)
    assert body["resource"] == "https://api.example.com/mcp"


async def test_oauth_authorization_server_returns_404_when_not_configured() -> None:
    """OAuth AS discovery returns 404 when authorization_server_metadata is None."""
    ctrl = _make_raw_streamable_ctrl("/oauth-no-as", oauth_settings=_MockOAuthSettingsNoAS())
    req = _make_mock_request()
    result = await ctrl.oauth_authorization_server(req)
    assert result.status == 404


async def test_oauth_protected_resource_returns_404_when_not_configured() -> None:
    """OAuth PR discovery returns 404 when no oauth_settings."""
    ctrl = _make_raw_streamable_ctrl("/oauth-no-pr")
    req = _make_mock_request()
    result = await ctrl.oauth_protected_resource(req)
    assert result.status == 404


# ---------------------------------------------------------------------------
# Streamable HTTP: transport_security guard wiring (lines 578-586)
# ---------------------------------------------------------------------------


def test_streamable_transport_security_guard_applied() -> None:
    """mcp_streamable_http_controller with transport_security wraps controller in guard."""
    from lauren_mcp._server._transport_security import TransportSecuritySettings

    settings = TransportSecuritySettings(allowed_origins=["https://example.com"])
    ctrl = mcp_streamable_http_controller(
        "/ts-test",
        transport_security=settings,
    )
    assert isinstance(ctrl, type)


async def test_streamable_transport_security_guard_can_activate() -> None:
    """The _BoundTransportSecurityGuard.can_activate runs the guard logic (line 584)."""
    from lauren_mcp._server._transport_security import TransportSecuritySettings

    settings = TransportSecuritySettings(allowed_hosts=["allowed.com"])
    ctrl_cls = mcp_streamable_http_controller(
        "/ts-test2",
        transport_security=settings,
    )
    # The guard class is the last element in the list of guards applied to the controller.
    # We need to actually invoke it with a mock execution context.
    # Find the _BoundTransportSecurityGuard from the guard list.
    from lauren.reflect import reflect_guards

    guards = reflect_guards(ctrl_cls)
    assert guards, "Expected transport security guard to be applied"

    # Create an instance of the guard and invoke can_activate
    guard_instance = guards[-1]()

    mock_request = MagicMock()
    mock_request.headers = {"host": "allowed.com"}
    mock_request.method = "GET"

    mock_ctx = MagicMock()
    mock_ctx.request = mock_request

    result = await guard_instance.can_activate(mock_ctx)
    assert result is True

    # Test with disallowed host
    mock_request.headers = {"host": "evil.com"}
    result2 = await guard_instance.can_activate(mock_ctx)
    assert result2 is False


# ---------------------------------------------------------------------------
# Full integration: streamable HTTP with TestClient — notification dispatch
# ---------------------------------------------------------------------------


from lauren_mcp._server._context import McpToolContext  # noqa: E402


@mcp_server("/mcp-notify")
class _NotifyServer:
    @mcp_tool()
    async def ping_with_progress(self, ctx: McpToolContext) -> str:
        """A tool that emits progress notification (covers _send_notification closure)."""
        await ctx.report_progress(50, 100, "halfway")
        return "pong"


@pytest.fixture(scope="module")
def notify_app() -> Any:
    return _make_streamable_app(_NotifyServer)


class TestStreamableNotificationDispatch:
    """Tests that cover _send_notification closure (lines 357-361) and GET push channel."""

    def test_tools_call_with_sse_dispatches_notifications(self, notify_app: Any) -> None:
        """SSE dispatch mode: progress notification goes to stream_queue (lines 357-361)."""
        client = TestClient(notify_app)
        session_id, _ = _initialize_streamable(client, path="/mcp-notify/")

        resp = client.post(
            "/mcp-notify/",
            content=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "ping_with_progress", "arguments": {}},
                }
            ).encode(),
            headers={
                "content-type": "application/json",
                "accept": "text/event-stream",
                _SESSION_HEADER: session_id,
            },
        )
        assert resp.status_code == 200
        body = resp.text
        data_lines = [line[5:].strip() for line in body.splitlines() if line.startswith("data:")]
        assert data_lines
        final = json.loads(data_lines[-1])
        assert final["result"]["content"][0]["text"] == "pong"

    def test_tools_call_json_mode_with_progress_notification(self, notify_app: Any) -> None:
        """JSON dispatch mode: progress notification goes to push_queue (line 361)."""
        client = TestClient(notify_app)
        session_id, _ = _initialize_streamable(client, path="/mcp-notify/")

        resp = client.post(
            "/mcp-notify/",
            content=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "ping_with_progress", "arguments": {}},
                }
            ).encode(),
            headers={
                "content-type": "application/json",
                _SESSION_HEADER: session_id,
            },
        )
        # JSON mode: returns direct JSON response
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["result"]["content"][0]["text"] == "pong"

    async def test_get_push_channel_receives_pushed_message(self, notify_app: Any) -> None:
        """GET push channel delivers messages from push_queue (line 480, 510)."""
        client = TestClient(notify_app)
        session_id, _ = _initialize_streamable(client, path="/mcp-notify/")

        store: StreamableSessionStore = await notify_app.container.resolve(StreamableSessionStore)
        session = store.get(session_id)
        assert session is not None

        # Put a real message + sentinel
        session.push_queue.put_nowait('{"jsonrpc":"2.0","method":"notifications/message"}')
        session.push_queue.put_nowait(None)

        resp = client.get(
            "/mcp-notify/",
            headers={
                "accept": "text/event-stream",
                _SESSION_HEADER: session_id,
            },
        )
        assert resp.status_code == 200
        assert "data:" in resp.text


# ---------------------------------------------------------------------------
# Full integration: streamable HTTP with TestClient
# ---------------------------------------------------------------------------


@mcp_server("/mcp-full")
class _FullStreamServer:
    @mcp_tool()
    async def multiply(self, x: int, y: int) -> int:
        """Multiply two numbers."""
        return x * y


@pytest.fixture(scope="module")
def full_stream_app() -> Any:
    return _make_streamable_app(_FullStreamServer)


class TestFullStreamableIntegration:
    def test_initialize_creates_session(self, full_stream_app: Any) -> None:
        client = TestClient(full_stream_app)
        session_id, payload = _initialize_streamable(client, path="/mcp-full/")
        assert session_id
        assert "result" in payload

    def test_tools_list_returns_200(self, full_stream_app: Any) -> None:
        client = TestClient(full_stream_app)
        session_id, _ = _initialize_streamable(client, path="/mcp-full/")
        resp = _rpc(
            client,
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            path="/mcp-full/",
            **{_SESSION_HEADER: session_id},
        )
        assert resp.status_code == 200
        names = [t["name"] for t in resp.json()["result"]["tools"]]
        assert "multiply" in names

    def test_tools_call_returns_result(self, full_stream_app: Any) -> None:
        client = TestClient(full_stream_app)
        session_id, _ = _initialize_streamable(client, path="/mcp-full/")
        resp = _rpc(
            client,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "multiply", "arguments": {"x": 6, "y": 7}},
            },
            path="/mcp-full/",
            **{_SESSION_HEADER: session_id},
        )
        assert resp.status_code == 200
        assert resp.json()["result"]["content"][0]["text"] == "42"

    def test_sse_dispatch_returns_event_stream(self, full_stream_app: Any) -> None:
        """Accept: text/event-stream returns SSE response (lines 412-452)."""
        client = TestClient(full_stream_app)
        session_id, _ = _initialize_streamable(client, path="/mcp-full/")
        resp = client.post(
            "/mcp-full/",
            content=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "tools/call",
                    "params": {"name": "multiply", "arguments": {"x": 3, "y": 4}},
                }
            ).encode(),
            headers={
                "content-type": "application/json",
                "accept": "text/event-stream",
                _SESSION_HEADER: session_id,
            },
        )
        assert resp.status_code == 200
        assert "text/event-stream" in (resp.header("content-type") or "")
        body = resp.text
        data_lines = [line[5:].strip() for line in body.splitlines() if line.startswith("data:")]
        assert data_lines
        final = json.loads(data_lines[-1])
        assert final["result"]["content"][0]["text"] == "12"

    def test_delete_removes_session(self, full_stream_app: Any) -> None:
        """DELETE /mcp-full/ removes session (lines 519-539)."""
        client = TestClient(full_stream_app)
        session_id, _ = _initialize_streamable(client, path="/mcp-full/")
        resp = client.delete("/mcp-full/", headers={_SESSION_HEADER: session_id})
        assert resp.status_code == 204
        # Session is gone
        resp2 = _rpc(
            client,
            {"jsonrpc": "2.0", "id": 9, "method": "tools/list"},
            path="/mcp-full/",
            **{_SESSION_HEADER: session_id},
        )
        assert resp2.status_code == 404

    async def test_get_push_channel_with_valid_session(self, full_stream_app: Any) -> None:
        """GET push channel with valid session opens SSE stream and receives queued messages."""
        client = TestClient(full_stream_app)
        session_id, _ = _initialize_streamable(client, path="/mcp-full/")

        # Put a message and then sentinel so the GET stream gets one event then exits
        store: StreamableSessionStore = await full_stream_app.container.resolve(
            StreamableSessionStore
        )
        session = store.get(session_id)
        assert session is not None
        # Push a real message first, then a sentinel to close the stream
        session.push_queue.put_nowait('{"jsonrpc":"2.0","method":"test/push","params":{}}')
        session.push_queue.put_nowait(None)

        resp = client.get(
            "/mcp-full/",
            headers={
                "accept": "text/event-stream",
                _SESSION_HEADER: session_id,
            },
        )
        assert resp.status_code == 200
        # Body should contain the message event
        assert "data:" in resp.text
