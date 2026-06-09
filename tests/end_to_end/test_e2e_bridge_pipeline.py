"""End-to-end: McpToolBridge wiring multiple real subprocess servers.

Two independent echo-server subprocesses are connected via McpToolBridge
under different aliases.  A MockRegistry records every register_mcp_server
call and stores executor closures so we can call through to the real
subprocesses and verify that results are correctly demultiplexed by alias.

What this tests that nothing else does:
- McpToolBridge.connect_all() drives real connect + list_tools on each server
- Tool names are namespaced (alias__tool_name) in the registry
- Executor closures route to the *correct* subprocess — alpha's executor
  never touches beta's process and vice-versa
- disconnect_all() shuts down every subprocess cleanly
- A broken server (bad command) does not prevent healthy servers from loading
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile

import pytest

from lauren_mcp import McpServer, McpServerConfig, McpToolBridge
from lauren_mcp._types import ToolSchema

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# MockRegistry — records register_mcp_server calls, stores executor closures
# ---------------------------------------------------------------------------


def _make_executor(client, tool_name: str):
    """Closure mirroring what lauren_ai's ToolRegistry would create."""

    async def _exec(arguments: dict):
        result = await client.call_tool(tool_name, arguments)
        content = result.get("content", [])
        if content and content[0].get("type") == "text":
            return content[0]["text"]
        return result

    return _exec


class MockRegistry:
    def __init__(self):
        self.calls: list[tuple[str, list[ToolSchema], object]] = []
        self.executors: dict[str, object] = {}  # "alias__name" → async callable

    def register_mcp_server(self, alias: str, tools: list[ToolSchema], client) -> None:
        self.calls.append((alias, tools, client))
        for tool in tools:
            key = f"{alias}__{tool.name}"
            self.executors[key] = _make_executor(client, tool.name)

    @property
    def registered_aliases(self) -> list[str]:
        return [alias for alias, _, _ in self.calls]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def alpha_command(echo_server_command):
    """First echo server — aliased as 'alpha'."""
    return echo_server_command


@pytest.fixture
def beta_command():
    """Second independent echo server — aliased as 'beta'.

    Creates its own tempfile so it is a fully separate subprocess from alpha.
    """
    script = """
import sys, json

def respond(id_, result):
    print(json.dumps({"jsonrpc": "2.0", "id": id_, "result": result}), flush=True)

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except Exception:
        continue
    method = msg.get("method")
    id_ = msg.get("id")
    if method == "initialize":
        respond(id_, {
            "protocolVersion": "2025-03-26",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "beta-echo-server", "version": "1.0.0"}
        })
    elif method == "tools/list":
        respond(id_, {"tools": [
            {"name": "echo", "description": "Beta echo.", "inputSchema": {
                "type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]
            }}
        ]})
    elif method == "tools/call":
        args = (msg.get("params") or {}).get("arguments", {})
        respond(id_, {"content": [{"type": "text", "text": args.get("text", "")}],
                      "isError": False})
    elif method == "ping":
        respond(id_, {})
    elif method in ("resources/list", "prompts/list"):
        respond(id_, {method.split("/")[0]: []})
    sys.stdout.flush()
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(script)
        fname = f.name
    yield [sys.executable, fname]
    os.unlink(fname)


@pytest.fixture
async def two_server_bridge(alpha_command, beta_command):
    """McpToolBridge connecting alpha and beta echo servers, with a MockRegistry."""
    registry = MockRegistry()
    bridge = McpToolBridge(
        [
            McpServerConfig(alias="alpha", client=McpServer.stdio(alpha_command)),
            McpServerConfig(alias="beta", client=McpServer.stdio(beta_command)),
        ]
    )
    bridge.set_registry(registry)
    await asyncio.wait_for(bridge.connect_all(), timeout=15.0)
    yield bridge, registry
    await bridge.disconnect_all()


# ---------------------------------------------------------------------------
# Connection and registration
# ---------------------------------------------------------------------------


class TestBridgeConnection:
    async def test_both_servers_registered_in_registry(self, two_server_bridge):
        _, registry = two_server_bridge
        assert set(registry.registered_aliases) == {"alpha", "beta"}

    async def test_each_server_registered_exactly_once(self, two_server_bridge):
        _, registry = two_server_bridge
        assert registry.registered_aliases.count("alpha") == 1
        assert registry.registered_aliases.count("beta") == 1

    async def test_connect_all_called_twice(self, two_server_bridge):
        _, registry = two_server_bridge
        assert len(registry.calls) == 2

    async def test_each_server_contributes_one_tool(self, two_server_bridge):
        _, registry = two_server_bridge
        for alias, tools, _ in registry.calls:
            assert len(tools) == 1, f"Expected 1 tool from '{alias}', got {len(tools)}"


# ---------------------------------------------------------------------------
# Namespace separation
# ---------------------------------------------------------------------------


class TestNamespacing:
    async def test_alpha_tool_namespaced_as_alpha_echo(self, two_server_bridge):
        _, registry = two_server_bridge
        assert "alpha__echo" in registry.executors

    async def test_beta_tool_namespaced_as_beta_echo(self, two_server_bridge):
        _, registry = two_server_bridge
        assert "beta__echo" in registry.executors

    async def test_no_unnamespaced_echo_key_in_registry(self, two_server_bridge):
        _, registry = two_server_bridge
        assert "echo" not in registry.executors

    async def test_total_executor_count_is_two(self, two_server_bridge):
        _, registry = two_server_bridge
        assert len(registry.executors) == 2

    async def test_tool_schemas_carry_original_name(self, two_server_bridge):
        _, registry = two_server_bridge
        for _alias, tools, _ in registry.calls:
            for tool in tools:
                assert isinstance(tool, ToolSchema)
                # The ToolSchema retains the original name; the registry key is namespaced
                assert tool.name == "echo"


# ---------------------------------------------------------------------------
# Executor call-through — routes to the correct subprocess
# ---------------------------------------------------------------------------


class TestExecutorCallThrough:
    async def test_alpha_executor_returns_correct_text(self, two_server_bridge):
        _, registry = two_server_bridge
        executor = registry.executors["alpha__echo"]
        result = await asyncio.wait_for(executor({"text": "hello from alpha"}), timeout=5.0)
        assert result == "hello from alpha"

    async def test_beta_executor_returns_correct_text(self, two_server_bridge):
        _, registry = two_server_bridge
        executor = registry.executors["beta__echo"]
        result = await asyncio.wait_for(executor({"text": "hello from beta"}), timeout=5.0)
        assert result == "hello from beta"

    async def test_alpha_and_beta_executors_are_independent(self, two_server_bridge):
        """Calling alpha's executor must not affect beta's response."""
        _, registry = two_server_bridge
        alpha_exec = registry.executors["alpha__echo"]
        beta_exec = registry.executors["beta__echo"]

        r_alpha = await asyncio.wait_for(alpha_exec({"text": "ping-alpha"}), timeout=5.0)
        r_beta = await asyncio.wait_for(beta_exec({"text": "ping-beta"}), timeout=5.0)

        assert r_alpha == "ping-alpha"
        assert r_beta == "ping-beta"

    async def test_concurrent_calls_to_both_executors(self, two_server_bridge):
        """Concurrent calls to both executors succeed and return correct values."""
        _, registry = two_server_bridge
        alpha_exec = registry.executors["alpha__echo"]
        beta_exec = registry.executors["beta__echo"]

        results = await asyncio.gather(
            alpha_exec({"text": "concurrent-alpha"}),
            beta_exec({"text": "concurrent-beta"}),
        )
        assert results[0] == "concurrent-alpha"
        assert results[1] == "concurrent-beta"

    async def test_multiple_sequential_calls_to_same_executor(self, two_server_bridge):
        _, registry = two_server_bridge
        executor = registry.executors["alpha__echo"]
        for i in range(5):
            result = await asyncio.wait_for(executor({"text": f"msg-{i}"}), timeout=5.0)
            assert result == f"msg-{i}"


# ---------------------------------------------------------------------------
# Resilience — broken server does not block healthy servers
# ---------------------------------------------------------------------------


class TestBridgeResilience:
    async def test_broken_server_does_not_prevent_healthy_server_loading(self, echo_server_command):
        """If one server command is invalid the other still loads."""
        registry = MockRegistry()
        bridge = McpToolBridge(
            [
                McpServerConfig(alias="good", client=McpServer.stdio(echo_server_command)),
                McpServerConfig(alias="bad", client=McpServer.stdio(["/nonexistent/server"])),
            ]
        )
        bridge.set_registry(registry)

        # Should not raise even though "bad" will fail to connect
        await asyncio.wait_for(bridge.connect_all(), timeout=15.0)

        assert "good" in registry.registered_aliases
        assert "bad" not in registry.registered_aliases
        assert "good__echo" in registry.executors

        await bridge.disconnect_all()

    async def test_healthy_executor_still_works_after_sibling_failure(self, echo_server_command):
        registry = MockRegistry()
        bridge = McpToolBridge(
            [
                McpServerConfig(alias="ok", client=McpServer.stdio(echo_server_command)),
                McpServerConfig(alias="broken", client=McpServer.stdio(["/nonexistent"])),
            ]
        )
        bridge.set_registry(registry)
        await asyncio.wait_for(bridge.connect_all(), timeout=15.0)

        result = await asyncio.wait_for(
            registry.executors["ok__echo"]({"text": "still works"}), timeout=5.0
        )
        assert result == "still works"

        await bridge.disconnect_all()


# ---------------------------------------------------------------------------
# Disconnect
# ---------------------------------------------------------------------------


class TestDisconnect:
    async def test_disconnect_all_completes_without_error(self, alpha_command, beta_command):
        bridge = McpToolBridge(
            [
                McpServerConfig(alias="alpha", client=McpServer.stdio(alpha_command)),
                McpServerConfig(alias="beta", client=McpServer.stdio(beta_command)),
            ]
        )
        bridge.set_registry(MockRegistry())
        await asyncio.wait_for(bridge.connect_all(), timeout=15.0)
        # Must not raise
        await asyncio.wait_for(bridge.disconnect_all(), timeout=10.0)

    async def test_disconnect_closes_all_clients(self, alpha_command, beta_command):
        alpha_client = McpServer.stdio(alpha_command)
        beta_client = McpServer.stdio(beta_command)
        bridge = McpToolBridge(
            [
                McpServerConfig(alias="alpha", client=alpha_client),
                McpServerConfig(alias="beta", client=beta_client),
            ]
        )
        bridge.set_registry(MockRegistry())
        await asyncio.wait_for(bridge.connect_all(), timeout=15.0)
        await asyncio.wait_for(bridge.disconnect_all(), timeout=10.0)

        # After close, further calls should raise
        with pytest.raises(Exception):  # noqa: B017
            await asyncio.wait_for(alpha_client.list_tools(), timeout=2.0)
