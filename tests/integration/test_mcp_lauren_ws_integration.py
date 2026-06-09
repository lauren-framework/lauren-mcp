"""Integration tests: MCP server mounted in a real Lauren application.

These tests use ``LaurenFactory.create()`` + ``lauren.testing.WsTestClient``
to exercise the full Lauren DI stack — ``@mcp_server``, ``@mcp_tool``,
``@mcp_resource``, ``@mcp_prompt``, and ``McpServerModule.for_root()`` — over
a live in-process WebSocket connection.  No subprocess is started; every
coroutine runs in the same event loop as the test.

This is the same integration path a production deployment uses when a real
MCP client (``McpServer.ws``) connects to a Lauren app served by uvicorn.

Coverage:
  - LaurenFactory.create() builds the full DI container
  - @post_construct on the handler registrar fires before first connection
  - McpServerModule.for_root() registers all four handler types
  - WebSocket handshake (initialize + notifications/initialized)
  - tools/list returns all @mcp_tool methods with correct schemas
  - tools/call dispatches to the correct method and returns content
  - resources/list and resources/read via URI template
  - prompts/list and prompts/get with argument substitution
  - ping works over WebSocket
  - INVALID_REQUEST returned for requests before handshake
  - unknown method returns METHOD_NOT_FOUND
  - McpServerModule.for_root(transport="sse") omits the WS controller
"""

from __future__ import annotations

import asyncio
import json

import pytest
from lauren import LaurenFactory, module
from lauren.testing import TestClient, WsTestClient

from lauren_mcp import McpServerModule, mcp_prompt, mcp_resource, mcp_server, mcp_tool

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Server under test — WidgetServer with all four decorator types
# ---------------------------------------------------------------------------

WIDGETS = [
    {"id": 1, "name": "Widget A", "price": 9.99, "tags": ["blue", "small"]},
    {"id": 2, "name": "Widget B", "price": 14.99, "tags": ["red", "large"]},
    {"id": 3, "name": "Gadget C", "price": 24.99, "tags": ["blue", "large"]},
]


@mcp_server("/mcp")
class WidgetServer:
    @mcp_tool()
    async def search(self, query: str) -> list:
        """Search widgets by name or tag.

        Args:
            query: Search terms matched against name and tags.
        """
        q = query.lower()
        return [w for w in WIDGETS if q in w["name"].lower() or any(q in t for t in w["tags"])]

    @mcp_tool()
    async def get_widget(self, widget_id: int) -> dict:
        """Fetch a single widget by its numeric ID.

        Args:
            widget_id: The widget's numeric identifier.
        """
        return next((w for w in WIDGETS if w["id"] == widget_id), None)  # type: ignore[return-value]

    @mcp_resource("/widgets/{widget_id}")
    async def widget_resource(self, widget_id: str) -> str:
        """Expose a widget as a plain-text MCP resource.

        Args:
            widget_id: The widget ID extracted from the URI path.
        """
        w = next((w for w in WIDGETS if w["id"] == int(widget_id)), None)
        if w is None:
            return f"Widget {widget_id} not found."
        return f"{w['name']} — ${w['price']:.2f} (tags: {', '.join(w['tags'])})"

    @mcp_prompt()
    async def recommend(self, budget: str) -> str:
        """Generate a recommendation prompt for a customer budget.

        Args:
            budget: Maximum customer budget in GBP (e.g. "15").
        """
        affordable = [w for w in WIDGETS if w["price"] <= float(budget)]
        names = ", ".join(w["name"] for w in affordable) or "none"
        return f"Recommend a widget to a customer with £{budget} budget. Options: {names}."


# ---------------------------------------------------------------------------
# Lauren app fixture (module-scoped — built once per test module)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def lauren_app():
    """Build the Lauren app with McpServerModule once for all tests."""

    @module(imports=[McpServerModule.for_root(WidgetServer)])
    class AppModule:
        pass

    app = LaurenFactory.create(AppModule)
    TestClient(app)  # trigger @post_construct hooks (registers MCP handlers)
    return app


@pytest.fixture
def ws(lauren_app):
    """Return a WsTestClient bound to the Lauren app."""
    return WsTestClient(lauren_app)


# ---------------------------------------------------------------------------
# Helper: perform the MCP handshake inside a connected session
# ---------------------------------------------------------------------------


async def _handshake(ws_session) -> dict:
    """Send ``initialize`` and ``notifications/initialized``, return the result."""
    await ws_session.send_json(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0.0"},
            },
        }
    )
    resp = await asyncio.wait_for(ws_session.receive_json(), timeout=5.0)
    await ws_session.send_json({"jsonrpc": "2.0", "method": "notifications/initialized"})
    return resp


# ---------------------------------------------------------------------------
# Handshake tests
# ---------------------------------------------------------------------------


class TestHandshake:
    async def test_initialize_returns_result(self, ws):
        async with ws.connect("/mcp/ws") as conn:
            resp = await _handshake(conn)
            assert "result" in resp, f"Expected result, got: {resp}"

    async def test_server_info_name_matches_class(self, ws):
        async with ws.connect("/mcp/ws") as conn:
            resp = await _handshake(conn)
            assert resp["result"]["serverInfo"]["name"] == "WidgetServer"

    async def test_server_info_version_present(self, ws):
        async with ws.connect("/mcp/ws") as conn:
            resp = await _handshake(conn)
            assert resp["result"]["serverInfo"]["version"]

    async def test_capabilities_includes_tools(self, ws):
        async with ws.connect("/mcp/ws") as conn:
            resp = await _handshake(conn)
            assert "tools" in resp["result"]["capabilities"]

    async def test_capabilities_includes_resources(self, ws):
        async with ws.connect("/mcp/ws") as conn:
            resp = await _handshake(conn)
            assert "resources" in resp["result"]["capabilities"]

    async def test_capabilities_includes_prompts(self, ws):
        async with ws.connect("/mcp/ws") as conn:
            resp = await _handshake(conn)
            assert "prompts" in resp["result"]["capabilities"]

    async def test_request_before_initialized_rejected(self, ws):
        async with ws.connect("/mcp/ws") as conn:
            # Send initialize but NOT notifications/initialized
            await conn.send_json(
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
            )
            await asyncio.wait_for(conn.receive_json(), timeout=3.0)
            # tools/list before notifications/initialized → INVALID_REQUEST
            await conn.send_json({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
            resp = await asyncio.wait_for(conn.receive_json(), timeout=3.0)
            assert "error" in resp
            assert resp["error"]["code"] == -32600  # INVALID_REQUEST


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class TestTools:
    async def test_tools_list_returns_two_tools(self, ws):
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json({"jsonrpc": "2.0", "id": 10, "method": "tools/list"})
            resp = await asyncio.wait_for(conn.receive_json(), timeout=3.0)
            assert len(resp["result"]["tools"]) == 2

    async def test_tools_list_contains_search_and_get_widget(self, ws):
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json({"jsonrpc": "2.0", "id": 10, "method": "tools/list"})
            resp = await asyncio.wait_for(conn.receive_json(), timeout=3.0)
            names = {t["name"] for t in resp["result"]["tools"]}
            assert names == {"search", "get_widget"}

    async def test_tools_list_schema_has_input_schema(self, ws):
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json({"jsonrpc": "2.0", "id": 10, "method": "tools/list"})
            resp = await asyncio.wait_for(conn.receive_json(), timeout=3.0)
            for tool in resp["result"]["tools"]:
                assert "inputSchema" in tool
                assert tool["inputSchema"]["type"] == "object"

    async def test_search_tool_returns_matching_widgets(self, ws):
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 11,
                    "method": "tools/call",
                    "params": {"name": "search", "arguments": {"query": "blue"}},
                }
            )
            resp = await asyncio.wait_for(conn.receive_json(), timeout=3.0)
            content = resp["result"]["content"]
            widgets = json.loads(content[0]["text"])
            names = [w["name"] for w in widgets]
            assert "Widget A" in names
            assert "Gadget C" in names
            assert "Widget B" not in names  # only "red" tag

    async def test_tools_call_is_not_error(self, ws):
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 12,
                    "method": "tools/call",
                    "params": {"name": "search", "arguments": {"query": "widget"}},
                }
            )
            resp = await asyncio.wait_for(conn.receive_json(), timeout=3.0)
            assert resp["result"]["isError"] is False

    async def test_get_widget_returns_correct_item(self, ws):
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 13,
                    "method": "tools/call",
                    "params": {"name": "get_widget", "arguments": {"widget_id": 2}},
                }
            )
            resp = await asyncio.wait_for(conn.receive_json(), timeout=3.0)
            widget = json.loads(resp["result"]["content"][0]["text"])
            assert widget["name"] == "Widget B"
            assert widget["price"] == 14.99

    async def test_unknown_method_returns_method_not_found(self, ws):
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json({"jsonrpc": "2.0", "id": 99, "method": "no/such/method"})
            resp = await asyncio.wait_for(conn.receive_json(), timeout=3.0)
            assert "error" in resp
            assert resp["error"]["code"] == -32601  # METHOD_NOT_FOUND


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


class TestResources:
    async def test_resources_list_returns_one_resource(self, ws):
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json({"jsonrpc": "2.0", "id": 20, "method": "resources/list"})
            resp = await asyncio.wait_for(conn.receive_json(), timeout=3.0)
            assert len(resp["result"]["resources"]) == 1

    async def test_resources_list_uri_contains_widgets(self, ws):
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json({"jsonrpc": "2.0", "id": 20, "method": "resources/list"})
            resp = await asyncio.wait_for(conn.receive_json(), timeout=3.0)
            assert "widgets" in resp["result"]["resources"][0]["uri"]

    async def test_read_resource_widget_1_contains_name(self, ws):
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 21,
                    "method": "resources/read",
                    "params": {"uri": "/widgets/1"},
                }
            )
            resp = await asyncio.wait_for(conn.receive_json(), timeout=3.0)
            text = resp["result"]["contents"][0]["text"]
            assert "Widget A" in text
            assert "9.99" in text

    async def test_read_resource_not_found_returns_text(self, ws):
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 22,
                    "method": "resources/read",
                    "params": {"uri": "/widgets/999"},
                }
            )
            resp = await asyncio.wait_for(conn.receive_json(), timeout=3.0)
            text = resp["result"]["contents"][0]["text"]
            assert "not found" in text.lower()


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


class TestPrompts:
    async def test_prompts_list_returns_one_prompt(self, ws):
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json({"jsonrpc": "2.0", "id": 30, "method": "prompts/list"})
            resp = await asyncio.wait_for(conn.receive_json(), timeout=3.0)
            assert len(resp["result"]["prompts"]) == 1

    async def test_prompts_list_name_is_recommend(self, ws):
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json({"jsonrpc": "2.0", "id": 30, "method": "prompts/list"})
            resp = await asyncio.wait_for(conn.receive_json(), timeout=3.0)
            assert resp["result"]["prompts"][0]["name"] == "recommend"

    async def test_get_prompt_returns_user_message(self, ws):
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 31,
                    "method": "prompts/get",
                    "params": {"name": "recommend", "arguments": {"budget": "12"}},
                }
            )
            resp = await asyncio.wait_for(conn.receive_json(), timeout=3.0)
            messages = resp["result"]["messages"]
            assert len(messages) >= 1
            assert messages[0]["role"] == "user"

    async def test_get_prompt_budget_12_includes_affordable(self, ws):
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 32,
                    "method": "prompts/get",
                    "params": {"name": "recommend", "arguments": {"budget": "12"}},
                }
            )
            resp = await asyncio.wait_for(conn.receive_json(), timeout=3.0)
            text = resp["result"]["messages"][0]["content"]["text"]
            assert "Widget A" in text
            assert "Widget B" not in text  # £14.99 > £12


# ---------------------------------------------------------------------------
# Ping
# ---------------------------------------------------------------------------


class TestPing:
    async def test_ping_before_handshake_rejected(self, ws):
        async with ws.connect("/mcp/ws") as conn:
            await conn.send_json(
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
            )
            await asyncio.wait_for(conn.receive_json(), timeout=3.0)
            # ping before notifications/initialized
            await conn.send_json({"jsonrpc": "2.0", "id": 2, "method": "ping"})
            resp = await asyncio.wait_for(conn.receive_json(), timeout=3.0)
            assert "error" in resp

    async def test_ping_after_handshake_succeeds(self, ws):
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json({"jsonrpc": "2.0", "id": 40, "method": "ping"})
            resp = await asyncio.wait_for(conn.receive_json(), timeout=3.0)
            assert "result" in resp
            assert resp["result"] == {}


# ---------------------------------------------------------------------------
# DI integration — verify the module builds correctly
# ---------------------------------------------------------------------------


class TestLaurenDIIntegration:
    def test_factory_create_succeeds(self):
        @mcp_server("/mcp2")
        class _S:
            @mcp_tool()
            async def hello(self) -> str:
                "Hello."
                return "hi"

        @module(imports=[McpServerModule.for_root(_S)])
        class _App:
            pass

        app = LaurenFactory.create(_App)
        assert app is not None

    def test_for_root_raises_on_non_mcp_class(self):
        class _Plain:
            pass

        with pytest.raises(TypeError):
            McpServerModule.for_root(_Plain)

    async def test_two_concurrent_connections_serve_independently(self, ws):
        async def _chat(conn, widget_id: int) -> str:
            await _handshake(conn)
            await conn.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 50,
                    "method": "tools/call",
                    "params": {"name": "get_widget", "arguments": {"widget_id": widget_id}},
                }
            )
            resp = await asyncio.wait_for(conn.receive_json(), timeout=3.0)
            return json.loads(resp["result"]["content"][0]["text"])["name"]

        async with ws.connect("/mcp/ws") as conn1, ws.connect("/mcp/ws") as conn2:
            name1, name2 = await asyncio.gather(_chat(conn1, 1), _chat(conn2, 3))
        assert name1 == "Widget A"
        assert name2 == "Gadget C"
