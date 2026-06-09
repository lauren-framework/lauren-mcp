# Testing

This guide covers the testing patterns used in the lauren-mcp test suite and
shows you how to apply them to your own server and client code.

---

## 1. Test structure overview

```
tests/
  unit/           — pure unit tests (no subprocess, no network)
  integration/    — tests with real subprocesses or live DI containers
  end_to_end/     — full-stack tests: subprocess server + connected client
  docs/           — E2E tests for every code example in the documentation
```

All tests use **pytest** with `asyncio_mode = "auto"` so every `async def
test_*` function is awaited automatically.

---

## 2. Testing a tool handler directly (unit)

The fastest way to test tool logic is to instantiate your server class and
call the method directly — no subprocess, no network:

```python
import pytest

# Assume BookServer is defined in your application module
# from myapp.server import BookServer, BOOKS

BOOKS = [
    {"id": 1, "title": "Clean Code", "author": "Martin"},
    {"id": 2, "title": "Pragmatic Programmer", "author": "Thomas"},
]

from lauren_mcp import mcp_server, mcp_tool

@mcp_server("/mcp")
class BookServer:
    @mcp_tool()
    async def search(self, query: str) -> list:
        "Search books."
        return [b for b in BOOKS if query.lower() in b["title"].lower()]

    @mcp_tool()
    async def get_book(self, book_id: int) -> dict:
        "Get a book by ID."
        return next((b for b in BOOKS if b["id"] == book_id), None)


@pytest.fixture
def server():
    return BookServer()


async def test_search_returns_matching_books(server):
    results = await server.search("clean")
    assert len(results) == 1
    assert results[0]["title"] == "Clean Code"


async def test_search_case_insensitive(server):
    assert await server.search("CLEAN") == await server.search("clean")


async def test_get_book_found(server):
    book = await server.get_book(1)
    assert book is not None
    assert book["id"] == 1


async def test_get_book_not_found(server):
    assert await server.get_book(9999) is None
```

---

## 3. Testing with a real subprocess (E2E)

For full-stack testing write your server as a standalone stdio script and
launch it with `McpServer.stdio`.  The subprocess reads JSON-RPC from stdin
and writes responses to stdout — no web server required.

```python
# tests/end_to_end/test_book_server.py
from __future__ import annotations
import asyncio, json, os, sys, tempfile, textwrap
import pytest
from lauren_mcp import McpServer


# Inline server script — uses handler factories, not a full Lauren app.
_BOOK_SERVER = textwrap.dedent('''\
    import sys, json, asyncio
    from lauren_mcp.server._decorators import mcp_server, mcp_tool
    from lauren_mcp.server._meta import MCP_TOOL_META
    from lauren_mcp.server._handlers import make_tools_list_handler, make_tools_call_handler
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
            return {"protocolVersion":"2025-03-26",
                    "capabilities":{"tools":{}},"serverInfo":{"name":"book","version":"1.0.0"}}
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
''')


@pytest.fixture
def book_server_cmd():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(_BOOK_SERVER)
        fname = f.name
    yield [sys.executable, fname]
    os.unlink(fname)


@pytest.fixture
async def book_client(book_server_cmd):
    client = McpServer.stdio(book_server_cmd, startup_timeout=10.0)
    await asyncio.wait_for(client.connect(), timeout=10.0)
    yield client
    await client.close()


async def test_list_tools_includes_search(book_client):
    tools = await asyncio.wait_for(book_client.list_tools(), timeout=5.0)
    assert any(t.name == "search" for t in tools)


async def test_search_returns_matching_books(book_client):
    result = await asyncio.wait_for(
        book_client.call_tool("search", {"query": "clean"}), timeout=5.0
    )
    books = json.loads(result["content"][0]["text"])
    assert len(books) == 1
    assert books[0]["title"] == "Clean Code"


async def test_search_no_results(book_client):
    result = await asyncio.wait_for(
        book_client.call_tool("search", {"query": "unicorn"}), timeout=5.0
    )
    books = json.loads(result["content"][0]["text"])
    assert books == []
```

---

## 4. Testing with mock clients (unit)

Use `unittest.mock.AsyncMock` to test code that consumes `McpClientProtocol`
without spawning any subprocess:

```python
from unittest.mock import AsyncMock, MagicMock
from lauren_mcp._types import ToolSchema
from lauren_mcp import McpServerConfig


def make_mock_client(*tool_names: str):
    client = MagicMock()
    client.connect = AsyncMock()
    client.close = AsyncMock()
    client.list_tools = AsyncMock(return_value=[
        ToolSchema(
            name=name,
            description=f"Tool {name}",
            inputSchema={"type": "object", "properties": {}, "required": []},
        )
        for name in tool_names
    ])

    async def call_tool(name, args):
        return {"content": [{"type": "text", "text": f"{name}:{args}"}], "isError": False}

    client.call_tool = call_tool
    return client


async def test_mock_client_list_tools():
    client = make_mock_client("search", "get_item")
    await client.connect()
    tools = await client.list_tools()
    assert {t.name for t in tools} == {"search", "get_item"}
    await client.close()
```

---

## 5. Marking tests that need live services

Use `@pytest.mark.eval` for tests that require an external network service.
These are excluded from the default run:

```python
import pytest
from lauren_mcp import McpServer


@pytest.mark.eval
async def test_filesystem_server_live():
    """Requires: npx and @modelcontextprotocol/server-filesystem."""
    client = McpServer.stdio(
        ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    )
    await client.connect()
    tools = await client.list_tools()
    assert any(t.name == "list_directory" for t in tools)
    await client.close()
```

Run eval tests explicitly:

```bash
pytest -m eval tests/integration/
```

---

## 6. Running the test suite

```bash
# Unit tests only (fastest, ~1 s)
uv run pytest tests/unit -q

# Unit + integration (~10 s)
uv run pytest tests/unit tests/integration -q

# Full suite including e2e and docs examples
uv run pytest -q

# With coverage report
uv run pytest --cov=src/lauren_mcp --cov-report=term-missing
```

---

## Next steps

- **[Error handling](error-handling.md)** — test error conditions
- **[Multiple servers](multiple-servers.md)** — test multi-server setups
