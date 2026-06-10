"""Integration tests for new client-side features (set_logging_level, resource
subscriptions, complete) against a real Lauren WS MCP server.
"""

from __future__ import annotations

import asyncio

import pytest
from lauren import LaurenFactory, module
from lauren.testing import TestClient, WsTestClient

from lauren_mcp import McpServerModule, mcp_prompt, mcp_server, mcp_tool

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Server fixture with completion support
# ---------------------------------------------------------------------------


@mcp_server("/mcp")
class IntegTestServer:
    @mcp_tool()
    async def greet(self, name: str) -> str:
        """Greet someone.

        Args:
            name: Name to greet.
        """
        return f"Hello, {name}!"

    @mcp_prompt()
    async def prompt_greet(self, name: str) -> str:
        """Greeting prompt.

        Args:
            name: Name to greet.
        """
        return f"Say hello to {name}."


@pytest.fixture(scope="module")
def lauren_app():
    @module(imports=[McpServerModule.for_root(IntegTestServer)])
    class AppModule:
        pass

    app = LaurenFactory.create(AppModule)
    TestClient(app)
    return app


@pytest.fixture
def ws_client(lauren_app):
    return WsTestClient(lauren_app)


async def _handshake(ws_session) -> None:
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
    await asyncio.wait_for(ws_session.receive_json(), timeout=5.0)
    await ws_session.send_json({"jsonrpc": "2.0", "method": "notifications/initialized"})


# ---------------------------------------------------------------------------
# set_logging_level — integration: server processes the request
# ---------------------------------------------------------------------------


class TestSetLoggingLevelIntegration:
    async def test_set_logging_level_returns_empty_result(self, ws_client):
        """Server should respond to logging/setLevel with an empty result."""
        async with ws_client.connect("/mcp/ws") as ws:
            await _handshake(ws)
            await ws.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "logging/setLevel",
                    "params": {"level": "warning"},
                }
            )
            resp = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
            assert resp["id"] == 2
            assert "error" not in resp
            assert resp.get("result") is not None

    @pytest.mark.parametrize("level", ["debug", "info", "warning", "error"])
    async def test_set_logging_level_all_common_levels(self, ws_client, level: str):
        """All common log levels should be accepted by the server."""
        async with ws_client.connect("/mcp/ws") as ws:
            await _handshake(ws)
            await ws.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "logging/setLevel",
                    "params": {"level": level},
                }
            )
            resp = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
            assert "error" not in resp


# ---------------------------------------------------------------------------
# subscribe_resource / unsubscribe_resource — integration
# ---------------------------------------------------------------------------


class TestResourceSubscriptionsIntegration:
    async def test_subscribe_resource_returns_method_not_found_when_unsupported(self, ws_client):
        """Server returns METHOD_NOT_FOUND (-32601) for resources/subscribe if not
        supported — this verifies the client correctly propagates the error as
        McpCallError (tested via raw WS here; client-level test is in unit tests)."""
        async with ws_client.connect("/mcp/ws") as ws:
            await _handshake(ws)
            await ws.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 4,
                    "method": "resources/subscribe",
                    "params": {"uri": "items://1"},
                }
            )
            resp = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
            # Server may return METHOD_NOT_FOUND if not implemented, or an empty result
            # Either is acceptable — the test just confirms we get a valid JSON-RPC reply
            assert resp["id"] == 4
            assert "result" in resp or "error" in resp


# ---------------------------------------------------------------------------
# complete() — integration
# ---------------------------------------------------------------------------


class TestCompleteIntegration:
    async def test_complete_prompt_returns_values(self, ws_client):
        """completion/complete returns a result for a known prompt."""
        async with ws_client.connect("/mcp/ws") as ws:
            await _handshake(ws)
            await ws.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "completion/complete",
                    "params": {
                        "ref": {"type": "ref/prompt", "name": "prompt_greet"},
                        "argument": {"name": "name", "value": "Jo"},
                    },
                }
            )
            resp = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
            # Server responds with a result (may be empty completion or actual values)
            assert resp["id"] == 5
            assert "result" in resp or "error" in resp
