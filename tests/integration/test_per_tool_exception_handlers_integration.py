"""Integration tests for Phase 4 per-tool exception handlers.

Uses a real Lauren app, WsTestClient, and the full DI/dispatch pipeline to
verify that @use_exception_handlers on @mcp_tool correctly intercepts domain
exceptions and converts them to isError: True tool results.
"""

from __future__ import annotations

import asyncio

import pytest
from lauren import LaurenFactory, exception_handler, module, use_exception_handlers
from lauren.testing import TestClient, WsTestClient

from lauren_mcp import McpServerModule, mcp_server, mcp_tool

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Handler classes
# ---------------------------------------------------------------------------


@exception_handler(ValueError)
class ValueErrorHandler:
    async def catch(self, exc: Exception, ctx: object) -> dict:
        return {
            "content": [{"type": "text", "text": f"Bad value: {exc}"}],
            "isError": True,
            "structuredContent": {"error_type": "ValueError", "message": str(exc)},
        }


@exception_handler(PermissionError)
class PermissionHandler:
    async def catch(self, exc: Exception, ctx: object) -> dict:
        return {
            "content": [{"type": "text", "text": "Not allowed"}],
            "isError": True,
        }


# ---------------------------------------------------------------------------
# Server under test
# ---------------------------------------------------------------------------


@mcp_server("/mcp")
class TestServer:
    @use_exception_handlers(ValueErrorHandler)
    @mcp_tool()
    async def value_error_tool(self, trigger: bool = False) -> dict:
        """Tool that optionally raises ValueError."""
        if trigger:
            raise ValueError("qty must be positive")
        return {"ok": True}

    @use_exception_handlers(PermissionHandler, ValueErrorHandler)
    @mcp_tool()
    async def multi_handler_tool(self, error_type: str = "none") -> dict:
        """Tool with multiple exception handlers."""
        if error_type == "ValueError":
            raise ValueError("bad value")
        if error_type == "PermissionError":
            raise PermissionError("no access")
        if error_type == "TypeError":
            raise TypeError("wrong type")
        return {"ok": True}

    @mcp_tool()
    async def unhandled_tool(self) -> dict:
        """Tool with no exception handlers."""
        raise RuntimeError("unhandled crash")


@module(imports=[McpServerModule.for_root(TestServer)])
class AppModule:
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _handshake(conn: object) -> None:
    """Perform MCP initialize handshake."""
    await conn.send_json(  # type: ignore[attr-defined]
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        }
    )
    await asyncio.wait_for(conn.receive_json(), timeout=5.0)  # type: ignore[attr-defined]
    await conn.send_json({"jsonrpc": "2.0", "method": "notifications/initialized"})  # type: ignore[attr-defined]


async def _call_tool(conn: object, name: str, args: dict, req_id: int = 2) -> dict:
    """Send a tools/call request and return the response dict."""
    await conn.send_json(  # type: ignore[attr-defined]
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
        }
    )
    return await asyncio.wait_for(conn.receive_json(), timeout=5.0)  # type: ignore[attr-defined]


async def _list_tools(conn: object, req_id: int = 3) -> list:
    """Send a tools/list request and return the tools list."""
    await conn.send_json(  # type: ignore[attr-defined]
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/list",
            "params": {},
        }
    )
    resp = await asyncio.wait_for(conn.receive_json(), timeout=5.0)  # type: ignore[attr-defined]
    return resp["result"]["tools"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def app():
    """Build the Lauren app once per module."""
    application = LaurenFactory.create(AppModule)
    TestClient(application)  # triggers @post_construct
    return application


@pytest.fixture
def ws(app):
    """Return a WsTestClient bound to the app."""
    return WsTestClient(app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_value_error_converted_to_is_error_content(ws: WsTestClient):
    """ValueError → ValueErrorHandler.catch → isError: True content block."""
    async with ws.connect("/mcp/ws") as conn:
        await _handshake(conn)
        resp = await _call_tool(conn, "value_error_tool", {"trigger": True})

    assert "result" in resp, f"Expected result, got: {resp}"
    result = resp["result"]
    assert result["isError"] is True
    assert "Bad value" in result["content"][0]["text"]
    assert result["structuredContent"]["error_type"] == "ValueError"


async def test_handled_exception_is_not_protocol_error(ws: WsTestClient):
    """Handled exceptions return a tools/call result, NOT a JSON-RPC error frame."""
    async with ws.connect("/mcp/ws") as conn:
        await _handshake(conn)
        resp = await _call_tool(conn, "value_error_tool", {"trigger": True})

    # A protocol error would have "error" key; a handled exception has "result"
    assert "result" in resp, f"Got a protocol error instead of a result: {resp}"
    assert "error" not in resp
    assert resp["result"]["isError"] is True


async def test_tool_success_no_handler_called(ws: WsTestClient):
    """Successful tool call — handler is never invoked, isError is False."""
    async with ws.connect("/mcp/ws") as conn:
        await _handshake(conn)
        resp = await _call_tool(conn, "value_error_tool", {"trigger": False})

    assert "result" in resp
    assert resp["result"]["isError"] is False


async def test_unmatched_exception_becomes_internal_error(ws: WsTestClient):
    """Exception with no matching handler → INTERNAL_ERROR JSON-RPC error frame."""
    async with ws.connect("/mcp/ws") as conn:
        await _handshake(conn)
        resp = await _call_tool(conn, "unhandled_tool", {})

    assert "error" in resp, f"Expected protocol error, got: {resp}"
    assert resp["error"]["code"] == -32603  # INTERNAL_ERROR


async def test_multi_handler_value_error_routes_to_correct_handler(ws: WsTestClient):
    """ValueError with PermissionHandler first, ValueErrorHandler second → ValueErrorHandler wins."""  # noqa: E501
    async with ws.connect("/mcp/ws") as conn:
        await _handshake(conn)
        resp = await _call_tool(conn, "multi_handler_tool", {"error_type": "ValueError"})

    assert "result" in resp
    result = resp["result"]
    assert result["isError"] is True
    assert "Bad value" in result["content"][0]["text"]


async def test_multi_handler_permission_error_routes_to_correct_handler(ws: WsTestClient):
    """PermissionError → PermissionHandler (listed first, matches first)."""
    async with ws.connect("/mcp/ws") as conn:
        await _handshake(conn)
        resp = await _call_tool(conn, "multi_handler_tool", {"error_type": "PermissionError"})

    assert "result" in resp
    result = resp["result"]
    assert result["isError"] is True
    assert result["content"][0]["text"] == "Not allowed"


async def test_multi_handler_unmatched_exception_is_internal_error(ws: WsTestClient):
    """TypeError with no matching handler → INTERNAL_ERROR."""
    async with ws.connect("/mcp/ws") as conn:
        await _handshake(conn)
        resp = await _call_tool(conn, "multi_handler_tool", {"error_type": "TypeError"})

    assert "error" in resp
    assert resp["error"]["code"] == -32603


async def test_tools_list_has_no_handler_metadata(ws: WsTestClient):
    """tools/list response has no exception handler fields."""
    async with ws.connect("/mcp/ws") as conn:
        await _handshake(conn)
        tools = await _list_tools(conn)

    tool_names = {t["name"] for t in tools}
    assert "value_error_tool" in tool_names
    for tool in tools:
        assert "exception_handlers" not in tool
        assert "exceptionHandlers" not in tool


async def test_handler_auto_registered_as_di_provider(ws: WsTestClient):
    """App starts without MissingProviderError and handler works — DI auto-registered."""
    async with ws.connect("/mcp/ws") as conn:
        await _handshake(conn)
        resp = await _call_tool(conn, "value_error_tool", {"trigger": True})

    # If DI registration failed, this test would have errored at fixture setup,
    # or the handler would have failed to instantiate (exception propagates → INTERNAL_ERROR)
    assert "result" in resp
    assert resp["result"]["isError"] is True
    assert "Bad value" in resp["result"]["content"][0]["text"]


async def test_tool_success_after_exception_same_connection(ws: WsTestClient):
    """After a handled exception, the connection is still usable."""
    async with ws.connect("/mcp/ws") as conn:
        await _handshake(conn)
        # First call raises handled exception
        resp1 = await _call_tool(conn, "value_error_tool", {"trigger": True}, req_id=2)
        assert resp1["result"]["isError"] is True

        # Second call succeeds on the same connection
        resp2 = await _call_tool(conn, "value_error_tool", {"trigger": False}, req_id=3)
        assert resp2["result"]["isError"] is False
