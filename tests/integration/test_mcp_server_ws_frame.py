"""Integration tests: McpWsController._handle_frame() logic.

We obtain the controller class via ``mcp_ws_controller()``, instantiate it
with a mock dispatcher, then call ``_handle_frame(mock_ws, raw)`` directly
so we can test protocol behaviour at the frame level without a running server.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from lauren_mcp._server._dispatcher import McpDispatcher
from lauren_mcp._server._ws import mcp_ws_controller
from lauren_mcp._types import (
    McpErrorCode,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_controller_instance(dispatcher: McpDispatcher | None = None):
    """Return a fresh McpWsController instance wired to *dispatcher*."""
    ctrl_cls = mcp_ws_controller("/mcp")
    dispatcher = dispatcher or McpDispatcher()
    dispatcher._register_builtins()
    instance = ctrl_cls.__new__(ctrl_cls)
    instance._dispatcher = dispatcher
    instance._initialized = False
    return instance


def make_ws() -> AsyncMock:
    """Return a mock WebSocket with a tracked ``send_text`` coroutine."""
    ws = MagicMock()
    ws.send_text = AsyncMock()
    return ws


def rpc_request(method: str, id_=1, params=None) -> str:
    obj = {"jsonrpc": "2.0", "method": method, "id": id_}
    if params is not None:
        obj["params"] = params
    return json.dumps(obj)


def rpc_notification(method: str, params=None) -> str:
    obj = {"jsonrpc": "2.0", "method": method}
    if params is not None:
        obj["params"] = params
    return json.dumps(obj)


def parse_sent(ws: AsyncMock) -> dict:
    """Parse the JSON sent via ws.send_text on the most recent call."""
    assert ws.send_text.called, "ws.send_text was never called"
    raw = ws.send_text.call_args[0][0]
    return json.loads(raw)


# ---------------------------------------------------------------------------
# Tests: initialize-first enforcement
# ---------------------------------------------------------------------------


class TestInitializeFirst:
    async def test_initialize_frame_before_initialized_is_dispatched(self):
        """``initialize`` request must be passed to dispatcher even when _initialized is False."""
        dispatcher = McpDispatcher()
        dispatcher._register_builtins()

        async def _init(params):
            return {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "serverInfo": {"name": "t", "version": "1"},
            }

        dispatcher.register("initialize", _init)
        ctrl = make_controller_instance(dispatcher)
        ws = make_ws()
        await ctrl._handle_frame(ws, rpc_request("initialize", id_=1))
        assert ws.send_text.called
        sent = parse_sent(ws)
        assert sent["jsonrpc"] == "2.0"
        assert "result" in sent

    async def test_non_initialize_frame_before_initialized_returns_invalid_request(self):
        """Any non-initialize request before the handshake must return INVALID_REQUEST."""
        ctrl = make_controller_instance()
        ws = make_ws()
        await ctrl._handle_frame(ws, rpc_request("tools/list", id_=2))
        assert ws.send_text.called
        sent = parse_sent(ws)
        assert "error" in sent
        assert sent["error"]["code"] == McpErrorCode.INVALID_REQUEST

    async def test_after_initialized_flag_non_initialize_request_dispatched(self):
        """After _initialized=True, non-initialize requests are forwarded to dispatcher."""
        dispatcher = McpDispatcher()
        dispatcher._register_builtins()

        async def _tools_list(params):
            return {"tools": []}

        dispatcher.register("tools/list", _tools_list)
        ctrl = make_controller_instance(dispatcher)
        ctrl._initialized = True  # simulate handshake complete
        ws = make_ws()
        await ctrl._handle_frame(ws, rpc_request("tools/list", id_=3))
        assert ws.send_text.called
        sent = parse_sent(ws)
        assert "result" in sent
        assert sent["result"] == {"tools": []}


# ---------------------------------------------------------------------------
# Tests: notifications/initialized
# ---------------------------------------------------------------------------


class TestNotificationsInitialized:
    async def test_notifications_initialized_sets_flag_to_true(self):
        ctrl = make_controller_instance()
        ws = make_ws()
        assert ctrl._initialized is False
        await ctrl._handle_frame(ws, rpc_notification("notifications/initialized"))
        assert ctrl._initialized is True

    async def test_notifications_initialized_sends_no_response(self):
        ctrl = make_controller_instance()
        ws = make_ws()
        await ctrl._handle_frame(ws, rpc_notification("notifications/initialized"))
        ws.send_text.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: $/cancelRequest
# ---------------------------------------------------------------------------


class TestCancelRequest:
    async def test_cancel_request_calls_dispatcher_cancel(self):
        mock_dispatcher = MagicMock()
        mock_dispatcher.cancel = MagicMock(return_value=False)
        # Build manually with mock dispatcher
        ctrl_cls = mcp_ws_controller("/mcp")
        instance = ctrl_cls.__new__(ctrl_cls)
        instance._dispatcher = mock_dispatcher
        instance._initialized = True

        ws = make_ws()
        await instance._handle_frame(ws, rpc_notification("$/cancelRequest", params={"id": 42}))
        mock_dispatcher.cancel.assert_called_once_with(42)

    async def test_cancel_request_sends_no_response(self):
        dispatcher = McpDispatcher()
        dispatcher._register_builtins()
        ctrl = make_controller_instance(dispatcher)
        ctrl._initialized = True
        ws = make_ws()
        await ctrl._handle_frame(ws, rpc_notification("$/cancelRequest", params={"id": 99}))
        ws.send_text.assert_not_called()

    async def test_cancel_request_unknown_id_no_exception(self):
        """$/cancelRequest for an unknown id should not raise."""
        dispatcher = McpDispatcher()
        dispatcher._register_builtins()
        ctrl = make_controller_instance(dispatcher)
        ctrl._initialized = True
        ws = make_ws()
        # Should not raise
        await ctrl._handle_frame(ws, rpc_notification("$/cancelRequest", params={"id": 9999}))
        ws.send_text.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: malformed JSON
# ---------------------------------------------------------------------------


class TestMalformedJson:
    async def test_malformed_json_sends_parse_error(self):
        ctrl = make_controller_instance()
        ws = make_ws()
        await ctrl._handle_frame(ws, "{ this is not valid json !!!")
        assert ws.send_text.called
        sent = parse_sent(ws)
        assert "error" in sent
        assert sent["error"]["code"] == McpErrorCode.PARSE_ERROR

    async def test_parse_error_response_has_jsonrpc_field(self):
        ctrl = make_controller_instance()
        ws = make_ws()
        await ctrl._handle_frame(ws, "NOT JSON AT ALL")
        sent = parse_sent(ws)
        assert sent.get("jsonrpc") == "2.0"

    async def test_parse_error_id_is_null(self):
        ctrl = make_controller_instance()
        ws = make_ws()
        await ctrl._handle_frame(ws, "BROKEN")
        sent = parse_sent(ws)
        assert sent.get("id") is None


# ---------------------------------------------------------------------------
# Tests: unknown method / method not found
# ---------------------------------------------------------------------------


class TestUnknownMethod:
    async def test_unknown_method_returns_method_not_found(self):
        dispatcher = McpDispatcher()
        dispatcher._register_builtins()
        ctrl = make_controller_instance(dispatcher)
        ctrl._initialized = True
        ws = make_ws()
        await ctrl._handle_frame(ws, rpc_request("does/not/exist", id_=10))
        sent = parse_sent(ws)
        assert "error" in sent
        assert sent["error"]["code"] == McpErrorCode.METHOD_NOT_FOUND


# ---------------------------------------------------------------------------
# Tests: response id and jsonrpc field preservation
# ---------------------------------------------------------------------------


class TestResponseFields:
    async def test_string_id_preserved_in_response(self):
        dispatcher = McpDispatcher()
        dispatcher._register_builtins()
        ctrl = make_controller_instance(dispatcher)
        ctrl._initialized = True
        ws = make_ws()
        await ctrl._handle_frame(ws, rpc_request("ping", id_="str-id-xyz"))
        sent = parse_sent(ws)
        assert sent["id"] == "str-id-xyz"

    async def test_int_id_preserved_in_response(self):
        dispatcher = McpDispatcher()
        dispatcher._register_builtins()
        ctrl = make_controller_instance(dispatcher)
        ctrl._initialized = True
        ws = make_ws()
        await ctrl._handle_frame(ws, rpc_request("ping", id_=12345))
        sent = parse_sent(ws)
        assert sent["id"] == 12345

    async def test_success_response_has_jsonrpc_2_0_field(self):
        dispatcher = McpDispatcher()
        dispatcher._register_builtins()
        ctrl = make_controller_instance(dispatcher)
        ctrl._initialized = True
        ws = make_ws()
        await ctrl._handle_frame(ws, rpc_request("ping", id_=1))
        sent = parse_sent(ws)
        assert sent["jsonrpc"] == "2.0"

    async def test_error_response_has_jsonrpc_2_0_field(self):
        dispatcher = McpDispatcher()
        dispatcher._register_builtins()
        ctrl = make_controller_instance(dispatcher)
        ctrl._initialized = True
        ws = make_ws()
        await ctrl._handle_frame(ws, rpc_request("no/such/method", id_=2))
        sent = parse_sent(ws)
        assert sent["jsonrpc"] == "2.0"


# ---------------------------------------------------------------------------
# Tests: notification (no id) — no response sent
# ---------------------------------------------------------------------------


class TestNotificationNoResponse:
    async def test_notification_without_known_method_sends_no_response(self):
        """Unknown notifications should be silently ignored (no response)."""
        dispatcher = McpDispatcher()
        dispatcher._register_builtins()
        ctrl = make_controller_instance(dispatcher)
        ctrl._initialized = True
        ws = make_ws()
        await ctrl._handle_frame(ws, rpc_notification("some/unknown/notification"))
        ws.send_text.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: sequential frames processed in order
# ---------------------------------------------------------------------------


class TestSequentialFrames:
    async def test_multiple_sequential_frames_processed_in_order(self):
        dispatcher = McpDispatcher()
        dispatcher._register_builtins()
        call_order: list[str] = []

        async def _tools_list(params):
            call_order.append("tools/list")
            return {"tools": []}

        async def _resources_list(params):
            call_order.append("resources/list")
            return {"resources": []}

        dispatcher.register("tools/list", _tools_list)
        dispatcher.register("resources/list", _resources_list)
        ctrl = make_controller_instance(dispatcher)
        ctrl._initialized = True
        ws = make_ws()

        await ctrl._handle_frame(ws, rpc_request("tools/list", id_=1))
        await ctrl._handle_frame(ws, rpc_request("resources/list", id_=2))
        await ctrl._handle_frame(ws, rpc_request("ping", id_=3))

        assert call_order == ["tools/list", "resources/list"]
        assert ws.send_text.call_count == 3


# ---------------------------------------------------------------------------
# Tests: large payload
# ---------------------------------------------------------------------------


class TestLargePayload:
    async def test_large_payload_handled_without_error(self):
        dispatcher = McpDispatcher()
        dispatcher._register_builtins()

        async def _tools_call(params):
            text = (params or {}).get("arguments", {}).get("text", "")
            return {"content": [{"type": "text", "text": text}], "isError": False}

        dispatcher.register("tools/call", _tools_call)
        ctrl = make_controller_instance(dispatcher)
        ctrl._initialized = True
        ws = make_ws()

        large_text = "x" * 1000
        payload = rpc_request(
            "tools/call",
            id_=99,
            params={"name": "echo_large", "arguments": {"text": large_text}},
        )
        await ctrl._handle_frame(ws, payload)
        assert ws.send_text.called
        sent = parse_sent(ws)
        # Should return a success response (result or error is fine — but no crash)
        assert sent.get("jsonrpc") == "2.0"
