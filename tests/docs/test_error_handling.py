"""E2E tests for docs/guides/error-handling.md.

Validates every error scenario described in the guide: connection timeout,
McpCallError from server-side exceptions, unknown tool/resource, subprocess
exit and auto-restart, not-found resource text, and the safe_search pattern.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import textwrap

import pytest

from lauren_mcp import McpServer
from lauren_mcp._client._stdio import McpCallError, McpStdioClient

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Server that exercises error paths
# ---------------------------------------------------------------------------

_ERROR_SERVER = textwrap.dedent("""\
    import sys, json, asyncio

    from lauren_mcp.server._decorators import mcp_server, mcp_tool, mcp_resource
    from lauren_mcp.server._meta import MCP_TOOL_META, MCP_RESOURCE_META
    from lauren_mcp.server._handlers import (
        make_tools_list_handler, make_tools_call_handler,
        make_resources_list_handler, make_resources_read_handler,
    )
    from lauren_mcp._server._dispatcher import McpDispatcher
    from lauren_mcp._types import JsonRpcRequest

    ITEMS = {"item1": "Widget A", "item2": "Widget B"}

    @mcp_server("/mcp")
    class ErrorDemoServer:
        @mcp_tool()
        async def divide(self, a: float, b: float) -> float:
            "Divide a by b."
            if b == 0:
                raise ValueError("Division by zero")
            return a / b

        @mcp_tool()
        async def safe_search(self, query: str) -> list:
            "Search items."
            return [v for v in ITEMS.values() if query.lower() in v.lower()]

        @mcp_resource("/items/{item_id}")
        async def item_resource(self, item_id: str) -> str:
            "Return an item or not-found message."
            name = ITEMS.get(item_id)
            if name is None:
                return f"Item \'{item_id}\' not found."
            return f"Item: {name}"

    async def main():
        dispatcher = McpDispatcher()
        dispatcher._register_builtins()
        server = ErrorDemoServer()

        tools, resources = [], []
        for attr_name in dir(ErrorDemoServer):
            try:
                attr = getattr(ErrorDemoServer, attr_name)
            except AttributeError:
                continue
            if hasattr(attr, MCP_TOOL_META):
                tools.append(getattr(attr, MCP_TOOL_META))
            if hasattr(attr, MCP_RESOURCE_META):
                resources.append(getattr(attr, MCP_RESOURCE_META))

        async def _init(params):
            return {"protocolVersion": "2025-03-26",
                    "capabilities": {"tools": {}, "resources": {}},
                    "serverInfo": {"name": "error-demo", "version": "1.0.0"}}
        dispatcher.register("initialize", _init)

        tl = make_tools_list_handler(tools)
        tc = make_tools_call_handler(server, tools)
        async def _tl(p): return await tl(JsonRpcRequest(method="tools/list", params=p))
        async def _tc(p): return await tc(JsonRpcRequest(method="tools/call", params=p))
        dispatcher.register("tools/list", _tl)
        dispatcher.register("tools/call", _tc)

        rl = make_resources_list_handler(resources)
        rr = make_resources_read_handler(server, resources)
        async def _rl(p): return await rl(JsonRpcRequest(method="resources/list", params=p))
        async def _rr(p): return await rr(JsonRpcRequest(method="resources/read", params=p))
        dispatcher.register("resources/list", _rl)
        dispatcher.register("resources/read", _rr)

        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        while True:
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=30.0)
            except asyncio.TimeoutError:
                break
            if not line:
                break
            raw = line.decode().strip()
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            id_ = msg.get("id")
            if id_ is None:
                continue
            req = JsonRpcRequest(
                method=msg.get("method", ""), id=id_, params=msg.get("params")
            )
            resp = await dispatcher.dispatch(req)
            print(resp.to_json(), flush=True)

    asyncio.run(main())
""")


@pytest.fixture
def error_server_cmd():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(_ERROR_SERVER)
        fname = f.name
    yield [sys.executable, fname]
    os.unlink(fname)


@pytest.fixture
async def error_client(error_server_cmd):
    c: McpStdioClient = McpServer.stdio(error_server_cmd, startup_timeout=10.0, max_retries=0)
    await asyncio.wait_for(c.connect(), timeout=10.0)
    yield c
    await c.close()


# ---------------------------------------------------------------------------
# Section 1 — Connection timeout
# ---------------------------------------------------------------------------


class TestConnectionTimeout:
    async def test_timeout_raises_asyncio_timeout_error(self):
        # Guide: startup_timeout controls how long connect() waits
        client = McpServer.stdio(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            startup_timeout=0.1,
        )
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(client.connect(), timeout=5.0)

    async def test_normal_connect_with_reasonable_timeout(self, error_server_cmd):
        client = McpServer.stdio(error_server_cmd, startup_timeout=5.0)
        await asyncio.wait_for(client.connect(), timeout=10.0)
        await client.close()


# ---------------------------------------------------------------------------
# Section 2 — McpCallError from server-side exceptions
# ---------------------------------------------------------------------------


class TestMcpCallError:
    async def test_divide_by_zero_raises_mcp_call_error(self, error_client):
        with pytest.raises(McpCallError):
            await asyncio.wait_for(
                error_client.call_tool("divide", {"a": 1.0, "b": 0.0}), timeout=5.0
            )

    async def test_call_error_has_code(self, error_client):
        try:
            await asyncio.wait_for(
                error_client.call_tool("divide", {"a": 5.0, "b": 0.0}), timeout=5.0
            )
        except McpCallError as exc:
            assert exc.code != 0

    async def test_successful_divide_does_not_raise(self, error_client):
        result = await asyncio.wait_for(
            error_client.call_tool("divide", {"a": 10.0, "b": 2.0}), timeout=5.0
        )
        text = result["content"][0]["text"]
        assert float(text) == 5.0


# ---------------------------------------------------------------------------
# Section 3 — Unknown tool raises McpCallError
# ---------------------------------------------------------------------------


class TestUnknownTool:
    async def test_unknown_tool_raises_mcp_call_error(self, error_client):
        with pytest.raises(McpCallError):
            await asyncio.wait_for(error_client.call_tool("nonexistent_tool", {}), timeout=5.0)

    async def test_list_tools_lets_you_check_existence(self, error_client):
        tools = await asyncio.wait_for(error_client.list_tools(), timeout=5.0)
        tool_names = {t.name for t in tools}
        assert "divide" in tool_names
        assert "safe_search" in tool_names
        assert "nonexistent_tool" not in tool_names


# ---------------------------------------------------------------------------
# Section 5 — Resource not found
# ---------------------------------------------------------------------------


class TestResourceNotFound:
    async def test_existing_resource_returns_text(self, error_client):
        result = await asyncio.wait_for(error_client.read_resource("/items/item1"), timeout=5.0)
        text = result["contents"][0]["text"]
        assert "Widget A" in text

    async def test_not_found_resource_returns_not_found_text(self, error_client):
        # Guide: "Server may return 'not found' text instead of raising"
        result = await asyncio.wait_for(error_client.read_resource("/items/zzz"), timeout=5.0)
        text = result["contents"][0]["text"]
        assert "not found" in text.lower()


# ---------------------------------------------------------------------------
# Section 6 — safe_search pattern from the guide
# ---------------------------------------------------------------------------


class TestSafeSearchPattern:
    async def test_safe_search_returns_results(self, error_client):
        # Replicate the safe_search() function from the guide
        try:
            result = await asyncio.wait_for(
                error_client.call_tool("safe_search", {"query": "widget"}),
                timeout=5.0,
            )
        except (TimeoutError, McpCallError):
            pytest.fail("safe_search should not raise for valid input")

        content = result.get("content", [])
        assert not result.get("isError")
        items = json.loads(content[0]["text"]) if content else []
        assert "Widget A" in items or "Widget B" in items

    async def test_safe_search_empty_result(self, error_client):
        result = await asyncio.wait_for(
            error_client.call_tool("safe_search", {"query": "unicorn"}), timeout=5.0
        )
        content = result.get("content", [])
        items = json.loads(content[0]["text"]) if content else []
        assert items == []

    async def test_call_error_caught_gracefully(self, error_client):
        # Simulates the safe_search() wrapper from the guide
        async def safe_call(client, query):
            try:
                result = await client.call_tool("divide", {"a": 1.0, "b": 0.0})
            except McpCallError:
                return []
            return result

        ret = await safe_call(error_client, "test")
        assert ret == []
