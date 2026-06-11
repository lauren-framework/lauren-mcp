"""Unit tests for client transports: _streamable.py, _sse.py, _ws.py, _oauth.py.

All network I/O is mocked — no real connections are made.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Optional-dependency guards
# ---------------------------------------------------------------------------
httpx = pytest.importorskip("httpx")
websockets = pytest.importorskip("websockets")


# ===========================================================================
# Helpers shared across tests
# ===========================================================================


def _make_initialize_result(version: str = "2025-11-25") -> dict[str, Any]:
    return {"protocolVersion": version, "capabilities": {}, "serverInfo": {"name": "test"}}


def _json_rpc_response(id: int, result: Any) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": id, "result": result})


def _json_rpc_error(id: int, code: int, message: str) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}})


def _json_rpc_notification(method: str, params: dict[str, Any] | None = None) -> str:
    msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        msg["params"] = params
    return json.dumps(msg)


# ===========================================================================
# _streamable.py — McpStreamableHttpClient
# ===========================================================================


class TestMcpStreamableHttpClient:
    """Tests for McpStreamableHttpClient."""

    def _make_client(self, **kwargs: Any):
        from lauren_mcp._client._streamable import McpStreamableHttpClient

        return McpStreamableHttpClient("http://localhost:8000/mcp", **kwargs)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def test_init_sets_url(self):
        client = self._make_client()
        assert client._url == "http://localhost:8000/mcp"

    def test_init_strips_trailing_slash(self):
        from lauren_mcp._client._streamable import McpStreamableHttpClient

        client = McpStreamableHttpClient("http://localhost:8000/mcp/")
        assert client._url == "http://localhost:8000/mcp"

    def test_init_stores_auth(self):
        auth = MagicMock()
        client = self._make_client(auth=auth)
        assert client._auth is auth

    def test_init_stores_headers(self):
        client = self._make_client(headers={"X-Custom": "value"})
        assert client._headers == {"X-Custom": "value"}

    def test_init_default_session_none(self):
        client = self._make_client()
        assert client._session_id is None

    def test_init_no_httpx_raises(self):
        from lauren_mcp._client import _streamable as mod

        original = mod._HTTPX_AVAILABLE
        try:
            mod._HTTPX_AVAILABLE = False
            with pytest.raises(ImportError, match="lauren-mcp\\[sse\\]"):
                mod.McpStreamableHttpClient("http://localhost/mcp")
        finally:
            mod._HTTPX_AVAILABLE = original

    # ------------------------------------------------------------------
    # _start_connection
    # ------------------------------------------------------------------

    async def test_start_connection_creates_http_client(self):
        client = self._make_client()
        with patch("lauren_mcp._client._streamable.httpx.AsyncClient") as MockClient:
            mock_http = AsyncMock()
            MockClient.return_value = mock_http
            await client._start_connection()
        assert client._http_client is mock_http
        assert client._session_id is None

    # ------------------------------------------------------------------
    # _close_connection
    # ------------------------------------------------------------------

    async def test_close_connection_cancels_push_task(self):
        client = self._make_client()
        mock_task = MagicMock()
        mock_task.done.return_value = False
        mock_task.cancel = MagicMock()

        async def fake_await():
            raise asyncio.CancelledError()

        mock_task.__await__ = lambda self: fake_await().__await__()

        # Use real asyncio task-like awaitable
        async def _noop():
            raise asyncio.CancelledError()

        real_task = asyncio.ensure_future(_noop())
        client._push_task = real_task

        mock_http = AsyncMock()
        mock_http.aclose = AsyncMock()
        client._http_client = mock_http
        client._session_id = None

        await client._close_connection()
        assert client._push_task is None

    async def test_close_connection_sends_delete_when_session_exists(self):
        client = self._make_client()
        client._push_task = None
        mock_http = AsyncMock()
        mock_http.delete = AsyncMock(return_value=MagicMock(status_code=200))
        mock_http.aclose = AsyncMock()
        client._http_client = mock_http
        client._session_id = "sess-123"

        await client._close_connection()

        mock_http.delete.assert_called_once()
        call_args = mock_http.delete.call_args
        assert "sess-123" in str(call_args)
        mock_http.aclose.assert_called_once()
        assert client._session_id is None
        assert client._http_client is None

    async def test_close_connection_no_delete_when_no_session(self):
        client = self._make_client()
        client._push_task = None
        mock_http = AsyncMock()
        mock_http.delete = AsyncMock()
        mock_http.aclose = AsyncMock()
        client._http_client = mock_http
        client._session_id = None

        await client._close_connection()
        mock_http.delete.assert_not_called()
        mock_http.aclose.assert_called_once()

    async def test_close_connection_delete_exception_ignored(self):
        client = self._make_client()
        client._push_task = None
        mock_http = AsyncMock()
        mock_http.delete = AsyncMock(side_effect=RuntimeError("delete failed"))
        mock_http.aclose = AsyncMock()
        client._http_client = mock_http
        client._session_id = "sess-123"

        # Should not raise
        await client._close_connection()
        mock_http.aclose.assert_called_once()

    async def test_close_connection_aclose_exception_ignored(self):
        client = self._make_client()
        client._push_task = None
        mock_http = AsyncMock()
        mock_http.delete = AsyncMock()
        mock_http.aclose = AsyncMock(side_effect=RuntimeError("close failed"))
        client._http_client = mock_http
        client._session_id = None

        await client._close_connection()  # Should not raise

    async def test_close_connection_none_http_client(self):
        client = self._make_client()
        client._push_task = None
        client._http_client = None
        client._session_id = None
        await client._close_connection()  # Should not raise

    # ------------------------------------------------------------------
    # _send_raw
    # ------------------------------------------------------------------

    async def test_send_raw_raises_when_not_connected(self):
        from lauren_mcp._client._stdio import McpCallError

        client = self._make_client()
        client._http_client = None
        with pytest.raises(McpCallError, match="not connected"):
            await client._send_raw({"jsonrpc": "2.0", "method": "ping", "id": 1})

    async def test_send_raw_posts_json_rpc_message(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 202
        mock_resp.headers = {}
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        client._http_client = mock_http
        client._session_id = "sess-abc"

        await client._send_raw({"jsonrpc": "2.0", "method": "ping", "id": 1})
        mock_http.post.assert_called_once()

    async def test_send_raw_extracts_session_id_from_initialize(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"mcp-session-id": "new-session-id", "content-type": "application/json"}
        mock_resp.text = _json_rpc_response(0, _make_initialize_result())
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        client._http_client = mock_http
        client._session_id = None
        client._pending = {}

        await client._send_raw({"jsonrpc": "2.0", "method": "initialize", "id": 0})
        assert client._session_id == "new-session-id"

    async def test_send_raw_204_returns_early(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 204
        mock_resp.headers = {}
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        client._http_client = mock_http
        client._session_id = "sess"

        await client._send_raw({"jsonrpc": "2.0", "method": "ping", "id": 1})

    async def test_send_raw_400_raises_mcp_call_error(self):
        from lauren_mcp._client._stdio import McpCallError

        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Bad Request"
        mock_resp.headers = {}
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        client._http_client = mock_http
        client._session_id = "sess"

        with pytest.raises(McpCallError, match="HTTP 400"):
            await client._send_raw({"jsonrpc": "2.0", "method": "bad", "id": 1})

    async def test_send_raw_network_exception_raises_mcp_call_error(self):
        from lauren_mcp._client._stdio import McpCallError

        client = self._make_client()
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=ConnectionError("network error"))
        client._http_client = mock_http
        client._session_id = "sess"

        with pytest.raises(McpCallError, match="HTTP send failed"):
            await client._send_raw({"jsonrpc": "2.0", "method": "ping", "id": 1})

    async def test_send_raw_dispatches_sse_response(self):
        client = self._make_client()
        sse_body = "data: " + _json_rpc_response(1, {"tools": []}) + "\n\n"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "text/event-stream"}
        mock_resp.text = sse_body
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        client._http_client = mock_http
        client._session_id = "sess"

        # Create a pending future so dispatch works
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        client._pending = {1: fut}
        client._notification_listeners = []

        await client._send_raw({"jsonrpc": "2.0", "method": "tools/list", "id": 1})
        assert fut.done()
        assert fut.result() == {"tools": []}

    async def test_send_raw_dispatches_json_response(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.text = _json_rpc_response(2, {"tools": []})
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        client._http_client = mock_http
        client._session_id = "sess"

        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        client._pending = {2: fut}
        client._notification_listeners = []

        await client._send_raw({"jsonrpc": "2.0", "method": "tools/list", "id": 2})
        assert fut.done()

    async def test_send_raw_includes_session_header(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 202
        mock_resp.headers = {}
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        client._http_client = mock_http
        client._session_id = "my-session"

        await client._send_raw({"jsonrpc": "2.0", "method": "ping", "id": 1})
        call_kwargs = mock_http.post.call_args[1]
        headers_sent = call_kwargs.get("headers", {})
        assert "mcp-session-id" in headers_sent
        assert headers_sent["mcp-session-id"] == "my-session"

    async def test_send_raw_no_session_header_when_none(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 202
        mock_resp.headers = {}
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        client._http_client = mock_http
        client._session_id = None

        await client._send_raw({"jsonrpc": "2.0", "method": "ping", "id": 1})
        call_kwargs = mock_http.post.call_args[1]
        headers_sent = call_kwargs.get("headers", {})
        assert "mcp-session-id" not in headers_sent

    # ------------------------------------------------------------------
    # connect / close (integration of lifecycle)
    # ------------------------------------------------------------------

    async def test_connect_calls_start_and_handshake(self):
        client = self._make_client(max_retries=0, startup_timeout=5.0)

        # Mock _start_connection and _handshake directly
        client._start_connection = AsyncMock()
        client._handshake = AsyncMock()
        client._session_id = None

        await client.connect()
        client._start_connection.assert_called_once()
        client._handshake.assert_called_once()

    async def test_connect_creates_push_task_when_session_exists(self):
        client = self._make_client(max_retries=0, startup_timeout=5.0)
        client._start_connection = AsyncMock()
        client._handshake = AsyncMock()
        client._session_id = "sess-123"

        push_loop_called = False

        async def fake_push_loop():
            nonlocal push_loop_called
            push_loop_called = True
            await asyncio.sleep(0)

        with patch.object(client, "_push_loop", fake_push_loop):
            await client.connect()

        # Give the task a chance to run
        await asyncio.sleep(0)
        # Cancel if still running
        if client._push_task and not client._push_task.done():
            client._push_task.cancel()
            try:
                await client._push_task
            except (asyncio.CancelledError, Exception):
                pass

    async def test_close_calls_fail_all_pending_and_close_connection(self):
        client = self._make_client()
        client._fail_all_pending = MagicMock()
        client._close_connection = AsyncMock()

        await client.close()
        client._fail_all_pending.assert_called_once_with("Client closed")
        client._close_connection.assert_called_once()

    # ------------------------------------------------------------------
    # _push_loop
    # ------------------------------------------------------------------

    async def test_push_loop_exits_early_when_no_client(self):
        client = self._make_client()
        client._http_client = None
        client._session_id = None
        # Should just return without error
        await client._push_loop()

    async def test_push_loop_exits_early_when_no_session(self):
        client = self._make_client()
        client._http_client = AsyncMock()
        client._session_id = None
        await client._push_loop()

    async def test_push_loop_handles_non_200_status(self):
        client = self._make_client()
        mock_http = AsyncMock()
        client._http_client = mock_http
        client._session_id = "sess"

        mock_resp = AsyncMock()
        mock_resp.status_code = 404

        async def fake_aiter_text():
            return
            yield  # make it an async generator

        mock_resp.aiter_text = fake_aiter_text
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        mock_http.stream = MagicMock(return_value=mock_resp)

        await client._push_loop()  # Should just return

    async def test_push_loop_dispatches_sse_messages(self):
        client = self._make_client()
        mock_http = AsyncMock()
        client._http_client = mock_http
        client._session_id = "sess"
        client._notification_listeners = []
        client._pending = {}

        notification_json = _json_rpc_notification("notifications/tools/list_changed")
        sse_chunk = f"data: {notification_json}\n\n"

        mock_resp = AsyncMock()
        mock_resp.status_code = 200

        async def fake_aiter_text():
            yield sse_chunk

        mock_resp.aiter_text = fake_aiter_text
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        mock_http.stream = MagicMock(return_value=mock_resp)

        handled = []
        client.on_list_changed(lambda kind: handled.append(kind))

        await client._push_loop()
        assert "tools" in handled

    async def test_push_loop_cancelled_error_propagates(self):
        client = self._make_client()
        mock_http = AsyncMock()
        client._http_client = mock_http
        client._session_id = "sess"

        mock_resp = AsyncMock()
        mock_resp.status_code = 200

        async def fake_aiter_text():
            raise asyncio.CancelledError()
            yield  # pragma: no cover

        mock_resp.aiter_text = fake_aiter_text
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        mock_http.stream = MagicMock(return_value=mock_resp)

        with pytest.raises(asyncio.CancelledError):
            await client._push_loop()

    async def test_push_loop_general_exception_logged(self):
        client = self._make_client()
        mock_http = AsyncMock()
        client._http_client = mock_http
        client._session_id = "sess"

        mock_resp = AsyncMock()

        async def bad_enter():
            raise RuntimeError("connection error")

        mock_resp.__aenter__ = bad_enter
        mock_resp.__aexit__ = AsyncMock(return_value=False)
        mock_http.stream = MagicMock(return_value=mock_resp)

        # Should not raise — exception is logged
        await client._push_loop()

    # ------------------------------------------------------------------
    # full connect cycle with mocked HTTP
    # ------------------------------------------------------------------

    async def test_full_connect_and_list_tools(self):
        """Simulate a full connect+list_tools flow with mock HTTP."""
        client = self._make_client(max_retries=0, startup_timeout=5.0)

        init_result = _make_initialize_result()
        init_response = _json_rpc_response(0, init_result)
        list_tools_response = _json_rpc_response(
            1, {"tools": [{"name": "greet", "description": "Say hello", "inputSchema": {}}]}
        )

        call_count = [0]

        async def mock_post(url, *, content, headers, **kwargs):
            resp = MagicMock()
            resp.headers = {"content-type": "application/json", "mcp-session-id": "test-session"}
            if call_count[0] == 0:
                resp.status_code = 200
                resp.text = init_response
            elif call_count[0] == 1:
                # initialized notification - no response needed
                resp.status_code = 202
                resp.text = ""
            else:
                resp.status_code = 200
                resp.text = list_tools_response
            call_count[0] += 1
            return resp

        with patch("lauren_mcp._client._streamable.httpx.AsyncClient") as MockClient:
            mock_http = AsyncMock()
            mock_http.post = mock_post
            mock_http.aclose = AsyncMock()
            MockClient.return_value = mock_http

            await client.connect()
            assert client._session_id == "test-session"

            tools = await client.list_tools()
            assert len(tools) == 1
            assert tools[0].name == "greet"

            client._push_task = None  # prevent push loop
            await client.close()


# ===========================================================================
# _iter_sse_data
# ===========================================================================


class TestIterSseData:
    def test_single_data_line(self):
        from lauren_mcp._client._streamable import _iter_sse_data

        result = _iter_sse_data("data: hello\n\n")
        assert result == ["hello"]

    def test_multiple_events(self):
        from lauren_mcp._client._streamable import _iter_sse_data

        text = "data: first\n\ndata: second\n\n"
        result = _iter_sse_data(text)
        assert result == ["first", "second"]

    def test_multi_line_data(self):
        from lauren_mcp._client._streamable import _iter_sse_data

        result = _iter_sse_data("data: line1\ndata: line2\n\n")
        assert result == ["line1\nline2"]

    def test_no_data_lines(self):
        from lauren_mcp._client._streamable import _iter_sse_data

        result = _iter_sse_data("event: connect\n\n")
        assert result == []

    def test_empty_string(self):
        from lauren_mcp._client._streamable import _iter_sse_data

        result = _iter_sse_data("")
        assert result == []

    def test_data_without_trailing_newlines(self):
        from lauren_mcp._client._streamable import _iter_sse_data

        result = _iter_sse_data("data: payload")
        assert result == ["payload"]

    def test_data_colon_stripping(self):
        from lauren_mcp._client._streamable import _iter_sse_data

        result = _iter_sse_data("data:  value\n\n")
        assert result == ["value"]


# ===========================================================================
# _sse.py — McpHttpSseClient
# ===========================================================================


class TestMcpHttpSseClient:
    """Tests for McpHttpSseClient."""

    def _make_client(self, **kwargs: Any):
        from lauren_mcp._client._sse import McpHttpSseClient

        return McpHttpSseClient("http://localhost:8000/mcp", **kwargs)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def test_init_strips_trailing_slash(self):
        from lauren_mcp._client._sse import McpHttpSseClient

        client = McpHttpSseClient("http://localhost:8000/mcp/")
        assert client._url == "http://localhost:8000/mcp"

    def test_init_stores_auth(self):
        auth = MagicMock()
        client = self._make_client(auth=auth)
        assert client._auth is auth

    def test_init_stores_headers(self):
        client = self._make_client(headers={"X-Custom": "value"})
        assert client._headers == {"X-Custom": "value"}

    def test_init_session_id_is_none(self):
        client = self._make_client()
        assert client._session_id is None

    def test_init_no_sse_raises(self):
        from lauren_mcp._client import _sse as mod

        original = mod._SSE_AVAILABLE
        try:
            mod._SSE_AVAILABLE = False
            with pytest.raises(ImportError, match="lauren-mcp\\[sse\\]"):
                mod.McpHttpSseClient("http://localhost/mcp")
        finally:
            mod._SSE_AVAILABLE = original

    # ------------------------------------------------------------------
    # connect / close
    # ------------------------------------------------------------------

    async def test_connect_calls_start_and_handshake(self):
        client = self._make_client()
        client._start_connection = AsyncMock()
        client._handshake = AsyncMock()
        await client.connect()
        client._start_connection.assert_called_once()
        client._handshake.assert_called_once()

    async def test_close_fails_pending_and_closes_connection(self):
        client = self._make_client()
        client._fail_all_pending = MagicMock()
        client._close_connection = AsyncMock()
        await client.close()
        client._fail_all_pending.assert_called_once_with("Client closed")
        client._close_connection.assert_called_once()

    # ------------------------------------------------------------------
    # _start_connection — timeout handling
    # ------------------------------------------------------------------

    async def test_start_connection_times_out_waiting_for_sse(self):
        from lauren_mcp._client._stdio import McpCallError

        client = self._make_client(startup_timeout=0.01)

        # Make the SSE loop hang forever
        async def hanging_sse_loop(session_ready):
            await asyncio.sleep(10)  # never completes

        with patch.object(client, "_sse_loop", hanging_sse_loop):
            with patch("lauren_mcp._client._sse.httpx.AsyncClient") as MockClient:
                mock_http = AsyncMock()
                MockClient.return_value = mock_http
                with pytest.raises((McpCallError, TimeoutError)):
                    await client._start_connection()

    async def test_start_connection_creates_http_client(self):
        client = self._make_client(startup_timeout=5.0)

        session_ready_fut: asyncio.Future[str] | None = None

        async def fast_sse_loop(session_ready: asyncio.Future[str]) -> None:
            nonlocal session_ready_fut
            session_ready_fut = session_ready
            session_ready.set_result("test-session-id")
            await asyncio.sleep(0)

        with patch.object(client, "_sse_loop", fast_sse_loop):
            with patch("lauren_mcp._client._sse.httpx.AsyncClient") as MockClient:
                mock_http = AsyncMock()
                MockClient.return_value = mock_http
                await client._start_connection()
        assert client._http_client is mock_http

    # ------------------------------------------------------------------
    # _close_connection
    # ------------------------------------------------------------------

    async def test_close_connection_cancels_reader_task(self):
        client = self._make_client()

        async def _hang():
            await asyncio.sleep(100)

        task = asyncio.ensure_future(_hang())
        client._reader_task = task
        client._http_client = None

        await client._close_connection()
        assert client._reader_task is None
        assert task.cancelled()

    async def test_close_connection_closes_http_client(self):
        client = self._make_client()
        client._reader_task = None
        mock_http = AsyncMock()
        mock_http.aclose = AsyncMock()
        client._http_client = mock_http
        client._session_id = "sess"

        await client._close_connection()
        mock_http.aclose.assert_called_once()
        assert client._http_client is None
        assert client._session_id is None

    async def test_close_connection_aclose_exception_ignored(self):
        client = self._make_client()
        client._reader_task = None
        mock_http = AsyncMock()
        mock_http.aclose = AsyncMock(side_effect=RuntimeError("aclose error"))
        client._http_client = mock_http
        client._session_id = None

        await client._close_connection()  # Should not raise

    # ------------------------------------------------------------------
    # _send_raw
    # ------------------------------------------------------------------

    async def test_send_raw_raises_when_no_http_client(self):
        from lauren_mcp._client._stdio import McpCallError

        client = self._make_client()
        client._http_client = None
        client._session_id = "sess"
        with pytest.raises(McpCallError, match="not connected"):
            await client._send_raw({"jsonrpc": "2.0", "method": "ping", "id": 1})

    async def test_send_raw_raises_when_no_session(self):
        from lauren_mcp._client._stdio import McpCallError

        client = self._make_client()
        client._http_client = AsyncMock()
        client._session_id = None
        with pytest.raises(McpCallError, match="session not yet established"):
            await client._send_raw({"jsonrpc": "2.0", "method": "ping", "id": 1})

    async def test_send_raw_posts_with_session_header(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        client._http_client = mock_http
        client._session_id = "sess-abc"

        await client._send_raw({"jsonrpc": "2.0", "method": "ping", "id": 1})
        mock_http.post.assert_called_once()
        call_kwargs = mock_http.post.call_args[1]
        headers = call_kwargs.get("headers", {})
        assert headers.get("mcp-session-id") == "sess-abc"

    async def test_send_raw_warns_on_non_200_202(self):
        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        client._http_client = mock_http
        client._session_id = "sess"

        # Should not raise — just logs warning
        await client._send_raw({"jsonrpc": "2.0", "method": "ping", "id": 1})

    async def test_send_raw_network_error_raises_mcp_call_error(self):
        from lauren_mcp._client._stdio import McpCallError

        client = self._make_client()
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(side_effect=ConnectionError("network"))
        client._http_client = mock_http
        client._session_id = "sess"

        with pytest.raises(McpCallError, match="HTTP send failed"):
            await client._send_raw({"jsonrpc": "2.0", "method": "ping", "id": 1})

    # ------------------------------------------------------------------
    # _sse_loop
    # ------------------------------------------------------------------

    async def test_sse_loop_sets_session_id_from_endpoint_event_json(self):
        """Endpoint event with JSON payload sets session_id."""
        client = self._make_client(max_retries=0)
        mock_http = AsyncMock()
        client._http_client = mock_http
        client._pending = {}
        client._notification_listeners = []

        loop = asyncio.get_running_loop()
        session_ready: asyncio.Future[str] = loop.create_future()

        endpoint_event = MagicMock()
        endpoint_event.event = "endpoint"
        endpoint_event.data = json.dumps({"session_id": "abc123"})

        class FakeEventSource:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args: Any):
                return False

            async def aiter_sse(self):
                yield endpoint_event

        with patch(
            "lauren_mcp._client._sse.httpx_sse.aconnect_sse", return_value=FakeEventSource()
        ):
            await client._sse_loop(session_ready)

        assert client._session_id == "abc123"
        assert session_ready.done()
        assert session_ready.result() == "abc123"

    async def test_sse_loop_sets_session_id_from_raw_string(self):
        """Endpoint event with raw string (not JSON) sets session_id."""
        client = self._make_client(max_retries=0)
        mock_http = AsyncMock()
        client._http_client = mock_http
        client._pending = {}
        client._notification_listeners = []

        loop = asyncio.get_running_loop()
        session_ready: asyncio.Future[str] = loop.create_future()

        endpoint_event = MagicMock()
        endpoint_event.event = "endpoint"
        endpoint_event.data = "raw-session-id"

        class FakeEventSource:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args: Any):
                return False

            async def aiter_sse(self):
                yield endpoint_event

        with patch(
            "lauren_mcp._client._sse.httpx_sse.aconnect_sse", return_value=FakeEventSource()
        ):
            await client._sse_loop(session_ready)

        assert client._session_id == "raw-session-id"

    async def test_sse_loop_uses_session_id_key(self):
        """Endpoint event using sessionId (camelCase) sets session_id."""
        client = self._make_client(max_retries=0)
        mock_http = AsyncMock()
        client._http_client = mock_http
        client._pending = {}
        client._notification_listeners = []

        loop = asyncio.get_running_loop()
        session_ready: asyncio.Future[str] = loop.create_future()

        endpoint_event = MagicMock()
        endpoint_event.event = "endpoint"
        endpoint_event.data = json.dumps({"sessionId": "camel-case-session"})

        class FakeEventSource:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args: Any):
                return False

            async def aiter_sse(self):
                yield endpoint_event

        with patch(
            "lauren_mcp._client._sse.httpx_sse.aconnect_sse", return_value=FakeEventSource()
        ):
            await client._sse_loop(session_ready)

        assert client._session_id == "camel-case-session"

    async def test_sse_loop_dispatches_message_events(self):
        """message events are dispatched through _dispatch_message."""
        client = self._make_client()
        mock_http = AsyncMock()
        client._http_client = mock_http
        client._notification_listeners = []

        loop = asyncio.get_running_loop()
        session_ready: asyncio.Future[str] = loop.create_future()
        # Pre-set session id to avoid hanging
        client._session_id = "sess-123"
        session_ready.set_result("sess-123")

        # A response to a pending request
        pending_fut = loop.create_future()
        client._pending = {5: pending_fut}

        msg_event = MagicMock()
        msg_event.event = "message"
        msg_event.data = _json_rpc_response(5, {"result": "ok"})

        class FakeEventSource:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args: Any):
                return False

            async def aiter_sse(self):
                yield msg_event

        with patch(
            "lauren_mcp._client._sse.httpx_sse.aconnect_sse", return_value=FakeEventSource()
        ):
            await client._sse_loop(session_ready)

        assert pending_fut.done()
        assert pending_fut.result() == {"result": "ok"}

    async def test_sse_loop_ignores_unknown_events(self):
        """Unknown event types are logged and ignored."""
        client = self._make_client()
        mock_http = AsyncMock()
        client._http_client = mock_http
        client._pending = {}
        client._notification_listeners = []

        loop = asyncio.get_running_loop()
        session_ready: asyncio.Future[str] = loop.create_future()
        session_ready.set_result("sess")
        client._session_id = "sess"

        unknown_event = MagicMock()
        unknown_event.event = "custom-event"
        unknown_event.data = "some data"

        class FakeEventSource:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args: Any):
                return False

            async def aiter_sse(self):
                yield unknown_event

        with patch(
            "lauren_mcp._client._sse.httpx_sse.aconnect_sse", return_value=FakeEventSource()
        ):
            await client._sse_loop(session_ready)  # should not raise

    async def test_sse_loop_cancelled_error_propagates(self):
        """CancelledError in SSE loop propagates."""
        client = self._make_client()
        mock_http = AsyncMock()
        client._http_client = mock_http
        client._pending = {}
        client._notification_listeners = []

        loop = asyncio.get_running_loop()
        session_ready: asyncio.Future[str] = loop.create_future()

        class FakeEventSourceCancelled:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args: Any):
                return False

            async def aiter_sse(self):
                raise asyncio.CancelledError()
                yield  # pragma: no cover

        with patch(
            "lauren_mcp._client._sse.httpx_sse.aconnect_sse",
            return_value=FakeEventSourceCancelled(),
        ):
            with pytest.raises(asyncio.CancelledError):
                await client._sse_loop(session_ready)

    async def test_sse_loop_stream_closed_sets_exception_on_future(self):
        """If SSE stream closes before endpoint event, session_ready gets exception."""
        client = self._make_client(max_retries=0)
        mock_http = AsyncMock()
        client._http_client = mock_http
        client._pending = {}
        client._notification_listeners = []

        loop = asyncio.get_running_loop()
        session_ready: asyncio.Future[str] = loop.create_future()

        class FakeEventSourceEmpty:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args: Any):
                return False

            async def aiter_sse(self):
                return
                yield  # pragma: no cover

        with patch(
            "lauren_mcp._client._sse.httpx_sse.aconnect_sse", return_value=FakeEventSourceEmpty()
        ):
            await client._sse_loop(session_ready)

        assert session_ready.done()
        with pytest.raises(Exception):
            session_ready.result()

    async def test_sse_loop_retry_on_stream_close(self):
        """SSE loop triggers reconnect when max_retries > 0."""
        client = self._make_client(max_retries=1)
        mock_http = AsyncMock()
        client._http_client = mock_http
        client._pending = {}
        client._notification_listeners = []
        client._retry_count = 0

        loop = asyncio.get_running_loop()
        session_ready: asyncio.Future[str] = loop.create_future()
        session_ready.set_result("sess")  # already done — bypass endpoint wait
        client._session_id = "sess"

        reconnect_called = []

        async def fake_start_connection():
            reconnect_called.append("start")

        async def fake_handshake():
            reconnect_called.append("handshake")

        class FakeEventSourceEmpty:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args: Any):
                return False

            async def aiter_sse(self):
                return
                yield  # pragma: no cover

        with patch(
            "lauren_mcp._client._sse.httpx_sse.aconnect_sse", return_value=FakeEventSourceEmpty()
        ):
            with patch.object(client, "_start_connection", fake_start_connection):
                with patch.object(client, "_handshake", fake_handshake):
                    await client._sse_loop(session_ready)

        assert "start" in reconnect_called
        assert "handshake" in reconnect_called

    async def test_sse_loop_no_http_client_returns_early(self):
        """SSE loop returns early if http_client is None."""
        client = self._make_client()
        client._http_client = None

        loop = asyncio.get_running_loop()
        session_ready: asyncio.Future[str] = loop.create_future()
        await client._sse_loop(session_ready)
        # session_ready is never resolved

    async def test_sse_loop_reconnect_exception_logged(self):
        """Reconnect failure is logged, not raised."""
        client = self._make_client(max_retries=1)
        mock_http = AsyncMock()
        client._http_client = mock_http
        client._pending = {}
        client._notification_listeners = []
        client._retry_count = 0

        loop = asyncio.get_running_loop()
        session_ready: asyncio.Future[str] = loop.create_future()
        session_ready.set_result("sess")
        client._session_id = "sess"

        async def fail_start():
            raise RuntimeError("reconnect failed")

        class FakeEventSourceEmpty:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args: Any):
                return False

            async def aiter_sse(self):
                return
                yield  # pragma: no cover

        with patch(
            "lauren_mcp._client._sse.httpx_sse.aconnect_sse", return_value=FakeEventSourceEmpty()
        ):
            with patch.object(client, "_start_connection", fail_start):
                await client._sse_loop(session_ready)  # Should not raise

    async def test_sse_loop_max_retries_exceeded_logs_error(self):
        """When retry_count >= max_retries, logs error instead of retrying."""
        client = self._make_client(max_retries=2)
        mock_http = AsyncMock()
        client._http_client = mock_http
        client._pending = {}
        client._notification_listeners = []
        client._retry_count = 2  # already at max

        loop = asyncio.get_running_loop()
        session_ready: asyncio.Future[str] = loop.create_future()
        session_ready.set_result("sess")
        client._session_id = "sess"

        class FakeEventSourceEmpty:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args: Any):
                return False

            async def aiter_sse(self):
                return
                yield  # pragma: no cover

        start_called = []

        async def fake_start():
            start_called.append(1)

        with patch(
            "lauren_mcp._client._sse.httpx_sse.aconnect_sse", return_value=FakeEventSourceEmpty()
        ):
            with patch.object(client, "_start_connection", fake_start):
                await client._sse_loop(session_ready)

        assert not start_called  # no reconnect when max_retries exceeded

    async def test_sse_loop_general_exception_logged(self):
        """Non-cancel exceptions in SSE loop are logged."""
        client = self._make_client(max_retries=0)
        mock_http = AsyncMock()
        client._http_client = mock_http
        client._pending = {}
        client._notification_listeners = []

        loop = asyncio.get_running_loop()
        session_ready: asyncio.Future[str] = loop.create_future()

        class FakeEventSourceError:
            async def __aenter__(self):
                raise RuntimeError("bad connection")

            async def __aexit__(self, *args: Any):
                return False

            async def aiter_sse(self):
                return
                yield  # pragma: no cover

        with patch(
            "lauren_mcp._client._sse.httpx_sse.aconnect_sse", return_value=FakeEventSourceError()
        ):
            await client._sse_loop(session_ready)  # Should not raise


# ===========================================================================
# _ws.py — McpWebSocketClient
# ===========================================================================


class TestMcpWebSocketClient:
    """Tests for McpWebSocketClient."""

    def _make_client(self, **kwargs: Any):
        from lauren_mcp._client._ws import McpWebSocketClient

        return McpWebSocketClient("ws://localhost:8000/mcp/ws", **kwargs)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def test_init_stores_url(self):
        client = self._make_client()
        assert client._url == "ws://localhost:8000/mcp/ws"

    def test_init_stores_headers(self):
        client = self._make_client(headers={"X-Custom": "value"})
        assert client._headers == {"X-Custom": "value"}

    def test_init_ws_is_none(self):
        client = self._make_client()
        assert client._ws is None

    def test_init_no_websockets_raises(self):
        from lauren_mcp._client import _ws as mod

        original = mod._WS_AVAILABLE
        try:
            mod._WS_AVAILABLE = False
            with pytest.raises(ImportError, match="lauren-mcp\\[ws\\]"):
                mod.McpWebSocketClient("ws://localhost/mcp/ws")
        finally:
            mod._WS_AVAILABLE = original

    # ------------------------------------------------------------------
    # connect / close
    # ------------------------------------------------------------------

    async def test_connect_calls_start_and_handshake(self):
        client = self._make_client()
        client._start_connection = AsyncMock()
        client._handshake = AsyncMock()
        await client.connect()
        client._start_connection.assert_called_once()
        client._handshake.assert_called_once()

    async def test_close_fails_pending_and_closes_connection(self):
        client = self._make_client()
        client._fail_all_pending = MagicMock()
        client._close_connection = AsyncMock()
        await client.close()
        client._fail_all_pending.assert_called_once_with("Client closed")
        client._close_connection.assert_called_once()

    # ------------------------------------------------------------------
    # _start_connection
    # ------------------------------------------------------------------

    async def test_start_connection_connects_websocket(self):
        from lauren_mcp._client import _ws as mod

        client = self._make_client()
        mock_ws = AsyncMock()

        async def _noop():
            pass

        mock_task = asyncio.ensure_future(_noop())

        with patch.object(mod, "ws_client") as mock_ws_client:
            mock_ws_client.connect = AsyncMock(return_value=mock_ws)
            with patch("asyncio.create_task", return_value=mock_task) as mock_create_task:
                await client._start_connection()

        assert client._ws is mock_ws
        mock_create_task.assert_called_once()

    async def test_start_connection_with_headers(self):
        from lauren_mcp._client import _ws as mod

        client = self._make_client(headers={"Authorization": "Bearer tok"})
        mock_ws = AsyncMock()

        async def _noop():
            pass

        mock_task = asyncio.ensure_future(_noop())

        with patch.object(mod, "ws_client") as mock_ws_client:
            mock_ws_client.connect = AsyncMock(return_value=mock_ws)
            with patch("asyncio.create_task", return_value=mock_task):
                await client._start_connection()

        call_kwargs = mock_ws_client.connect.call_args[1]
        extra_headers = call_kwargs.get("additional_headers")
        assert extra_headers is not None
        assert any("Authorization" in str(h) for h in extra_headers)

    async def test_start_connection_no_headers_passes_none(self):
        from lauren_mcp._client import _ws as mod

        client = self._make_client(headers={})
        mock_ws = AsyncMock()

        async def _noop():
            pass

        mock_task = asyncio.ensure_future(_noop())

        with patch.object(mod, "ws_client") as mock_ws_client:
            mock_ws_client.connect = AsyncMock(return_value=mock_ws)
            with patch("asyncio.create_task", return_value=mock_task):
                await client._start_connection()

        call_kwargs = mock_ws_client.connect.call_args[1]
        assert call_kwargs.get("additional_headers") is None

    # ------------------------------------------------------------------
    # _close_connection
    # ------------------------------------------------------------------

    async def test_close_connection_cancels_reader_and_closes_ws(self):
        client = self._make_client()

        async def _hang():
            await asyncio.sleep(100)

        task = asyncio.ensure_future(_hang())
        client._reader_task = task

        mock_ws = AsyncMock()
        mock_ws.close = AsyncMock()
        client._ws = mock_ws

        await client._close_connection()
        assert client._reader_task is None
        assert task.cancelled()
        mock_ws.close.assert_called_once()
        assert client._ws is None

    async def test_close_connection_ws_close_exception_ignored(self):
        client = self._make_client()
        client._reader_task = None
        mock_ws = AsyncMock()
        mock_ws.close = AsyncMock(side_effect=RuntimeError("close error"))
        client._ws = mock_ws

        await client._close_connection()  # Should not raise
        assert client._ws is None

    async def test_close_connection_no_ws(self):
        client = self._make_client()
        client._reader_task = None
        client._ws = None
        await client._close_connection()  # Should not raise

    # ------------------------------------------------------------------
    # _send_raw
    # ------------------------------------------------------------------

    async def test_send_raw_raises_when_no_ws(self):
        from lauren_mcp._client._stdio import McpCallError

        client = self._make_client()
        client._ws = None
        with pytest.raises(McpCallError, match="not connected"):
            await client._send_raw({"jsonrpc": "2.0", "method": "ping", "id": 1})

    async def test_send_raw_sends_json_text_frame(self):
        client = self._make_client()
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()
        client._ws = mock_ws

        await client._send_raw({"jsonrpc": "2.0", "method": "ping", "id": 1})
        mock_ws.send.assert_called_once()
        sent_arg = mock_ws.send.call_args[0][0]
        parsed = json.loads(sent_arg)
        assert parsed["method"] == "ping"

    # ------------------------------------------------------------------
    # _read_loop
    # ------------------------------------------------------------------

    async def test_read_loop_dispatches_text_messages(self):
        client = self._make_client()
        client._notification_listeners = []

        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        client._pending = {0: fut}

        response_msg = _json_rpc_response(0, {"result": "pong"})

        class FakeWs:
            def __aiter__(self):
                return self

            async def __anext__(self):
                if not hasattr(self, "_sent"):
                    self._sent = True
                    return response_msg
                raise StopAsyncIteration

        client._ws = FakeWs()
        client._max_retries = 0

        await client._read_loop()

        assert fut.done()
        assert fut.result() == {"result": "pong"}

    async def test_read_loop_dispatches_bytes_as_utf8(self):
        client = self._make_client()
        client._notification_listeners = []

        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        client._pending = {0: fut}

        response_msg = _json_rpc_response(0, {"result": "pong"})

        class FakeWs:
            def __aiter__(self):
                return self

            async def __anext__(self):
                if not hasattr(self, "_sent"):
                    self._sent = True
                    return response_msg.encode("utf-8")
                raise StopAsyncIteration

        client._ws = FakeWs()
        client._max_retries = 0

        await client._read_loop()

        assert fut.done()

    async def test_read_loop_skips_empty_messages(self):
        client = self._make_client()
        client._notification_listeners = []
        client._pending = {}
        client._max_retries = 0

        dispatch_calls = []
        original_dispatch = client._dispatch_message

        def tracked_dispatch(raw: str) -> None:
            dispatch_calls.append(raw)
            original_dispatch(raw)

        client._dispatch_message = tracked_dispatch

        class FakeWs:
            _items = iter(["   ", ""])

            def __aiter__(self):
                return self

            async def __anext__(self):
                try:
                    return next(self._items)
                except StopIteration:
                    raise StopAsyncIteration

        client._ws = FakeWs()

        await client._read_loop()
        assert dispatch_calls == []

    async def test_read_loop_cancelled_error_propagates(self):
        client = self._make_client()
        client._notification_listeners = []
        client._pending = {}
        client._max_retries = 0

        class FakeWsCancelled:
            def __aiter__(self):
                return self

            async def __anext__(self):
                raise asyncio.CancelledError()

        client._ws = FakeWsCancelled()

        with pytest.raises(asyncio.CancelledError):
            await client._read_loop()

    async def test_read_loop_general_exception_logged(self):
        client = self._make_client()
        client._notification_listeners = []
        client._pending = {}
        client._max_retries = 0

        class FakeWsError:
            def __aiter__(self):
                return self

            async def __anext__(self):
                raise RuntimeError("ws error")

        client._ws = FakeWsError()

        # Should not raise — logged instead
        await client._read_loop()

    async def test_read_loop_ws_none_returns_early(self):
        client = self._make_client()
        client._ws = None
        await client._read_loop()  # Should return without error

    async def test_read_loop_retry_on_disconnect(self):
        """After disconnect with retries left, triggers reconnect."""
        client = self._make_client(max_retries=1)
        client._notification_listeners = []
        client._pending = {}
        client._retry_count = 0

        class FakeWsEmpty:
            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

        client._ws = FakeWsEmpty()

        reconnect_called = []

        async def fake_start():
            reconnect_called.append("start")

        async def fake_handshake():
            reconnect_called.append("handshake")

        with patch.object(client, "_start_connection", fake_start):
            with patch.object(client, "_handshake", fake_handshake):
                await client._read_loop()

        assert "start" in reconnect_called
        assert "handshake" in reconnect_called

    async def test_read_loop_max_retries_exceeded(self):
        """When max retries exceeded, logs error instead of reconnecting."""
        client = self._make_client(max_retries=0)
        client._notification_listeners = []
        client._pending = {}
        client._retry_count = 0

        class FakeWsEmpty:
            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

        client._ws = FakeWsEmpty()

        start_called = []

        async def fake_start():
            start_called.append(1)

        with patch.object(client, "_start_connection", fake_start):
            await client._read_loop()

        assert not start_called

    async def test_read_loop_reconnect_exception_logged(self):
        """Reconnect failure is logged, not raised."""
        client = self._make_client(max_retries=1)
        client._notification_listeners = []
        client._pending = {}
        client._retry_count = 0

        class FakeWsEmpty:
            def __aiter__(self):
                return self

            async def __anext__(self):
                raise StopAsyncIteration

        client._ws = FakeWsEmpty()

        async def fail_start():
            raise RuntimeError("reconnect error")

        with patch.object(client, "_start_connection", fail_start):
            await client._read_loop()  # Should not raise


# ===========================================================================
# _oauth.py — ClientCredentialsProvider (additional coverage)
# ===========================================================================


class TestClientCredentialsProviderAdditional:
    """Additional tests for ClientCredentialsProvider coverage."""

    def test_init_no_httpx_raises(self):
        from lauren_mcp._client import _oauth as mod

        original = mod._HTTPX_AVAILABLE
        try:
            mod._HTTPX_AVAILABLE = False
            with pytest.raises(ImportError, match="lauren-mcp\\[sse\\]"):
                mod.ClientCredentialsProvider(
                    token_endpoint="https://auth.example.com/token",
                    client_id="cid",
                    client_secret="secret",
                )
        finally:
            mod._HTTPX_AVAILABLE = original

    async def test_fetch_token_no_scopes(self):
        """_fetch_token works when scopes is empty."""
        from unittest.mock import patch as _patch

        from lauren_mcp._client._oauth import ClientCredentialsProvider

        provider = ClientCredentialsProvider(
            token_endpoint="https://auth.example.com/token",
            client_id="cid",
            client_secret="secret",
        )

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"access_token": "tok", "expires_in": 3600}
        mock_resp.raise_for_status = MagicMock()
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with _patch("lauren_mcp._client._oauth.httpx.AsyncClient", return_value=mock_http):
            token = await provider._fetch_token()

        assert token == "tok"

    async def test_fetch_token_with_scopes(self):
        """_fetch_token includes scope in the request."""
        from unittest.mock import patch as _patch

        from lauren_mcp._client._oauth import ClientCredentialsProvider

        provider = ClientCredentialsProvider(
            token_endpoint="https://auth.example.com/token",
            client_id="cid",
            client_secret="secret",
            scopes=["read", "write"],
        )

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"access_token": "scoped_tok", "expires_in": 3600}
        mock_resp.raise_for_status = MagicMock()
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with _patch("lauren_mcp._client._oauth.httpx.AsyncClient", return_value=mock_http):
            token = await provider._fetch_token()

        assert token == "scoped_tok"
        call_kwargs = mock_http.post.call_args[1]
        data_sent = call_kwargs.get("data", {})
        assert "scope" in data_sent
        assert "read" in data_sent["scope"]

    async def test_fetch_token_no_expires_in(self):
        """_fetch_token without expires_in stores without TTL."""
        from unittest.mock import patch as _patch

        from lauren_mcp._client._oauth import ClientCredentialsProvider

        provider = ClientCredentialsProvider(
            token_endpoint="https://auth.example.com/token",
            client_id="cid",
            client_secret="secret",
        )

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"access_token": "no_expiry_tok"}
        mock_resp.raise_for_status = MagicMock()
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with _patch("lauren_mcp._client._oauth.httpx.AsyncClient", return_value=mock_http):
            token = await provider._fetch_token()

        assert token == "no_expiry_tok"

    async def test_fetch_token_with_extra_params(self):
        """_fetch_token includes extra_params in the request."""
        from unittest.mock import patch as _patch

        from lauren_mcp._client._oauth import ClientCredentialsProvider

        provider = ClientCredentialsProvider(
            token_endpoint="https://auth.example.com/token",
            client_id="cid",
            client_secret="secret",
            extra_params={"audience": "https://api.example.com"},
        )

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"access_token": "extra_tok", "expires_in": 60}
        mock_resp.raise_for_status = MagicMock()
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with _patch("lauren_mcp._client._oauth.httpx.AsyncClient", return_value=mock_http):
            token = await provider._fetch_token()

        call_kwargs = mock_http.post.call_args[1]
        data_sent = call_kwargs.get("data", {})
        assert "audience" in data_sent

    async def test_get_token_returns_cached(self):
        """get_token returns cached token without fetching."""
        from lauren_mcp._client._oauth import ClientCredentialsProvider, InMemoryTokenStorage

        store = InMemoryTokenStorage()
        await store.set_token("cached_tok", expires_in=3600)

        provider = ClientCredentialsProvider(
            token_endpoint="https://auth.example.com/token",
            client_id="cid",
            client_secret="secret",
            storage=store,
        )

        fetch_called = []

        async def fake_fetch():
            fetch_called.append(1)
            return "new_tok"

        provider._fetch_token = fake_fetch
        token = await provider.get_token()
        assert token == "cached_tok"
        assert not fetch_called

    async def test_get_token_double_checked_locking(self):
        """get_token uses double-checked locking — if another coroutine fills
        the cache before we acquire the lock, we return the cached value."""
        from lauren_mcp._client._oauth import ClientCredentialsProvider, InMemoryTokenStorage

        store = InMemoryTokenStorage()

        provider = ClientCredentialsProvider(
            token_endpoint="https://auth.example.com/token",
            client_id="cid",
            client_secret="secret",
            storage=store,
        )

        call_count = 0
        original_fetch = provider._fetch_token

        async def counting_fetch():
            nonlocal call_count
            call_count += 1
            await store.set_token("concurrent_tok", expires_in=3600)
            return "concurrent_tok"

        provider._fetch_token = counting_fetch
        token = await provider.get_token()
        assert token == "concurrent_tok"
        assert call_count == 1

    async def test_async_auth_flow_attaches_bearer_header(self):
        """async_auth_flow attaches bearer token to the request."""
        from unittest.mock import patch as _patch

        from lauren_mcp._client._oauth import ClientCredentialsProvider

        provider = ClientCredentialsProvider(
            token_endpoint="https://auth.example.com/token",
            client_id="cid",
            client_secret="secret",
        )

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"access_token": "bearer_tok", "expires_in": 3600}
        mock_resp.raise_for_status = MagicMock()
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with _patch("lauren_mcp._client._oauth.httpx.AsyncClient", return_value=mock_http):
            request = httpx.Request("GET", "https://api.example.com/mcp")
            flow = provider.async_auth_flow(request)
            sent_request = await flow.__anext__()
            assert sent_request.headers.get("authorization") == "Bearer bearer_tok"
            # Finish flow with 200 response
            try:
                await flow.asend(httpx.Response(200))
            except StopAsyncIteration:
                pass

    async def test_async_auth_flow_retries_on_401(self):
        """async_auth_flow invalidates cache and retries on 401."""
        from unittest.mock import patch as _patch

        from lauren_mcp._client._oauth import ClientCredentialsProvider

        provider = ClientCredentialsProvider(
            token_endpoint="https://auth.example.com/token",
            client_id="cid",
            client_secret="secret",
        )

        call_count = [0]
        tokens = ["first_tok", "second_tok"]

        mock_resp = MagicMock()

        def make_json():
            tok = tokens[call_count[0]]
            call_count[0] += 1
            return {"access_token": tok, "expires_in": 3600}

        mock_resp.json.side_effect = make_json
        mock_resp.raise_for_status = MagicMock()
        mock_http = AsyncMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=False)

        with _patch("lauren_mcp._client._oauth.httpx.AsyncClient", return_value=mock_http):
            request = httpx.Request("GET", "https://api.example.com/mcp")
            flow = provider.async_auth_flow(request)
            # First yield: attach first token
            sent_request = await flow.__anext__()
            assert sent_request.headers.get("authorization") == "Bearer first_tok"
            # Send 401 response — triggers retry
            try:
                retry_request = await flow.asend(httpx.Response(401))
                assert retry_request.headers.get("authorization") == "Bearer second_tok"
                # Finish the flow
                await flow.asend(None)
            except StopAsyncIteration:
                pass
