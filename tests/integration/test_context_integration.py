"""Integration tests for McpToolContext changes (progress, log levels, list[str] elicitation)."""

from __future__ import annotations

import asyncio

import pytest
from lauren import LaurenFactory, module
from lauren.testing import TestClient, WsTestClient

from lauren_mcp import McpServerModule, mcp_server, mcp_tool
from lauren_mcp._server._context import McpToolContext

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Shared handshake helper
# ---------------------------------------------------------------------------


async def _handshake(conn, *, capabilities: dict | None = None) -> dict:
    caps = capabilities or {}
    await conn.send_json(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": caps,
                "clientInfo": {"name": "test-client", "version": "0"},
            },
        }
    )
    resp = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
    await conn.send_json({"jsonrpc": "2.0", "method": "notifications/initialized"})
    return resp


# ---------------------------------------------------------------------------
# 1. Progress message field — WS integration
# ---------------------------------------------------------------------------


@mcp_server("/progress-test")
class ProgressMsgServer:
    @mcp_tool()
    async def count(self, ctx: McpToolContext) -> str:
        for i in range(3):
            await ctx.report_progress(i, 3, f"step {i}")
        return "done"


@pytest.fixture(scope="module")
def progress_app_fixture():
    @module(imports=[McpServerModule.for_root(ProgressMsgServer)])
    class AppModule:
        pass

    app = LaurenFactory.create(AppModule)
    TestClient(app)
    return app


class TestProgressMessageIntegration:
    async def test_progress_messages_received(self, progress_app_fixture):
        ws_client = WsTestClient(progress_app_fixture)
        async with ws_client.connect("/progress-test/ws") as ws:
            await _handshake(ws)
            await ws.send_json(
                {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "id": 2,
                    "params": {
                        "name": "count",
                        "arguments": {},
                        "_meta": {"progressToken": "p1"},
                    },
                }
            )

            messages: list[dict] = []
            while True:
                msg = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
                if "id" in msg:
                    break
                messages.append(msg)

        progress_notifications = [
            m for m in messages if m.get("method") == "notifications/progress"
        ]
        assert len(progress_notifications) == 3
        for i, note in enumerate(progress_notifications):
            p = note["params"]
            assert p["progress"] == i
            assert p["total"] == 3
            assert p["message"] == f"step {i}"


# ---------------------------------------------------------------------------
# 2. Notice log level — WS integration
# ---------------------------------------------------------------------------


@mcp_server("/log-test")
class LogServer:
    @mcp_tool()
    async def emit_notice(self, ctx: McpToolContext) -> str:
        await ctx.info("info message")
        await ctx.notice("notice message")
        return "done"


@pytest.fixture(scope="module")
def log_app():
    @module(imports=[McpServerModule.for_root(LogServer)])
    class AppModule:
        pass

    app = LaurenFactory.create(AppModule)
    TestClient(app)
    return app


class TestLogSeverityIntegration:
    async def test_info_and_notice_emitted(self, log_app):
        """Server emits both info and notice when log level is debug (default)."""
        ws_client = WsTestClient(log_app)
        async with ws_client.connect("/log-test/ws") as ws:
            await _handshake(ws)
            await ws.send_json(
                {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "id": 2,
                    "params": {"name": "emit_notice", "arguments": {}},
                }
            )

            log_messages: list[dict] = []
            while True:
                msg = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
                if "id" in msg:
                    break
                if msg.get("method") == "notifications/message":
                    log_messages.append(msg["params"])

        levels = [m["level"] for m in log_messages]
        assert "info" in levels
        assert "notice" in levels

    async def test_info_dropped_after_set_level_notice(self, log_app):
        """After logging/setLevel = 'notice', info messages are suppressed."""
        ws_client = WsTestClient(log_app)
        async with ws_client.connect("/log-test/ws") as ws:
            await _handshake(ws)
            # Raise log level to notice
            await ws.send_json(
                {
                    "jsonrpc": "2.0",
                    "method": "logging/setLevel",
                    "id": 10,
                    "params": {"level": "notice"},
                }
            )
            set_result = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
            assert "result" in set_result

            await ws.send_json(
                {
                    "jsonrpc": "2.0",
                    "method": "tools/call",
                    "id": 2,
                    "params": {"name": "emit_notice", "arguments": {}},
                }
            )

            log_messages: list[dict] = []
            while True:
                msg = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
                if "id" in msg:
                    break
                if msg.get("method") == "notifications/message":
                    log_messages.append(msg["params"])

        levels = [m["level"] for m in log_messages]
        assert "info" not in levels  # dropped — below notice threshold
        assert "notice" in levels  # still passes


# ---------------------------------------------------------------------------
# 3. list[str] elicitation — integration
# ---------------------------------------------------------------------------


@mcp_server("/elicit-list-test")
class ElicitListServer:
    @mcp_tool()
    async def get_tags(self, ctx: McpToolContext) -> str:
        result = await ctx.elicit("Pick tags", list[str])
        if result.action != "accept":
            return "cancelled"
        tags: list[str] = (result.content or {}).get("value", [])
        return ",".join(tags)


@pytest.fixture(scope="module")
def elicit_list_app():
    @module(imports=[McpServerModule.for_root(ElicitListServer)])
    class AppModule:
        pass

    app = LaurenFactory.create(AppModule)
    TestClient(app)
    return app


class TestElicitationListStrIntegration:
    def test_list_str_elicitation_schema(self):
        """build_elicitation_schema(list[str]) produces the correct wire schema.

        This is an in-process unit-style test verifying the schema is correct
        before it would be sent in a real elicitation/create request.
        Full round-trip WS tests require concurrent message loop handling
        (server-to-client RPCs), which is covered by end-to-end tests.
        """
        from lauren_mcp._server._context import build_elicitation_schema

        schema = build_elicitation_schema(list[str])
        assert schema is not None
        assert schema["type"] == "object"
        assert schema["properties"]["value"]["type"] == "array"
        assert schema["properties"]["value"]["items"] == {"type": "string"}
        assert schema["required"] == ["value"]

    async def test_elicitation_list_str_tool_registered(self, elicit_list_app):
        """The tool that uses ctx.elicit(list[str]) is listed correctly."""
        ws_client = WsTestClient(elicit_list_app)
        async with ws_client.connect("/elicit-list-test/ws") as ws:
            await _handshake(ws, capabilities={"elicitation": {}})
            await ws.send_json(
                {
                    "jsonrpc": "2.0",
                    "method": "tools/list",
                    "id": 3,
                    "params": {},
                }
            )
            resp = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
            tools = resp["result"]["tools"]
            tool_names = [t["name"] for t in tools]
            assert "get_tags" in tool_names
