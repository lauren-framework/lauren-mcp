"""Integration tests for per-tool @use_interceptors on @mcp_tool and @mcp_resource.

Uses a real Lauren DI application with WsTestClient (WebSocket transport).
Verifies end-to-end interceptor behaviour without subprocesses.

Coverage:
  - AuditInterceptor logs tool call
  - TimingInterceptor adds _elapsed_ms to structuredContent
  - Interceptor scoped to its declared tool (does not affect others)
  - tools/list schema unchanged (no interceptors field)
  - Two interceptors on one tool (both run)
  - Interceptor auto-registered as DI provider (no MissingProviderError)
  - Resource method with interceptor
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from lauren import LaurenFactory, interceptor, module, use_interceptors
from lauren.testing import TestClient, WsTestClient

from lauren_mcp import (
    McpCallHandler,
    McpExecutionContext,
    McpServerModule,
    mcp_resource,
    mcp_server,
    mcp_tool,
)

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Shared interceptor implementations
# ---------------------------------------------------------------------------


@interceptor()
class AuditInterceptor:
    """Records each tool call in a class-level log for assertion."""

    audit_log: list[dict[str, Any]] = []

    async def intercept(self, ctx: McpExecutionContext, call_handler: McpCallHandler) -> dict:
        result = await call_handler.handle()
        AuditInterceptor.audit_log.append(
            {
                "tool": ctx.tool_name,
                "is_error": result.get("isError", False),
            }
        )
        return result


@interceptor()
class TimingInterceptor:
    """Adds _elapsed_ms to structuredContent of the result."""

    async def intercept(self, ctx: McpExecutionContext, call_handler: McpCallHandler) -> dict:
        import time

        start = time.perf_counter()
        result = await call_handler.handle()
        elapsed = time.perf_counter() - start
        sc = result.get("structuredContent")
        if isinstance(sc, dict):
            sc["_elapsed_ms"] = int(elapsed * 1000)
        return result


# ---------------------------------------------------------------------------
# MCP server under test
# ---------------------------------------------------------------------------


@mcp_server("/mcp")
class InterceptorTestServer:
    @use_interceptors(AuditInterceptor)
    @mcp_tool()
    async def audited_tool(self) -> dict:
        return {"status": "ok"}

    @use_interceptors(TimingInterceptor)
    @mcp_tool()
    async def timed_tool(self) -> dict:
        return {"value": 99}

    @use_interceptors(AuditInterceptor, TimingInterceptor)
    @mcp_tool()
    async def doubly_wrapped_tool(self) -> dict:
        return {"x": 1}

    @mcp_tool()
    async def plain_tool(self) -> dict:
        return {"plain": True}

    @use_interceptors(AuditInterceptor)
    @mcp_resource("test://resource")
    async def intercepted_resource(self) -> str:
        return "resource_content"


# ---------------------------------------------------------------------------
# Lauren app fixture (module-scoped — built once for all tests in this file)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def lauren_app():
    """Build the Lauren app with McpServerModule once for all tests."""

    @module(imports=[McpServerModule.for_root(InterceptorTestServer)])
    class AppModule:
        pass

    app = LaurenFactory.create(AppModule)
    TestClient(app)  # trigger @post_construct hooks
    return app


@pytest.fixture
def ws(lauren_app):
    """Return a WsTestClient bound to the Lauren app."""
    return WsTestClient(lauren_app)


# ---------------------------------------------------------------------------
# WS helper
# ---------------------------------------------------------------------------


async def _ws_call(ws_client: WsTestClient, method: str, params: dict) -> dict:
    """Perform a full MCP handshake + single method call and return the result."""
    async with ws_client.connect("/mcp/ws") as conn:
        # Handshake
        await conn.send_json(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1.0.0"},
                },
            }
        )
        await asyncio.wait_for(conn.receive_json(), timeout=5.0)
        await conn.send_json({"jsonrpc": "2.0", "method": "notifications/initialized"})

        # Method call
        await conn.send_json({"jsonrpc": "2.0", "id": 2, "method": method, "params": params})
        resp = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
        assert "error" not in resp, f"RPC error: {resp}"
        return resp["result"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAuditInterceptor:
    async def test_audit_interceptor_records_tool_call(self, ws: WsTestClient) -> None:
        """AuditInterceptor.intercept() fires and records the call."""
        AuditInterceptor.audit_log.clear()
        await _ws_call(ws, "tools/call", {"name": "audited_tool", "arguments": {}})
        assert len(AuditInterceptor.audit_log) == 1
        assert AuditInterceptor.audit_log[0]["tool"] == "audited_tool"
        assert AuditInterceptor.audit_log[0]["is_error"] is False

    async def test_audit_interceptor_records_correct_tool_name(self, ws: WsTestClient) -> None:
        """The tool_name in ctx matches the registered MCP name."""
        AuditInterceptor.audit_log.clear()
        await _ws_call(ws, "tools/call", {"name": "audited_tool", "arguments": {}})
        assert AuditInterceptor.audit_log[0]["tool"] == "audited_tool"


class TestTimingInterceptor:
    async def test_timing_interceptor_adds_elapsed_ms(self, ws: WsTestClient) -> None:
        """TimingInterceptor adds _elapsed_ms to structuredContent."""
        result = await _ws_call(ws, "tools/call", {"name": "timed_tool", "arguments": {}})
        sc = result.get("structuredContent", {})
        assert "_elapsed_ms" in sc, f"structuredContent={sc}"
        assert isinstance(sc["_elapsed_ms"], int)
        assert sc["_elapsed_ms"] >= 0


class TestInterceptorScoping:
    async def test_interceptor_does_not_fire_for_plain_tool(self, ws: WsTestClient) -> None:
        """Interceptor declared on one tool does not affect another."""
        AuditInterceptor.audit_log.clear()
        await _ws_call(ws, "tools/call", {"name": "plain_tool", "arguments": {}})
        assert len(AuditInterceptor.audit_log) == 0, (
            f"AuditInterceptor fired for plain_tool: {AuditInterceptor.audit_log}"
        )

    async def test_two_interceptors_both_run(self, ws: WsTestClient) -> None:
        """With @use_interceptors(AuditInterceptor, TimingInterceptor), both fire."""
        AuditInterceptor.audit_log.clear()
        result = await _ws_call(ws, "tools/call", {"name": "doubly_wrapped_tool", "arguments": {}})
        # AuditInterceptor logged the call
        assert len(AuditInterceptor.audit_log) == 1
        assert AuditInterceptor.audit_log[0]["tool"] == "doubly_wrapped_tool"
        # TimingInterceptor added _elapsed_ms
        sc = result.get("structuredContent", {})
        assert "_elapsed_ms" in sc, f"structuredContent={sc}"


class TestToolsListSchema:
    async def test_tools_list_schema_has_no_interceptors_field(self, ws: WsTestClient) -> None:
        """tools/list response never exposes an 'interceptors' field."""
        result = await _ws_call(ws, "tools/list", {})
        for tool in result["tools"]:
            assert "interceptors" not in tool, (
                f"Tool {tool['name']!r} has unexpected 'interceptors' key"
            )


class TestAutoRegistration:
    async def test_interceptor_auto_registered_as_provider(self) -> None:
        """Building the module works without explicitly listing interceptors in providers."""
        _McpModule = McpServerModule.for_root(InterceptorTestServer)
        # Extract provider list from the module's __lauren_module__ ModuleMeta
        module_meta = _McpModule.__dict__.get("__lauren_module__")
        all_providers: list[Any] = list(getattr(module_meta, "providers", []) or [])
        assert AuditInterceptor in all_providers, (
            f"AuditInterceptor not in providers: {all_providers}"
        )
        assert TimingInterceptor in all_providers, (
            f"TimingInterceptor not in providers: {all_providers}"
        )


class TestResourceInterceptor:
    async def test_resource_interceptor_fires_on_resource_read(self, ws: WsTestClient) -> None:
        """@use_interceptors on @mcp_resource wraps the resource read."""
        AuditInterceptor.audit_log.clear()
        await _ws_call(ws, "resources/read", {"uri": "test://resource"})
        assert len(AuditInterceptor.audit_log) == 1
        assert AuditInterceptor.audit_log[0]["tool"] == "intercepted_resource"

    async def test_resource_interceptor_returns_correct_content(self, ws: WsTestClient) -> None:
        """Resource result is correctly returned after interceptor runs."""
        result = await _ws_call(ws, "resources/read", {"uri": "test://resource"})
        assert "contents" in result
        assert len(result["contents"]) >= 1
        assert result["contents"][0].get("text") == "resource_content"
