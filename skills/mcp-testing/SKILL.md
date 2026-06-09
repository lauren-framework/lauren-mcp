---
skill: mcp-testing
version: 2.0.0
tags: [mcp, testing, pytest, subprocess, mock, lauren, WsTestClient, lauren-mcp]
summary: Test MCP servers with subprocess e2e tests, Lauren's WsTestClient, and mock clients.
---

# Skill: MCP Testing

## When to use this skill

Use this skill when you need to:
- Write E2E tests for an MCP server using a real subprocess (no Lauren app server)
- Write integration tests using Lauren's `WsTestClient` and `LaurenFactory`
- Write unit tests with mock `McpClientProtocol`
- Set up pytest fixtures for MCP clients

## Pattern 1: Subprocess E2E (no Lauren app)

The simplest and fastest approach for testing MCP server logic.  The server
script runs as a subprocess and speaks JSON-RPC over stdin/stdout.

```python
# tests/end_to_end/test_my_server.py
from __future__ import annotations
import asyncio, json, os, sys, tempfile, textwrap
import pytest
from lauren_mcp import McpServer
from lauren_mcp._client._stdio import McpStdioClient

_SERVER_SCRIPT = textwrap.dedent('''\
    import sys, json, asyncio
    from lauren_mcp.server._decorators import mcp_server, mcp_tool
    from lauren_mcp.server._meta import MCP_TOOL_META
    from lauren_mcp.server._handlers import make_tools_list_handler, make_tools_call_handler
    from lauren_mcp._server._dispatcher import McpDispatcher
    from lauren_mcp._types import JsonRpcRequest

    @mcp_server("/mcp")
    class EchoServer:
        @mcp_tool()
        async def echo(self, message: str) -> str:
            "Echo the message back. Args: message: Any string."
            return message

    async def main():
        dispatcher = McpDispatcher()
        dispatcher._register_builtins()
        server = EchoServer()
        tools = [getattr(getattr(EchoServer, n), MCP_TOOL_META)
                 for n in dir(EchoServer)
                 if hasattr(getattr(EchoServer, n, None), MCP_TOOL_META)]
        async def _init(p):
            return {"protocolVersion":"2025-03-26",
                    "capabilities":{"tools":{}},"serverInfo":{"name":"echo","version":"1.0.0"}}
        dispatcher.register("initialize", _init)
        tl = make_tools_list_handler(tools); tc = make_tools_call_handler(server, tools)
        async def _tl(p): return await tl(JsonRpcRequest(method="tools/list",params=p))
        async def _tc(p): return await tc(JsonRpcRequest(method="tools/call",params=p))
        dispatcher.register("tools/list", _tl); dispatcher.register("tools/call", _tc)
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader(); protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        while True:
            try: line = await asyncio.wait_for(reader.readline(), timeout=30.0)
            except asyncio.TimeoutError: break
            if not line: break
            raw = line.decode().strip()
            if not raw: continue
            try: msg = json.loads(raw)
            except json.JSONDecodeError: continue
            id_ = msg.get("id")
            if id_ is None: continue
            req = JsonRpcRequest(method=msg.get("method",""), id=id_, params=msg.get("params"))
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
    c: McpStdioClient = McpServer.stdio(echo_cmd, max_retries=0, startup_timeout=10.0)
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

For testing the full Lauren DI stack (handlers registered via `@post_construct`,
WebSocket transport, etc.):

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
        # Initialize
        await ws.send_json({"jsonrpc":"2.0","id":1,"method":"initialize",
                            "params":{"protocolVersion":"2025-03-26","capabilities":{},
                                      "clientInfo":{"name":"t","version":"1"}}})
        await asyncio.wait_for(ws.receive_json(), timeout=3.0)
        await ws.send_json({"jsonrpc":"2.0","method":"notifications/initialized"})
        # Call tool
        await ws.send_json({"jsonrpc":"2.0","id":2,"method":"tools/call",
                            "params":{"name":"greet","arguments":{"name":"World"}}})
        resp = await asyncio.wait_for(ws.receive_json(), timeout=3.0)
        assert resp["result"]["content"][0]["text"] == "Hello, World!"
```

## Pattern 3: Mock McpClientProtocol (unit tests)

```python
from unittest.mock import AsyncMock, MagicMock
from lauren_mcp._types import ToolSchema
from lauren_mcp import McpServerConfig

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

## Pattern 4: `pytest.mark.eval` for live external servers

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
- `McpCallError` (from `lauren_mcp`) is raised on server JSON-RPC errors, not
  `McpToolError` or `McpConnectionError`.
