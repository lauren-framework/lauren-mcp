"""Unit tests for McpToolBridge and McpServerConfig."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from lauren_mcp._bridge import McpServerConfig, McpToolBridge
from lauren_mcp._types import ToolSchema


def make_tool(name: str) -> ToolSchema:
    return ToolSchema(name=name, description=f"Tool {name}", inputSchema={"type": "object"})


def make_mock_client(tools: list[ToolSchema] | None = None) -> AsyncMock:
    client = AsyncMock()
    client.connect = AsyncMock(return_value=None)
    client.list_tools = AsyncMock(return_value=tools or [])
    client.close = AsyncMock(return_value=None)
    return client


def make_mock_registry() -> MagicMock:
    registry = MagicMock()
    registry.register_mcp_server = MagicMock()
    return registry


class TestMcpServerConfig:
    def test_stores_alias(self):
        client = make_mock_client()
        cfg = McpServerConfig(alias="weather", client=client)
        assert cfg.alias == "weather"

    def test_stores_client(self):
        client = make_mock_client()
        cfg = McpServerConfig(alias="weather", client=client)
        assert cfg.client is client


class TestMcpToolBridgeConnectAll:
    @pytest.mark.asyncio
    async def test_connect_all_calls_connect_on_each_client(self):
        client_a = make_mock_client()
        client_b = make_mock_client()
        bridge = McpToolBridge(
            servers=[
                McpServerConfig(alias="a", client=client_a),
                McpServerConfig(alias="b", client=client_b),
            ]
        )
        await bridge.connect_all()
        client_a.connect.assert_awaited_once()
        client_b.connect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_all_calls_list_tools_after_connect(self):
        client = make_mock_client(tools=[make_tool("search")])
        bridge = McpToolBridge(servers=[McpServerConfig(alias="svc", client=client)])
        await bridge.connect_all()
        client.list_tools.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_connect_all_registers_tools_with_registry(self):
        tools = [make_tool("echo"), make_tool("search")]
        client = make_mock_client(tools=tools)
        registry = make_mock_registry()
        bridge = McpToolBridge(servers=[McpServerConfig(alias="svc", client=client)])
        bridge.set_registry(registry)
        await bridge.connect_all()
        registry.register_mcp_server.assert_called_once_with("svc", tools, client)

    @pytest.mark.asyncio
    async def test_connect_all_namespaces_tool_names_logged(self, caplog):
        """Tools should be logged with alias__tool_name format."""
        import logging

        tools = [make_tool("echo")]
        client = make_mock_client(tools=tools)
        bridge = McpToolBridge(servers=[McpServerConfig(alias="myalias", client=client)])

        with caplog.at_level(logging.INFO, logger="lauren_mcp._bridge"):
            await bridge.connect_all()

        # The log should contain alias__toolname
        assert any("myalias__echo" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_connect_all_logs_info_on_success(self, caplog):
        import logging

        tools = [make_tool("tool1"), make_tool("tool2")]
        client = make_mock_client(tools=tools)
        bridge = McpToolBridge(servers=[McpServerConfig(alias="my-svc", client=client)])

        with caplog.at_level(logging.INFO, logger="lauren_mcp._bridge"):
            await bridge.connect_all()

        assert any("my-svc" in record.message for record in caplog.records)
        assert any("2" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_connect_all_logs_error_on_failure(self, caplog):
        import logging

        client = make_mock_client()
        client.connect = AsyncMock(side_effect=RuntimeError("connection refused"))
        bridge = McpToolBridge(servers=[McpServerConfig(alias="bad-svc", client=client)])

        with caplog.at_level(logging.ERROR, logger="lauren_mcp._bridge"):
            await bridge.connect_all()

        assert any("bad-svc" in record.message for record in caplog.records)

    @pytest.mark.asyncio
    async def test_connect_all_continues_after_one_failure(self):
        """A failure in one server should not prevent other servers from connecting."""
        bad_client = make_mock_client()
        bad_client.connect = AsyncMock(side_effect=RuntimeError("refused"))
        good_client = make_mock_client(tools=[make_tool("echo")])
        registry = make_mock_registry()

        bridge = McpToolBridge(
            servers=[
                McpServerConfig(alias="bad", client=bad_client),
                McpServerConfig(alias="good", client=good_client),
            ]
        )
        bridge.set_registry(registry)
        await bridge.connect_all()

        # The good client should still have been connected and registered
        good_client.connect.assert_awaited_once()
        registry.register_mcp_server.assert_called_once_with(
            "good", [make_tool("echo")], good_client
        )

    @pytest.mark.asyncio
    async def test_registry_register_called_with_correct_alias(self):
        tools = [make_tool("search")]
        client = make_mock_client(tools=tools)
        registry = make_mock_registry()
        bridge = McpToolBridge(servers=[McpServerConfig(alias="search-svc", client=client)])
        bridge.set_registry(registry)
        await bridge.connect_all()
        call_args = registry.register_mcp_server.call_args[0]
        assert call_args[0] == "search-svc"

    @pytest.mark.asyncio
    async def test_multiple_servers_registered_independently(self):
        client_a = make_mock_client(tools=[make_tool("tool_a")])
        client_b = make_mock_client(tools=[make_tool("tool_b"), make_tool("tool_c")])
        registry = make_mock_registry()

        bridge = McpToolBridge(
            servers=[
                McpServerConfig(alias="svc-a", client=client_a),
                McpServerConfig(alias="svc-b", client=client_b),
            ]
        )
        bridge.set_registry(registry)
        await bridge.connect_all()

        assert registry.register_mcp_server.call_count == 2
        calls = registry.register_mcp_server.call_args_list
        aliases = [c[0][0] for c in calls]
        assert "svc-a" in aliases
        assert "svc-b" in aliases

    @pytest.mark.asyncio
    async def test_server_with_no_tools_still_connects(self):
        client = make_mock_client(tools=[])
        registry = make_mock_registry()
        bridge = McpToolBridge(servers=[McpServerConfig(alias="empty-svc", client=client)])
        bridge.set_registry(registry)
        await bridge.connect_all()
        client.connect.assert_awaited_once()
        registry.register_mcp_server.assert_called_once_with("empty-svc", [], client)


class TestMcpToolBridgeDisconnectAll:
    @pytest.mark.asyncio
    async def test_disconnect_all_closes_all_clients(self):
        client_a = make_mock_client()
        client_b = make_mock_client()
        bridge = McpToolBridge(
            servers=[
                McpServerConfig(alias="a", client=client_a),
                McpServerConfig(alias="b", client=client_b),
            ]
        )
        await bridge.disconnect_all()
        client_a.close.assert_awaited_once()
        client_b.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_all_cancels_watch_tasks(self):
        bridge = McpToolBridge(servers=[])

        # Create a real dummy task
        async def dummy():
            await asyncio.sleep(3600)

        task = asyncio.create_task(dummy())
        bridge._watch_tasks.append(task)
        await bridge.disconnect_all()
        # Yield control so the cancellation can propagate through the event loop
        await asyncio.sleep(0)
        assert task.cancelled() or task.done() or task.cancelling() > 0

    @pytest.mark.asyncio
    async def test_disconnect_all_handles_close_exception(self):
        """Exceptions from close() should not propagate."""
        client = make_mock_client()
        client.close = AsyncMock(side_effect=RuntimeError("close failed"))
        bridge = McpToolBridge(servers=[McpServerConfig(alias="svc", client=client)])
        # Should not raise
        await bridge.disconnect_all()


class TestMcpToolBridgeSetRegistry:
    def test_set_registry_stores_registry_reference(self):
        bridge = McpToolBridge(servers=[])
        registry = make_mock_registry()
        bridge.set_registry(registry)
        assert bridge._registry is registry

    def test_set_registry_replaces_previous_registry(self):
        bridge = McpToolBridge(servers=[])
        registry_a = make_mock_registry()
        registry_b = make_mock_registry()
        bridge.set_registry(registry_a)
        bridge.set_registry(registry_b)
        assert bridge._registry is registry_b

    @pytest.mark.asyncio
    async def test_no_registry_skips_registration(self):
        """When no registry is set, connect_all should not fail."""
        client = make_mock_client(tools=[make_tool("tool")])
        bridge = McpToolBridge(servers=[McpServerConfig(alias="svc", client=client)])
        # No set_registry call
        await bridge.connect_all()
        # Just verify it ran without error
        client.connect.assert_awaited_once()
