"""E2E tests for docs/guides/multiple-servers.md.

Validates: multi-server simultaneous connection, tool namespacing,
independent tool calls routing to the correct server, failure of one server
not blocking the other, and graceful disconnect of all clients.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import textwrap

import pytest

from lauren_mcp import McpServer, McpServerConfig, McpToolBridge
from lauren_mcp._client._stdio import McpStdioClient

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Minimal echo server (accepts a name arg, echoes {name}:{text})
# ---------------------------------------------------------------------------

_ECHO_SERVER = textwrap.dedent("""\
    import sys, json, asyncio

    from lauren_mcp.server._decorators import mcp_server, mcp_tool
    from lauren_mcp.server._meta import MCP_TOOL_META
    from lauren_mcp.server._handlers import (
        make_tools_list_handler, make_tools_call_handler,
    )
    from lauren_mcp._server._dispatcher import McpDispatcher
    from lauren_mcp._types import JsonRpcRequest
    import sys as _sys

    SERVER_NAME = sys.argv[1] if len(sys.argv) > 1 else "unknown"

    @mcp_server("/mcp")
    class EchoServer:
        @mcp_tool()
        async def echo(self, text: str) -> str:
            "Echo text back with server name prefix."
            return f"{SERVER_NAME}:{text}"

        @mcp_tool()
        async def info(self) -> str:
            "Return server name."
            return SERVER_NAME

    async def main():
        dispatcher = McpDispatcher()
        dispatcher._register_builtins()
        server = EchoServer()

        tools = [getattr(getattr(EchoServer, n), MCP_TOOL_META)
                 for n in dir(EchoServer)
                 if hasattr(getattr(EchoServer, n, None), MCP_TOOL_META)]

        async def _init(params):
            return {"protocolVersion": "2025-03-26",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": SERVER_NAME, "version": "1.0.0"}}
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
            req = JsonRpcRequest(
                method=msg.get("method", ""), id=id_, params=msg.get("params")
            )
            resp = await dispatcher.dispatch(req)
            print(resp.to_json(), flush=True)

    asyncio.run(main())
""")


@pytest.fixture
def echo_script():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(_ECHO_SERVER)
        fname = f.name
    yield fname
    os.unlink(fname)


@pytest.fixture
def alpha_cmd(echo_script):
    return [sys.executable, echo_script, "alpha"]


@pytest.fixture
def beta_cmd(echo_script):
    return [sys.executable, echo_script, "beta"]


@pytest.fixture
async def alpha_client(alpha_cmd):
    c: McpStdioClient = McpServer.stdio(alpha_cmd, startup_timeout=10.0, max_retries=0)
    await asyncio.wait_for(c.connect(), timeout=10.0)
    yield c
    await c.close()


@pytest.fixture
async def beta_client(beta_cmd):
    c: McpStdioClient = McpServer.stdio(beta_cmd, startup_timeout=10.0, max_retries=0)
    await asyncio.wait_for(c.connect(), timeout=10.0)
    yield c
    await c.close()


# ---------------------------------------------------------------------------
# Section 2 — Tool namespacing: alias__tool_name
# ---------------------------------------------------------------------------


class TestToolNamespacing:
    async def test_alpha_tools_present(self, alpha_client):
        tools = await asyncio.wait_for(alpha_client.list_tools(), timeout=5.0)
        names = {t.name for t in tools}
        assert "echo" in names
        assert "info" in names

    async def test_beta_tools_present(self, beta_client):
        tools = await asyncio.wait_for(beta_client.list_tools(), timeout=5.0)
        names = {t.name for t in tools}
        assert "echo" in names
        assert "info" in names

    async def test_alpha_and_beta_expose_same_tool_names(self, alpha_client, beta_client):
        alpha_names = {t.name for t in await alpha_client.list_tools()}
        beta_names = {t.name for t in await beta_client.list_tools()}
        assert alpha_names == beta_names


# ---------------------------------------------------------------------------
# Section 3 — Calls route to the correct server
# ---------------------------------------------------------------------------


class TestRoutingToCorrectServer:
    async def test_alpha_echo_returns_alpha_prefix(self, alpha_client):
        result = await asyncio.wait_for(
            alpha_client.call_tool("echo", {"text": "hello"}), timeout=5.0
        )
        text = result["content"][0]["text"]
        assert text == "alpha:hello"

    async def test_beta_echo_returns_beta_prefix(self, beta_client):
        result = await asyncio.wait_for(
            beta_client.call_tool("echo", {"text": "hello"}), timeout=5.0
        )
        text = result["content"][0]["text"]
        assert text == "beta:hello"

    async def test_alpha_info_returns_alpha(self, alpha_client):
        result = await asyncio.wait_for(alpha_client.call_tool("info", {}), timeout=5.0)
        assert result["content"][0]["text"] == "alpha"

    async def test_beta_info_returns_beta(self, beta_client):
        result = await asyncio.wait_for(beta_client.call_tool("info", {}), timeout=5.0)
        assert result["content"][0]["text"] == "beta"

    async def test_concurrent_calls_to_different_servers(self, alpha_client, beta_client):
        results = await asyncio.gather(
            alpha_client.call_tool("echo", {"text": "concurrent"}),
            beta_client.call_tool("echo", {"text": "concurrent"}),
        )
        assert results[0]["content"][0]["text"] == "alpha:concurrent"
        assert results[1]["content"][0]["text"] == "beta:concurrent"


# ---------------------------------------------------------------------------
# Section 4 — Broken server does not prevent healthy server loading
# ---------------------------------------------------------------------------


class TestBrokenServerResilience:
    async def test_broken_server_does_not_block_healthy(self, alpha_cmd):
        bridge = McpToolBridge(
            [
                McpServerConfig(alias="broken", client=McpServer.stdio(["false"])),
                McpServerConfig(alias="working", client=McpServer.stdio(alpha_cmd)),
            ]
        )

        class MockRegistry:
            def __init__(self):
                self.calls = []

            def register_mcp_server(self, alias, tools, client):
                self.calls.append(alias)

        registry = MockRegistry()
        bridge.set_registry(registry)
        await asyncio.wait_for(bridge.connect_all(), timeout=20.0)

        assert "working" in registry.calls
        await bridge.disconnect_all()

    async def test_broken_server_absent_from_registry(self, alpha_cmd):

        class MockRegistry:
            def __init__(self):
                self.calls = []

            def register_mcp_server(self, alias, tools, client):
                self.calls.append(alias)

        registry = MockRegistry()
        bridge = McpToolBridge(
            [
                McpServerConfig(alias="broken", client=McpServer.stdio(["false"])),
                McpServerConfig(alias="ok", client=McpServer.stdio(alpha_cmd)),
            ]
        )
        bridge.set_registry(registry)
        await asyncio.wait_for(bridge.connect_all(), timeout=20.0)
        assert "broken" not in registry.calls
        await bridge.disconnect_all()


# ---------------------------------------------------------------------------
# Section 5 — Graceful disconnect
# ---------------------------------------------------------------------------


class TestDisconnect:
    async def test_disconnect_all_closes_all_clients(self, alpha_cmd, beta_cmd):
        client_a = McpServer.stdio(alpha_cmd, startup_timeout=10.0, max_retries=0)
        client_b = McpServer.stdio(beta_cmd, startup_timeout=10.0, max_retries=0)

        bridge = McpToolBridge(
            [
                McpServerConfig(alias="alpha", client=client_a),
                McpServerConfig(alias="beta", client=client_b),
            ]
        )
        await asyncio.wait_for(bridge.connect_all(), timeout=20.0)
        await bridge.disconnect_all()

        # After disconnect, calls should fail
        with pytest.raises(Exception):  # noqa: B017
            await asyncio.wait_for(client_a.list_tools(), timeout=2.0)

    async def test_disconnect_all_does_not_raise_if_some_clients_already_closed(self, alpha_cmd):
        client_a = McpServer.stdio(alpha_cmd, startup_timeout=10.0, max_retries=0)
        bridge = McpToolBridge(
            [
                McpServerConfig(alias="a", client=client_a),
            ]
        )
        await asyncio.wait_for(bridge.connect_all(), timeout=15.0)
        # Double-close must not raise
        await bridge.disconnect_all()
        await bridge.disconnect_all()


# ---------------------------------------------------------------------------
# Section 6 — Two independent servers from the guide's full example
# ---------------------------------------------------------------------------


class TestTwoIndependentServers:
    async def test_two_servers_both_connected_simultaneously(self, alpha_cmd, beta_cmd):
        ca = McpServer.stdio(alpha_cmd, startup_timeout=10.0, max_retries=0)
        cb = McpServer.stdio(beta_cmd, startup_timeout=10.0, max_retries=0)
        await asyncio.gather(
            asyncio.wait_for(ca.connect(), timeout=10.0),
            asyncio.wait_for(cb.connect(), timeout=10.0),
        )

        ra = await asyncio.wait_for(ca.call_tool("echo", {"text": "from a"}), timeout=5.0)
        rb = await asyncio.wait_for(cb.call_tool("echo", {"text": "from b"}), timeout=5.0)

        assert ra["content"][0]["text"] == "alpha:from a"
        assert rb["content"][0]["text"] == "beta:from b"

        await ca.close()
        await cb.close()
