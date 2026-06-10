"""Integration tests: Depends[callable] injection in a real Lauren app over WS."""

# No 'from __future__ import annotations' — needed for type hints to be evaluated
# at class definition time so typing.get_type_hints() resolves them correctly.

import asyncio
import json

import pytest
from lauren import Depends, LaurenFactory, module
from lauren.testing import TestClient, WsTestClient

from lauren_mcp import McpServerModule, mcp_server, mcp_tool

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Dependency providers
# ---------------------------------------------------------------------------


_db_calls = 0
_cleanup_log: list[str] = []


def _sync_db_factory():
    global _db_calls
    _db_calls += 1
    return {"id": _db_calls, "type": "sync"}


async def _async_token_factory():
    return "async_tok"


async def _gen_db_factory():
    """Async generator that yields a DB stub and logs cleanup."""
    _cleanup_log.append("open")
    try:
        yield {"type": "gen"}
    finally:
        _cleanup_log.append("close")


# ---------------------------------------------------------------------------
# Server under test
# ---------------------------------------------------------------------------


@mcp_server("/mcp")
class DependsServer:
    @mcp_tool()
    async def sync_tool(self, limit: int, db: Depends[_sync_db_factory]) -> dict:
        """Tool using a sync Depends factory."""
        return {"limit": limit, "db_type": db["type"], "db_id": db["id"]}

    @mcp_tool()
    async def async_tool(self, token: Depends[_async_token_factory]) -> str:
        """Tool using an async Depends factory."""
        return token

    @mcp_tool()
    async def gen_tool(self, db: Depends[_gen_db_factory]) -> dict:
        """Tool using an async generator Depends factory."""
        return {"db_type": db["type"]}

    @mcp_tool()
    async def memo_tool(
        self,
        a: Depends[_sync_db_factory],
        b: Depends[_sync_db_factory],
    ) -> dict:
        """Two Depends[same_factory] params — should call factory once."""
        return {"same": a is b}


# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def lauren_app():
    @module(imports=[McpServerModule.for_root(DependsServer)])
    class AppModule:
        pass

    app = LaurenFactory.create(AppModule)
    TestClient(app)
    return app


@pytest.fixture
def ws(lauren_app):
    return WsTestClient(lauren_app)


# ---------------------------------------------------------------------------
# Handshake helper
# ---------------------------------------------------------------------------


async def _handshake(conn) -> dict:
    await conn.send_json(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"},
            },
        }
    )
    resp = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
    await conn.send_json({"jsonrpc": "2.0", "method": "notifications/initialized"})
    return resp


async def _call_tool(conn, name: str, arguments: dict | None = None) -> dict:
    await conn.send_json(
        {
            "jsonrpc": "2.0",
            "id": 42,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        }
    )
    return await asyncio.wait_for(conn.receive_json(), timeout=5.0)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestDependsIntegration:
    async def test_sync_factory_injected(self, ws):
        """Sync factory resolves and its return value reaches the tool body."""
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            resp = await _call_tool(conn, "sync_tool", {"limit": 5})
            assert "result" in resp, resp
            data = json.loads(resp["result"]["content"][0]["text"])
            assert data["limit"] == 5
            assert data["db_type"] == "sync"

    async def test_async_factory_injected(self, ws):
        """Async factory is awaited and its value reaches the tool body."""
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            resp = await _call_tool(conn, "async_tool")
            assert "result" in resp, resp
            assert resp["result"]["content"][0]["text"] == "async_tok"

    async def test_gen_factory_cleanup_called_after_success(self, ws):
        """Async generator cleanup runs after a successful tool call."""
        _cleanup_log.clear()
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            resp = await _call_tool(conn, "gen_tool")
            assert "result" in resp, resp
            data = json.loads(resp["result"]["content"][0]["text"])
            assert data["db_type"] == "gen"
        # Cleanup runs in finally after the handler returns
        # Give asyncio a tick to process the finally block
        await asyncio.sleep(0)
        assert "close" in _cleanup_log

    async def test_schema_omits_depends_param(self, ws):
        """tools/list must not include Depends params in inputSchema."""
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json({"jsonrpc": "2.0", "id": 10, "method": "tools/list"})
            resp = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
            tools = {t["name"]: t for t in resp["result"]["tools"]}
            assert "db" not in tools["sync_tool"]["inputSchema"].get("properties", {})
            assert "limit" in tools["sync_tool"]["inputSchema"].get("properties", {})

    async def test_call_without_depends_arg_accepted(self, ws):
        """tools/call with only public args succeeds — Depends resolved internally."""
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            # Only pass "limit" — NOT "db" (which is Depends-injected)
            resp = await _call_tool(conn, "sync_tool", {"limit": 3})
            assert "result" in resp, resp

    async def test_memoization_within_call(self, ws):
        """Same Depends factory used twice → called once; both params get same obj."""
        global _db_calls
        _db_calls = 0
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            resp = await _call_tool(conn, "memo_tool")
            assert "result" in resp, resp
            data = json.loads(resp["result"]["content"][0]["text"])
            assert data["same"] is True
            assert _db_calls == 1
