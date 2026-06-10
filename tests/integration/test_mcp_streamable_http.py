"""Integration tests for the Streamable HTTP transport (MCP 2025-03-26)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from lauren import LaurenFactory, module
from lauren.testing import TestClient

from lauren_mcp import McpServerModule, mcp_server, mcp_tool

pytestmark = pytest.mark.asyncio

_SESSION_HEADER = "mcp-session-id"


@mcp_server("/mcp")
class _CalcServer:
    @mcp_tool()
    async def add(self, a: int, b: int) -> int:
        """Add two numbers."""
        return a + b


@pytest.fixture(scope="module")
def app():
    @module(imports=[McpServerModule.for_root(_CalcServer, transport="streamable")])
    class _App:
        pass

    a = LaurenFactory.create(_App)
    TestClient(a)
    return a


def _rpc(client: TestClient, body: dict[str, Any], **headers: str) -> Any:
    return client.post(
        "/mcp/",
        content=json.dumps(body).encode(),
        headers={"content-type": "application/json", **headers},
    )


def _initialize(client: TestClient) -> tuple[str, dict[str, Any]]:
    resp = _rpc(
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
    assert resp.status_code == 200
    session_id = resp.header(_SESSION_HEADER)
    assert session_id
    payload = resp.json()
    # Complete the handshake.
    notif = _rpc(
        client,
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        **{_SESSION_HEADER: session_id},
    )
    assert notif.status_code == 202
    return session_id, payload


class TestInitialize:
    async def test_initialize_returns_session_header_and_version(self, app):
        client = TestClient(app)
        session_id, payload = _initialize(client)
        assert payload["result"]["protocolVersion"] == "2025-03-26"
        assert "tools" in payload["result"]["capabilities"]

    async def test_each_initialize_creates_distinct_session(self, app):
        client = TestClient(app)
        s1, _ = _initialize(client)
        s2, _ = _initialize(client)
        assert s1 != s2


class TestPostDispatch:
    async def test_request_without_session_is_rejected(self, app):
        client = TestClient(app)
        resp = _rpc(client, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert resp.status_code == 400

    async def test_unknown_session_is_404(self, app):
        client = TestClient(app)
        resp = _rpc(
            client,
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            **{_SESSION_HEADER: "bogus"},
        )
        assert resp.status_code == 404

    async def test_tools_call_returns_direct_json(self, app):
        client = TestClient(app)
        session_id, _ = _initialize(client)
        resp = _rpc(
            client,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "add", "arguments": {"a": 2, "b": 3}},
            },
            **{_SESSION_HEADER: session_id},
        )
        assert resp.status_code == 200
        assert "application/json" in (resp.header("content-type") or "")
        payload = resp.json()
        assert payload["result"]["content"][0]["text"] == "5"
        assert payload["result"]["isError"] is False

    async def test_parse_error_returns_400(self, app):
        client = TestClient(app)
        resp = client.post(
            "/mcp/",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 400
        assert resp.json()["error"]["code"] == -32700


class TestSseResponseMode:
    async def test_accept_sse_yields_event_stream(self, app):
        client = TestClient(app)
        session_id, _ = _initialize(client)
        resp = _rpc(
            client,
            {"jsonrpc": "2.0", "id": 5, "method": "tools/list"},
            **{_SESSION_HEADER: session_id, "accept": "text/event-stream"},
        )
        assert resp.status_code == 200
        body = resp.text
        assert "data:" in body
        # The final event carries the JSON-RPC response.
        data_lines = [line[5:].strip() for line in body.splitlines() if line.startswith("data:")]
        final = json.loads(data_lines[-1])
        names = [t["name"] for t in final["result"]["tools"]]
        assert "add" in names


class TestSessionTeardown:
    async def test_delete_removes_session(self, app):
        client = TestClient(app)
        session_id, _ = _initialize(client)
        resp = client.delete("/mcp/", headers={_SESSION_HEADER: session_id})
        assert resp.status_code == 204
        # Session is gone afterwards.
        resp = _rpc(
            client,
            {"jsonrpc": "2.0", "id": 9, "method": "tools/list"},
            **{_SESSION_HEADER: session_id},
        )
        assert resp.status_code == 404
