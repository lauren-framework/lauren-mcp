# Testing

This guide covers the testing patterns used in the `lauren-mcp` test suite and
shows you how to apply them to your own server and client code.

---

## 1. Test structure overview

```
tests/
  unit/           — pure unit tests (no subprocess, no network)
  integration/    — in-process tests with real DI containers and test HTTP clients
  end_to_end/     — full-stack tests: subprocess server + connected McpStdioClient
  docs/           — E2E tests for every code example in the documentation
```

All tests use **pytest** with `asyncio_mode = "auto"` so every `async def
test_*` function is awaited automatically.

---

## 2. Testing a tool handler directly (unit)

The fastest way to test tool logic is to instantiate your server class and call
the method directly — no subprocess, no network, no DI:

```python
import pytest
from lauren_mcp import mcp_server, mcp_tool

BOOKS = [
    {"id": 1, "title": "Clean Code", "author": "Martin"},
    {"id": 2, "title": "Pragmatic Programmer", "author": "Thomas"},
]

@mcp_server("/mcp")
class BookServer:
    @mcp_tool()
    async def search(self, query: str) -> list:
        """Search books by title."""
        return [b for b in BOOKS if query.lower() in b["title"].lower()]

    @mcp_tool()
    async def get_book(self, book_id: int) -> dict | None:
        """Get a book by ID."""
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


async def test_get_book_not_found(server):
    assert await server.get_book(9999) is None
```

---

## 3. Testing with `McpToolContext` injection

Tools that accept a `McpToolContext` parameter get it injected by the dispatcher
at runtime. In unit tests, wire the handler directly using `make_tools_call_handler`
and set `CURRENT_BINDING` to supply transport-specific state:

```python
from lauren_mcp import mcp_tool, McpToolContext
from lauren_mcp._server._binding import CURRENT_BINDING, TransportBinding
from lauren_mcp._types import JsonRpcRequest
from lauren_mcp.server._handlers import make_context_factory, make_tools_call_handler
from lauren_mcp.server._meta import MCP_TOOL_META


class MyServer:
    @mcp_tool()
    async def whoami(self, ctx: McpToolContext) -> dict:
        """Return caller identity."""
        return {
            "session_id": ctx.session_id,
            "lifespan": ctx.lifespan_context,
        }


async def test_context_injected():
    meta = getattr(MyServer.whoami, MCP_TOOL_META)

    # make_context_factory takes server-level metadata and a lifespan getter.
    factory = make_context_factory(
        {"team": "core"},
        lifespan_getter=lambda: {"db": "conn"},
    )
    handler = make_tools_call_handler(MyServer(), [meta], context_factory=factory)

    # CURRENT_BINDING is a ContextVar; set it before calling the handler.
    binding = TransportBinding(session_id="sess-42")
    token = CURRENT_BINDING.set(binding)
    try:
        req = JsonRpcRequest(method="tools/call", id=1, params={"name": "whoami"})
        result = await handler(req)
    finally:
        CURRENT_BINDING.reset(token)

    facts = result["structuredContent"]
    assert facts["session_id"] == "sess-42"
    assert facts["lifespan"] == {"db": "conn"}
```

---

## 4. Testing progress notifications and logging

Mock `send_notification` in the `TransportBinding` to assert that your tool
sends the expected progress and log payloads:

```python
from lauren_mcp import mcp_tool, McpToolContext
from lauren_mcp._server._binding import CURRENT_BINDING, TransportBinding
from lauren_mcp._types import JsonRpcRequest
from lauren_mcp.server._handlers import make_context_factory, make_tools_call_handler
from lauren_mcp.server._meta import MCP_TOOL_META


class WorkServer:
    @mcp_tool()
    async def process(self, n: int, ctx: McpToolContext) -> str:
        """Process n items, reporting progress."""
        for i in range(n):
            await ctx.report_progress(i + 1, total=n)
        await ctx.info("done", {"items": n})
        return "ok"


async def test_progress_and_log():
    sent = []

    async def capture(payload):
        sent.append(payload)

    meta = getattr(WorkServer.process, MCP_TOOL_META)
    handler = make_tools_call_handler(WorkServer(), [meta], context_factory=make_context_factory())

    binding = TransportBinding(
        send_notification=capture,
    )
    token = CURRENT_BINDING.set(binding)
    try:
        req = JsonRpcRequest(
            method="tools/call",
            id=1,
            params={"name": "process", "arguments": {"n": 3}, "_meta": {"progressToken": "p-1"}},
        )
        await handler(req)
    finally:
        CURRENT_BINDING.reset(token)

    progress_events = [m for m in sent if m["method"] == "notifications/progress"]
    assert len(progress_events) == 3
    assert progress_events[-1]["params"]["progress"] == 3

    log_events = [m for m in sent if m["method"] == "notifications/message"]
    assert len(log_events) == 1
    assert log_events[0]["params"]["level"] == "info"
```

---

## 5. Testing lifespan (`@mcp_lifespan`)

The lifespan generator runs inside `_McpHandlerRegistrar._register_handlers()`.
You can test it without the full DI stack using the `build_wired_dispatcher`
helper:

```python
from lauren_mcp import mcp_server, mcp_tool, McpToolContext
from lauren_mcp.server import mcp_lifespan
from lauren_mcp.server._module import McpServerModule
from lauren_mcp._server._catalog import McpCatalogManager
from lauren_mcp._server._registry import McpConnectionRegistry
from lauren_mcp._server._dispatcher import McpDispatcher
from lauren_mcp._types import JsonRpcRequest


async def build_wired_dispatcher(server_cls, **kwargs):
    """Wire handlers without starting a Lauren app — useful in unit tests."""
    mod = McpServerModule.for_root(server_cls, **kwargs)
    dispatcher = McpDispatcher()
    dispatcher._register_builtins()
    server = server_cls()
    registrar_cls = mod._handler_registrar_cls
    registrar = registrar_cls(
        dispatcher, McpConnectionRegistry(), McpCatalogManager(), server
    )
    await registrar._register_handlers()
    return dispatcher, server


@mcp_server("/mcp")
class DbServer:
    @mcp_lifespan
    async def lifespan(self):
        connection = {"url": "sqlite:///:memory:"}
        try:
            yield {"db": connection}
        finally:
            pass  # close connection

    @mcp_tool()
    async def ping_db(self, ctx: McpToolContext) -> str:
        """Ping the database."""
        db = ctx.lifespan_context.get("db")
        return f"connected: {db['url']}"


async def test_lifespan_context_reaches_tool():
    dispatcher, _ = await build_wired_dispatcher(DbServer)

    # Initialize
    init_req = JsonRpcRequest(
        method="initialize",
        id=0,
        params={
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        },
    )
    await dispatcher.dispatch(init_req)

    # Call the tool
    call_req = JsonRpcRequest(
        method="tools/call",
        id=1,
        params={"name": "ping_db", "arguments": {}},
    )
    result = await dispatcher.dispatch(call_req)
    assert "sqlite:///:memory:" in result.result["content"][0]["text"]
```

---

## 6. Testing with a Lauren app (integration)

For testing with real WebSocket connections, wrap your module in a Lauren app
and use `TestClient` + `WsTestClient`:

```python
import json
import pytest
from lauren import LaurenFactory, module
from lauren.testing import TestClient, WsTestClient
from lauren_mcp import McpServerModule, mcp_server, mcp_tool

@mcp_server("/mcp")
class CalcServer:
    @mcp_tool()
    async def add(self, a: int, b: int) -> int:
        """Add two numbers."""
        return a + b


@pytest.fixture(scope="module")
def app():
    @module(imports=[McpServerModule.for_root(CalcServer, transport="ws")])
    class App:
        pass

    # LaurenFactory.create builds the DI container.
    # TestClient(app) triggers @post_construct hooks (including handler registration).
    a = LaurenFactory.create(App)
    TestClient(a)  # important — must come after create()
    return a


async def test_add_tool(app):
    async with WsTestClient(app).connect("/mcp/ws") as ws:
        # Handshake
        await ws.send_text(json.dumps({
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        }))
        await ws.receive_text()
        await ws.send_text(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}))

        # Tool call
        await ws.send_text(json.dumps({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "add", "arguments": {"a": 3, "b": 4}},
        }))
        resp = json.loads(await ws.receive_text())

    assert resp["result"]["content"][0]["text"] == "7"
```

> **Critical:** Always call `TestClient(app)` after `LaurenFactory.create(app)`.
> It triggers `@post_construct` hooks. Without it, `initialize` will fail with
> `McpCallError: Method not found: 'initialize'`.

---

## 7. Testing Streamable HTTP transport

Use `TestClient(app).post("/mcp/", ...)` to drive the Streamable HTTP transport.
The first request must be `initialize`, which returns an `mcp-session-id` header.
Subsequent requests must include that header:

```python
import json
import pytest
from lauren import LaurenFactory, module
from lauren.testing import TestClient
from lauren_mcp import McpServerModule, mcp_server, mcp_tool

@mcp_server("/mcp")
class EchoServer:
    @mcp_tool()
    async def echo(self, message: str) -> str:
        """Echo a message."""
        return message


@pytest.fixture(scope="module")
def app():
    @module(imports=[McpServerModule.for_root(EchoServer, transport="streamable")])
    class App:
        pass

    a = LaurenFactory.create(App)
    TestClient(a)
    return a


def _post(client, body, session_id=None):
    headers = {"content-type": "application/json"}
    if session_id:
        headers["mcp-session-id"] = session_id
    return client.post("/mcp/", content=json.dumps(body).encode(), headers=headers)


async def test_echo_tool_streamable(app):
    client = TestClient(app)

    # Initialize — no session header yet
    resp = _post(client, {
        "jsonrpc": "2.0", "id": 0, "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "0"},
        },
    })
    assert resp.status_code == 200
    session_id = resp.header("mcp-session-id")

    # Complete handshake
    _post(client, {"jsonrpc": "2.0", "method": "notifications/initialized"}, session_id)

    # Tool call
    resp = _post(client, {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": "echo", "arguments": {"message": "hello"}},
    }, session_id)
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["result"]["content"][0]["text"] == "hello"
```

Key behaviours to test:

- Request without `mcp-session-id` → HTTP 400
- Unknown `mcp-session-id` → HTTP 404
- `DELETE /mcp/` with session header → HTTP 204 (terminates the session)
- `Accept: text/event-stream` header → response is an SSE stream

---

## 8. Testing with mock clients (unit)

Use `unittest.mock.AsyncMock` to test code that consumes `McpClientProtocol`
without spawning any subprocess:

```python
from unittest.mock import AsyncMock, MagicMock
from lauren_mcp._types import ToolSchema


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

## 9. Testing with a real subprocess (end-to-end)

For full-stack testing write your server as a standalone stdio script and
launch it with `McpServer.stdio`. Set `max_retries=0` to get immediate failures
rather than 30-second hangs if the script crashes.

```python
# tests/end_to_end/test_book_server.py
from __future__ import annotations
import asyncio, json, os, sys, tempfile, textwrap
import pytest
from lauren_mcp import McpServer

_BOOK_SERVER = textwrap.dedent('''\
    import sys, json, asyncio
    from lauren_mcp.server._decorators import mcp_server, mcp_tool
    from lauren_mcp.server._meta import MCP_TOOL_META
    from lauren_mcp.server._handlers import make_tools_list_handler, make_tools_call_handler
    from lauren_mcp._server._dispatcher import McpDispatcher
    from lauren_mcp._types import JsonRpcRequest

    BOOKS = [{"id": 1, "title": "Clean Code", "author": "Martin"}]

    @mcp_server('/mcp')
    class BookServer:
        @mcp_tool()
        async def search(self, query: str) -> list:
            'Search books.'
            return [b for b in BOOKS if query.lower() in b['title'].lower()]

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
        dispatcher.register('initialize', _init)
        tl = make_tools_list_handler(tools)
        tc = make_tools_call_handler(server, tools)
        async def _tl(p): return await tl(JsonRpcRequest(method='tools/list', params=p))
        async def _tc(p): return await tc(JsonRpcRequest(method='tools/call', params=p))
        dispatcher.register('tools/list', _tl)
        dispatcher.register('tools/call', _tc)
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
        while True:
            line = await reader.readline()
            if not line:
                break
            msg = json.loads(line.decode().strip())
            req = JsonRpcRequest(method=msg.get('method',''), id=msg.get('id'),
                                 params=msg.get('params'))
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
    # max_retries=0 prevents 30-second hangs if the server script crashes
    client = McpServer.stdio(book_server_cmd, startup_timeout=10.0, max_retries=0)
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
    assert books[0]["title"] == "Clean Code"
```

> **Note:** Subprocess scripts use single-quoted docstrings to avoid
> terminating the outer `'''...'''` string literal.

---

## 10. Marking tests that need live services

Use `@pytest.mark.eval` for tests that require an external network service.
These are excluded from the default run:

```python
import pytest
from lauren_mcp import McpServer

@pytest.mark.eval
async def test_filesystem_server_live():
    """Requires: npx and @modelcontextprotocol/server-filesystem."""
    client = McpServer.stdio(
        ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        max_retries=0,
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

## 11. Running the test suite

```bash
# Unit tests only (fastest, ~1 s)
uv run --no-sync pytest tests/unit -q

# Unit + integration (~10 s)
uv run --no-sync pytest tests/unit tests/integration -q

# Full suite including e2e and docs examples
uv run --no-sync pytest -q

# Specific test file
uv run --no-sync pytest tests/integration/test_mcp_streamable_http.py -v

# With coverage report
uv run --no-sync pytest --cov=src/lauren_mcp --cov-report=term-missing

# Via nox (all Python versions)
uv run --no-sync nox -s tests-3.12
```

---

## Next steps

- **[Error handling](error-handling.md)** — test error conditions
- **[Multiple servers](multiple-servers.md)** — test multi-server composition
