"""E2E tests for docs/guides/first-client.md.

Exercises every code example in the guide: connect/disconnect, list_tools,
call_tool (including dict/list result JSON parsing), list_resources,
read_resource, list_prompts, get_prompt, ping, and max_retries.
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
from lauren_mcp._client._stdio import McpStdioClient

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Reusable server script (covers all client guide examples)
# ---------------------------------------------------------------------------

_SERVER = textwrap.dedent("""\
    import sys, json, asyncio

    from lauren_mcp.server._decorators import (
        mcp_server, mcp_tool, mcp_resource, mcp_prompt,
    )
    from lauren_mcp.server._meta import (
        MCP_TOOL_META, MCP_RESOURCE_META, MCP_PROMPT_META,
    )
    from lauren_mcp.server._handlers import (
        make_tools_list_handler, make_tools_call_handler,
        make_resources_list_handler, make_resources_read_handler,
        make_prompts_list_handler, make_prompts_get_handler,
    )
    from lauren_mcp._server._dispatcher import McpDispatcher
    from lauren_mcp._types import JsonRpcRequest

    BOOKS = [
        {"id": 1, "title": "Clean Code", "author": "Martin"},
        {"id": 2, "title": "Design Patterns", "author": "GoF"},
    ]

    @mcp_server("/mcp")
    class ClientGuideServer:
        @mcp_tool()
        async def search(self, query: str) -> list:
            "Search books."
            return [b for b in BOOKS if query.lower() in b["title"].lower()]

        @mcp_tool()
        async def list_books(self) -> list:
            "List all books."
            return BOOKS

        @mcp_resource("/books/{book_id}")
        async def book_resource(self, book_id: str) -> str:
            "A book as text."
            b = next((b for b in BOOKS if b["id"] == int(book_id)), None)
            return f"{b[\'title\']} by {b[\'author\']}" if b else f"Not found: {book_id}"

        @mcp_prompt()
        async def reading_list(self, topic: str) -> str:
            "Reading list prompt."
            titles = ", ".join(b["title"] for b in BOOKS)
            return f"Books on {topic}: {titles}"


    async def main():
        dispatcher = McpDispatcher()
        dispatcher._register_builtins()
        server = ClientGuideServer()

        tools, resources, prompts = [], [], []
        for attr_name in dir(ClientGuideServer):
            try:
                attr = getattr(ClientGuideServer, attr_name)
            except AttributeError:
                continue
            if hasattr(attr, MCP_TOOL_META):
                tools.append(getattr(attr, MCP_TOOL_META))
            if hasattr(attr, MCP_RESOURCE_META):
                resources.append(getattr(attr, MCP_RESOURCE_META))
            if hasattr(attr, MCP_PROMPT_META):
                prompts.append(getattr(attr, MCP_PROMPT_META))

        async def _init(params):
            return {"protocolVersion": "2025-03-26",
                    "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                    "serverInfo": {"name": "client-guide", "version": "1.0.0"}}
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

        pl = make_prompts_list_handler(prompts)
        pg = make_prompts_get_handler(server, prompts)
        async def _pl(p): return await pl(JsonRpcRequest(method="prompts/list", params=p))
        async def _pg(p): return await pg(JsonRpcRequest(method="prompts/get", params=p))
        dispatcher.register("prompts/list", _pl)
        dispatcher.register("prompts/get", _pg)

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
def server_cmd():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(_SERVER)
        fname = f.name
    yield [sys.executable, fname]
    os.unlink(fname)


@pytest.fixture
async def client(server_cmd):
    c: McpStdioClient = McpServer.stdio(server_cmd, startup_timeout=10.0, max_retries=0)
    await asyncio.wait_for(c.connect(), timeout=10.0)
    yield c
    await c.close()


# ---------------------------------------------------------------------------
# Section 2 — Connect and disconnect
# ---------------------------------------------------------------------------


class TestConnectDisconnect:
    async def test_connect_succeeds(self, server_cmd):
        c = McpServer.stdio(server_cmd, startup_timeout=10.0, max_retries=0)
        await asyncio.wait_for(c.connect(), timeout=10.0)
        await c.close()

    async def test_double_close_does_not_raise(self, server_cmd):
        c = McpServer.stdio(server_cmd, startup_timeout=10.0, max_retries=0)
        await asyncio.wait_for(c.connect(), timeout=10.0)
        await c.close()
        await c.close()  # second close must be a no-op


# ---------------------------------------------------------------------------
# Section 3 — list_tools
# ---------------------------------------------------------------------------


class TestListTools:
    async def test_list_tools_returns_nonempty(self, client):
        tools = await asyncio.wait_for(client.list_tools(), timeout=5.0)
        assert len(tools) >= 1

    async def test_list_tools_names_description_schema(self, client):
        tools = await asyncio.wait_for(client.list_tools(), timeout=5.0)
        for t in tools:
            assert t.name
            assert isinstance(t.description, str)
            assert isinstance(t.inputSchema, dict)

    async def test_search_and_list_books_present(self, client):
        tools = await asyncio.wait_for(client.list_tools(), timeout=5.0)
        names = {t.name for t in tools}
        assert "search" in names
        assert "list_books" in names


# ---------------------------------------------------------------------------
# Section 4 — call_tool result format
# ---------------------------------------------------------------------------


class TestCallTool:
    async def test_result_has_content_and_isError(self, client):
        result = await asyncio.wait_for(client.call_tool("search", {"query": "clean"}), timeout=5.0)
        assert "content" in result
        assert "isError" in result

    async def test_is_error_false(self, client):
        result = await asyncio.wait_for(
            client.call_tool("search", {"query": "design"}), timeout=5.0
        )
        assert result["isError"] is False

    async def test_content_first_item_is_text_type(self, client):
        result = await asyncio.wait_for(client.call_tool("search", {"query": "clean"}), timeout=5.0)
        content = result["content"]
        assert content[0]["type"] == "text"

    async def test_json_result_is_parseable(self, client):
        # Guide section: "When the tool returns a Python dict or list..."
        result = await asyncio.wait_for(client.call_tool("list_books", {}), timeout=5.0)
        text = result["content"][0]["text"]
        books = json.loads(text)
        assert isinstance(books, list)
        assert len(books) == 2

    async def test_search_results_contain_matching_book(self, client):
        result = await asyncio.wait_for(client.call_tool("search", {"query": "clean"}), timeout=5.0)
        books = json.loads(result["content"][0]["text"])
        assert any("Clean Code" in b["title"] for b in books)

    async def test_empty_search_returns_empty_list(self, client):
        result = await asyncio.wait_for(
            client.call_tool("search", {"query": "zzz_no_match_zzz"}), timeout=5.0
        )
        assert json.loads(result["content"][0]["text"]) == []


# ---------------------------------------------------------------------------
# Section 5 — list_resources and read_resource
# ---------------------------------------------------------------------------


class TestResources:
    async def test_list_resources_nonempty(self, client):
        resources = await asyncio.wait_for(client.list_resources(), timeout=5.0)
        assert len(resources) >= 1

    async def test_resource_has_uri_and_name(self, client):
        resources = await asyncio.wait_for(client.list_resources(), timeout=5.0)
        for r in resources:
            assert r.uri
            assert r.name

    async def test_read_resource_returns_contents(self, client):
        result = await asyncio.wait_for(client.read_resource("/books/1"), timeout=5.0)
        assert "contents" in result
        assert len(result["contents"]) >= 1

    async def test_read_resource_text_contains_title(self, client):
        result = await asyncio.wait_for(client.read_resource("/books/1"), timeout=5.0)
        text = result["contents"][0]["text"]
        assert "Clean Code" in text

    async def test_read_resource_uri_substitution(self, client):
        # Guide section: "Substitute values yourself when calling read_resource"
        for book_id in [1, 2]:
            result = await asyncio.wait_for(client.read_resource(f"/books/{book_id}"), timeout=5.0)
            assert result["contents"][0]["text"]


# ---------------------------------------------------------------------------
# Section 6 — list_prompts and get_prompt
# ---------------------------------------------------------------------------


class TestPrompts:
    async def test_list_prompts_nonempty(self, client):
        prompts = await asyncio.wait_for(client.list_prompts(), timeout=5.0)
        assert len(prompts) >= 1

    async def test_get_prompt_returns_messages(self, client):
        result = await asyncio.wait_for(
            client.get_prompt("reading_list", {"topic": "architecture"}),
            timeout=5.0,
        )
        assert "messages" in result
        messages = result["messages"]
        assert len(messages) >= 1

    async def test_get_prompt_role_user(self, client):
        result = await asyncio.wait_for(
            client.get_prompt("reading_list", {"topic": "testing"}),
            timeout=5.0,
        )
        assert result["messages"][0]["role"] == "user"

    async def test_get_prompt_text_contains_topic(self, client):
        result = await asyncio.wait_for(
            client.get_prompt("reading_list", {"topic": "refactoring"}),
            timeout=5.0,
        )
        text = result["messages"][0]["content"]["text"]
        assert "refactoring" in text


# ---------------------------------------------------------------------------
# Section 7 — ping
# ---------------------------------------------------------------------------


class TestPing:
    async def test_ping_succeeds(self, client):
        await asyncio.wait_for(client.ping(), timeout=5.0)

    async def test_ping_after_tool_calls(self, client):
        await asyncio.wait_for(client.call_tool("list_books", {}), timeout=5.0)
        await asyncio.wait_for(client.ping(), timeout=5.0)


# ---------------------------------------------------------------------------
# Section 8 — max_retries config
# ---------------------------------------------------------------------------


class TestMaxRetries:
    async def test_max_retries_zero_connects_normally(self, server_cmd):
        c = McpServer.stdio(server_cmd, max_retries=0, startup_timeout=10.0)
        await asyncio.wait_for(c.connect(), timeout=10.0)
        tools = await asyncio.wait_for(c.list_tools(), timeout=5.0)
        assert len(tools) >= 1
        await c.close()

    async def test_max_retries_five_connects_normally(self, server_cmd):
        c = McpServer.stdio(server_cmd, max_retries=5, startup_timeout=10.0)
        await asyncio.wait_for(c.connect(), timeout=10.0)
        await asyncio.wait_for(c.ping(), timeout=5.0)
        await c.close()
