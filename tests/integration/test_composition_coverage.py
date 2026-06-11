"""Integration tests for lauren_mcp.server._composition.

Covers:
  - make_mount_binder: TypeError when not @mcp_server, prefix applied, tools callable,
    resources and prompts registered, McpToolNameCollision on duplicate name
  - make_proxy_binder: connect/list_tools called at startup, tools registered with prefix,
    call forwarded via _RemoteToolTarget, pre_destruct unregisters + closes client
  - _RemoteToolTarget: call returns ToolOutput (dict and non-dict result paths)
  - McpToolNameCollision: raised correctly
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from lauren import LaurenFactory, module
from lauren.testing import TestClient, WsTestClient

from lauren_mcp import McpServerModule, mcp_prompt, mcp_resource, mcp_server, mcp_tool
from lauren_mcp.server._composition import (
    McpToolNameCollision,
    _RemoteToolTarget,
    _prefixed_metas,
    make_mount_binder,
    make_proxy_binder,
)
from lauren_mcp._types import ToolOutput, ToolSchema

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _ws_handshake(ws: Any) -> None:
    await ws.send_text(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "t", "version": "0"},
                },
            }
        )
    )
    await ws.receive_text()
    await ws.send_text(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}))


async def _ws_call(ws: Any, id_: int, method: str, params: dict | None = None) -> dict:
    msg: dict[str, Any] = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        msg["params"] = params
    await ws.send_text(json.dumps(msg))
    return json.loads(await ws.receive_text())


# ---------------------------------------------------------------------------
# Servers used in tests
# ---------------------------------------------------------------------------


@mcp_server("/mcp-comp-main")
class _MainServer:
    @mcp_tool()
    async def main_op(self) -> str:
        """Main operation."""
        return "main-result"


@mcp_server("/mcp-comp-side")
class _SideServer:
    @mcp_tool()
    async def side_op(self) -> str:
        """Side operation."""
        return "side-result"

    @mcp_tool()
    async def another_op(self, value: int) -> int:
        """Another operation with a parameter."""
        return value * 2


@mcp_server("/mcp-comp-rich")
class _RichServer:
    """Server with tools, resources, and prompts — for composition coverage."""

    @mcp_tool()
    async def rich_tool(self) -> str:
        """Rich tool."""
        return "rich"

    @mcp_resource("/rich/{item_id}")
    async def rich_resource(self, item_id: str) -> str:
        """Rich resource."""
        return f"rich-resource-{item_id}"

    @mcp_prompt()
    async def rich_prompt(self, topic: str = "default") -> str:
        """Rich prompt.

        Args:
            topic: The topic for the prompt.
        """
        return f"Tell me about {topic}"


# ---------------------------------------------------------------------------
# McpToolNameCollision
# ---------------------------------------------------------------------------


class TestMcpToolNameCollision:
    def test_is_exception(self):
        err = McpToolNameCollision("test")
        assert isinstance(err, Exception)

    def test_message_preserved(self):
        err = McpToolNameCollision("collision on 'foo'")
        assert "foo" in str(err)


# ---------------------------------------------------------------------------
# make_mount_binder — error cases (unit-level, no full Lauren app)
# ---------------------------------------------------------------------------


class TestMakeMountBinderErrors:
    def test_raises_type_error_for_non_mcp_server(self):
        class Plain:
            pass

        with pytest.raises(TypeError, match="@mcp_server"):
            make_mount_binder(Plain, "pfx_")

    def test_accepts_valid_mcp_server_class(self):
        binder_cls = make_mount_binder(_SideServer, "s_")
        assert binder_cls is not None

    def test_binder_class_name_reflects_server(self):
        binder_cls = make_mount_binder(_SideServer, "s_")
        assert "_SideServer" in binder_cls.__name__


# ---------------------------------------------------------------------------
# make_mount_binder — integration (full Lauren DI app)
# ---------------------------------------------------------------------------


class TestMakeMountBinderIntegration:
    async def test_mounted_tools_exposed_with_prefix(self):
        binder = make_mount_binder(_SideServer, "s_")

        @module(
            imports=[
                McpServerModule.for_root(
                    _MainServer,
                    transport="ws",
                    providers=[_SideServer, binder],
                )
            ]
        )
        class _App:
            pass

        app = LaurenFactory.create(_App)
        TestClient(app)

        async with WsTestClient(app).connect("/mcp-comp-main/ws") as ws:
            await _ws_handshake(ws)
            listing = await _ws_call(ws, 1, "tools/list")
            names = {t["name"] for t in listing["result"]["tools"]}
            assert "main_op" in names
            assert "s_side_op" in names
            assert "s_another_op" in names

    async def test_mounted_tool_callable(self):
        binder = make_mount_binder(_SideServer, "side_")

        @module(
            imports=[
                McpServerModule.for_root(
                    _MainServer,
                    transport="ws",
                    providers=[_SideServer, binder],
                )
            ]
        )
        class _App2:
            pass

        app = LaurenFactory.create(_App2)
        TestClient(app)

        async with WsTestClient(app).connect("/mcp-comp-main/ws") as ws:
            await _ws_handshake(ws)
            result = await _ws_call(ws, 1, "tools/call", {"name": "side_side_op", "arguments": {}})
            assert result["result"]["content"][0]["text"] == "side-result"

    async def test_mounted_tool_with_param(self):
        binder = make_mount_binder(_SideServer, "p_")

        @module(
            imports=[
                McpServerModule.for_root(
                    _MainServer,
                    transport="ws",
                    providers=[_SideServer, binder],
                )
            ]
        )
        class _App3:
            pass

        app = LaurenFactory.create(_App3)
        TestClient(app)

        async with WsTestClient(app).connect("/mcp-comp-main/ws") as ws:
            await _ws_handshake(ws)
            result = await _ws_call(
                ws, 1, "tools/call", {"name": "p_another_op", "arguments": {"value": 7}}
            )
            assert result["result"]["content"][0]["text"] == "14"


# ---------------------------------------------------------------------------
# make_mount_binder — name collision
# ---------------------------------------------------------------------------


@mcp_server("/mcp-collision-a")
class _CollisionServerA:
    @mcp_tool()
    async def shared_name(self) -> str:
        """Shared tool name."""
        return "from-a"


@mcp_server("/mcp-collision-b")
class _CollisionServerB:
    @mcp_tool()
    async def shared_name(self) -> str:
        """Same tool name."""
        return "from-b"


class TestMakeMountBinderCollision:
    async def test_duplicate_tool_name_raises_collision(self):
        """When two mounted servers expose the same tool name, McpToolNameCollision is raised."""
        binder_a = make_mount_binder(_CollisionServerA, "")  # no prefix — will collide
        binder_b = make_mount_binder(_CollisionServerB, "")

        @module(
            imports=[
                McpServerModule.for_root(
                    _MainServer,
                    transport="ws",
                    providers=[_CollisionServerA, binder_a, _CollisionServerB, binder_b],
                )
            ]
        )
        class _ColApp:
            pass

        app = LaurenFactory.create(_ColApp)
        with pytest.raises(McpToolNameCollision):
            TestClient(app)


# ---------------------------------------------------------------------------
# _prefixed_metas — unit tests
# ---------------------------------------------------------------------------


class TestPrefixedMetas:
    def test_tools_get_prefix(self):
        tools, resources, prompts = _prefixed_metas(_SideServer, "pfx_")
        names = {t.name for t in tools}
        assert "pfx_side_op" in names
        assert "pfx_another_op" in names

    def test_empty_prefix(self):
        tools, _, _ = _prefixed_metas(_SideServer, "")
        names = {t.name for t in tools}
        assert "side_op" in names

    def test_no_resources_no_prompts(self):
        _, resources, prompts = _prefixed_metas(_SideServer, "x_")
        assert resources == []
        assert prompts == []

    def test_attribute_error_in_getattr_is_skipped(self):
        """If getattr raises AttributeError for an attr listed by dir(), it is silently skipped."""

        @mcp_server("/mcp-attr-error-test")
        class _BrokenAttrServer:
            @mcp_tool()
            async def normal_tool(self) -> str:
                """Normal tool."""
                return "ok"

        # Override __dir__ to include a name that getattr will raise on.
        # A __get__ descriptor that raises AttributeError works when accessed on class.
        class _RaisingDescriptor:
            def __get__(self, obj: Any, objtype: Any = None) -> None:
                raise AttributeError("simulated missing via descriptor")

        _BrokenAttrServer.phantom = _RaisingDescriptor()  # type: ignore[attr-defined]

        # _prefixed_metas should still return the normal_tool without crashing
        tools, resources, prompts = _prefixed_metas(_BrokenAttrServer, "t_")
        tool_names = {t.name for t in tools}
        assert "t_normal_tool" in tool_names


# ---------------------------------------------------------------------------
# _RemoteToolTarget — unit tests
# ---------------------------------------------------------------------------


class TestRemoteToolTarget:
    async def test_call_dict_result_with_content(self):
        client = MagicMock()
        client.call_tool = AsyncMock(
            return_value={"content": [{"type": "text", "text": "hello"}], "isError": False}
        )
        target = _RemoteToolTarget(client, "remote_tool")
        result = await target.call(foo="bar")
        assert isinstance(result, ToolOutput)
        assert result.content == [{"type": "text", "text": "hello"}]
        assert not result.is_error

    async def test_call_dict_result_is_error(self):
        client = MagicMock()
        client.call_tool = AsyncMock(return_value={"content": [], "isError": True})
        target = _RemoteToolTarget(client, "remote_tool")
        result = await target.call()
        assert result.is_error

    async def test_call_non_dict_result(self):
        client = MagicMock()
        client.call_tool = AsyncMock(return_value="plain string result")
        target = _RemoteToolTarget(client, "remote_tool")
        result = await target.call()
        assert isinstance(result, ToolOutput)
        assert result.content[0]["text"] == "plain string result"

    async def test_call_forwards_kwargs(self):
        client = MagicMock()
        client.call_tool = AsyncMock(return_value={"content": [], "isError": False})
        target = _RemoteToolTarget(client, "my_remote")
        await target.call(x=1, y=2)
        client.call_tool.assert_called_once_with("my_remote", {"x": 1, "y": 2})

    async def test_call_dict_result_with_structured_content(self):
        client = MagicMock()
        client.call_tool = AsyncMock(
            return_value={
                "content": [],
                "structuredContent": {"key": "value"},
                "isError": False,
            }
        )
        target = _RemoteToolTarget(client, "t")
        result = await target.call()
        assert result.structured_content == {"key": "value"}


# ---------------------------------------------------------------------------
# make_proxy_binder — unit tests (mock client, no full Lauren app)
# ---------------------------------------------------------------------------


class TestMakeProxyBinderUnit:
    def test_returns_class(self):
        client = MagicMock()
        cls = make_proxy_binder(client, "remote_")
        assert cls is not None

    def test_class_name_includes_prefix(self):
        client = MagicMock()
        cls = make_proxy_binder(client, "myprefix_")
        assert "myprefix_" in cls.__name__

    def test_class_name_empty_prefix_uses_remote(self):
        client = MagicMock()
        cls = make_proxy_binder(client, "")
        assert "remote" in cls.__name__


# ---------------------------------------------------------------------------
# make_proxy_binder — integration (mock client, full Lauren app)
# ---------------------------------------------------------------------------


def _make_mock_mcp_client(tools: list[ToolSchema]) -> MagicMock:
    """Build a mock McpClientProtocol that returns fixed tool list."""
    client = MagicMock()
    client.connect = AsyncMock()
    client.list_tools = AsyncMock(return_value=tools)
    client.call_tool = AsyncMock(
        return_value={"content": [{"type": "text", "text": "proxy-result"}], "isError": False}
    )
    client.close = AsyncMock()
    return client


class TestMakeProxyBinderIntegration:
    async def test_proxy_tools_registered(self):
        remote_tools = [
            ToolSchema(
                name="remote_op",
                description="A remote op",
                inputSchema={"type": "object", "properties": {}},
            ),
        ]
        mock_client = _make_mock_mcp_client(remote_tools)
        proxy = make_proxy_binder(mock_client, "r_")

        @mcp_server("/mcp-proxy-host")
        class _ProxyHost:
            @mcp_tool()
            async def local_op(self) -> str:
                """Local op."""
                return "local"

        @module(
            imports=[
                McpServerModule.for_root(
                    _ProxyHost,
                    transport="ws",
                    providers=[proxy],
                )
            ]
        )
        class _ProxyApp:
            pass

        app = LaurenFactory.create(_ProxyApp)
        TestClient(app)

        # client.connect and list_tools should have been called at startup
        mock_client.connect.assert_called_once()
        mock_client.list_tools.assert_called_once()

        async with WsTestClient(app).connect("/mcp-proxy-host/ws") as ws:
            await _ws_handshake(ws)
            listing = await _ws_call(ws, 1, "tools/list")
            names = {t["name"] for t in listing["result"]["tools"]}
            assert "r_remote_op" in names
            assert "local_op" in names

    async def test_proxy_tool_call_forwarded(self):
        remote_tools = [
            ToolSchema(
                name="echo",
                description="Echo op",
                inputSchema={"type": "object", "properties": {"msg": {"type": "string"}}},
            ),
        ]
        mock_client = _make_mock_mcp_client(remote_tools)
        proxy = make_proxy_binder(mock_client, "prx_")

        @mcp_server("/mcp-proxy-call")
        class _ProxyCallHost:
            @mcp_tool()
            async def noop(self) -> str:
                """Noop."""
                return "noop"

        @module(
            imports=[
                McpServerModule.for_root(
                    _ProxyCallHost,
                    transport="ws",
                    providers=[proxy],
                )
            ]
        )
        class _ProxyCallApp:
            pass

        app = LaurenFactory.create(_ProxyCallApp)
        TestClient(app)

        async with WsTestClient(app).connect("/mcp-proxy-call/ws") as ws:
            await _ws_handshake(ws)
            result = await _ws_call(
                ws, 1, "tools/call", {"name": "prx_echo", "arguments": {"msg": "hi"}}
            )
            assert result["result"]["content"][0]["text"] == "proxy-result"
            mock_client.call_tool.assert_called()

    async def test_proxy_tool_collision_raises(self):
        """Two proxy binders with same prefix+name should raise McpToolNameCollision."""
        tools = [ToolSchema(name="clash", description="Clash", inputSchema={})]
        client_a = _make_mock_mcp_client(tools)
        client_b = _make_mock_mcp_client(tools)
        proxy_a = make_proxy_binder(client_a, "")
        proxy_b = make_proxy_binder(client_b, "")

        @mcp_server("/mcp-proxy-clash")
        class _ClashHost:
            @mcp_tool()
            async def host_op(self) -> str:
                """Host op."""
                return "host"

        @module(
            imports=[
                McpServerModule.for_root(
                    _ClashHost,
                    transport="ws",
                    providers=[proxy_a, proxy_b],
                )
            ]
        )
        class _ClashApp:
            pass

        app = LaurenFactory.create(_ClashApp)
        with pytest.raises(McpToolNameCollision):
            TestClient(app)


# ---------------------------------------------------------------------------
# make_mount_binder — resources and prompts coverage
# ---------------------------------------------------------------------------


class TestMakeMountBinderResourcesAndPrompts:
    def test_prefixed_metas_with_resources(self):
        tools, resources, prompts = _prefixed_metas(_RichServer, "r_")
        resource_names = {r.name for r in resources}
        # The name is whatever the @mcp_resource decorator assigns (likely the URI template)
        assert any("r_" in n for n in resource_names)

    def test_prefixed_metas_with_prompts(self):
        _, _, prompts = _prefixed_metas(_RichServer, "p_")
        prompt_names = {p.name for p in prompts}
        assert any("p_" in n for n in prompt_names)

    async def test_mounted_resources_registered(self):
        """Resources from a mounted server are registered with prefix (name field)."""
        binder = make_mount_binder(_RichServer, "rich_")

        @module(
            imports=[
                McpServerModule.for_root(
                    _MainServer,
                    transport="ws",
                    providers=[_RichServer, binder],
                )
            ]
        )
        class _RichApp:
            pass

        app = LaurenFactory.create(_RichApp)
        TestClient(app)

        async with WsTestClient(app).connect("/mcp-comp-main/ws") as ws:
            await _ws_handshake(ws)
            # Tools include rich_tool with prefix — proves binder ran successfully
            listing = await _ws_call(ws, 1, "tools/list")
            names = {t["name"] for t in listing["result"]["tools"]}
            assert "rich_rich_tool" in names

            # Resources are also registered (register_resource called at lines 84-86)
            res_listing = await _ws_call(ws, 2, "resources/list")
            # Resources appear — at least the one from _RichServer should be there
            assert len(res_listing["result"]["resources"]) >= 1

    async def test_mounted_prompts_registered(self):
        """Prompts from a mounted server are registered with prefix."""
        binder = make_mount_binder(_RichServer, "rp_")

        @module(
            imports=[
                McpServerModule.for_root(
                    _MainServer,
                    transport="ws",
                    providers=[_RichServer, binder],
                )
            ]
        )
        class _RichPromptApp:
            pass

        app = LaurenFactory.create(_RichPromptApp)
        TestClient(app)

        async with WsTestClient(app).connect("/mcp-comp-main/ws") as ws:
            await _ws_handshake(ws)
            prompt_listing = await _ws_call(ws, 1, "prompts/list")
            names = {p["name"] for p in prompt_listing["result"]["prompts"]}
            assert any("rp_" in n for n in names)


# ---------------------------------------------------------------------------
# make_proxy_binder — pre_destruct (_unbind) coverage
# ---------------------------------------------------------------------------


class TestMakeProxyBinderUnbind:
    async def test_proxy_unbind_called_on_shutdown(self):
        """_unbind (pre_destruct) unregisters tools and calls client.close()."""
        remote_tools = [
            ToolSchema(
                name="unbind_op",
                description="Op to unbind",
                inputSchema={"type": "object", "properties": {}},
            ),
        ]
        mock_client = _make_mock_mcp_client(remote_tools)
        proxy = make_proxy_binder(mock_client, "ub_")

        @mcp_server("/mcp-proxy-unbind")
        class _UnbindHost:
            @mcp_tool()
            async def host_op(self) -> str:
                """Host op."""
                return "host"

        @module(
            imports=[
                McpServerModule.for_root(
                    _UnbindHost,
                    transport="ws",
                    providers=[proxy],
                )
            ]
        )
        class _UnbindApp:
            pass

        app = LaurenFactory.create(_UnbindApp)
        TestClient(app)

        # Verify proxy tools were registered
        mock_client.connect.assert_called_once()
        mock_client.list_tools.assert_called_once()

        # Now trigger shutdown — should call _unbind which calls client.close()
        await app.shutdown()

        mock_client.close.assert_called_once()

    async def test_proxy_unbind_handles_close_exception(self):
        """_unbind catches exceptions from client.close() gracefully."""
        remote_tools = [
            ToolSchema(
                name="err_op",
                description="Op",
                inputSchema={},
            ),
        ]
        mock_client = _make_mock_mcp_client(remote_tools)
        mock_client.close = AsyncMock(side_effect=RuntimeError("connection broken"))
        proxy = make_proxy_binder(mock_client, "err_")

        @mcp_server("/mcp-proxy-errclose")
        class _ErrCloseHost:
            @mcp_tool()
            async def host_op(self) -> str:
                """Host op."""
                return "host"

        @module(
            imports=[
                McpServerModule.for_root(
                    _ErrCloseHost,
                    transport="ws",
                    providers=[proxy],
                )
            ]
        )
        class _ErrCloseApp:
            pass

        app = LaurenFactory.create(_ErrCloseApp)
        TestClient(app)

        # Shutdown should not raise even though client.close() raises
        await app.shutdown()  # should not raise
