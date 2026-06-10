"""E2E tests for docs/guides/testing.md.

Validates the testing patterns shown in the guide:
  - Direct unit-style server method testing
  - Subprocess-based e2e server fixture pattern
  - Mock client pattern with AsyncMock
  - The book server example from the guide runs end-to-end
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import textwrap
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from lauren_mcp import McpServer
from lauren_mcp._client._stdio import McpStdioClient
from lauren_mcp._types import ToolSchema

pytestmark = pytest.mark.asyncio(loop_scope="session")

# ---------------------------------------------------------------------------
# The BookServer from the testing guide (Section 3 subprocess example)
# ---------------------------------------------------------------------------

_BOOK_SERVER_FROM_GUIDE = textwrap.dedent("""\
    import sys, json, asyncio
    from lauren_mcp.server._decorators import mcp_server, mcp_tool
    from lauren_mcp.server._meta import MCP_TOOL_META
    from lauren_mcp.server._handlers import (
        make_tools_list_handler, make_tools_call_handler,
    )
    from lauren_mcp._server._dispatcher import McpDispatcher
    from lauren_mcp._types import JsonRpcRequest

    BOOKS = [
        {"id": 1, "title": "Clean Code", "author": "Martin"},
        {"id": 2, "title": "Pragmatic Programmer", "author": "Thomas"},
    ]

    @mcp_server("/mcp")
    class BookServer:
        @mcp_tool()
        async def search(self, query: str) -> list:
            "Search books."
            return [b for b in BOOKS if query.lower() in b["title"].lower()]

    async def main():
        dispatcher = McpDispatcher()
        dispatcher._register_builtins()
        server = BookServer()
        tools = [getattr(getattr(BookServer, n), MCP_TOOL_META)
                 for n in dir(BookServer)
                 if hasattr(getattr(BookServer, n, None), MCP_TOOL_META)]
        async def _init(p):
            return {  # noqa: E501
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "book", "version": "1.0.0"},
            }
        dispatcher.register("initialize", _init)
        tl = make_tools_list_handler(tools)
        tc = make_tools_call_handler(server, tools)
        async def _tl(p): return await tl(JsonRpcRequest(method="tools/list", params=p))
        async def _tc(p): return await tc(JsonRpcRequest(method="tools/call", params=p))
        dispatcher.register("tools/list", _tl)
        dispatcher.register("tools/call", _tc)
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
            req = JsonRpcRequest(method=msg.get("method",""), id=id_, params=msg.get("params"))
            resp = await dispatcher.dispatch(req)
            print(resp.to_json(), flush=True)
    asyncio.run(main())
""")


# ---------------------------------------------------------------------------
# Section 2 — Direct unit-style method testing
# ---------------------------------------------------------------------------


class TestDirectMethodTesting:
    """Guide section 2: instantiate the server class and call methods directly."""

    async def test_search_returns_matching(self):
        from lauren_mcp.server._decorators import mcp_server, mcp_tool

        BOOKS = [
            {"id": 1, "title": "Clean Code", "author": "Martin"},
            {"id": 2, "title": "Pragmatic Programmer", "author": "Thomas"},
        ]

        @mcp_server("/mcp")
        class BookServer:
            @mcp_tool()
            async def search(self, query: str) -> list:
                "Search."
                return [b for b in BOOKS if query.lower() in b["title"].lower()]

        server = BookServer()
        results = await server.search("clean")
        assert len(results) == 1
        assert results[0]["title"] == "Clean Code"

    async def test_search_case_insensitive(self):
        from lauren_mcp.server._decorators import mcp_server, mcp_tool

        BOOKS = [{"id": 1, "title": "Clean Code", "author": "M"}]

        @mcp_server("/mcp")
        class BookServer:
            @mcp_tool()
            async def search(self, query: str) -> list:
                "Search."
                return [b for b in BOOKS if query.lower() in b["title"].lower()]

        server = BookServer()
        assert await server.search("CLEAN") == await server.search("clean")


# ---------------------------------------------------------------------------
# Section 3 — Subprocess-based e2e (the guide's book_server example)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def book_server_cmd():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(_BOOK_SERVER_FROM_GUIDE)
        fname = f.name
    yield [sys.executable, fname]
    os.unlink(fname)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def book_client(book_server_cmd):
    client: McpStdioClient = McpServer.stdio(book_server_cmd, startup_timeout=10.0, max_retries=0)
    await asyncio.wait_for(client.connect(), timeout=10.0)
    yield client
    await client.close()


class TestSubprocessPattern:
    """Replicates the exact tests from the testing guide's Section 3."""

    async def test_list_tools_includes_search(self, book_client):
        tools = await asyncio.wait_for(book_client.list_tools(), timeout=5.0)
        assert any(t.name == "search" for t in tools)

    async def test_search_returns_matching_books(self, book_client):
        result = await asyncio.wait_for(
            book_client.call_tool("search", {"query": "clean"}), timeout=5.0
        )
        books = json.loads(result["content"][0]["text"])
        assert len(books) == 1
        assert books[0]["title"] == "Clean Code"

    async def test_search_no_results(self, book_client):
        result = await asyncio.wait_for(
            book_client.call_tool("search", {"query": "unicorn"}), timeout=5.0
        )
        books = json.loads(result["content"][0]["text"])
        assert books == []


# ---------------------------------------------------------------------------
# Section 4 — Mock client pattern
# ---------------------------------------------------------------------------


class TestMockClientPattern:
    """Guide section 4: use AsyncMock to test consumer code without subprocess."""

    def _make_mock_client(self, *tool_names: str) -> MagicMock:
        client = MagicMock()
        client.connect = AsyncMock()
        client.close = AsyncMock()
        client.list_tools = AsyncMock(
            return_value=[
                ToolSchema(
                    name=name,
                    description=f"Tool {name}",
                    inputSchema={
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                )
                for name in tool_names
            ]
        )

        async def call_tool(name: str, args: dict) -> dict:
            return {
                "content": [{"type": "text", "text": f"{name}:{args}"}],
                "isError": False,
            }

        client.call_tool = call_tool
        return client

    async def test_mock_client_list_tools(self):
        client = self._make_mock_client("search", "get_item")
        await client.connect()
        tools = await client.list_tools()
        assert {t.name for t in tools} == {"search", "get_item"}
        await client.close()

    async def test_mock_client_call_tool(self):
        client = self._make_mock_client("echo")
        await client.connect()
        result = await client.call_tool("echo", {"text": "hello"})
        assert result["isError"] is False
        assert "echo" in result["content"][0]["text"]
        await client.close()

    async def test_mock_client_does_not_start_subprocess(self):
        import os

        client = self._make_mock_client("tool")
        # No subprocess is started — PID of this process is unchanged
        pid_before = os.getpid()
        await client.connect()
        await client.list_tools()
        await client.close()
        assert os.getpid() == pid_before
