"""Integration tests for ExecutionContext injection into MCP transport handlers.

Uses full Lauren DI: LaurenFactory.create(AppModule) + TestClient(app) +
WsTestClient(app).

Verifies that @set_metadata on the @mcp_server class flows through to
McpExecutionContext.metadata in guards applied to individual @mcp_tool methods,
via the real Lauren ExecutionContext injected into transport handlers.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from lauren import (
    LaurenFactory,
    Scope,
    injectable,
    module,
    set_metadata,
    use_guards,
)
from lauren.testing import TestClient, WsTestClient

from lauren_mcp import McpServerModule, mcp_server, mcp_tool

pytestmark = pytest.mark.asyncio(loop_scope="session")

# ---------------------------------------------------------------------------
# Shared: captured metadata collected by guards during tests
# ---------------------------------------------------------------------------

_captured: list[dict[str, Any]] = []


@injectable(scope=Scope.SINGLETON)
class MetaCapturingGuard:
    """Guard that records the metadata it sees and always allows the call."""

    async def can_activate(self, ctx: Any) -> bool:
        _captured.append(
            {
                "ec_metadata": dict(
                    getattr(getattr(ctx, "execution_context", None) or {}, "metadata", {}) or {}
                ),  # noqa: E501
                "ctx_metadata": dict(getattr(ctx, "metadata", {})),
            }
        )
        return True


# ---------------------------------------------------------------------------
# Server under test
# ---------------------------------------------------------------------------


@set_metadata("service", "mcp-integration-test")
@set_metadata("env", "test")
@mcp_server("/mcp")
class _MetaServer:
    @set_metadata("scope", "tool-level")  # per-tool metadata
    @use_guards(MetaCapturingGuard)
    @mcp_tool()
    async def guarded_tool(self) -> dict:
        """A tool guarded by MetaCapturingGuard."""
        return {"ok": True}

    @mcp_tool()
    async def unguarded_tool(self) -> dict:
        """No guard — captures nothing."""
        return {"ok": True}


@pytest.fixture(scope="session")
def meta_app():
    @module(imports=[McpServerModule.for_root(_MetaServer, transport="both")])
    class _App:
        pass

    a = LaurenFactory.create(_App)
    TestClient(a)  # trigger @post_construct
    return a


# ---------------------------------------------------------------------------
# WS helpers
# ---------------------------------------------------------------------------


async def _handshake(conn: Any) -> None:
    await conn.send_json(
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
    await conn.receive_json()
    await conn.send_json({"jsonrpc": "2.0", "method": "notifications/initialized"})


async def _call(conn: Any, name: str, req_id: int = 1) -> dict:
    await conn.send_json(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": {}},
        }
    )
    while True:
        msg = await conn.receive_json()
        if msg.get("id") == req_id:
            return msg


# ---------------------------------------------------------------------------
# Tests: WS transport
# ---------------------------------------------------------------------------


class TestWsExecutionContextInjection:
    """Guard receives McpExecutionContext; metadata has @set_metadata values."""

    def setup_method(self):
        _captured.clear()

    async def test_guard_sees_server_set_metadata_via_ctx_metadata(self, meta_app):
        """McpExecutionContext.metadata has service/env from @set_metadata."""
        async with WsTestClient(meta_app).connect("/mcp/ws") as conn:
            await _handshake(conn)
            resp = await _call(conn, "guarded_tool")

        assert resp.get("result", {}).get("isError") is not True
        assert len(_captured) >= 1
        last = _captured[-1]
        # ctx.metadata (McpExecutionContext.metadata) has the @set_metadata values
        assert last["ctx_metadata"].get("service") == "mcp-integration-test"
        assert last["ctx_metadata"].get("env") == "test"

    async def test_per_tool_metadata_present_in_guard(self, meta_app):
        """Per-tool @set_metadata is in ctx.metadata with highest priority."""
        async with WsTestClient(meta_app).connect("/mcp/ws") as conn:
            await _handshake(conn)
            await _call(conn, "guarded_tool")

        last = _captured[-1]
        assert last["ctx_metadata"].get("scope") == "tool-level"

    async def test_ws_execution_context_is_none(self, meta_app):
        """For WS, ec_metadata is empty dict (no per-frame HTTP request)."""
        async with WsTestClient(meta_app).connect("/mcp/ws") as conn:
            await _handshake(conn)
            await _call(conn, "guarded_tool")

        last = _captured[-1]
        # WS has no per-frame EC; ec_metadata comes from None EC → empty dict
        assert last["ec_metadata"] == {}

    async def test_unguarded_tool_captures_nothing(self, meta_app):
        """Guard only fires for tools it is applied to."""
        _captured.clear()
        async with WsTestClient(meta_app).connect("/mcp/ws") as conn:
            await _handshake(conn)
            await _call(conn, "unguarded_tool")

        assert _captured == []

    async def test_tools_list_unchanged_by_guard(self, meta_app):
        """Guard on @mcp_tool does not affect tools/list schema."""
        async with WsTestClient(meta_app).connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json({"jsonrpc": "2.0", "id": 99, "method": "tools/list"})
            resp = await conn.receive_json()
        tools = {t["name"] for t in resp["result"]["tools"]}
        assert "guarded_tool" in tools
        assert "unguarded_tool" in tools


# ---------------------------------------------------------------------------
# Tests: Streamable HTTP transport
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def streamable_app():
    @module(imports=[McpServerModule.for_root(_MetaServer, transport="streamable")])
    class _StreamApp:
        pass

    a = LaurenFactory.create(_StreamApp)
    TestClient(a)
    return a


def _streamable_post(client: TestClient, body: dict, session_id: str | None = None) -> Any:
    headers: dict = {"content-type": "application/json"}
    if session_id:
        headers["mcp-session-id"] = session_id
    return client.post("/mcp/", content=json.dumps(body).encode(), headers=headers)


def _streamable_init(client: TestClient) -> str:
    resp = _streamable_post(
        client,
        {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "0"},
            },
        },
    )
    session_id = resp.header("mcp-session-id")
    assert session_id, "initialize must return mcp-session-id"
    _streamable_post(
        client, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session_id=session_id
    )
    return session_id


class TestStreamableHttpExecutionContextInjection:
    """Streamable HTTP injects a real ExecutionContext (per-POST request)."""

    def setup_method(self):
        _captured.clear()

    async def test_guard_sees_server_metadata_via_ctx_metadata(self, streamable_app):
        client = TestClient(streamable_app)
        sid = _streamable_init(client)
        _streamable_post(
            client,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": "guarded_tool", "arguments": {}},
            },
            session_id=sid,
        )

        assert len(_captured) >= 1
        last = _captured[-1]
        assert last["ctx_metadata"].get("service") == "mcp-integration-test"

    async def test_ec_metadata_populated_from_real_ec(self, streamable_app):
        """For Streamable HTTP, ec_metadata has @set_metadata via real EC."""
        client = TestClient(streamable_app)
        sid = _streamable_init(client)
        _streamable_post(
            client,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "guarded_tool", "arguments": {}},
            },
            session_id=sid,
        )

        last = _captured[-1]
        # Streamable HTTP provides a real EC; ec_metadata should have @set_metadata values
        assert last["ec_metadata"].get("service") == "mcp-integration-test"

    async def test_per_tool_metadata_in_guard(self, streamable_app):
        client = TestClient(streamable_app)
        sid = _streamable_init(client)
        _streamable_post(
            client,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "guarded_tool", "arguments": {}},
            },
            session_id=sid,
        )

        last = _captured[-1]
        assert last["ctx_metadata"].get("scope") == "tool-level"
