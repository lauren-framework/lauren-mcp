"""Integration tests for Phase 1: per-tool @set_metadata / @use_guards metadata.

Tests use the full Lauren DI stack: LaurenFactory.create + TestClient + WsTestClient.

Decorator ordering note: @mcp_tool() must be the OUTERMOST decorator so that
Lauren attribute-setting decorators (@use_guards, @set_metadata, etc.) run first
(they are inner/applied first), and then _read_method_decorators picks them up
when @mcp_tool() runs last.

Correct canonical order:
    @mcp_tool()                   # OUTERMOST — runs last, sees all Lauren attrs
    @use_guards(AdminGuard)       # runs second, sets __lauren_use_guards__
    @set_metadata("role", "admin")  # INNERMOST — runs first, sets __lauren_metadata__
    async def method(self): ...

Coverage:
  Group F: @set_metadata visible in McpToolContext at call time
  Group G: class-level vs method-level @set_metadata override
  Group H: @use_guards guard class auto-registered as DI provider (no MissingProviderError)
  Group I: tools/list unaffected by new meta fields
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from lauren import LaurenFactory, Scope, injectable, module, set_metadata, use_guards
from lauren.testing import TestClient, WsTestClient

from lauren_mcp import McpServerModule, McpToolContext, mcp_server, mcp_tool
from lauren_mcp.server._meta import MCP_TOOL_META

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helper: MCP WebSocket handshake + calls
# ---------------------------------------------------------------------------


async def _handshake(ws_session: Any, req_id: int = 1) -> dict:
    await ws_session.send_json(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0.0"},
            },
        }
    )
    resp = await asyncio.wait_for(ws_session.receive_json(), timeout=5.0)
    await ws_session.send_json({"jsonrpc": "2.0", "method": "notifications/initialized"})
    return resp


async def _call_tool(
    ws_session: Any, name: str, arguments: dict | None = None, req_id: int = 2
) -> dict:
    await ws_session.send_json(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        }
    )
    return await asyncio.wait_for(ws_session.receive_json(), timeout=5.0)


async def _list_tools(ws_session: Any, req_id: int = 3) -> dict:
    await ws_session.send_json(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/list",
            "params": None,
        }
    )
    return await asyncio.wait_for(ws_session.receive_json(), timeout=5.0)


# ---------------------------------------------------------------------------
# Group F: @set_metadata visible in ctx at call time
# ---------------------------------------------------------------------------

# NOTE: @mcp_tool() is outermost so it runs after @set_metadata has stored attrs.


@set_metadata("team", "core")
@mcp_server("/mcp_meta")
class MetaServer:
    @mcp_tool()
    @set_metadata("team", "core")
    async def tagged_tool(self, ctx: McpToolContext) -> str:  # type: ignore[misc]
        return ctx.get_metadata("team", "unset")

    @mcp_tool()
    async def plain_tool(self, ctx: McpToolContext) -> str:  # type: ignore[misc]
        return ctx.get_metadata("team", "unset")


@pytest.fixture(scope="module")
def meta_app():
    @module(imports=[McpServerModule.for_root(MetaServer)])
    class AppModule:
        pass

    app = LaurenFactory.create(AppModule)
    TestClient(app)
    return app


class TestSetMetadataVisibleInContext:
    async def test_f1_tagged_tool_returns_metadata_value(self, meta_app):
        """F1: WS call to tagged_tool returns 'core' (from @set_metadata)."""
        async with WsTestClient(meta_app).connect("/mcp_meta/ws") as ws:
            await _handshake(ws)
            resp = await _call_tool(ws, "tagged_tool")

        content = resp["result"]["content"]
        assert len(content) == 1
        assert content[0]["text"] == "core"

    async def test_f2_tagged_tool_does_not_return_unset(self, meta_app):
        """F2: Belt-and-suspenders: result is not 'unset'."""
        async with WsTestClient(meta_app).connect("/mcp_meta/ws") as ws:
            await _handshake(ws)
            resp = await _call_tool(ws, "tagged_tool")

        content = resp["result"]["content"]
        assert content[0]["text"] != "unset"

    async def test_f3_plain_tool_still_gets_class_level_metadata(self, meta_app):
        """Class-level @set_metadata('team', 'core') is visible in plain_tool too."""
        async with WsTestClient(meta_app).connect("/mcp_meta/ws") as ws:
            await _handshake(ws)
            resp = await _call_tool(ws, "plain_tool")

        content = resp["result"]["content"]
        assert content[0]["text"] == "core"


# ---------------------------------------------------------------------------
# Group G: class-level vs method-level @set_metadata override
# ---------------------------------------------------------------------------


@set_metadata("env", "prod")
@mcp_server("/mcp_override")
class OverrideServer:
    @mcp_tool()
    @set_metadata("env", "staging")
    async def overridden(self, ctx: McpToolContext) -> str:  # type: ignore[misc]
        return ctx.get_metadata("env", "unset")

    @mcp_tool()
    async def not_overridden(self, ctx: McpToolContext) -> str:  # type: ignore[misc]
        return ctx.get_metadata("env", "unset")


@pytest.fixture(scope="module")
def override_app():
    @module(imports=[McpServerModule.for_root(OverrideServer)])
    class AppModule2:
        pass

    app = LaurenFactory.create(AppModule2)
    TestClient(app)
    return app


class TestClassVsMethodMetadataOverride:
    async def test_g1_method_level_wins_for_overridden(self, override_app):
        """G1: @set_metadata('env', 'staging') on method overrides class 'prod'."""
        async with WsTestClient(override_app).connect("/mcp_override/ws") as ws:
            await _handshake(ws)
            resp = await _call_tool(ws, "overridden")

        content = resp["result"]["content"]
        assert content[0]["text"] == "staging"

    async def test_g2_class_level_preserved_for_not_overridden(self, override_app):
        """G2: Tool without method @set_metadata still sees class-level 'prod'."""
        async with WsTestClient(override_app).connect("/mcp_override/ws") as ws:
            await _handshake(ws)
            resp = await _call_tool(ws, "not_overridden")

        content = resp["result"]["content"]
        assert content[0]["text"] == "prod"


# ---------------------------------------------------------------------------
# Group H: @use_guards guard class auto-registered as DI provider
# ---------------------------------------------------------------------------


@injectable(scope=Scope.SINGLETON)
class NopGuard:
    """Guard that always passes — used to verify DI registration, not execution."""

    async def can_activate(self, ctx: Any) -> bool:
        return True


@mcp_server("/mcp_guarded")
class GuardedServer:
    # @mcp_tool() outermost so it sees @use_guards attrs after they're set
    @mcp_tool()
    @use_guards(NopGuard)
    async def guarded(self) -> str:  # type: ignore[misc]
        return "ok"


class TestGuardAutoRegistration:
    def test_h1_tool_meta_guards_populated(self):
        """H1: McpToolMeta for 'guarded' has meta.guards == (NopGuard,)."""
        method = GuardedServer.guarded
        meta = getattr(method, MCP_TOOL_META)
        assert meta.guards == (NopGuard,)

    async def test_h2_guard_auto_registered_no_missing_provider_error(self):
        """H2: LaurenFactory.create succeeds with NopGuard NOT in explicit providers=."""

        @module(imports=[McpServerModule.for_root(GuardedServer)])
        class AppModule3:
            pass

        # Should not raise MissingProviderError
        app = LaurenFactory.create(AppModule3)
        TestClient(app)  # triggers @post_construct

    async def test_h3_guarded_tool_calls_succeed(self):
        """H3: Guard is stored but not executed in Phase 1; tool runs normally."""

        @module(imports=[McpServerModule.for_root(GuardedServer)])
        class AppModule3b:
            pass

        app = LaurenFactory.create(AppModule3b)
        TestClient(app)

        async with WsTestClient(app).connect("/mcp_guarded/ws") as ws:
            await _handshake(ws)
            resp = await _call_tool(ws, "guarded")

        content = resp["result"]["content"]
        assert content[0]["text"] == "ok"


# ---------------------------------------------------------------------------
# Group I: tools/list unaffected by new meta fields
# ---------------------------------------------------------------------------


class TestToolsListUnaffected:
    async def test_i1_tools_list_contains_correct_names(self, meta_app):
        """I1: tools/list contains correct tool names when methods have @set_metadata."""
        async with WsTestClient(meta_app).connect("/mcp_meta/ws") as ws:
            await _handshake(ws)
            resp = await _list_tools(ws)

        tools = resp["result"]["tools"]
        names = {t["name"] for t in tools}
        assert "tagged_tool" in names
        assert "plain_tool" in names

    async def test_i2_tools_list_input_schema_unaffected(self, meta_app):
        """I2: tools/list inputSchema is unchanged (new meta fields are server-internal)."""
        async with WsTestClient(meta_app).connect("/mcp_meta/ws") as ws:
            await _handshake(ws)
            resp = await _list_tools(ws)

        tools = {t["name"]: t for t in resp["result"]["tools"]}
        tagged = tools["tagged_tool"]
        # inputSchema should not contain any metadata keys
        schema_keys = set(tagged.get("inputSchema", {}).get("properties", {}).keys())
        assert "team" not in schema_keys
        assert "role" not in schema_keys

    async def test_i3_tools_list_description_unchanged(self, meta_app):
        """I3: tools/list description is not affected by @set_metadata."""
        async with WsTestClient(meta_app).connect("/mcp_meta/ws") as ws:
            await _handshake(ws)
            resp = await _list_tools(ws)

        tools = {t["name"]: t for t in resp["result"]["tools"]}
        # description should be a string
        desc = tools["tagged_tool"].get("description", "")
        assert isinstance(desc, str)
