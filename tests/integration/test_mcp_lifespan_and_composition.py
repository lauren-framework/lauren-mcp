"""Integration tests for @mcp_lifespan and server composition (mounts)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from lauren import LaurenFactory, module
from lauren.testing import TestClient, WsTestClient

from lauren_mcp import McpServerModule, McpToolContext, mcp_server, mcp_tool
from lauren_mcp.server import mcp_lifespan

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

_lifespan_events: list[str] = []


@mcp_server("/mcp-ls")
class _LifespanServer:
    @mcp_lifespan
    async def lifespan(self):
        _lifespan_events.append("startup")
        try:
            yield {"resource": "shared-handle"}
        finally:
            _lifespan_events.append("shutdown")

    @mcp_tool()
    async def use_resource(self, ctx: McpToolContext) -> str:
        """Use the lifespan resource."""
        return str(ctx.lifespan_context.get("resource"))


async def _ws_handshake(ws: Any) -> None:
    await ws.send_text(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "0"},
                },
            }
        )
    )
    await ws.receive_text()
    await ws.send_text(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}))


async def _ws_call(ws: Any, id_: int, method: str, params: dict | None = None) -> dict:
    msg: dict[str, Any] = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        msg["params"] = params
    await ws.send_text(json.dumps(msg))
    return json.loads(await ws.receive_text())


class TestLifespan:
    async def test_lifespan_context_reaches_tool(self):
        _lifespan_events.clear()

        @module(imports=[McpServerModule.for_root(_LifespanServer, transport="ws")])
        class _App:
            pass

        app = LaurenFactory.create(_App)
        TestClient(app)
        assert "startup" in _lifespan_events

        async with WsTestClient(app).connect("/mcp-ls/ws") as ws:
            await _ws_handshake(ws)
            resp = await _ws_call(ws, 1, "tools/call", {"name": "use_resource", "arguments": {}})
        assert resp["result"]["content"][0]["text"] == "shared-handle"

    def test_decorator_rejects_non_generator(self):
        with pytest.raises(TypeError, match="async generator"):

            @mcp_lifespan
            async def not_a_generator(self):
                return {}

    def test_two_lifespans_rejected(self):
        @mcp_server("/dup")
        class TwoLifespans:
            @mcp_lifespan
            async def one(self):
                yield {}

            @mcp_lifespan
            async def two(self):
                yield {}

        with pytest.raises(TypeError, match="more than one"):
            McpServerModule.for_root(TwoLifespans)


# ---------------------------------------------------------------------------
# Composition (mounts)
# ---------------------------------------------------------------------------


@mcp_server("/mcp-main")
class _PrimaryServer:
    @mcp_tool()
    async def main_tool(self) -> str:
        """Primary tool."""
        return "from-primary"


@mcp_server("/unused")
class _SecondaryServer:
    @mcp_tool()
    async def helper(self) -> str:
        """Secondary tool."""
        return "from-secondary"


class TestComposition:
    async def test_mounted_tools_exposed_with_prefix(self):
        @module(
            imports=[
                McpServerModule.for_root(
                    _PrimaryServer,
                    transport="ws",
                    mounts=[(_SecondaryServer, "sec_")],
                )
            ]
        )
        class _App:
            pass

        app = LaurenFactory.create(_App)
        TestClient(app)

        async with WsTestClient(app).connect("/mcp-main/ws") as ws:
            await _ws_handshake(ws)
            listing = await _ws_call(ws, 1, "tools/list")
            names = {t["name"] for t in listing["result"]["tools"]}
            assert "main_tool" in names
            assert "sec_helper" in names

            call = await _ws_call(ws, 2, "tools/call", {"name": "sec_helper", "arguments": {}})
            assert call["result"]["content"][0]["text"] == "from-secondary"

            primary = await _ws_call(ws, 3, "tools/call", {"name": "main_tool", "arguments": {}})
            assert primary["result"]["content"][0]["text"] == "from-primary"
