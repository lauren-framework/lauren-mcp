"""Integration tests for completion/complete handler."""

from __future__ import annotations

import asyncio

import pytest
from lauren import LaurenFactory, module
from lauren.testing import TestClient, WsTestClient

from lauren_mcp import McpServerModule
from lauren_mcp.server._decorators import mcp_completion, mcp_prompt, mcp_resource, mcp_server

# ---------------------------------------------------------------------------
# Server under test
# ---------------------------------------------------------------------------

CITIES = ["Amsterdam", "Athens", "Berlin", "Brussels", "Budapest"]
LANGS = ["python", "go", "rust"]


@mcp_server("/mcp")
class _CompServer:
    @mcp_prompt()
    async def weather(self, city: str) -> str:
        """Get weather for a city."""
        return f"Weather in {city}: sunny"

    @mcp_completion("weather", "city")
    async def complete_city(self, partial: str) -> list[str]:
        return [c for c in CITIES if c.lower().startswith(partial.lower())]

    @mcp_resource("code://{lang}/hello", name="hello_in_lang")
    async def hello_in_lang(self, lang: str) -> str:
        return f"print('hello') # {lang}"

    @mcp_completion("code://{lang}/hello", "lang", ref_type="ref/resource")
    async def complete_lang(self, partial: str) -> list[str]:
        return [la for la in LANGS if la.startswith(partial)]


@module(imports=[McpServerModule.for_root(_CompServer, transport="ws")])
class _CompApp:
    pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def app():
    a = LaurenFactory.create(_CompApp)
    TestClient(a)  # trigger @post_construct hooks
    return a


@pytest.fixture
def ws(app):
    return WsTestClient(app)


# ---------------------------------------------------------------------------
# Helper: WS handshake
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
    await asyncio.wait_for(conn.receive_json(), timeout=3.0)
    await conn.send_json({"jsonrpc": "2.0", "method": "notifications/initialized"})


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_complete_prompt_argument_partial(ws) -> None:
    async with ws.connect("/mcp/ws") as conn:
        await _handshake(conn)
        await conn.send_json(
            {
                "jsonrpc": "2.0",
                "method": "completion/complete",
                "id": 2,
                "params": {
                    "ref": {"type": "ref/prompt", "name": "weather"},
                    "argument": {"name": "city", "value": "Am"},
                },
            }
        )
        resp = await asyncio.wait_for(conn.receive_json(), timeout=3.0)
        assert resp.get("error") is None
        values = resp["result"]["completion"]["values"]
        assert "Amsterdam" in values
        assert "Berlin" not in values


async def test_complete_prompt_argument_empty(ws) -> None:
    async with ws.connect("/mcp/ws") as conn:
        await _handshake(conn)
        await conn.send_json(
            {
                "jsonrpc": "2.0",
                "method": "completion/complete",
                "id": 2,
                "params": {
                    "ref": {"type": "ref/prompt", "name": "weather"},
                    "argument": {"name": "city", "value": ""},
                },
            }
        )
        resp = await asyncio.wait_for(conn.receive_json(), timeout=3.0)
        values = resp["result"]["completion"]["values"]
        assert len(values) == len(CITIES)


async def test_complete_unknown_prompt_returns_empty(ws) -> None:
    async with ws.connect("/mcp/ws") as conn:
        await _handshake(conn)
        await conn.send_json(
            {
                "jsonrpc": "2.0",
                "method": "completion/complete",
                "id": 2,
                "params": {
                    "ref": {"type": "ref/prompt", "name": "nonexistent"},
                    "argument": {"name": "city", "value": ""},
                },
            }
        )
        resp = await asyncio.wait_for(conn.receive_json(), timeout=3.0)
        assert resp.get("error") is None
        values = resp["result"]["completion"]["values"]
        assert values == []


async def test_complete_resource_template_argument(ws) -> None:
    async with ws.connect("/mcp/ws") as conn:
        await _handshake(conn)
        await conn.send_json(
            {
                "jsonrpc": "2.0",
                "method": "completion/complete",
                "id": 2,
                "params": {
                    "ref": {"type": "ref/resource", "uri": "code://{lang}/hello"},
                    "argument": {"name": "lang", "value": "p"},
                },
            }
        )
        resp = await asyncio.wait_for(conn.receive_json(), timeout=3.0)
        assert resp.get("error") is None
        values = resp["result"]["completion"]["values"]
        assert "python" in values


async def test_server_capabilities_include_completions(ws) -> None:
    """Server with @mcp_completion methods advertises completions capability."""
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
        caps = resp["result"]["capabilities"]
        assert "completions" in caps
