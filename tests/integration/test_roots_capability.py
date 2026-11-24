"""Integration coverage for MCP roots capability negotiation and changes."""

from __future__ import annotations

import asyncio

import pytest
from lauren import LaurenFactory, module
from lauren.testing import TestClient, WsTestClient

from lauren_mcp import McpServerModule, McpToolContext, mcp_server, mcp_tool

pytestmark = pytest.mark.asyncio


@mcp_server("/roots")
class RootsServer:
    @mcp_tool()
    async def show_roots(self, ctx: McpToolContext) -> list[dict]:
        roots = await ctx.list_roots()
        return [{"uri": root.uri, "name": root.name} for root in roots]


@pytest.fixture(scope="module")
def roots_app():
    @module(imports=[McpServerModule.for_root(RootsServer)])
    class AppModule:
        pass

    app = LaurenFactory.create(AppModule)
    TestClient(app)
    return app


async def _handshake(ws, capabilities: dict) -> None:
    await ws.send_json(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": capabilities,
                "clientInfo": {"name": "roots-test", "version": "1.0.0"},
            },
        }
    )
    await asyncio.wait_for(ws.receive_json(), timeout=5.0)
    await ws.send_json({"jsonrpc": "2.0", "method": "notifications/initialized"})


class TestRootsCapabilityIntegration:
    async def test_server_lists_roots_and_accepts_change_notification(self, roots_app):
        ws_client = WsTestClient(roots_app)
        async with ws_client.connect("/roots/ws") as ws:
            await _handshake(ws, {"roots": {"listChanged": True}})
            await ws.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "show_roots", "arguments": {}},
                }
            )

            server_request = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
            assert server_request["method"] == "roots/list"
            assert server_request["params"] == {}
            await ws.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": server_request["id"],
                    "result": {
                        "roots": [
                            {"uri": "file:///workspace", "name": "Workspace"},
                            {"uri": "file:///data"},
                        ]
                    },
                }
            )
            response = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
            roots = response["result"]["structuredContent"]
            assert roots == [
                {"uri": "file:///workspace", "name": "Workspace"},
                {"uri": "file:///data", "name": None},
            ]

            # The client notifies the server after its dynamic root set changes.
            await ws.send_json(
                {"jsonrpc": "2.0", "method": "notifications/roots/list_changed"}
            )
            await ws.send_json({"jsonrpc": "2.0", "id": 3, "method": "ping"})
            ping = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
            assert ping["id"] == 3
            assert ping["result"] == {}
