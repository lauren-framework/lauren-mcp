"""Integration tests: State[T] injection in a real Lauren app over WS."""

# No 'from __future__ import annotations' — type hints must be evaluated at class
# definition time so typing.get_type_hints() resolves them correctly.

import asyncio
import json
from dataclasses import dataclass, field

import pytest
from lauren import LaurenFactory, module
from lauren import StateExtractor as State
from lauren.testing import TestClient, WsTestClient

from lauren_mcp import McpServerModule, mcp_server, mcp_tool

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# State types used in tests
# ---------------------------------------------------------------------------


@dataclass
class Counter:
    value: int = 0


@dataclass
class AuditLog:
    entries: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Server under test
# ---------------------------------------------------------------------------


@mcp_server("/mcp")
class StateServer:
    @mcp_tool()
    async def increment(self, amount: int, counter: State[Counter]) -> dict:
        """Increment a per-call counter and return its value."""
        counter.value += amount
        counter.value += amount  # mutate twice in one call
        return {"value": counter.value}

    @mcp_tool()
    async def append_entry(self, entry: str, log: State[AuditLog]) -> dict:
        """Append an entry to the per-call audit log."""
        log.entries.append(entry)
        return {"entries": log.entries}

    @mcp_tool()
    async def two_refs(
        self,
        a: State[AuditLog],
        b: State[AuditLog],
    ) -> dict:
        """Two State[T] refs with same T — must be same instance."""
        a.entries.append("via_a")
        return {"same": a is b, "b_entries": b.entries}


# ---------------------------------------------------------------------------
# App fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def lauren_app():
    @module(imports=[McpServerModule.for_root(StateServer)])
    class AppModule:
        pass

    app = LaurenFactory.create(AppModule)
    TestClient(app)
    return app


@pytest.fixture
def ws(lauren_app):
    return WsTestClient(lauren_app)


# ---------------------------------------------------------------------------
# Helpers
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


class TestStateIntegration:
    async def test_state_mutated_within_call(self, ws):
        """Tool mutates State[Counter] twice; result reflects both mutations."""
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            resp = await _call_tool(conn, "increment", {"amount": 5})
            assert "result" in resp, resp
            data = json.loads(resp["result"]["content"][0]["text"])
            # counter.value += 5 twice → 10
            assert data["value"] == 10

    async def test_separate_calls_get_fresh_state(self, ws):
        """Two separate tool calls each get a fresh Counter()."""
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            r1 = await _call_tool(conn, "increment", {"amount": 3})
            r2 = await _call_tool(conn, "increment", {"amount": 3})
            d1 = json.loads(r1["result"]["content"][0]["text"])
            d2 = json.loads(r2["result"]["content"][0]["text"])
            # Each call starts from Counter(value=0), so both return 6
            assert d1["value"] == 6
            assert d2["value"] == 6

    async def test_two_state_refs_same_instance(self, ws):
        """Two State[AuditLog] params in same tool are the same object."""
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            resp = await _call_tool(conn, "two_refs")
            assert "result" in resp, resp
            data = json.loads(resp["result"]["content"][0]["text"])
            assert data["same"] is True
            # Mutation via 'a' is visible through 'b'
            assert "via_a" in data["b_entries"]

    async def test_schema_omits_state_param(self, ws):
        """tools/list must not include State params in inputSchema."""
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json({"jsonrpc": "2.0", "id": 10, "method": "tools/list"})
            resp = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
            tools = {t["name"]: t for t in resp["result"]["tools"]}
            assert "counter" not in tools["increment"]["inputSchema"].get("properties", {})
            assert "amount" in tools["increment"]["inputSchema"].get("properties", {})

    async def test_call_without_state_arg_succeeds(self, ws):
        """tools/call with only public args; State injected transparently."""
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            # Only pass "amount", NOT "counter"
            resp = await _call_tool(conn, "increment", {"amount": 1})
            assert "result" in resp, resp
