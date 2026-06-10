"""Integration tests: BackgroundTasks injection on @mcp_tool via WebSocket."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

# Skip if lauren not installed
lauren = pytest.importorskip("lauren", reason="lauren not installed")

from lauren import BackgroundTasks, LaurenFactory, module  # noqa: E402
from lauren.testing import TestClient, WsTestClient  # noqa: E402

from lauren_mcp import McpServerModule, mcp_resource, mcp_server, mcp_tool  # noqa: E402

pytestmark = pytest.mark.asyncio

# Shared side-effects list (reset per-test via autouse fixture)
_side_effects: list[Any] = []


# ---------------------------------------------------------------------------
# Server under test
# ---------------------------------------------------------------------------


@mcp_server("/mcp")
class BgTaskServer:
    @mcp_tool()
    async def submit(self, order_id: str, tasks: BackgroundTasks) -> dict:
        tasks.add_task(lambda: _side_effects.append(f"submitted:{order_id}"))
        return {"status": "submitted", "order_id": order_id}

    @mcp_tool()
    async def failing_tool(self, tasks: BackgroundTasks) -> str:
        tasks.add_task(lambda: _side_effects.append("task_ran"))
        raise ValueError("tool failed deliberately")

    @mcp_tool()
    async def no_bg_tool(self, name: str) -> str:
        return f"hi {name}"

    @mcp_resource("/bg-items/{item_id}")
    async def bg_item(self, item_id: str, tasks: BackgroundTasks) -> str:
        tasks.add_task(lambda: _side_effects.append(f"read:{item_id}"))
        return f"item-{item_id}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_side_effects():
    _side_effects.clear()
    yield
    _side_effects.clear()


@pytest.fixture
def lauren_app():
    @module(imports=[McpServerModule.for_root(BgTaskServer)])
    class AppModule:
        pass

    a = LaurenFactory.create(AppModule)
    TestClient(a)  # trigger @post_construct
    return a


@pytest.fixture
def ws(lauren_app):
    return WsTestClient(lauren_app)


# ---------------------------------------------------------------------------
# Handshake helper
# ---------------------------------------------------------------------------


async def _handshake(conn) -> None:
    await conn.send_json(
        {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0.0.1"},
            },
        }
    )
    await asyncio.wait_for(conn.receive_json(), timeout=5.0)
    await conn.send_json({"jsonrpc": "2.0", "method": "notifications/initialized"})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestBgTaskIntegration:
    async def test_ws_tool_bg_task_side_effect(self, ws) -> None:
        """Background task appends to side_effects after tools/call."""
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "submit", "arguments": {"order_id": "ord-1"}},
                }
            )
            resp = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
        assert "result" in resp
        # Allow background task to drain
        await asyncio.sleep(0)
        await asyncio.sleep(0.05)
        assert any("submitted:ord-1" in s for s in _side_effects)

    async def test_ws_tool_result_correct_with_bg_task(self, ws) -> None:
        """Tool returns correct result dict; background task is separate."""
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "submit", "arguments": {"order_id": "ord-2"}},
                }
            )
            resp = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
        assert "result" in resp
        content_text = resp["result"]["content"][0]["text"]
        data = json.loads(content_text)
        assert data["status"] == "submitted"
        assert data["order_id"] == "ord-2"

    async def test_ws_tool_bg_task_excluded_from_tools_list(self, ws) -> None:
        """tools/list contains no 'tasks' parameter in inputSchema."""
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            resp = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
        assert "result" in resp
        tools = {t["name"]: t for t in resp["result"]["tools"]}
        assert "submit" in tools
        assert "tasks" not in tools["submit"]["inputSchema"]["properties"]
        assert "tasks" not in tools["submit"]["inputSchema"].get("required", [])

    async def test_ws_tool_only_public_args_sent(self, ws) -> None:
        """Client sends only non-BackgroundTasks args; server injects tasks automatically."""
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "submit", "arguments": {"order_id": "ord-3"}},
                }
            )
            resp = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
        # If the tool received tasks correctly, it returned without error
        assert "result" in resp

    async def test_ws_tool_raises_bg_tasks_still_run(self, ws) -> None:
        """Tool raises; tools/call returns error; tasks added before raise still run."""
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "failing_tool", "arguments": {}},
                }
            )
            resp = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
        # Tool raised → error response
        assert "error" in resp
        # Background task added before the raise should still run
        await asyncio.sleep(0)
        await asyncio.sleep(0.05)
        assert "task_ran" in _side_effects

    async def test_resource_bg_task_side_effect(self, ws) -> None:
        """@mcp_resource with BackgroundTasks: side-effect runs after resources/read."""
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "resources/read",
                    "params": {"uri": "/bg-items/item-42"},
                }
            )
            resp = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
        assert "result" in resp
        await asyncio.sleep(0)
        await asyncio.sleep(0.05)
        assert any("read:item-42" in s for s in _side_effects)
