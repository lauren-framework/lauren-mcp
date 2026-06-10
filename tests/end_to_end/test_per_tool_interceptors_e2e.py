"""End-to-end tests for per-tool interceptors over stdio transport.

A real subprocess MCP server with @use_interceptors is spawned.
The interceptor adds ``"_intercepted": True`` to ``structuredContent``.
The client verifies the key is present.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest
import pytest_asyncio

from lauren_mcp import McpServer
from lauren_mcp._client._stdio import McpStdioClient

pytestmark = pytest.mark.asyncio(loop_scope="session")

# ---------------------------------------------------------------------------
# Server script (single-quoted docstrings to avoid terminating the outer triple-quotes)
# ---------------------------------------------------------------------------

SERVER_SCRIPT = """
import sys
import json
import asyncio

from lauren import LaurenFactory, module, interceptor, use_interceptors
from lauren.testing import TestClient
from lauren_mcp import mcp_server, mcp_tool, McpServerModule, McpCallHandler
from lauren_mcp._server._dispatcher import McpDispatcher
from lauren_mcp._server._handshake import negotiate_version
from lauren_mcp._types import JsonRpcRequest

@interceptor()
class FlagInterceptor:
    async def intercept(self, ctx, call_handler: McpCallHandler):
        result = await call_handler.handle()
        sc = result.get('structuredContent')
        if isinstance(sc, dict):
            sc['_intercepted'] = True
        else:
            result['structuredContent'] = {'_intercepted': True}
        return result

@mcp_server('/mcp')
class TestServer:

    @use_interceptors(FlagInterceptor)
    @mcp_tool()
    async def flagged_tool(self) -> dict:
        return {'data': 'hello'}

    @mcp_tool()
    async def plain_tool(self) -> dict:
        return {'data': 'world'}


@module(imports=[McpServerModule.for_root(TestServer, transport='ws')])
class AppModule:
    pass


async def main():
    # Build the full Lauren app and trigger @post_construct (handler registration).
    app = LaurenFactory.create(AppModule)
    TestClient(app)   # fires @post_construct hooks

    # Pull the registered dispatcher from the DI container.
    dispatcher = await app.container.resolve(McpDispatcher)

    # Serve over stdin/stdout.
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

        id_ = msg.get('id')
        if id_ is None:
            # Notification - no response needed
            continue

        req = JsonRpcRequest(
            method=msg.get('method', ''),
            params=msg.get('params'),
            id=id_,
        )
        try:
            resp = await dispatcher.dispatch(req)
            print(resp.to_json(), flush=True)
        except Exception as exc:
            err_resp = json.dumps({
                'jsonrpc': '2.0',
                'id': id_,
                'error': {'code': -32603, 'message': str(exc)},
            })
            print(err_resp, flush=True)


asyncio.run(main())
"""


# ---------------------------------------------------------------------------
# Ensure the subprocess can import the worktree's src/lauren_mcp.
# We patch PYTHONPATH at module import time (before any fixtures run).
# ---------------------------------------------------------------------------

_SRC_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "src"))
if os.path.isdir(os.path.join(_SRC_DIR, "lauren_mcp")):
    _existing_pp = os.environ.get("PYTHONPATH", "")
    os.environ["PYTHONPATH"] = f"{_SRC_DIR}:{_existing_pp}" if _existing_pp else _SRC_DIR


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def mcp_client():
    """Spawn the subprocess MCP server and yield a connected client."""
    client: McpStdioClient = McpServer.stdio(
        [sys.executable, "-c", SERVER_SCRIPT],
        max_retries=0,
        startup_timeout=15.0,
    )
    await asyncio.wait_for(client.connect(), timeout=15.0)
    yield client
    await client.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_interceptor_adds_flag_to_structured_content(mcp_client: McpStdioClient) -> None:
    """The FlagInterceptor adds _intercepted=True to structuredContent."""
    result = await asyncio.wait_for(mcp_client.call_tool("flagged_tool", {}), timeout=10.0)
    sc = result.get("structuredContent", {})
    assert sc.get("_intercepted") is True, (
        f"Expected _intercepted=True in structuredContent, got: {sc}"
    )


async def test_interceptor_does_not_affect_plain_tool(mcp_client: McpStdioClient) -> None:
    """FlagInterceptor declared on one tool does not affect other tools."""
    result = await asyncio.wait_for(mcp_client.call_tool("plain_tool", {}), timeout=10.0)
    sc = result.get("structuredContent", {})
    assert "_intercepted" not in sc, f"Unexpected _intercepted key in plain_tool result: {sc}"


async def test_tools_list_does_not_expose_interceptors(mcp_client: McpStdioClient) -> None:
    """tools/list response never exposes an 'interceptors' field."""
    tools = await asyncio.wait_for(mcp_client.list_tools(), timeout=10.0)
    for tool in tools:
        tool_dict = tool if isinstance(tool, dict) else vars(tool)
        assert "interceptors" not in tool_dict, f"Tool {tool!r} exposes interceptors field"
