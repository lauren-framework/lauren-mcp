"""Integration tests for ToolStream over WS transport."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Any

import pytest
from lauren import LaurenFactory, module
from lauren.testing import TestClient, WsTestClient

from lauren_mcp import McpServerModule, McpToolContext, mcp_server, mcp_tool
from lauren_mcp._types import ToolStream

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Server under test
# ---------------------------------------------------------------------------


@mcp_server("/mcp-stream")
class StreamServer:
    @mcp_tool()
    async def count(self, n: int, ctx: McpToolContext) -> ToolStream:  # type: ignore[return]
        """Count to n, streaming each number.

        Args:
            n: How many numbers to count.
            ctx: Tool context for progress notifications.
        """

        async def gen() -> AsyncGenerator[str, None]:
            for i in range(n):
                yield str(i)

        return ToolStream(gen(), total=n)

    @mcp_tool()
    async def add_numbers(self, items: str) -> ToolStream:  # type: ignore[return]
        """Sum numbers provided as space-separated string.

        Args:
            items: Space-separated integers to sum.
        """

        async def gen() -> AsyncGenerator[int, None]:
            for x in items.split():
                yield int(x)

        return ToolStream(gen(), accumulate=lambda chunks: sum(chunks))

    @mcp_tool()
    async def count_no_ctx(self, n: int) -> ToolStream:  # type: ignore[return]
        """Count without ctx param (no context injection).

        Args:
            n: How many numbers to count.
        """

        async def gen() -> AsyncGenerator[str, None]:
            for i in range(n):
                yield str(i)

        return ToolStream(gen(), total=n)

    @mcp_tool()
    async def empty_stream(self) -> ToolStream:  # type: ignore[return]
        """Return an empty ToolStream."""

        async def gen() -> AsyncGenerator[str, None]:
            return
            yield  # make it an async generator

        return ToolStream(gen())


# ---------------------------------------------------------------------------
# Lauren app fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def stream_app():
    @module(imports=[McpServerModule.for_root(StreamServer)])
    class AppModule:
        pass

    app = LaurenFactory.create(AppModule)
    TestClient(app)  # trigger @post_construct
    return app


@pytest.fixture
def ws(stream_app):
    return WsTestClient(stream_app)


# ---------------------------------------------------------------------------
# Helper: perform the MCP handshake
# ---------------------------------------------------------------------------


async def _handshake(conn) -> None:
    await conn.send_json(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0.0"},
            },
        }
    )
    await asyncio.wait_for(conn.receive_json(), timeout=5.0)
    await conn.send_json({"jsonrpc": "2.0", "method": "notifications/initialized"})


async def _call_tool_with_progress(
    conn, name: str, arguments: dict, progress_token: str | None = None, req_id: int = 10
) -> tuple[dict, list[dict]]:
    """Send tools/call and collect progress notifications + final result."""
    params: dict[str, Any] = {"name": name, "arguments": arguments}
    if progress_token is not None:
        params["_meta"] = {"progressToken": progress_token}

    await conn.send_json({"jsonrpc": "2.0", "id": req_id, "method": "tools/call", "params": params})

    notifications: list[dict] = []
    final: dict | None = None

    # Collect messages until we get the tools/call response
    for _ in range(50):  # safety limit
        msg = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
        if "id" in msg:
            # This is the response
            final = msg
            break
        elif msg.get("method") == "notifications/progress":
            notifications.append(msg)

    assert final is not None, "No tools/call response received"
    return final, notifications


# ---------------------------------------------------------------------------
# Tests: str chunks, progress notifications
# ---------------------------------------------------------------------------


class TestWsToolStreamStrChunks:
    async def test_str_chunks_joined_result(self, ws) -> None:
        """count(3) → joined '012' as final result."""
        async with ws.connect("/mcp-stream/ws") as conn:
            await _handshake(conn)
            resp, _ = await _call_tool_with_progress(conn, "count", {"n": 3}, progress_token="tok")
            assert "result" in resp
            assert resp["result"]["content"][0]["text"] == "012"

    async def test_str_chunks_progress_notifications_count(self, ws) -> None:
        """count(3) with progressToken → 3 notifications."""
        async with ws.connect("/mcp-stream/ws") as conn:
            await _handshake(conn)
            _, notifications = await _call_tool_with_progress(
                conn, "count", {"n": 3}, progress_token="tok"
            )
            assert len(notifications) == 3

    async def test_str_chunks_progress_token_in_notifications(self, ws) -> None:
        """Each notification carries the progressToken."""
        async with ws.connect("/mcp-stream/ws") as conn:
            await _handshake(conn)
            _, notifications = await _call_tool_with_progress(
                conn, "count", {"n": 2}, progress_token="my-token"
            )
            for n in notifications:
                assert n["params"]["progressToken"] == "my-token"

    async def test_str_chunks_progress_order(self, ws) -> None:
        """Progress notifications arrive in order (0, 1, 2)."""
        async with ws.connect("/mcp-stream/ws") as conn:
            await _handshake(conn)
            _, notifications = await _call_tool_with_progress(
                conn, "count", {"n": 3}, progress_token="tok"
            )
            for i, n in enumerate(notifications):
                assert n["params"]["progress"] == i

    async def test_total_in_progress_notifications(self, ws) -> None:
        """ToolStream with total=n → each notification has total=n."""
        async with ws.connect("/mcp-stream/ws") as conn:
            await _handshake(conn)
            _, notifications = await _call_tool_with_progress(
                conn, "count", {"n": 4}, progress_token="tok"
            )
            for n in notifications:
                assert n["params"]["total"] == 4


class TestWsToolStreamNoProgressToken:
    async def test_no_progress_token_no_notifications(self, ws) -> None:
        """Without progressToken: no notifications, tool still returns correct result."""
        async with ws.connect("/mcp-stream/ws") as conn:
            await _handshake(conn)
            resp, notifications = await _call_tool_with_progress(conn, "count", {"n": 3})
            assert notifications == []
            assert resp["result"]["content"][0]["text"] == "012"

    async def test_no_progress_token_result_correct(self, ws) -> None:
        """Without progressToken: accumulated result is still correct."""
        async with ws.connect("/mcp-stream/ws") as conn:
            await _handshake(conn)
            resp, _ = await _call_tool_with_progress(conn, "count", {"n": 5})
            assert resp["result"]["content"][0]["text"] == "01234"


class TestWsToolStreamCustomAccumulate:
    async def test_custom_accumulate_sum(self, ws) -> None:
        """accumulate=sum: final result is sum of yielded ints."""
        async with ws.connect("/mcp-stream/ws") as conn:
            await _handshake(conn)
            resp, _ = await _call_tool_with_progress(
                conn, "add_numbers", {"items": "1 2 3 4"}, progress_token="tok"
            )
            assert resp["result"]["content"][0]["text"] == "10"


class TestWsToolStreamEmpty:
    async def test_empty_generator_returns_none_text(self, ws) -> None:
        """Empty generator → final=None, no notifications."""
        async with ws.connect("/mcp-stream/ws") as conn:
            await _handshake(conn)
            resp, notifications = await _call_tool_with_progress(
                conn, "empty_stream", {}, progress_token="tok"
            )
            assert notifications == []
            assert resp["result"]["content"][0]["text"] == "None"


class TestWsToolStreamWithoutCtxParam:
    async def test_no_ctx_param_with_progress_token_sends_notifications(self, ws) -> None:
        """Tool without ctx param + progressToken → notifications still sent."""
        async with ws.connect("/mcp-stream/ws") as conn:
            await _handshake(conn)
            resp, notifications = await _call_tool_with_progress(
                conn, "count_no_ctx", {"n": 2}, progress_token="no-ctx-tok"
            )
            assert len(notifications) == 2
            assert resp["result"]["content"][0]["text"] == "01"

    async def test_no_ctx_param_without_progress_token(self, ws) -> None:
        """Tool without ctx param, no progressToken → correct result, no crash."""
        async with ws.connect("/mcp-stream/ws") as conn:
            await _handshake(conn)
            resp, notifications = await _call_tool_with_progress(conn, "count_no_ctx", {"n": 3})
            assert notifications == []
            assert resp["result"]["content"][0]["text"] == "012"


class TestToolStreamSchema:
    async def test_tools_list_count_schema_no_stream_params(self, ws) -> None:
        """tools/list for 'count' only shows 'n' (no ToolStream params)."""
        async with ws.connect("/mcp-stream/ws") as conn:
            await _handshake(conn)
            await conn.send_json({"jsonrpc": "2.0", "id": 20, "method": "tools/list"})
            resp = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
            tools = {t["name"]: t for t in resp["result"]["tools"]}
            count_schema = tools["count"]["inputSchema"]
            props = count_schema.get("properties", {})
            # 'n' should be there; 'ctx' and 'ToolStream' should NOT be
            assert "n" in props
            assert "ctx" not in props
            assert "stream" not in json.dumps(props).lower().replace("n", "")
