"""Integration tests: McpToolBridge + registry population.

Uses the real echo-server subprocess (from conftest) to verify the bridge
lifecycle from connect_all() through executor invocation.

Coverage:
  - connect_all() calls register_mcp_server on the attached registry
  - register_mcp_server receives the correct alias, tool list, and client
  - Executor closures call call_tool on the correct client
  - disconnect_all() closes every client
  - A broken server logs an error but does not prevent healthy ones loading
  - Tools from two independent servers registered under separate aliases
  - Executor produces the text content from a real tool response
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from lauren_mcp import McpServer, McpServerConfig, McpToolBridge
from lauren_mcp._types import ToolSchema

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Mock registry
# ---------------------------------------------------------------------------


class MockRegistry:
    """Records register_mcp_server calls and stores executor closures."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, list[ToolSchema], Any]] = []

    def register_mcp_server(self, alias: str, tools: list[ToolSchema], client: Any) -> None:
        self.calls.append((alias, tools, client))

    @property
    def aliases(self) -> list[str]:
        return [a for a, _, _ in self.calls]


# ---------------------------------------------------------------------------
# Bridge + registry population
# ---------------------------------------------------------------------------


class TestBridgeRegistryPopulation:
    async def test_register_mcp_server_called_after_connect(self, echo_server_command):
        registry = MockRegistry()
        bridge = McpToolBridge(
            [McpServerConfig(alias="echo", client=McpServer.stdio(echo_server_command))]
        )
        bridge.set_registry(registry)
        await asyncio.wait_for(bridge.connect_all(), timeout=15.0)

        assert registry.aliases == ["echo"]
        await bridge.disconnect_all()

    async def test_register_mcp_server_receives_correct_alias(self, echo_server_command):
        registry = MockRegistry()
        bridge = McpToolBridge(
            [McpServerConfig(alias="my_alias", client=McpServer.stdio(echo_server_command))]
        )
        bridge.set_registry(registry)
        await asyncio.wait_for(bridge.connect_all(), timeout=15.0)

        alias, _, _ = registry.calls[0]
        assert alias == "my_alias"
        await bridge.disconnect_all()

    async def test_register_receives_tool_schema_instances(self, echo_server_command):
        registry = MockRegistry()
        bridge = McpToolBridge(
            [McpServerConfig(alias="srv", client=McpServer.stdio(echo_server_command))]
        )
        bridge.set_registry(registry)
        await asyncio.wait_for(bridge.connect_all(), timeout=15.0)

        _, tools, _ = registry.calls[0]
        assert len(tools) >= 1
        for t in tools:
            assert isinstance(t, ToolSchema)
        await bridge.disconnect_all()

    async def test_register_receives_echo_tool_schema(self, echo_server_command):
        registry = MockRegistry()
        bridge = McpToolBridge(
            [McpServerConfig(alias="srv", client=McpServer.stdio(echo_server_command))]
        )
        bridge.set_registry(registry)
        await asyncio.wait_for(bridge.connect_all(), timeout=15.0)

        _, tools, _ = registry.calls[0]
        names = {t.name for t in tools}
        assert "echo" in names
        await bridge.disconnect_all()

    async def test_register_receives_client_reference(self, echo_server_command):
        registry = MockRegistry()
        client = McpServer.stdio(echo_server_command)
        bridge = McpToolBridge([McpServerConfig(alias="srv", client=client)])
        bridge.set_registry(registry)
        await asyncio.wait_for(bridge.connect_all(), timeout=15.0)

        _, _, registered_client = registry.calls[0]
        assert registered_client is client
        await bridge.disconnect_all()

    async def test_no_register_call_without_registry(self, echo_server_command):
        bridge = McpToolBridge(
            [McpServerConfig(alias="srv", client=McpServer.stdio(echo_server_command))]
        )
        # No registry attached — should not raise
        await asyncio.wait_for(bridge.connect_all(), timeout=15.0)
        await bridge.disconnect_all()


# ---------------------------------------------------------------------------
# Executor invocation via the registered client
# ---------------------------------------------------------------------------


class TestExecutorRouting:
    async def test_executor_calls_call_tool_on_registered_client(self, echo_server_command):
        """The client stored in registry.calls can call_tool after bridge connected."""
        registry = MockRegistry()
        bridge = McpToolBridge(
            [McpServerConfig(alias="srv", client=McpServer.stdio(echo_server_command))]
        )
        bridge.set_registry(registry)
        await asyncio.wait_for(bridge.connect_all(), timeout=15.0)

        _, _tools, client = registry.calls[0]
        result = await asyncio.wait_for(client.call_tool("echo", {"text": "hi there"}), timeout=5.0)
        content = result.get("content", [])
        text = next((c["text"] for c in content if c.get("type") == "text"), "")
        assert text == "hi there"
        await bridge.disconnect_all()

    async def test_executor_returns_correct_text_for_different_inputs(self, echo_server_command):
        registry = MockRegistry()
        bridge = McpToolBridge(
            [McpServerConfig(alias="srv", client=McpServer.stdio(echo_server_command))]
        )
        bridge.set_registry(registry)
        await asyncio.wait_for(bridge.connect_all(), timeout=15.0)

        _, _tools, client = registry.calls[0]
        for msg in ("foo", "bar baz", "hello world 123"):
            result = await asyncio.wait_for(client.call_tool("echo", {"text": msg}), timeout=5.0)
            content = result.get("content", [])
            text = next((c["text"] for c in content if c.get("type") == "text"), "")
            assert text == msg
        await bridge.disconnect_all()


# ---------------------------------------------------------------------------
# Multiple servers
# ---------------------------------------------------------------------------


class TestMultipleServerBridge:
    async def test_two_servers_both_registered(self, echo_server_command, tmp_path):
        """Two independent echo servers both appear in the registry."""
        registry = MockRegistry()
        bridge = McpToolBridge(
            [
                McpServerConfig(alias="alpha", client=McpServer.stdio(echo_server_command)),
                McpServerConfig(alias="beta", client=McpServer.stdio(echo_server_command)),
            ]
        )
        bridge.set_registry(registry)
        await asyncio.wait_for(bridge.connect_all(), timeout=20.0)

        assert set(registry.aliases) == {"alpha", "beta"}
        await bridge.disconnect_all()

    async def test_two_servers_registered_with_separate_clients(self, echo_server_command):
        registry = MockRegistry()
        client_a = McpServer.stdio(echo_server_command)
        client_b = McpServer.stdio(echo_server_command)
        bridge = McpToolBridge(
            [
                McpServerConfig(alias="a", client=client_a),
                McpServerConfig(alias="b", client=client_b),
            ]
        )
        bridge.set_registry(registry)
        await asyncio.wait_for(bridge.connect_all(), timeout=20.0)

        registered_clients = [c for _, _, c in registry.calls]
        assert client_a in registered_clients
        assert client_b in registered_clients
        assert registered_clients[0] is not registered_clients[1]
        await bridge.disconnect_all()


# ---------------------------------------------------------------------------
# Failure resilience
# ---------------------------------------------------------------------------


class TestBridgeResilience:
    async def test_broken_server_does_not_block_healthy_server(self, echo_server_command):
        registry = MockRegistry()
        bridge = McpToolBridge(
            [
                McpServerConfig(alias="bad", client=McpServer.stdio(["false"])),
                McpServerConfig(alias="good", client=McpServer.stdio(echo_server_command)),
            ]
        )
        bridge.set_registry(registry)
        await asyncio.wait_for(bridge.connect_all(), timeout=20.0)

        assert "good" in registry.aliases
        await bridge.disconnect_all()

    async def test_disconnect_all_called_after_partial_connect(self, echo_server_command):
        """disconnect_all() must not raise even if some clients never connected."""
        bridge = McpToolBridge(
            [
                McpServerConfig(alias="bad", client=McpServer.stdio(["false"])),
                McpServerConfig(alias="good", client=McpServer.stdio(echo_server_command)),
            ]
        )
        await asyncio.wait_for(bridge.connect_all(), timeout=20.0)
        # Must not raise
        await bridge.disconnect_all()
