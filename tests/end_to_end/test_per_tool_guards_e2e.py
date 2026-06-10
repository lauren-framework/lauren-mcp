"""End-to-end tests for per-tool guards via stdio transport.

A subprocess MCP server is started using McpServerModule / LaurenFactory with
a custom stdio read loop.  Guard classes are fully evaluated inside the
subprocess using Lauren's DI system — no mocking.

Tests:
  - Unguarded tool: result returned normally
  - AllowGuard on tool: result returned normally
  - DenyGuard on tool: McpCallError raised
  - @set_metadata + guard: public passes, private denied
"""

from __future__ import annotations

import sys

import pytest

from lauren_mcp import McpCallError, McpServer

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Subprocess server script (single-quoted docstrings to avoid delimiter clash)
# ---------------------------------------------------------------------------
# Uses McpServerModule.for_root() + LaurenFactory so guards are resolved via
# the real DI container, then serves JSON-RPC over stdin/stdout.

_SERVER_SCRIPT = """
import asyncio, json, sys
from lauren import injectable, use_guards, set_metadata, LaurenFactory, module
from lauren.testing import TestClient
from lauren_mcp import mcp_server, mcp_tool, McpExecutionContext, McpServerModule
from lauren_mcp._server._dispatcher import McpDispatcher
from lauren_mcp._server._binding import CURRENT_BINDING
from lauren_mcp._types import JsonRpcRequest


@injectable()
class AllowGuard:
    async def can_activate(self, ctx):
        return True


@injectable()
class DenyGuard:
    async def can_activate(self, ctx):
        return False


@injectable()
class PublicityGuard:
    async def can_activate(self, ctx):
        return ctx.get_metadata('public', False)


@mcp_server('/mcp')
class E2EServer:
    @mcp_tool()
    async def no_guard(self) -> str:
        return 'no_guard_ok'

    @use_guards(AllowGuard)
    @mcp_tool()
    async def with_allow(self) -> str:
        return 'allow_ok'

    @use_guards(DenyGuard)
    @mcp_tool()
    async def with_deny(self) -> str:
        return 'deny_should_not_reach'

    @set_metadata('public', True)
    @use_guards(PublicityGuard)
    @mcp_tool()
    async def public_tool(self) -> str:
        return 'public_ok'

    @set_metadata('public', False)
    @use_guards(PublicityGuard)
    @mcp_tool()
    async def private_tool(self) -> str:
        return 'private_should_not_reach'


E2EModule = McpServerModule.for_root(E2EServer, transport='ws')


@module(imports=[E2EModule])
class App:
    pass


async def main():
    app = LaurenFactory.create(App)
    TestClient(app)  # trigger @post_construct so handlers are registered

    dispatcher = await app._container.resolve(McpDispatcher)

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
            continue   # notification
        req = JsonRpcRequest(method=msg.get('method', ''), id=id_, params=msg.get('params'))
        resp = await dispatcher.dispatch(req)
        print(resp.to_json(), flush=True)


asyncio.run(main())
"""


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def _make_client():
    """Create and connect an McpStdioClient backed by the guard test server."""
    client = McpServer.stdio([sys.executable, "-c", _SERVER_SCRIPT], max_retries=0)
    await client.connect()
    return client


def _get_text(result: dict) -> str:
    """Extract the first text content item from a tools/call result dict."""
    content = result.get("content", [])
    return next((c["text"] for c in content if c.get("type") == "text"), "")


class TestE2EGuards:
    async def test_unguarded_tool(self) -> None:
        """Unguarded tool returns its result over stdio."""
        client = await _make_client()
        try:
            result = await client.call_tool("no_guard", {})
        finally:
            await client.close()
        assert _get_text(result) == "no_guard_ok"

    async def test_allow_guard_passes(self) -> None:
        """Tool with AllowGuard: guard passes, result returned."""
        client = await _make_client()
        try:
            result = await client.call_tool("with_allow", {})
        finally:
            await client.close()
        assert _get_text(result) == "allow_ok"

    async def test_deny_guard_raises_call_error(self) -> None:
        """Tool with DenyGuard: guard rejects, McpCallError raised."""
        client = await _make_client()
        try:
            with pytest.raises(McpCallError) as exc_info:
                await client.call_tool("with_deny", {})
        finally:
            await client.close()
        # Should be an internal error (code -32603) with FORBIDDEN data
        assert exc_info.value.code == -32603 or "FORBIDDEN" in str(exc_info.value)

    async def test_public_tool_passes_with_metadata_guard(self) -> None:
        """Tool with @set_metadata('public', True) and PublicityGuard: passes."""
        client = await _make_client()
        try:
            result = await client.call_tool("public_tool", {})
        finally:
            await client.close()
        assert _get_text(result) == "public_ok"

    async def test_private_tool_denied_with_metadata_guard(self) -> None:
        """Tool with @set_metadata('public', False) and PublicityGuard: denied."""
        client = await _make_client()
        try:
            with pytest.raises(McpCallError):
                await client.call_tool("private_tool", {})
        finally:
            await client.close()
