"""Integration tests for resource subscriptions (resources/subscribe / unsubscribe)."""

from __future__ import annotations

import asyncio
import json

import pytest
from lauren import LaurenFactory, module
from lauren.testing import TestClient, WsTestClient

from lauren_mcp import McpServerModule
from lauren_mcp._server._subscriptions import ResourceSubscriptionManager
from lauren_mcp.server._decorators import mcp_resource, mcp_server

# ---------------------------------------------------------------------------
# Server under test
# ---------------------------------------------------------------------------

# We keep a module-level reference to the subscription manager so tests
# can call notify_updated without needing DI container access.
_sub_mgr: ResourceSubscriptionManager | None = None


@mcp_server("/mcp")
class _SubServer:
    @mcp_resource("file:///counter.txt", name="counter")
    async def get_counter(self) -> str:
        return "42"


@module(imports=[McpServerModule.for_root(_SubServer, transport="ws")])
class _SubApp:
    pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def app():
    global _sub_mgr
    a = LaurenFactory.create(_SubApp)
    TestClient(a)  # trigger @post_construct hooks
    # Grab the subscription manager from the module by instantiating it directly
    _sub_mgr = ResourceSubscriptionManager()
    return a


@pytest.fixture
def ws(app):
    return WsTestClient(app)


# ---------------------------------------------------------------------------
# Helper: full WS handshake
# ---------------------------------------------------------------------------


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
    await asyncio.wait_for(conn.receive_json(), timeout=3.0)  # initialize result
    await conn.send_json({"jsonrpc": "2.0", "method": "notifications/initialized"})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_subscribe_handler_registered(ws) -> None:
    """resources/subscribe is a registered handler (returns {})."""
    async with ws.connect("/mcp/ws") as conn:
        await _handshake(conn)
        await conn.send_json(
            {
                "jsonrpc": "2.0",
                "method": "resources/subscribe",
                "id": 2,
                "params": {"uri": "file:///counter.txt"},
            }
        )
        resp = await asyncio.wait_for(conn.receive_json(), timeout=3.0)
        assert resp.get("result") == {}


async def test_unsubscribe_handler_registered(ws) -> None:
    """resources/unsubscribe is a registered handler (returns {})."""
    async with ws.connect("/mcp/ws") as conn:
        await _handshake(conn)
        await conn.send_json(
            {
                "jsonrpc": "2.0",
                "method": "resources/unsubscribe",
                "id": 2,
                "params": {"uri": "file:///counter.txt"},
            }
        )
        resp = await asyncio.wait_for(conn.receive_json(), timeout=3.0)
        assert resp.get("result") == {}


async def test_subscribe_requires_uri(ws) -> None:
    """resources/subscribe without a 'uri' param should return an error."""
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
        resp = await asyncio.wait_for(conn.receive_json(), timeout=3.0)
        assert "error" in resp


async def test_capabilities_include_subscribe(ws) -> None:
    """Server capabilities include resources.subscribe = True when resources exist."""
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
        resp = await asyncio.wait_for(conn.receive_json(), timeout=3.0)
        caps = resp.get("result", {}).get("capabilities", {})
        resources_cap = caps.get("resources", {})
        assert resources_cap.get("subscribe") is True


async def test_subscription_manager_unit() -> None:
    """ResourceSubscriptionManager notifies and unsubscribes correctly (unit-level)."""
    mgr = ResourceSubscriptionManager()
    received: list[str] = []

    async def send(raw: str) -> None:
        received.append(raw)

    mgr.subscribe("file:///counter.txt", "test-sess", send)
    await mgr.notify_updated("file:///counter.txt")
    assert len(received) == 1
    notif = json.loads(received[0])
    assert notif["method"] == "notifications/resources/updated"

    # Unsubscribe
    mgr.unsubscribe("file:///counter.txt", "test-sess")
    await mgr.notify_updated("file:///counter.txt")
    assert len(received) == 1  # no new notifications
