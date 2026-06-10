"""E2E tests for docs/guides/first-server.md.

Every code example from the guide is exercised end-to-end via a real
subprocess server and a connected McpStdioClient.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import textwrap

import pytest
import pytest_asyncio

from lauren_mcp import McpServer
from lauren_mcp._client._stdio import McpStdioClient
from lauren_mcp._types import PromptSchema, ResourceSchema, ToolSchema

pytestmark = pytest.mark.asyncio(loop_scope="session")

# ---------------------------------------------------------------------------
# Server script — BookServer from first-server.md
# ---------------------------------------------------------------------------
# Uses single-quoted docstrings to avoid terminating the outer triple-quote.

_BOOK_SERVER = textwrap.dedent("""\
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
        {"id": 1, "title": "Clean Code", "author": "Martin", "year": 2008},
        {"id": 2, "title": "The Pragmatic Programmer", "author": "Thomas", "year": 1999},
        {"id": 3, "title": "Design Patterns", "author": "GoF", "year": 1994},
    ]

    @mcp_server("/mcp")
    class BookServer:
        @mcp_tool()
        async def search(self, query: str) -> list:
            "Search books by title or author."
            q = query.lower()
            return [b for b in BOOKS if q in b["title"].lower() or q in b["author"].lower()]

        @mcp_tool()
        async def get_book(self, book_id: int) -> dict:
            "Fetch a single book by its numeric ID."
            return next((b for b in BOOKS if b["id"] == book_id), None)

        @mcp_tool()
        async def list_books(self) -> list:
            "Return the full book catalogue."
            return BOOKS

        @mcp_resource("/books/{book_id}")
        async def book_resource(self, book_id: str) -> str:
            "Expose a book as a readable MCP resource."
            book = next((b for b in BOOKS if b["id"] == int(book_id)), None)
            if book is None:
                return f"Book {book_id} not found."
            return f"{book[\'title\']} by {book[\'author\']} ({book[\'year\']})"

        @mcp_prompt()
        async def book_recommendation(self, topic: str) -> str:
            "Generate a reading-list prompt for a given topic."
            titles = ", ".join(b["title"] for b in BOOKS)
            return (
                f"From this reading list: {titles} -- "
                f"recommend the best books about \'{topic}\' and explain why."
            )


    async def main():
        dispatcher = McpDispatcher()
        dispatcher._register_builtins()
        server = BookServer()

        tools, resources, prompts = [], [], []
        for attr_name in dir(BookServer):
            try:
                attr = getattr(BookServer, attr_name)
            except AttributeError:
                continue
            if hasattr(attr, MCP_TOOL_META):
                tools.append(getattr(attr, MCP_TOOL_META))
            if hasattr(attr, MCP_RESOURCE_META):
                resources.append(getattr(attr, MCP_RESOURCE_META))
            if hasattr(attr, MCP_PROMPT_META):
                prompts.append(getattr(attr, MCP_PROMPT_META))

        async def _init(params):
            return {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                "serverInfo": {"name": "book-server", "version": "1.0.0"},
            }
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def book_server_cmd():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(_BOOK_SERVER)
        fname = f.name
    yield [sys.executable, fname]
    os.unlink(fname)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def book_client(book_server_cmd):
    client: McpStdioClient = McpServer.stdio(book_server_cmd, startup_timeout=10.0, max_retries=0)
    await asyncio.wait_for(client.connect(), timeout=10.0)
    yield client
    await client.close()


# ---------------------------------------------------------------------------
# Section 1 — Minimal working server: search tool
# ---------------------------------------------------------------------------


class TestMinimalServer:
    async def test_connect_succeeds(self, book_server_cmd):
        client = McpServer.stdio(book_server_cmd, startup_timeout=10.0, max_retries=0)
        await asyncio.wait_for(client.connect(), timeout=10.0)
        await client.close()

    async def test_list_tools_returns_tool_schema_instances(self, book_client):
        tools = await asyncio.wait_for(book_client.list_tools(), timeout=5.0)
        for t in tools:
            assert isinstance(t, ToolSchema)

    async def test_search_tool_present(self, book_client):
        tools = await asyncio.wait_for(book_client.list_tools(), timeout=5.0)
        assert any(t.name == "search" for t in tools)


# ---------------------------------------------------------------------------
# Section 2 — Multiple tools
# ---------------------------------------------------------------------------


class TestMultipleTools:
    async def test_all_three_tools_present(self, book_client):
        tools = await asyncio.wait_for(book_client.list_tools(), timeout=5.0)
        names = {t.name for t in tools}
        assert {"search", "get_book", "list_books"}.issubset(names)

    async def test_search_by_title(self, book_client):
        result = await asyncio.wait_for(
            book_client.call_tool("search", {"query": "clean"}), timeout=5.0
        )
        books = json.loads(result["content"][0]["text"])
        assert len(books) == 1
        assert books[0]["title"] == "Clean Code"

    async def test_search_by_author(self, book_client):
        result = await asyncio.wait_for(
            book_client.call_tool("search", {"query": "GoF"}), timeout=5.0
        )
        books = json.loads(result["content"][0]["text"])
        assert len(books) == 1
        assert books[0]["title"] == "Design Patterns"

    async def test_search_case_insensitive(self, book_client):
        r1 = await asyncio.wait_for(
            book_client.call_tool("search", {"query": "CLEAN"}), timeout=5.0
        )
        r2 = await asyncio.wait_for(
            book_client.call_tool("search", {"query": "clean"}), timeout=5.0
        )
        assert json.loads(r1["content"][0]["text"]) == json.loads(r2["content"][0]["text"])

    async def test_search_no_results(self, book_client):
        result = await asyncio.wait_for(
            book_client.call_tool("search", {"query": "unicorn"}), timeout=5.0
        )
        assert json.loads(result["content"][0]["text"]) == []

    async def test_get_book_found(self, book_client):
        result = await asyncio.wait_for(
            book_client.call_tool("get_book", {"book_id": 1}), timeout=5.0
        )
        book = json.loads(result["content"][0]["text"])
        assert book["title"] == "Clean Code"
        assert book["id"] == 1

    async def test_get_book_not_found(self, book_client):
        result = await asyncio.wait_for(
            book_client.call_tool("get_book", {"book_id": 9999}), timeout=5.0
        )
        assert result["content"][0]["text"] == "None"

    async def test_list_books_returns_all_three(self, book_client):
        result = await asyncio.wait_for(book_client.call_tool("list_books", {}), timeout=5.0)
        books = json.loads(result["content"][0]["text"])
        assert len(books) == 3

    async def test_tool_result_is_not_error(self, book_client):
        result = await asyncio.wait_for(
            book_client.call_tool("search", {"query": "clean"}), timeout=5.0
        )
        assert result.get("isError") is False


# ---------------------------------------------------------------------------
# Section 3 — Resource
# ---------------------------------------------------------------------------


class TestResource:
    async def test_list_resources_returns_one(self, book_client):
        resources = await asyncio.wait_for(book_client.list_resources(), timeout=5.0)
        assert len(resources) == 1

    async def test_resource_is_schema_instance(self, book_client):
        resources = await asyncio.wait_for(book_client.list_resources(), timeout=5.0)
        assert isinstance(resources[0], ResourceSchema)

    async def test_resource_uri_contains_books(self, book_client):
        resources = await asyncio.wait_for(book_client.list_resources(), timeout=5.0)
        assert "books" in resources[0].uri

    async def test_read_resource_book_1(self, book_client):
        result = await asyncio.wait_for(book_client.read_resource("/books/1"), timeout=5.0)
        text = result["contents"][0]["text"]
        assert "Clean Code" in text
        assert "Martin" in text
        assert "2008" in text

    async def test_read_resource_book_2(self, book_client):
        result = await asyncio.wait_for(book_client.read_resource("/books/2"), timeout=5.0)
        text = result["contents"][0]["text"]
        assert "Pragmatic" in text

    async def test_read_resource_not_found(self, book_client):
        result = await asyncio.wait_for(book_client.read_resource("/books/999"), timeout=5.0)
        text = result["contents"][0]["text"]
        assert "not found" in text.lower()


# ---------------------------------------------------------------------------
# Section 4 — Prompt
# ---------------------------------------------------------------------------


class TestPrompt:
    async def test_list_prompts_returns_one(self, book_client):
        prompts = await asyncio.wait_for(book_client.list_prompts(), timeout=5.0)
        assert len(prompts) == 1

    async def test_prompt_is_schema_instance(self, book_client):
        prompts = await asyncio.wait_for(book_client.list_prompts(), timeout=5.0)
        assert isinstance(prompts[0], PromptSchema)

    async def test_prompt_name_is_book_recommendation(self, book_client):
        prompts = await asyncio.wait_for(book_client.list_prompts(), timeout=5.0)
        assert prompts[0].name == "book_recommendation"

    async def test_get_prompt_returns_messages(self, book_client):
        result = await asyncio.wait_for(
            book_client.get_prompt("book_recommendation", {"topic": "design"}),
            timeout=5.0,
        )
        assert "messages" in result
        assert len(result["messages"]) >= 1

    async def test_get_prompt_message_role_is_user(self, book_client):
        result = await asyncio.wait_for(
            book_client.get_prompt("book_recommendation", {"topic": "design"}),
            timeout=5.0,
        )
        assert result["messages"][0]["role"] == "user"

    async def test_get_prompt_contains_topic(self, book_client):
        result = await asyncio.wait_for(
            book_client.get_prompt("book_recommendation", {"topic": "craftsmanship"}),
            timeout=5.0,
        )
        text = str(result["messages"])
        assert "craftsmanship" in text

    async def test_get_prompt_lists_all_book_titles(self, book_client):
        result = await asyncio.wait_for(
            book_client.get_prompt("book_recommendation", {"topic": "any"}),
            timeout=5.0,
        )
        text = str(result["messages"])
        assert "Clean Code" in text
        assert "Pragmatic Programmer" in text
        assert "Design Patterns" in text


# ---------------------------------------------------------------------------
# Section 7 — Schema generation
# ---------------------------------------------------------------------------


class TestSchemaGeneration:
    async def test_search_schema_query_is_string(self, book_client):
        tools = await asyncio.wait_for(book_client.list_tools(), timeout=5.0)
        search = next(t for t in tools if t.name == "search")
        assert search.inputSchema["properties"]["query"]["type"] == "string"

    async def test_search_schema_query_is_required(self, book_client):
        tools = await asyncio.wait_for(book_client.list_tools(), timeout=5.0)
        search = next(t for t in tools if t.name == "search")
        assert "query" in search.inputSchema.get("required", [])

    async def test_get_book_schema_book_id_is_integer(self, book_client):
        tools = await asyncio.wait_for(book_client.list_tools(), timeout=5.0)
        get_book = next(t for t in tools if t.name == "get_book")
        assert get_book.inputSchema["properties"]["book_id"]["type"] == "integer"

    async def test_list_books_has_no_required_params(self, book_client):
        tools = await asyncio.wait_for(book_client.list_tools(), timeout=5.0)
        list_books = next(t for t in tools if t.name == "list_books")
        assert list_books.inputSchema.get("required", []) == []

    async def test_ping_works_after_all_calls(self, book_client):
        await asyncio.wait_for(book_client.ping(), timeout=5.0)
