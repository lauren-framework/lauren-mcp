"""Unit tests for the dynamic catalogue and connection registry."""

from __future__ import annotations

import asyncio
import json

from lauren_mcp._server._catalog import McpCatalogManager
from lauren_mcp._server._registry import McpConnectionRegistry
from lauren_mcp.server._meta import McpToolMeta


def tool(name: str) -> McpToolMeta:
    return McpToolMeta(name=name, description="", input_schema={}, method_name=name)


class TestCatalog:
    def test_register_and_list(self):
        catalog = McpCatalogManager()
        catalog.register_tool(tool("a"))
        catalog.register_tool(tool("b"))
        assert [t.name for t in catalog.list_tools()] == ["a", "b"]

    def test_unregister(self):
        catalog = McpCatalogManager()
        catalog.register_tool(tool("a"))
        assert catalog.unregister_tool("a") is True
        assert catalog.unregister_tool("a") is False
        assert catalog.list_tools() == []

    async def test_mutation_fires_broadcast(self):
        catalog = McpCatalogManager()
        seen: list[str] = []

        async def broadcast(method: str) -> None:
            seen.append(method)

        catalog.set_broadcast_fn(broadcast)
        catalog.register_tool(tool("a"))
        catalog.unregister_tool("a")
        await asyncio.sleep(0)  # let the created tasks run
        assert seen == [
            "notifications/tools/list_changed",
            "notifications/tools/list_changed",
        ]

    async def test_silent_before_broadcast_fn(self):
        catalog = McpCatalogManager()
        seen: list[str] = []

        async def broadcast(method: str) -> None:
            seen.append(method)

        catalog.register_tool(tool("seeded"))
        catalog.set_broadcast_fn(broadcast)
        await asyncio.sleep(0)
        assert seen == []

    def test_name_collision_raises_when_requested(self):
        import pytest

        from lauren_mcp import McpToolNameCollision

        catalog = McpCatalogManager()
        catalog.register_tool(tool("dup"))
        with pytest.raises(McpToolNameCollision):
            catalog.register_tool(tool("dup"), on_conflict="error")


class TestRegistry:
    async def test_broadcast_reaches_all_connections(self):
        registry = McpConnectionRegistry()
        received: dict[str, list[str]] = {"a": [], "b": []}

        async def send_a(raw: str) -> None:
            received["a"].append(raw)

        async def send_b(raw: str) -> None:
            received["b"].append(raw)

        registry.register(send_a)
        key_b = registry.register(send_b)
        await registry.broadcast_method("notifications/tools/list_changed")
        assert len(received["a"]) == 1
        assert json.loads(received["a"][0])["method"] == "notifications/tools/list_changed"
        assert len(received["b"]) == 1

        registry.unregister(key_b)
        await registry.broadcast_method("notifications/tools/list_changed")
        assert len(received["a"]) == 2
        assert len(received["b"]) == 1

    async def test_one_dead_connection_does_not_block_others(self):
        registry = McpConnectionRegistry()
        received: list[str] = []

        async def dead(raw: str) -> None:
            raise RuntimeError("socket closed")

        async def alive(raw: str) -> None:
            received.append(raw)

        registry.register(dead)
        registry.register(alive)
        await registry.broadcast({"jsonrpc": "2.0", "method": "x"})
        assert len(received) == 1

    def test_count(self):
        registry = McpConnectionRegistry()
        assert registry.count == 0
        key = registry.register(lambda raw: None)  # type: ignore[arg-type, return-value]
        assert registry.count == 1
        registry.unregister(key)
        assert registry.count == 0
