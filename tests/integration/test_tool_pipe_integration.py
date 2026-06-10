"""Integration tests: pipe/FieldDescriptor validation on @mcp_tool via WebSocket."""

from __future__ import annotations

import asyncio
from typing import Annotated

import pytest

# Skip if lauren is not installed
lauren = pytest.importorskip("lauren", reason="lauren not installed")

from lauren import LaurenFactory, QueryField, module, pipe  # noqa: E402  # noqa: E402
from lauren.exceptions import ExtractorFieldError  # noqa: E402
from lauren.extractors import PipeContext  # noqa: E402
from lauren.testing import TestClient, WsTestClient  # noqa: E402

from lauren_mcp import McpServerModule, mcp_server, mcp_tool  # noqa: E402

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Pipe helpers
# ---------------------------------------------------------------------------


@pipe()
def ensure_positive(v: int, ctx: PipeContext) -> int:
    if v <= 0:
        raise ExtractorFieldError(f"{ctx.name} must be positive")
    return v


@pipe()
def to_upper(v: str) -> str:
    return v.upper()


@pipe()
def double_val(v: int) -> int:
    return v * 2


@pipe()
async def async_upper(v: str) -> str:
    return v.upper() + "!"


# ---------------------------------------------------------------------------
# Server under test
# ---------------------------------------------------------------------------


@mcp_server("/mcp")
class PipeTestServer:
    @mcp_tool()
    async def order(self, qty: Annotated[int, QueryField(ge=1), ensure_positive]) -> str:
        return f"qty={qty}"

    @mcp_tool()
    async def tagged(self, tag: Annotated[str, QueryField(pattern=r"^[a-z]+$")]) -> str:
        return f"tag={tag}"

    @mcp_tool()
    async def upper_name(self, name: Annotated[str, QueryField(), to_upper]) -> str:
        return f"name={name}"

    @mcp_tool()
    async def doubled(self, n: Annotated[int, QueryField(), double_val]) -> str:
        return f"n={n}"

    @mcp_tool()
    async def async_upper_name(self, name: Annotated[str, QueryField(), async_upper]) -> str:
        return f"name={name}"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def lauren_app():
    @module(imports=[McpServerModule.for_root(PipeTestServer)])
    class AppModule:
        pass

    a = LaurenFactory.create(AppModule)
    TestClient(a)  # trigger @post_construct
    return a


@pytest.fixture(scope="session")
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


class TestPipeValidationIntegration:
    async def test_ge_constraint_rejection(self, ws) -> None:
        """qty=0 fails ge=1 → INVALID_PARAMS."""
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "order", "arguments": {"qty": 0}},
                }
            )
            resp = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
        assert "error" in resp
        assert resp["error"]["code"] == -32602

    async def test_ge_constraint_success(self, ws) -> None:
        """qty=5 passes ge=1 → success."""
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "order", "arguments": {"qty": 5}},
                }
            )
            resp = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
        assert "result" in resp
        assert "qty=5" in resp["result"]["content"][0]["text"]

    async def test_pattern_rejection(self, ws) -> None:
        """tag="123" fails pattern → INVALID_PARAMS."""
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "tagged", "arguments": {"tag": "123"}},
                }
            )
            resp = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
        assert "error" in resp
        assert resp["error"]["code"] == -32602

    async def test_pattern_success(self, ws) -> None:
        """tag="abc" passes pattern → success."""
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "tagged", "arguments": {"tag": "abc"}},
                }
            )
            resp = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
        assert "result" in resp

    async def test_pipe_transforms_str(self, ws) -> None:
        """to_upper pipe transforms name → "HELLO"."""
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "upper_name", "arguments": {"name": "hello"}},
                }
            )
            resp = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
        assert "result" in resp
        assert "HELLO" in resp["result"]["content"][0]["text"]

    async def test_pipe_transforms_int(self, ws) -> None:
        """double_val pipe transforms n=5 → 10."""
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "doubled", "arguments": {"n": 5}},
                }
            )
            resp = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
        assert "result" in resp
        assert "n=10" in resp["result"]["content"][0]["text"]

    async def test_async_pipe_transforms(self, ws) -> None:
        """Async pipe transforms name → "HELLO!"."""
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": "async_upper_name", "arguments": {"name": "hello"}},
                }
            )
            resp = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
        assert "result" in resp
        assert "HELLO!" in resp["result"]["content"][0]["text"]

    async def test_tools_list_shows_minimum(self, ws) -> None:
        """tools/list includes minimum: 1 in the qty property."""
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            resp = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
        assert "result" in resp
        tools = {t["name"]: t for t in resp["result"]["tools"]}
        assert "order" in tools
        qty_schema = tools["order"]["inputSchema"]["properties"]["qty"]
        assert qty_schema.get("minimum") == 1

    async def test_tools_list_shows_pattern(self, ws) -> None:
        """tools/list includes pattern in the tag property."""
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            resp = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
        assert "result" in resp
        tools = {t["name"]: t for t in resp["result"]["tools"]}
        assert "tagged" in tools
        tag_schema = tools["tagged"]["inputSchema"]["properties"]["tag"]
        assert "pattern" in tag_schema
