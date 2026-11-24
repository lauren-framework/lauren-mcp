"""Integration tests for resource subscription lifecycle over WebSockets."""

from __future__ import annotations

import asyncio

import pytest
from lauren import LaurenFactory, module
from lauren.testing import TestClient, WsTestClient

from lauren_mcp import McpServerModule
from lauren_mcp._server._subscriptions import ResourceSubscriptionManager
from lauren_mcp.server._decorators import mcp_resource, mcp_server

pytestmark = pytest.mark.asyncio

_sub_mgr: ResourceSubscriptionManager | None = None


@mcp_server("/mcp")
class _SubServer:
    def __init__(self, subscriptions: ResourceSubscriptionManager) -> None:
        global _sub_mgr
        self._subscriptions = subscriptions
        _sub_mgr = subscriptions

    @mcp_resource("file:///counter.txt", name="counter")
    async def get_counter(self) -> str:
        return "42"


@module(imports=[McpServerModule.for_root(_SubServer, transport="ws")])
class _SubApp:
    pass


@pytest.fixture(scope="module")
def app():
    a = LaurenFactory.create(_SubApp)
    TestClient(a)  # trigger @post_construct hooks and construct the server.
    assert _sub_mgr is not None
    return a


@pytest.fixture
def ws(app):
    return WsTestClient(app)


async def _handshake(conn) -> None:
    await conn.send_json(
        {
            "jsonrpc": "2.0",
            "method": "initialize",
            "id": 1,
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        }
    )
    await asyncio.wait_for(conn.receive_json(), timeout=3.0)
    await conn.send_json({"jsonrpc": "2.0", "method": "notifications/initialized"})


async def _request(conn, method: str, uri: str, request_id: int = 2) -> dict:
    await conn.send_json(
        {
            "jsonrpc": "2.0",
            "method": method,
            "id": request_id,
            "params": {"uri": uri},
        }
    )
    return await asyncio.wait_for(conn.receive_json(), timeout=3.0)


async def test_subscribe_and_update_notification(ws) -> None:
    assert _sub_mgr is not None
    async with ws.connect("/mcp/ws") as conn:
        await _handshake(conn)
        response = await _request(conn, "resources/subscribe", "file:///counter.txt")
        assert response.get("result") == {}
        assert _sub_mgr.subscription_count == 1

        await _sub_mgr.notify_updated("file:///counter.txt")
        notification = await asyncio.wait_for(conn.receive_json(), timeout=3.0)
        assert notification["method"] == "notifications/resources/updated"
        assert notification["params"] == {"uri": "file:///counter.txt"}


async def test_unsubscribe_stops_notifications(ws) -> None:
    assert _sub_mgr is not None
    async with ws.connect("/mcp/ws") as conn:
        await _handshake(conn)
        await _request(conn, "resources/subscribe", "file:///counter.txt")
        response = await _request(
            conn, "resources/unsubscribe", "file:///counter.txt", request_id=3
        )
        assert response.get("result") == {}
        assert _sub_mgr.subscription_count == 0

        await _sub_mgr.notify_updated("file:///counter.txt")
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(conn.receive_json(), timeout=0.1)


async def test_subscriptions_are_isolated_between_websocket_clients(ws) -> None:
    assert _sub_mgr is not None
    async with ws.connect("/mcp/ws") as first, ws.connect("/mcp/ws") as second:
        await _handshake(first)
        await _handshake(second)
        await _request(first, "resources/subscribe", "file:///first.txt")
        await _request(second, "resources/subscribe", "file:///second.txt")
        assert _sub_mgr.subscription_count == 2

        await _sub_mgr.notify_updated("file:///first.txt")
        first_notification = await asyncio.wait_for(first.receive_json(), timeout=3.0)
        assert first_notification["params"]["uri"] == "file:///first.txt"

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(second.receive_json(), timeout=0.1)


async def test_disconnect_cleans_up_and_reconnect_requires_resubscription(ws) -> None:
    assert _sub_mgr is not None
    async with ws.connect("/mcp/ws") as first:
        await _handshake(first)
        await _request(first, "resources/subscribe", "file:///counter.txt")
        assert _sub_mgr.subscription_count == 1

    # Closing a WebSocket ends its subscription lifecycle.
    assert _sub_mgr.subscription_count == 0

    # A reconnect is a new connection and must explicitly subscribe again.
    async with ws.connect("/mcp/ws") as reconnected:
        await _handshake(reconnected)
        assert _sub_mgr.subscription_count == 0
        await _request(reconnected, "resources/subscribe", "file:///counter.txt")
        assert _sub_mgr.subscription_count == 1

        await _sub_mgr.notify_updated("file:///counter.txt")
        notification = await asyncio.wait_for(reconnected.receive_json(), timeout=3.0)
        assert notification["method"] == "notifications/resources/updated"
        assert notification["params"]["uri"] == "file:///counter.txt"


async def test_subscribe_requires_uri(ws) -> None:
    async with ws.connect("/mcp/ws") as conn:
        await _handshake(conn)
        await conn.send_json(
            {
                "jsonrpc": "2.0",
                "method": "resources/subscribe",
                "id": 2,
                "params": {},
            }
        )
        response = await asyncio.wait_for(conn.receive_json(), timeout=3.0)
        assert "error" in response


async def test_capabilities_include_subscribe(ws) -> None:
    async with ws.connect("/mcp/ws") as conn:
        await conn.send_json(
            {
                "jsonrpc": "2.0",
                "method": "initialize",
                "id": 1,
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "0"},
                },
            }
        )
        response = await asyncio.wait_for(conn.receive_json(), timeout=3.0)
        resources = response.get("result", {}).get("capabilities", {}).get("resources", {})
        assert resources.get("subscribe") is True
