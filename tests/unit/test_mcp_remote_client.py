"""Unit tests for _McpBaseRemoteClient, McpWebSocketClient, McpHttpSseClient."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from lauren_mcp._client._base_remote import _McpBaseRemoteClient
from lauren_mcp._client._stdio import McpCallError
from lauren_mcp._types import (
    JsonRpcNotification,
)

# ---------------------------------------------------------------------------
# Concrete test subclass that replaces all abstract methods with mocks
# ---------------------------------------------------------------------------


class _ConcreteClient(_McpBaseRemoteClient):
    """Concrete subclass of _McpBaseRemoteClient for unit testing."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._sent: list[dict] = []
        self._connection_started = False
        self._connection_closed = False

    async def _send_raw(self, obj: dict) -> None:
        self._sent.append(obj)

    async def _start_connection(self) -> None:
        self._connection_started = True

    async def _close_connection(self) -> None:
        self._connection_closed = True

    async def connect(self) -> None:
        await self._start_connection()
        await self._handshake()

    async def close(self) -> None:
        self._fail_all_pending("Client closed")
        await self._close_connection()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response_raw(req_id: int, result: Any) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": req_id, "result": result})


def _make_error_raw(req_id: int, code: int, message: str) -> str:
    return json.dumps(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message},
        }
    )


def _make_notification_raw(method: str) -> str:
    return json.dumps({"jsonrpc": "2.0", "method": method})


# ---------------------------------------------------------------------------
# Tests for _McpBaseRemoteClient
# ---------------------------------------------------------------------------


class TestMcpBaseRemoteClient:
    async def test_handshake_sends_initialize_request(self):
        """_handshake must send an initialize request."""
        client = _ConcreteClient()
        # Simulate server responding to initialize right away

        async def _fake_handshake() -> None:
            # Schedule a response for id=0 (the initialize request)
            async def _respond():
                await asyncio.sleep(0)
                client._dispatch_message(_make_response_raw(0, {"protocolVersion": "2024-11-05"}))

            asyncio.create_task(_respond())
            await client._handshake()

        await _fake_handshake()

        assert any(m.get("method") == "initialize" for m in client._sent)

    async def test_handshake_sets_initialized_flag(self):
        """After _handshake completes, _initialized must be True."""
        client = _ConcreteClient()

        async def _respond_then_handshake():
            async def _deliver():
                await asyncio.sleep(0)
                client._dispatch_message(_make_response_raw(0, {"protocolVersion": "2024-11-05"}))

            asyncio.create_task(_deliver())
            await client._handshake()

        assert client._initialized is False
        await _respond_then_handshake()
        assert client._initialized is True

    async def test_request_increments_next_id(self):
        """Each _request call should increment _next_id."""
        client = _ConcreteClient()

        async def _make_request_and_resolve(expected_id: int) -> None:
            async def _deliver():
                await asyncio.sleep(0)
                client._dispatch_message(_make_response_raw(expected_id, {"ok": True}))

            asyncio.create_task(_deliver())
            await client._request("ping")

        assert client._next_id == 0
        await _make_request_and_resolve(0)
        assert client._next_id == 1
        await _make_request_and_resolve(1)
        assert client._next_id == 2

    async def test_request_creates_future_keyed_by_id(self):
        """While a request is in flight, _pending contains the future keyed by its id."""
        client = _ConcreteClient()
        captured_id: list[int] = []

        async def _capture_and_resolve():
            await asyncio.sleep(0)
            # At this point, _request has put the future in _pending
            captured_id.extend(list(client._pending.keys()))
            client._dispatch_message(_make_response_raw(0, {}))

        asyncio.create_task(_capture_and_resolve())
        await client._request("ping")
        assert 0 in captured_id

    async def test_request_returns_result_from_future(self):
        """_request must return the result carried by the JSON-RPC response."""
        client = _ConcreteClient()

        async def _deliver():
            await asyncio.sleep(0)
            client._dispatch_message(_make_response_raw(0, {"answer": 42}))

        asyncio.create_task(_deliver())
        result = await client._request("tools/list")
        assert result == {"answer": 42}

    async def test_dispatch_message_resolves_pending_future_on_success(self):
        """A success response JSON-RPC message resolves the matching pending future."""
        client = _ConcreteClient()
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        client._pending[5] = fut
        client._dispatch_message(_make_response_raw(5, {"data": "value"}))
        result = await fut
        assert result == {"data": "value"}

    async def test_dispatch_message_raises_mcp_call_error_on_error_response(self):
        """An error response JSON-RPC message causes the future to raise McpCallError."""
        client = _ConcreteClient()
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        client._pending[7] = fut
        client._dispatch_message(_make_error_raw(7, -32600, "Invalid request"))
        with pytest.raises(McpCallError):
            await fut

    async def test_dispatch_message_ignores_notification_with_no_matching_future(self):
        """Notification messages do not affect pending futures."""
        client = _ConcreteClient()
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        client._pending[1] = fut
        # A notification — should not touch _pending
        client._dispatch_message(_make_notification_raw("notifications/initialized"))
        # Future is still pending
        assert not fut.done()

    async def test_fail_all_pending_cancels_all_futures(self):
        """_fail_all_pending must set exceptions on all in-flight futures."""
        client = _ConcreteClient()
        loop = asyncio.get_running_loop()
        fut1: asyncio.Future = loop.create_future()
        fut2: asyncio.Future = loop.create_future()
        client._pending[1] = fut1
        client._pending[2] = fut2
        client._fail_all_pending("Test failure")
        with pytest.raises(McpCallError):
            await fut1
        with pytest.raises(McpCallError):
            await fut2
        assert client._pending == {}

    async def test_list_tools_sends_tools_list_method(self):
        client = _ConcreteClient()

        async def _deliver():
            await asyncio.sleep(0)
            client._dispatch_message(_make_response_raw(0, {"tools": []}))

        asyncio.create_task(_deliver())
        await client.list_tools()
        assert client._sent[0]["method"] == "tools/list"

    async def test_call_tool_sends_tools_call_with_correct_params(self):
        client = _ConcreteClient()

        async def _deliver():
            await asyncio.sleep(0)
            client._dispatch_message(_make_response_raw(0, {"content": [], "isError": False}))

        asyncio.create_task(_deliver())
        await client.call_tool("greet", {"name": "Alice"})
        sent = client._sent[0]
        assert sent["method"] == "tools/call"
        assert sent["params"]["name"] == "greet"
        assert sent["params"]["arguments"] == {"name": "Alice"}

    async def test_list_resources_sends_resources_list(self):
        client = _ConcreteClient()

        async def _deliver():
            await asyncio.sleep(0)
            client._dispatch_message(_make_response_raw(0, {"resources": []}))

        asyncio.create_task(_deliver())
        await client.list_resources()
        assert client._sent[0]["method"] == "resources/list"

    async def test_read_resource_sends_resources_read(self):
        client = _ConcreteClient()

        async def _deliver():
            await asyncio.sleep(0)
            client._dispatch_message(_make_response_raw(0, {"contents": []}))

        asyncio.create_task(_deliver())
        await client.read_resource("/items/5")
        sent = client._sent[0]
        assert sent["method"] == "resources/read"
        assert sent["params"]["uri"] == "/items/5"

    async def test_list_prompts_sends_prompts_list(self):
        client = _ConcreteClient()

        async def _deliver():
            await asyncio.sleep(0)
            client._dispatch_message(_make_response_raw(0, {"prompts": []}))

        asyncio.create_task(_deliver())
        await client.list_prompts()
        assert client._sent[0]["method"] == "prompts/list"

    async def test_get_prompt_sends_prompts_get(self):
        client = _ConcreteClient()

        async def _deliver():
            await asyncio.sleep(0)
            client._dispatch_message(_make_response_raw(0, {"messages": []}))

        asyncio.create_task(_deliver())
        await client.get_prompt("my_prompt", {"key": "val"})
        sent = client._sent[0]
        assert sent["method"] == "prompts/get"
        assert sent["params"]["name"] == "my_prompt"
        assert sent["params"]["arguments"] == {"key": "val"}

    async def test_ping_sends_ping_method(self):
        client = _ConcreteClient()

        async def _deliver():
            await asyncio.sleep(0)
            client._dispatch_message(_make_response_raw(0, {}))

        asyncio.create_task(_deliver())
        await client.ping()
        assert client._sent[0]["method"] == "ping"

    async def test_close_calls_close_connection(self):
        client = _ConcreteClient()
        await client.close()
        assert client._connection_closed is True

    async def test_close_fails_all_pending(self):
        """close() must drain pending futures before closing connection."""
        client = _ConcreteClient()
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        client._pending[1] = fut
        await client.close()
        assert fut.done()
        assert client._pending == {}

    async def test_dispatch_message_removes_future_after_resolving(self):
        """After dispatching a success response, _pending should no longer contain the id."""
        client = _ConcreteClient()
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        client._pending[3] = fut
        client._dispatch_message(_make_response_raw(3, "done"))
        assert 3 not in client._pending

    async def test_list_tools_returns_tool_schema_list(self):
        client = _ConcreteClient()

        async def _deliver():
            await asyncio.sleep(0)
            client._dispatch_message(
                _make_response_raw(
                    0,
                    {
                        "tools": [
                            {
                                "name": "greet",
                                "description": "Greets someone",
                                "inputSchema": {},
                            }
                        ]
                    },
                )
            )

        asyncio.create_task(_deliver())
        tools = await client.list_tools()
        assert len(tools) == 1
        assert tools[0].name == "greet"

    async def test_notification_listener_called_on_notification(self):
        """Registered notification listeners are called for incoming notifications."""
        client = _ConcreteClient()
        received: list = []

        def _listener(notification: JsonRpcNotification) -> None:
            received.append(notification)

        client._notification_listeners.append(_listener)
        client._dispatch_message(_make_notification_raw("notifications/initialized"))
        assert len(received) == 1
        assert received[0].method == "notifications/initialized"


# ---------------------------------------------------------------------------
# Import guards — test without real deps
# ---------------------------------------------------------------------------


class TestMcpWebSocketClientImportGuard:
    def test_raises_import_error_when_ws_not_available(self):
        """McpWebSocketClient.__init__ raises ImportError when websockets is unavailable."""
        import lauren_mcp._client._ws as ws_module

        original = ws_module._WS_AVAILABLE
        try:
            ws_module._WS_AVAILABLE = False
            with pytest.raises(ImportError, match="lauren-mcp\\[ws\\]"):
                from lauren_mcp._client._ws import McpWebSocketClient

                McpWebSocketClient("ws://localhost:8000/mcp/ws")
        finally:
            ws_module._WS_AVAILABLE = original


class TestMcpHttpSseClientImportGuard:
    def test_raises_import_error_when_http_not_available(self):
        """McpHttpSseClient.__init__ raises ImportError when httpx is unavailable."""
        import lauren_mcp._client._sse as sse_module

        original = sse_module._SSE_AVAILABLE
        try:
            sse_module._SSE_AVAILABLE = False
            with pytest.raises(ImportError, match="lauren-mcp\\[sse\\]"):
                from lauren_mcp._client._sse import McpHttpSseClient

                McpHttpSseClient("http://localhost:8000/mcp")
        finally:
            sse_module._SSE_AVAILABLE = original


# ---------------------------------------------------------------------------
# McpWebSocketClient — only tested if websockets is installed
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def websockets():
    return pytest.importorskip("websockets")


class TestMcpWebSocketClient:
    async def test_send_raw_calls_ws_send_with_json(self, websockets):
        """_send_raw must JSON-encode the payload and call ws.send()."""
        from lauren_mcp._client._ws import McpWebSocketClient

        client = McpWebSocketClient("ws://localhost:9999/mcp/ws")
        fake_ws = AsyncMock()
        client._ws = fake_ws

        await client._send_raw({"method": "ping", "jsonrpc": "2.0", "id": 0})

        fake_ws.send.assert_called_once()
        sent_arg = fake_ws.send.call_args[0][0]
        parsed = json.loads(sent_arg)
        assert parsed["method"] == "ping"

    async def test_connect_calls_start_connection_then_handshake(self, websockets):
        """connect() must call _start_connection before _handshake."""
        from lauren_mcp._client._ws import McpWebSocketClient

        client = McpWebSocketClient("ws://localhost:9999/mcp/ws")
        call_order: list[str] = []

        async def _fake_start():
            call_order.append("start")

        async def _fake_handshake():
            call_order.append("handshake")

        with (
            patch.object(client, "_start_connection", side_effect=_fake_start),
            patch.object(client, "_handshake", side_effect=_fake_handshake),
        ):
            await client.connect()

        assert call_order == ["start", "handshake"]

    async def test_close_cancels_reader_task_and_closes_ws(self, websockets):
        """close() must cancel the reader task and close the ws."""
        from lauren_mcp._client._ws import McpWebSocketClient

        client = McpWebSocketClient("ws://localhost:9999/mcp/ws")

        # Create a real task so cancellation is observable
        async def _noop():
            try:  # noqa: SIM105
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                pass

        client._reader_task = asyncio.create_task(_noop())

        fake_ws = AsyncMock()
        client._ws = fake_ws

        await client.close()

        assert client._ws is None
        fake_ws.close.assert_called_once()

    async def test_send_raw_raises_when_ws_is_none(self, websockets):
        """_send_raw must raise McpCallError when ws is not connected."""
        from lauren_mcp._client._ws import McpWebSocketClient

        client = McpWebSocketClient("ws://localhost:9999/mcp/ws")
        # _ws starts as None

        with pytest.raises(McpCallError):
            await client._send_raw({"method": "ping"})


# ---------------------------------------------------------------------------
# McpHttpSseClient — only tested if httpx is installed
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def httpx():
    return pytest.importorskip("httpx")


class TestMcpHttpSseClient:
    async def test_send_raw_posts_to_url_with_session_header(self, httpx):
        """_send_raw must POST to {url}/ with the mcp-session-id header."""
        from lauren_mcp._client._sse import McpHttpSseClient

        client = McpHttpSseClient("http://localhost:8000/mcp")
        client._session_id = "test-session-123"

        mock_http = AsyncMock()
        mock_http.post.return_value = AsyncMock(status_code=202)
        client._http_client = mock_http

        await client._send_raw({"jsonrpc": "2.0", "method": "ping", "id": 0})

        mock_http.post.assert_called_once()
        call_kwargs = mock_http.post.call_args
        # Check URL
        assert call_kwargs[0][0] == "http://localhost:8000/mcp/"
        # Check header presence
        headers = call_kwargs[1]["headers"]
        assert "mcp-session-id" in headers
        assert headers["mcp-session-id"] == "test-session-123"

    async def test_connect_calls_start_connection_then_handshake(self, httpx):
        """connect() must call _start_connection before _handshake."""
        from lauren_mcp._client._sse import McpHttpSseClient

        client = McpHttpSseClient("http://localhost:8000/mcp")
        call_order: list[str] = []

        async def _fake_start():
            call_order.append("start")

        async def _fake_handshake():
            call_order.append("handshake")

        with (
            patch.object(client, "_start_connection", side_effect=_fake_start),
            patch.object(client, "_handshake", side_effect=_fake_handshake),
        ):
            await client.connect()

        assert call_order == ["start", "handshake"]

    async def test_send_raw_raises_when_session_not_established(self, httpx):
        """_send_raw must raise McpCallError when session_id is None."""
        from lauren_mcp._client._sse import McpHttpSseClient

        client = McpHttpSseClient("http://localhost:8000/mcp")
        mock_http = AsyncMock()
        client._http_client = mock_http
        # _session_id is None (not yet established)

        with pytest.raises(McpCallError):
            await client._send_raw({"method": "ping"})

    async def test_send_raw_raises_when_http_client_not_connected(self, httpx):
        """_send_raw must raise McpCallError when http client is None."""
        from lauren_mcp._client._sse import McpHttpSseClient

        client = McpHttpSseClient("http://localhost:8000/mcp")
        # Both _http_client and _session_id are None

        with pytest.raises(McpCallError):
            await client._send_raw({"method": "ping"})

    async def test_url_trailing_slash_stripped(self, httpx):
        """McpHttpSseClient strips trailing slashes from url."""
        from lauren_mcp._client._sse import McpHttpSseClient

        client = McpHttpSseClient("http://localhost:8000/mcp/")
        assert client._url == "http://localhost:8000/mcp"
