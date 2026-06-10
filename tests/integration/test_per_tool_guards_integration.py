"""Integration tests for Phase 2 per-tool guards.

Uses full Lauren DI: LaurenFactory.create(AppModule) + TestClient(app) +
WsTestClient(app) to exercise the entire pipeline from WS message to
JSON-RPC response.

Tests:
  - AllowGuard → tool result returned
  - DenyGuard → FORBIDDEN error returned, connection stays open
  - Unguarded tool unaffected by another tool's guard
  - tools/list schema unchanged (guards not visible to clients)
  - Guard auto-registered as DI provider (no explicit providers=[] needed)
  - McpExecutionContext.tool_name correct in guard's can_activate
  - McpExecutionContext.get_metadata() works for @set_metadata
  - Transport-level @use_guards still gates WS connection
  - MetadataGuard reads @set_metadata: public passes, private fails
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from lauren import LaurenFactory, injectable, module, set_metadata, use_guards
from lauren.testing import TestClient, WsTestClient

from lauren_mcp import McpExecutionContext, McpServerModule, mcp_server, mcp_tool

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Shared injectable guard classes
# ---------------------------------------------------------------------------


@injectable()
class AllowGuard:
    """Always allows the call."""

    async def can_activate(self, ctx: McpExecutionContext) -> bool:
        return True


@injectable()
class DenyGuard:
    """Always denies the call."""

    async def can_activate(self, ctx: McpExecutionContext) -> bool:
        return False


@injectable()
class MetadataGuard:
    """Allows when ctx.get_metadata('public') is True."""

    async def can_activate(self, ctx: McpExecutionContext) -> bool:
        return ctx.get_metadata("public", False) is True


# ---------------------------------------------------------------------------
# MCP server under test
# ---------------------------------------------------------------------------


@mcp_server("/mcp")
class GuardedServer:
    @mcp_tool()
    async def unguarded(self) -> str:
        """No guard — always succeeds."""
        return "hello"

    @use_guards(AllowGuard)
    @mcp_tool()
    async def allow_guarded(self) -> str:
        """AllowGuard always passes."""
        return "allowed"

    @use_guards(DenyGuard)
    @mcp_tool()
    async def deny_guarded(self) -> str:
        """DenyGuard always blocks."""
        return "should not reach"

    @set_metadata("public", True)
    @use_guards(MetadataGuard)
    @mcp_tool()
    async def public_tool(self) -> str:
        """MetadataGuard: public=True → passes."""
        return "public"

    @set_metadata("public", False)
    @use_guards(MetadataGuard)
    @mcp_tool()
    async def private_tool(self) -> str:
        """MetadataGuard: public=False → denied."""
        return "private"


GuardedModule = McpServerModule.for_root(GuardedServer, transport="ws")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _do_handshake(ws: Any, req_id: int = 0) -> None:
    await ws.send_json(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        }
    )
    await asyncio.wait_for(ws.receive_json(), timeout=5.0)
    await ws.send_json({"jsonrpc": "2.0", "method": "notifications/initialized"})


def _tools_call_msg(tool_name: str, args: dict[str, Any], *, req_id: int) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": args},
    }


def _tools_list_msg(*, req_id: int) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "method": "tools/list", "params": {}}


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def guarded_app():
    app = LaurenFactory.create(GuardedModule)
    TestClient(app)
    return app


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAllowGuard:
    async def test_allow_guard_passes(self, guarded_app: Any) -> None:
        """AllowGuard allows the call — result is returned."""
        async with WsTestClient(guarded_app).connect("/mcp/ws") as ws:
            await _do_handshake(ws, req_id=0)
            await ws.send_json(_tools_call_msg("allow_guarded", {}, req_id=1))
            resp = await asyncio.wait_for(ws.receive_json(), timeout=5.0)

        assert "result" in resp, f"Expected result, got: {resp}"
        assert resp["result"]["content"][0]["text"] == "allowed"
        assert resp["result"]["isError"] is False


class TestDenyGuard:
    async def test_deny_guard_returns_forbidden(self, guarded_app: Any) -> None:
        """DenyGuard blocks the call — FORBIDDEN error returned."""
        async with WsTestClient(guarded_app).connect("/mcp/ws") as ws:
            await _do_handshake(ws, req_id=0)
            await ws.send_json(_tools_call_msg("deny_guarded", {}, req_id=2))
            resp = await asyncio.wait_for(ws.receive_json(), timeout=5.0)

        assert "error" in resp, f"Expected error, got: {resp}"
        assert resp["error"]["code"] == -32603
        assert resp["error"]["data"]["type"] == "FORBIDDEN"
        assert resp["error"]["data"]["guard"] == "DenyGuard"

    async def test_connection_stays_open_after_rejection(self, guarded_app: Any) -> None:
        """After a FORBIDDEN error, the connection stays open for subsequent calls."""
        async with WsTestClient(guarded_app).connect("/mcp/ws") as ws:
            await _do_handshake(ws, req_id=0)

            # First call: rejected
            await ws.send_json(_tools_call_msg("deny_guarded", {}, req_id=3))
            rejected = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
            assert "error" in rejected

            # Second call on same connection: succeeds
            await ws.send_json(_tools_call_msg("unguarded", {}, req_id=4))
            ok_resp = await asyncio.wait_for(ws.receive_json(), timeout=5.0)

        assert "result" in ok_resp, f"Expected result, got: {ok_resp}"
        assert ok_resp["result"]["content"][0]["text"] == "hello"


class TestUnguardedTool:
    async def test_unguarded_tool_always_succeeds(self, guarded_app: Any) -> None:
        """Unguarded tool is unaffected by other tools' guards."""
        async with WsTestClient(guarded_app).connect("/mcp/ws") as ws:
            await _do_handshake(ws, req_id=0)
            await ws.send_json(_tools_call_msg("unguarded", {}, req_id=5))
            resp = await asyncio.wait_for(ws.receive_json(), timeout=5.0)

        assert "result" in resp, f"Expected result, got: {resp}"
        assert resp["result"]["content"][0]["text"] == "hello"


class TestToolsList:
    async def test_tools_list_includes_guarded_tools(self, guarded_app: Any) -> None:
        """tools/list returns ALL tools regardless of whether they have guards."""
        async with WsTestClient(guarded_app).connect("/mcp/ws") as ws:
            await _do_handshake(ws, req_id=0)
            await ws.send_json(_tools_list_msg(req_id=6))
            resp = await asyncio.wait_for(ws.receive_json(), timeout=5.0)

        names = {t["name"] for t in resp["result"]["tools"]}
        assert "unguarded" in names
        assert "allow_guarded" in names
        assert "deny_guarded" in names  # listed even though guard will deny calls
        assert "public_tool" in names
        assert "private_tool" in names


class TestGuardAutoRegistration:
    async def test_guard_auto_registered_without_explicit_providers(self) -> None:
        """Guard classes must not require explicit providers=[] listing.

        GuardedModule was created without providers=[AllowGuard, DenyGuard, ...].
        If auto-registration works, TestClient fires @post_construct without
        raising MissingProviderError.
        """
        # If we get here, auto-registration succeeded
        app = LaurenFactory.create(GuardedModule)
        TestClient(app)  # @post_construct fires — raises if DI fails


class TestGuardContext:
    async def test_guard_receives_correct_tool_name(self) -> None:
        """Guard's can_activate receives McpExecutionContext with correct tool_name."""
        received: list[McpExecutionContext] = []

        @injectable()
        class CapturingGuard:
            async def can_activate(self, ctx: McpExecutionContext) -> bool:
                received.append(ctx)
                return True

        @set_metadata("tag", "captured")
        @use_guards(CapturingGuard)
        @mcp_server("/mcp_capture")
        class CaptureServer:
            @set_metadata("method_tag", "method_val")
            @use_guards(CapturingGuard)
            @mcp_tool()
            async def tagged(self) -> str:
                return "ok"

        capture_mod = McpServerModule.for_root(CaptureServer, transport="ws")

        @module(imports=[capture_mod])
        class CaptureApp:
            pass

        app = LaurenFactory.create(CaptureApp)
        TestClient(app)

        async with WsTestClient(app).connect("/mcp_capture/ws") as ws:
            await _do_handshake(ws, req_id=0)
            await ws.send_json(_tools_call_msg("tagged", {}, req_id=1))
            await asyncio.wait_for(ws.receive_json(), timeout=5.0)

        # The per-tool guard should have been called (server-level guard is NOT a per-tool guard)
        assert len(received) >= 1
        # Find the call for the tool (not the server-level connection guard)
        tool_calls = [c for c in received if hasattr(c, "tool_name")]
        assert tool_calls, f"No McpExecutionContext calls received, got: {received}"
        ctx = tool_calls[0]
        assert ctx.tool_name == "tagged"
        assert ctx.server_class is CaptureServer

    async def test_guard_receives_set_metadata(self) -> None:
        """Guard receives merged @set_metadata keys via ctx.get_metadata()."""
        meta_received: list[dict[str, Any]] = []

        @injectable()
        class MetaCapture:
            async def can_activate(self, ctx: McpExecutionContext) -> bool:
                meta_received.append(dict(ctx.metadata))
                return True

        @set_metadata("server_key", "from_server")
        @mcp_server("/mcp_meta_capture")
        class MetaServer:
            @set_metadata("tool_key", "from_tool")
            @use_guards(MetaCapture)
            @mcp_tool()
            async def meta_tool(self) -> str:
                return "ok"

        meta_mod = McpServerModule.for_root(MetaServer, transport="ws")

        @module(imports=[meta_mod])
        class MetaApp:
            pass

        app = LaurenFactory.create(MetaApp)
        TestClient(app)

        async with WsTestClient(app).connect("/mcp_meta_capture/ws") as ws:
            await _do_handshake(ws, req_id=0)
            await ws.send_json(_tools_call_msg("meta_tool", {}, req_id=1))
            await asyncio.wait_for(ws.receive_json(), timeout=5.0)

        assert len(meta_received) >= 1
        md = meta_received[0]
        assert md.get("server_key") == "from_server"
        assert md.get("tool_key") == "from_tool"


class TestMetadataGuard:
    async def test_public_tool_passes(self, guarded_app: Any) -> None:
        """MetadataGuard reads @set_metadata('public', True) → passes."""
        async with WsTestClient(guarded_app).connect("/mcp/ws") as ws:
            await _do_handshake(ws, req_id=0)
            await ws.send_json(_tools_call_msg("public_tool", {}, req_id=7))
            resp = await asyncio.wait_for(ws.receive_json(), timeout=5.0)

        assert "result" in resp, f"Expected result for public_tool, got: {resp}"
        assert resp["result"]["content"][0]["text"] == "public"

    async def test_private_tool_denied(self, guarded_app: Any) -> None:
        """MetadataGuard reads @set_metadata('public', False) → denied."""
        async with WsTestClient(guarded_app).connect("/mcp/ws") as ws:
            await _do_handshake(ws, req_id=0)
            await ws.send_json(_tools_call_msg("private_tool", {}, req_id=8))
            resp = await asyncio.wait_for(ws.receive_json(), timeout=5.0)

        assert "error" in resp, f"Expected error for private_tool, got: {resp}"
        assert resp["error"]["data"]["type"] == "FORBIDDEN"


class TestTransportLevelGuard:
    async def test_transport_guard_still_gates_connection(self) -> None:
        """Transport-level @use_guards(DenyGuard) on @mcp_server rejects WS connection."""

        @use_guards(DenyGuard)
        @mcp_server("/denied_server")
        class DeniedServer:
            @use_guards(AllowGuard)
            @mcp_tool()
            async def tool(self) -> str:
                return "unreachable"

        denied_mod = McpServerModule.for_root(DeniedServer, transport="ws")

        @module(imports=[denied_mod])
        class DeniedApp:
            pass

        app = LaurenFactory.create(DeniedApp)
        TestClient(app)

        # Transport guard (DenyGuard) fires at @on_connect; WS connection is refused.
        with pytest.raises(Exception):  # noqa: B017
            async with WsTestClient(app).connect("/denied_server/ws") as ws:
                # Connection should be rejected
                await ws.send_json(
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-03-26",
                            "capabilities": {},
                            "clientInfo": {"name": "test", "version": "1"},
                        },
                    }
                )
                await asyncio.wait_for(ws.receive_json(), timeout=5.0)
