"""End-to-end tests for transport changes.

Verifies that a subprocess stdio server handles all four supported protocol
versions and that client.protocol_version reflects the negotiated version.

Uses the same low-level subprocess pattern as other e2e tests — no Lauren DI,
just a dispatcher wired directly over stdin/stdout.
"""

from __future__ import annotations

import asyncio
import os
import sys
import textwrap

import pytest

from lauren_mcp import McpServer
from lauren_mcp._mcp_version import LATEST, SUPPORTED

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Subprocess server script — serves over stdin/stdout using the dispatcher
# directly, with the updated four-version SUPPORTED set.
# ---------------------------------------------------------------------------

_VERSION_AWARE_SERVER_SCRIPT = textwrap.dedent("""\
    import sys, json, asyncio

    from lauren_mcp.server._decorators import mcp_server, mcp_tool
    from lauren_mcp.server._meta import MCP_TOOL_META
    from lauren_mcp.server._handlers import make_tools_list_handler, make_tools_call_handler
    from lauren_mcp._server._dispatcher import McpDispatcher
    from lauren_mcp._server._handshake import negotiate_version
    from lauren_mcp._types import JsonRpcRequest


    @mcp_server('/mcp')
    class SimpleServer:
        @mcp_tool()
        async def greet(self, name: str) -> str:
            'Return a greeting.'
            return f'hello {name}'


    async def main():
        dispatcher = McpDispatcher()
        server = SimpleServer()

        tools = []
        for attr_name in dir(SimpleServer):
            try:
                attr = getattr(SimpleServer, attr_name)
            except AttributeError:
                continue
            if hasattr(attr, MCP_TOOL_META):
                tools.append(getattr(attr, MCP_TOOL_META))

        async def _init(params):
            version = negotiate_version((params or {}).get('protocolVersion', ''))
            return {
                'protocolVersion': version,
                'capabilities': {'tools': {}},
                'serverInfo': {'name': 'simple-server', 'version': '1.0.0'},
            }
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


@pytest.fixture(autouse=True)
def _ensure_lauren_mcp_importable():
    """Set PYTHONPATH so subprocesses can import lauren_mcp from the worktree src."""
    src_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "src"))
    if os.path.isdir(os.path.join(src_dir, "lauren_mcp")):
        existing = os.environ.get("PYTHONPATH", "")
        new_pythonpath = f"{src_dir}:{existing}" if existing else src_dir
        old_pythonpath = os.environ.get("PYTHONPATH")
        os.environ["PYTHONPATH"] = new_pythonpath
        yield
        if old_pythonpath is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = old_pythonpath
    else:
        yield


@pytest.fixture
def server_script_path(tmp_path):
    """Write the server script to a temp file and return the command."""
    script_file = tmp_path / "version_server.py"
    script_file.write_text(_VERSION_AWARE_SERVER_SCRIPT)
    yield [sys.executable, str(script_file)]


async def test_client_connects_default_protocol_version(server_script_path):
    """Client connects and negotiates LATEST protocol version by default."""
    client = McpServer.stdio(server_script_path, max_retries=0)
    await asyncio.wait_for(client.connect(), timeout=10.0)
    try:
        assert client.protocol_version in SUPPORTED
    finally:
        await client.close()


async def test_client_defaults_to_latest(server_script_path):
    """Client without explicit protocol_version negotiates LATEST."""
    client = McpServer.stdio(server_script_path, max_retries=0)
    await asyncio.wait_for(client.connect(), timeout=10.0)
    try:
        assert client.protocol_version == LATEST
    finally:
        await client.close()


async def test_client_requests_2025_03_26(server_script_path):
    """Client explicitly requesting 2025-03-26 gets that version back."""
    client = McpServer.stdio(server_script_path, max_retries=0, protocol_version="2025-03-26")
    await asyncio.wait_for(client.connect(), timeout=10.0)
    try:
        assert client.protocol_version == "2025-03-26"
    finally:
        await client.close()


async def test_client_requests_2024_11_05(server_script_path):
    """Client explicitly requesting 2024-11-05 gets that version back."""
    client = McpServer.stdio(server_script_path, max_retries=0, protocol_version="2024-11-05")
    await asyncio.wait_for(client.connect(), timeout=10.0)
    try:
        assert client.protocol_version == "2024-11-05"
    finally:
        await client.close()


async def test_client_requests_supported_version_is_negotiated(server_script_path):
    """A supported version should be echoed back unchanged."""
    for version in SUPPORTED:
        client = McpServer.stdio(server_script_path, max_retries=0, protocol_version=version)
        await asyncio.wait_for(client.connect(), timeout=10.0)
        try:
            assert client.protocol_version == version, (
                f"Expected {version!r} to be negotiated, got {client.protocol_version!r}"
            )
        finally:
            await client.close()
