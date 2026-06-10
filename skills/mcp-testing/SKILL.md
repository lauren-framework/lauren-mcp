---
skill: mcp-testing
version: 3.0.0
tags: [mcp, testing, pytest, subprocess, mock, WsTestClient, streamable-http, context, progress, lauren-mcp]
summary: Test MCP servers with subprocess e2e tests, Lauren's WsTestClient, Streamable HTTP TestClient, and mock clients.
---

# Skill: MCP Testing

## When to use this skill

Use this skill when you need to:
- Write E2E tests for an MCP server using a real subprocess
- Write integration tests using Lauren's `WsTestClient` or `TestClient` (Streamable HTTP)
- Test `McpToolContext` injection, progress notifications, or resource subscriptions
- Test `@mcp_lifespan` startup/shutdown behavior
- Write unit tests with mock `McpClientProtocol`

## Pattern 1: Subprocess E2E (no Lauren app)

```python
# tests/end_to_end/test_my_server.py
from __future__ import annotations
import asyncio, os, sys, tempfile, textwrap
import pytest
from lauren_mcp import McpServer

_SERVER_SCRIPT = textwrap.dedent('''\
    import sys, json, asyncio
    from lauren_mcp.server._decorators import mcp_server, mcp_tool
    from lauren_mcp.server._meta import MCP_TOOL_META
    from lauren_mcp.server._handlers import make_tools_list_handler, make_tools_call_handler
    from lauren_mcp._server._dispatcher import McpDispatcher
    from lauren_mcp._types import JsonRpcRequest

    @mcp_server('/mcp')
    class EchoServer:
        @mcp_tool()
        async def echo(self, message: str) -> str:
            'Echo the message back. Args: message: Any string.'
            return message

    async def main():
        dispatcher = McpDispatcher()
        dispatcher._register_builtins()
        server = EchoServer()
        tools = [getattr(getattr(EchoServer, n), MCP_TOOL_META)
                 for n in dir(EchoServer)
                 if hasattr(getattr(EchoServer, n, None), MCP_TOOL_META)]
        async def _init(p):
            return {'protocolVersion': '2025-03-26',
                    'capabilities': {'tools': {}},
                    'serverInfo': {'name': 'echo', 'version': '1.0.0'}}
        dispatcher.register('initialize', _init)
        tl = make_tools_list_handler(tools)
        tc = make_tools_call_handler(server, tools)
        async def _tl(p): return await tl(JsonRpcRequest(method='tools/list', params=p))
        async def _tc(p): return await tc(JsonRpcRequest(method='tools/call', params=p))
        dispatcher.register('tools/list', _tl)
        dispatcher.register('tools/call', _tc)
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        while True:
            try: line = await asyncio.wait_for(reader.readline(), timeout=30.0)
            except asyncio.TimeoutError: break
            if not line: break
            raw = line.decode().strip()
            if not raw: continue
            try: msg = json.loads(raw)
            except json.JSONDecodeError: continue
            id_ = msg.get('id')
            if id_ is None: continue
            req = JsonRpcRequest(method=msg.get('method', ''), id=id_, params=msg.get('params'))
            resp = await dispatcher.dispatch(req)
            print(resp.to_json(), flush=True)
    asyncio.run(main())
''')

@pytest.fixture
def echo_cmd():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(_SERVER_SCRIPT)
        fname = f.name
    yield [sys.executable, fname]
    os.unlink(fname)

@pytest.fixture
async def echo_client(echo_cmd):
    c = McpServer.stdio(echo_cmd, max_retries=0, startup_timeout=10.0)
    await asyncio.wait_for(c.connect(), timeout=10.0)
    yield c
    await c.close()

async def test_echo_tool(echo_client):
    result = await asyncio.wait_for(
        echo_client.call_tool("echo", {"message": "hello world"}), timeout=5.0
    )
    assert result["content"][0]["text"] == "hello world"
    assert result["isError"] is False

async def test_list_tools(echo_client):
    tools = await asyncio.wait_for(echo_client.list_tools(), timeout=5.0)
    assert any(t.name == "echo" for t in tools)
```

## Pattern 2: Lauren integration test with WsTestClient

```python
import asyncio, json, pytest
from lauren import LaurenFactory, module
from lauren.testing import TestClient, WsTestClient
from lauren_mcp import McpServerModule, mcp_server, mcp_tool

@mcp_server("/mcp")
class TestServer:
    @mcp_tool()
    async def greet(self, name: str) -> str:
        "Greet someone. Args: name: Name."
        return f"Hello, {name}!"

@pytest.fixture(scope="module")
def app():
    @module(imports=[McpServerModule.for_root(TestServer)])
    class App: pass
    a = LaurenFactory.create(App)
    TestClient(a)       # REQUIRED: triggers @post_construct (registers handlers)
    return a

async def test_greet_via_ws(app):
    async with WsTestClient(app).connect("/mcp/ws") as ws:
        await ws.send_json({"jsonrpc":"2.0","id":1,"method":"initialize",
                            "params":{"protocolVersion":"2025-03-26","capabilities":{},
                                      "clientInfo":{"name":"t","version":"1"}}})
        await asyncio.wait_for(ws.receive_json(), timeout=3.0)
        await ws.send_json({"jsonrpc":"2.0","method":"notifications/initialized"})
        await ws.send_json({"jsonrpc":"2.0","id":2,"method":"tools/call",
                            "params":{"name":"greet","arguments":{"name":"World"}}})
        resp = await asyncio.wait_for(ws.receive_json(), timeout=3.0)
        assert resp["result"]["content"][0]["text"] == "Hello, World!"
```

## Pattern 3: Streamable HTTP integration test

```python
import json, pytest
from lauren import LaurenFactory, module
from lauren.testing import TestClient
from lauren_mcp import McpServerModule, mcp_server, mcp_tool

@mcp_server("/mcp", transport="streamable")
class HttpServer:
    @mcp_tool()
    async def ping(self) -> str:
        return "pong"

@pytest.fixture(scope="module")
def app():
    @module(imports=[McpServerModule.for_root(HttpServer, transport="streamable")])
    class App: pass
    a = LaurenFactory.create(App)
    TestClient(a)   # triggers @post_construct
    return a

def test_initialize_streamable(app):
    client = TestClient(app)
    init_payload = json.dumps({
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                   "clientInfo": {"name": "test", "version": "1"}},
    }).encode()
    resp = client.post("/mcp/", content=init_payload,
                       headers={"content-type": "application/json"})
    assert resp.status_code == 200
    session_id = resp.headers["mcp-session-id"]
    body = resp.json()
    assert body["result"]["protocolVersion"] == "2025-03-26"
    return session_id

def test_call_tool_streamable(app):
    client = TestClient(app)
    # initialize first
    session_id = test_initialize_streamable(app)
    # send initialized notification
    client.post("/mcp/", content=json.dumps({
        "jsonrpc":"2.0","method":"notifications/initialized"}).encode(),
        headers={"content-type":"application/json","mcp-session-id":session_id})
    # call tool
    payload = json.dumps({
        "jsonrpc":"2.0","id":2,"method":"tools/call",
        "params":{"name":"ping","arguments":{}}
    }).encode()
    resp = client.post("/mcp/", content=payload,
                       headers={"content-type":"application/json",
                                 "mcp-session-id":session_id})
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"]["content"][0]["text"] == "pong"
```

## Pattern 4: Testing `McpToolContext` injection with `CURRENT_BINDING`

To unit-test a tool method that uses `McpToolContext`, set `CURRENT_BINDING`
directly so the handler can read transport state:

```python
import pytest
from lauren_mcp._server._binding import CURRENT_BINDING, TransportBinding
from lauren_mcp._server._handlers import make_tools_call_handler
from lauren_mcp._types import JsonRpcRequest

@mcp_server("/mcp")
class MyServer:
    @mcp_tool()
    async def greet(self, name: str, ctx: McpToolContext | None = None) -> str:
        if ctx:
            await ctx.info(f"Greeting {name}")
        return f"Hello, {name}!"

async def test_tool_with_context():
    server = MyServer()
    notifications = []

    async def send_notif(payload):
        notifications.append(payload)

    binding = TransportBinding(
        session_id="test-sess",
        send_notification=send_notif,
    )
    token = CURRENT_BINDING.set(binding)
    try:
        from lauren_mcp.server._meta import MCP_TOOL_META
        tools = [getattr(getattr(MyServer, n), MCP_TOOL_META)
                 for n in dir(MyServer)
                 if hasattr(getattr(MyServer, n, None), MCP_TOOL_META)]
        handler = make_tools_call_handler(server, tools)
        req = JsonRpcRequest(
            method="tools/call", id=1,
            params={"name": "greet", "arguments": {"name": "World"}}
        )
        result = await handler(req)
        assert result["content"][0]["text"] == "Hello, World!"
        # Check that the log notification was sent
        assert any(n.get("method") == "notifications/message" for n in notifications)
    finally:
        CURRENT_BINDING.reset(token)
```

## Pattern 5: Testing `@mcp_lifespan`

The lifespan hook fires during `_McpHandlerRegistrar._register_handlers()`
(the `@post_construct`). To test it, trigger `@post_construct` via
`TestClient(app)`:

```python
from lauren import LaurenFactory, module
from lauren.testing import TestClient
from lauren_mcp import McpServerModule, mcp_lifespan, mcp_server, mcp_tool

started = []
stopped = []

@mcp_server("/mcp")
class LifespanServer:
    @mcp_lifespan
    async def lifespan(self):
        started.append(True)
        try:
            yield {"key": "value"}
        finally:
            stopped.append(True)

    @mcp_tool()
    async def check(self, ctx: McpToolContext) -> str:
        return ctx.lifespan_context.get("key", "missing")

def test_lifespan_runs():
    @module(imports=[McpServerModule.for_root(LifespanServer)])
    class App: pass
    app = LaurenFactory.create(App)
    TestClient(app)   # triggers @post_construct → runs lifespan startup
    assert len(started) == 1
    # Shutdown (pre_destruct) runs when the module tears down
```

## Pattern 6: Testing progress notifications

```python
from lauren_mcp._server._binding import CURRENT_BINDING, TransportBinding

async def test_progress():
    notifications = []

    async def send_notif(payload):
        notifications.append(payload)

    @mcp_server("/mcp")
    class ProgressServer:
        @mcp_tool()
        async def work(self, steps: int, ctx: McpToolContext) -> str:
            for i in range(1, steps + 1):
                await ctx.report_progress(i, steps, f"Step {i}")
            return "done"

    server = ProgressServer()
    binding = TransportBinding(
        session_id="sess",
        send_notification=send_notif,
        # Provide a progress token so report_progress fires
    )
    # ... (set up handler, set CURRENT_BINDING, then inject progressToken via params)
    # See Pattern 4 for full handler invocation setup
```

## Pattern 7: Testing cancellation

Send `$/cancelRequest` while a long-running tool is executing:

```python
async def test_cancel(app):
    async with WsTestClient(app).connect("/mcp/ws") as ws:
        # ... initialize handshake ...
        # Start a long-running tool call (id=2)
        await ws.send_json({"jsonrpc":"2.0","id":2,"method":"tools/call",
                            "params":{"name":"slow_tool","arguments":{}}})
        # Cancel it immediately
        await ws.send_json({"jsonrpc":"2.0","method":"$/cancelRequest",
                            "params":{"id":2}})
        # Server responds with an error or early result
        resp = await asyncio.wait_for(ws.receive_json(), timeout=3.0)
        assert "error" in resp or resp.get("result") is not None
```

## Pattern 8: Mock McpClientProtocol (unit tests)

```python
from unittest.mock import AsyncMock, MagicMock
from lauren_mcp._types import ToolSchema

def make_mock_client(*tool_names: str):
    client = MagicMock()
    client.connect = AsyncMock()
    client.close = AsyncMock()
    client.list_tools = AsyncMock(return_value=[
        ToolSchema(name=n, description=f"Tool {n}.",
                   inputSchema={"type":"object","properties":{},"required":[]})
        for n in tool_names
    ])
    async def call_tool(name, args):
        return {"content": [{"type":"text","text":f"{name}:{args}"}], "isError": False}
    client.call_tool = call_tool
    return client

async def test_something_with_mock():
    client = make_mock_client("search", "get_item")
    await client.connect()
    tools = await client.list_tools()
    assert {t.name for t in tools} == {"search", "get_item"}
    await client.close()
```

## Pattern 9: `pytest.mark.eval` for live external servers

```python
import pytest
from lauren_mcp import McpServer

@pytest.mark.eval
async def test_filesystem_server_live():
    """Requires: npx and @modelcontextprotocol/server-filesystem installed."""
    client = McpServer.stdio(
        ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        max_retries=0,
    )
    await client.connect()
    tools = await client.list_tools()
    assert any(t.name == "list_directory" for t in tools)
    await client.close()
```

Run live tests explicitly:

```bash
pytest -m eval tests/integration/
```

## Important notes

- Always set `max_retries=0` in test fixtures to prevent 30-second retry hangs
  when the subprocess crashes.
- `call_tool()` returns a **raw dict** `{"content": [...], "isError": bool}` —
  not `list[TextContent]`.
- Use `asyncio.wait_for(..., timeout=5.0)` on every client call in tests.
- `McpCallError` (from `lauren_mcp`) is raised on server JSON-RPC errors.
- `CURRENT_BINDING` is a `contextvars.ContextVar`; always `reset(token)` in
  a `finally` block to avoid polluting unrelated tests.
- For Streamable HTTP tests, `TestClient(app)` issues synchronous HTTP
  requests directly against the ASGI app — no real network needed.
