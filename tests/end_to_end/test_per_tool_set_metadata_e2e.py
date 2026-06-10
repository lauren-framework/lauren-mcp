"""End-to-end tests for Phase 1: per-tool @set_metadata metadata visible in tool context.

A subprocess MCP server is started via McpServer.stdio; the tool reads its own
per-method @set_metadata value from the McpToolContext and returns it.

The server uses the same handler-factory wiring as McpServerModule.for_root()
but bypasses Lauren DI (faster subprocess startup).

Tests:
  J1: check_permission tool → "permission=read"
  J2: admin_action tool → "permission=admin"
  J3: Both tools visible in list_tools()
  J4: tools/list inputSchema has no "permission" key (internal metadata not leaked)
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import tempfile
import textwrap

import pytest
import pytest_asyncio

from lauren_mcp import McpServer
from lauren_mcp._client._stdio import McpStdioClient

pytestmark = pytest.mark.asyncio(loop_scope="session")

# Resolve the worktree src directory so the subprocess imports our modified code,
# not the editable-install path that points to the main checkout.
_THIS_DIR = pathlib.Path(__file__).parent
_SRC_DIR = str((_THIS_DIR / ".." / ".." / "src").resolve())

# ---------------------------------------------------------------------------
# Subprocess server script
#
# Decorator ordering: @mcp_tool() is outermost so it runs AFTER @set_metadata
# has stored __lauren_metadata__ on the function, making it visible to
# _read_method_decorators inside the @mcp_tool() decorator factory.
#
# Single-quoted strings used inside to avoid ending the outer triple-quoted literal.
# ---------------------------------------------------------------------------

_SCRIPT_BODY = textwrap.dedent("""\
    import sys, json, asyncio

    from lauren import set_metadata
    from lauren_mcp.server._decorators import mcp_server, mcp_tool
    from lauren_mcp.server._meta import MCP_TOOL_META
    from lauren_mcp.server._handlers import (
        make_tools_list_handler,
        make_tools_call_handler,
        make_context_factory,
    )
    from lauren_mcp._server._dispatcher import McpDispatcher
    from lauren_mcp._types import JsonRpcRequest
    from lauren_mcp._server._context import McpToolContext


    @mcp_server('/mcp')
    class E2eServer:
        @mcp_tool()
        @set_metadata('permission', 'read')
        async def check_permission(self, ctx: McpToolContext) -> str:
            perm = ctx.get_metadata('permission', 'none')
            return f'permission={perm}'

        @mcp_tool()
        @set_metadata('permission', 'admin')
        async def admin_action(self, ctx: McpToolContext) -> str:
            perm = ctx.get_metadata('permission', 'none')
            return f'permission={perm}'


    async def main():
        dispatcher = McpDispatcher()
        dispatcher._register_builtins()
        server = E2eServer()

        tools = []
        for name in dir(E2eServer):
            try:
                attr = getattr(E2eServer, name)
            except AttributeError:
                continue
            if hasattr(attr, MCP_TOOL_META):
                tools.append(getattr(attr, MCP_TOOL_META))

        async def _init(params):
            return {
                'protocolVersion': '2025-03-26',
                'capabilities': {'tools': {}},
                'serverInfo': {'name': 'e2e-meta-server', 'version': '1.0.0'},
            }

        dispatcher.register('initialize', _init)

        ctx_factory = make_context_factory({})

        tl = make_tools_list_handler(tools)
        tc = make_tools_call_handler(server, tools, context_factory=ctx_factory)

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
                continue  # notification — no response needed
            req = JsonRpcRequest(method=msg.get('method', ''), id=id_, params=msg.get('params'))
            resp = await dispatcher.dispatch(req)
            print(resp.to_json(), flush=True)


    asyncio.run(main())
""")


@pytest.fixture(scope="session")
def e2e_server_command():
    """Write the server script to a temp file and return the launch command.

    The script includes a sys.path.insert to ensure the worktree's modified
    source is imported, not the editable-install pointing to the main checkout.
    """
    # Prepend the worktree src so our changes are visible to the subprocess.
    script = f"import sys; sys.path.insert(0, {_SRC_DIR!r})\n" + _SCRIPT_BODY
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(script)
        fname = f.name
    yield [sys.executable, fname]
    os.unlink(fname)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def e2e_client(e2e_server_command):
    """Start the subprocess server and return a connected McpStdioClient."""
    client: McpStdioClient = McpServer.stdio(e2e_server_command, max_retries=0)
    await asyncio.wait_for(client.connect(), timeout=10.0)
    yield client
    await client.close()


class TestPerToolSetMetadataE2E:
    async def test_j1_check_permission_returns_read(self, e2e_client):
        """J1: check_permission tool returns 'permission=read'."""
        result = await e2e_client.call_tool("check_permission")
        texts = [c["text"] for c in result["content"] if c.get("type") == "text"]
        assert any("permission=read" in t for t in texts), f"Got: {result}"

    async def test_j2_admin_action_returns_admin(self, e2e_client):
        """J2: admin_action tool returns 'permission=admin'."""
        result = await e2e_client.call_tool("admin_action")
        texts = [c["text"] for c in result["content"] if c.get("type") == "text"]
        assert any("permission=admin" in t for t in texts), f"Got: {result}"

    async def test_j3_both_tools_visible_in_list(self, e2e_client):
        """J3: Both tools are visible in list_tools() with correct names."""
        tools = await e2e_client.list_tools()
        names = {t.name for t in tools}
        assert "check_permission" in names
        assert "admin_action" in names

    async def test_j4_tools_list_does_not_leak_metadata(self, e2e_client):
        """J4: inputSchema has no 'permission' key (metadata is internal)."""
        tools = await e2e_client.list_tools()
        tool_map = {t.name: t for t in tools}
        for tool_name in ("check_permission", "admin_action"):
            schema = tool_map[tool_name].inputSchema or {}
            props = schema.get("properties", {})
            assert "permission" not in props, f"{tool_name} inputSchema leaks 'permission': {props}"
