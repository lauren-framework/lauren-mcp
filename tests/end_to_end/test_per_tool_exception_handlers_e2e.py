"""End-to-end tests for Phase 4 per-tool exception handlers.

Runs a real subprocess stdio MCP server with @use_exception_handlers on @mcp_tool.
Verifies that:
- Domain exceptions (ValueError) are converted to isError: True tool results.
- Good inputs return normal (isError: False) results.
- Unhandled exceptions raise McpCallError on the client.
- tools/list does not expose exception handler metadata.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import textwrap

import pytest
import pytest_asyncio

from lauren_mcp import McpCallError, McpServer
from lauren_mcp._client._stdio import McpStdioClient

pytestmark = pytest.mark.asyncio(loop_scope="session")

# ---------------------------------------------------------------------------
# Subprocess server script
# ---------------------------------------------------------------------------
# Uses single-quoted docstrings per CLAUDE.md convention.
# The server manually refreshes exception_handlers from the decorated methods,
# mirroring what McpServerModule.for_root() does in production.

_SERVER_SCRIPT = textwrap.dedent("""\
    import sys, json, asyncio

    from lauren import exception_handler, use_exception_handlers
    from lauren.decorators import USE_EXCEPTION_HANDLERS
    from lauren_mcp.server._decorators import mcp_server, mcp_tool
    from lauren_mcp.server._meta import MCP_TOOL_META
    from lauren_mcp.server._handlers import (
        make_tools_list_handler,
        make_tools_call_handler,
    )
    from lauren_mcp._server._dispatcher import McpDispatcher
    from lauren_mcp._types import JsonRpcRequest


    @exception_handler(ValueError)
    class ValueErrorHandler:
        async def catch(self, exc, ctx):
            return {
                'content': [{'type': 'text', 'text': f'handled: {exc}'}],
                'isError': True,
            }


    @mcp_server('/mcp')
    class DemoServer:

        @use_exception_handlers(ValueErrorHandler)
        @mcp_tool()
        async def validated_tool(self, value: int) -> dict:
            'Tool that raises ValueError for negative values.'
            if value < 0:
                raise ValueError(f'value must be non-negative, got {value}')
            return {'result': value * 2}

        @mcp_tool()
        async def crashing_tool(self) -> dict:
            'Tool with no exception handlers — always crashes.'
            raise RuntimeError('crash')


    async def main():
        server = DemoServer()
        dispatcher = McpDispatcher()
        dispatcher._register_builtins()

        tools = []
        for attr_name in dir(DemoServer):
            try:
                attr = getattr(DemoServer, attr_name)
            except AttributeError:
                continue
            meta = getattr(attr, MCP_TOOL_META, None)
            if meta is not None:
                # Refresh exception_handlers from the fully-decorated method.
                # This mirrors what McpServerModule.for_root() does at startup.
                exc_handlers = tuple(getattr(attr, USE_EXCEPTION_HANDLERS, ()))
                if exc_handlers:
                    meta.exception_handlers = exc_handlers
                tools.append(meta)

        async def _initialize(params):
            return {
                'protocolVersion': '2025-03-26',
                'capabilities': {'tools': {}},
                'serverInfo': {'name': 'demo-server', 'version': '1.0.0'},
            }
        dispatcher.register('initialize', _initialize)

        tl = make_tools_list_handler(tools)
        tc = make_tools_call_handler(server, tools)

        async def _tl(p):
            return await tl(JsonRpcRequest(method='tools/list', params=p))

        async def _tc(p):
            return await tc(JsonRpcRequest(method='tools/call', params=p))

        dispatcher.register('tools/list', _tl)
        dispatcher.register('tools/call', _tc)

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
                continue
            req = JsonRpcRequest(method=msg.get('method', ''), id=id_, params=msg.get('params'))
            resp = await dispatcher.dispatch(req)
            print(resp.to_json(), flush=True)


    asyncio.run(main())
""")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def server_command():
    """Write the server script to a temp file and return the launch command."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(_SERVER_SCRIPT)
        fname = f.name
    yield [sys.executable, fname]
    os.unlink(fname)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def client(server_command):
    """Connected McpStdioClient backed by the demo subprocess server."""
    c: McpStdioClient = McpServer.stdio(server_command, max_retries=0)
    await asyncio.wait_for(c.connect(), timeout=15.0)
    yield c
    await c.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_bad_input_returns_is_error_not_mcp_call_error(client: McpStdioClient):
    """ValueError converted to isError: True — NOT a McpCallError on the client."""
    result = await client.call_tool("validated_tool", {"value": -5})
    assert result["isError"] is True
    assert "handled: value must be non-negative" in result["content"][0]["text"]


async def test_good_input_returns_normal_result(client: McpStdioClient):
    """Successful call returns normal result with isError: False."""
    result = await client.call_tool("validated_tool", {"value": 4})
    assert result["isError"] is False
    assert result["structuredContent"]["result"] == 8


async def test_unhandled_exception_raises_mcp_call_error(client: McpStdioClient):
    """Unhandled exception → McpCallError raised on the client."""
    with pytest.raises(McpCallError) as exc_info:
        await client.call_tool("crashing_tool", {})
    assert exc_info.value.code == -32603  # INTERNAL_ERROR


async def test_tools_list_does_not_expose_handlers(client: McpStdioClient):
    """tools/list response has clean schema (no exception handler leakage)."""
    tools = await client.list_tools()
    # tools is a list of ToolSchema dataclass instances
    validated = next(t for t in tools if t.name == "validated_tool")
    # Check as dict (ToolSchema should not have exception_handlers field)
    import dataclasses

    tool_dict = (
        dataclasses.asdict(validated) if dataclasses.is_dataclass(validated) else vars(validated)
    )  # noqa: E501
    assert "exception_handlers" not in tool_dict
    assert "exceptionHandlers" not in tool_dict
