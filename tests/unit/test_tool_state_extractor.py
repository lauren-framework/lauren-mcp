"""Unit tests for State[T] injector on @mcp_tool methods."""

# NOTE: No 'from __future__ import annotations' — it would stringify annotations
# and break typing.get_type_hints() for locally-defined classes.

from dataclasses import dataclass, field
from typing import Any

import pytest
from lauren import StateExtractor as State

from lauren_mcp._server._context import McpToolContext as _McpToolContext
from lauren_mcp._types import JsonRpcRequest
from lauren_mcp.server._decorators import _is_state_annotation, mcp_tool
from lauren_mcp.server._handlers import _state_key, make_context_factory, make_tools_call_handler
from lauren_mcp.server._meta import McpToolMeta

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Module-level state types
# ---------------------------------------------------------------------------


@dataclass
class AuditLog:
    entries: list[str] = field(default_factory=list)


@dataclass
class RequestCache:
    items: dict[str, Any] = field(default_factory=dict)


class Outer:
    @dataclass
    class Inner:
        x: int = 0


# ---------------------------------------------------------------------------
# Module-level server stubs
# ---------------------------------------------------------------------------


class SrvWithAudit:
    @mcp_tool()
    async def my_tool(self, data: str, audit: State[AuditLog]) -> dict:
        return {}


class SrvWithCtxAndAudit:
    @mcp_tool()
    async def my_tool(
        self,
        data: str,
        audit: State[AuditLog],
        ctx: _McpToolContext,
    ) -> dict:
        return {}


class SrvTwoSameState:
    @mcp_tool()
    async def my_tool(
        self,
        a: State[AuditLog],
        b: State[AuditLog],
    ) -> dict:
        return {"same": a is b}


class SrvTwoDifferentState:
    @mcp_tool()
    async def my_tool(
        self,
        audit: State[AuditLog],
        cache: State[RequestCache],
    ) -> dict:
        return {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_req(name: str, arguments: dict | None = None) -> JsonRpcRequest:
    return JsonRpcRequest(
        jsonrpc="2.0",
        id=1,
        method="tools/call",
        params={"name": name, "arguments": arguments or {}},
    )


def _meta_for_fn(fn: Any) -> McpToolMeta:
    return fn.__mcp_tool_meta__


# ---------------------------------------------------------------------------
# _is_state_annotation
# ---------------------------------------------------------------------------


class TestIsStateAnnotation:
    def test_state_recognised(self):
        ann = State[AuditLog]
        assert _is_state_annotation(ann)

    def test_plain_type_not_state(self):
        assert not _is_state_annotation(AuditLog)

    def test_string_annotation(self):
        assert _is_state_annotation("State[AuditLog]")

    def test_no_lauren_returns_false(self, monkeypatch):
        import builtins

        original_import = builtins.__import__

        def mock_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "lauren":
                raise ImportError("no lauren")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        assert not _is_state_annotation(AuditLog)


# ---------------------------------------------------------------------------
# _state_key
# ---------------------------------------------------------------------------


class TestStateKey:
    def test_simple_class(self):
        assert _state_key(AuditLog) == "AuditLog"

    def test_nested_class(self):
        assert _state_key(Outer.Inner) == "Outer.Inner"


# ---------------------------------------------------------------------------
# Schema exclusion
# ---------------------------------------------------------------------------


class TestStateSchemaExclusion:
    def test_state_param_excluded_from_schema(self):
        meta = _meta_for_fn(SrvWithAudit.my_tool)
        assert "audit" not in meta.input_schema.get("properties", {})
        assert "audit" not in meta.input_schema.get("required", [])
        assert "data" in meta.input_schema.get("properties", {})

    def test_state_params_populated(self):
        meta = _meta_for_fn(SrvWithAudit.my_tool)
        assert "audit" in meta.state_params
        assert meta.state_params["audit"] is AuditLog


# ---------------------------------------------------------------------------
# State injection via handler
# ---------------------------------------------------------------------------


class TestStateInjection:
    async def test_first_call_creates_instance_in_ctx_state(self):
        from lauren_mcp._server._context import McpToolContext

        received: dict[str, Any] = {}

        class Srv:
            @mcp_tool()
            async def my_tool(
                self,
                data: str,
                audit: State[AuditLog],
                ctx: McpToolContext,
            ) -> dict:
                received["audit"] = audit
                received["ctx_state"] = ctx.state
                return {}

        meta = _meta_for_fn(Srv.my_tool)
        srv = Srv()
        ctx_factory = make_context_factory()
        handler = make_tools_call_handler(srv, [meta], context_factory=ctx_factory)
        await handler(_make_req("my_tool", {"data": "hello"}))
        assert isinstance(received["audit"], AuditLog)
        # ctx.state["AuditLog"] should be the same object as injected audit
        assert received["ctx_state"]["AuditLog"] is received["audit"]

    async def test_two_state_params_same_type_same_instance(self):
        import json

        meta = _meta_for_fn(SrvTwoSameState.my_tool)
        srv = SrvTwoSameState()
        handler = make_tools_call_handler(srv, [meta])
        result = await handler(_make_req("my_tool"))
        data = json.loads(result["content"][0]["text"])
        assert data["same"] is True

    async def test_separate_calls_get_fresh_instances(self):
        instances: list[Any] = []

        class Srv:
            @mcp_tool()
            async def my_tool(self, audit: State[AuditLog]) -> dict:
                instances.append(audit)
                return {}

        meta = _meta_for_fn(Srv.my_tool)
        srv = Srv()
        handler = make_tools_call_handler(srv, [meta])
        await handler(_make_req("my_tool"))
        await handler(_make_req("my_tool"))
        assert len(instances) == 2
        assert instances[0] is not instances[1]

    async def test_state_without_context_param(self):
        """State[T] works when McpToolContext is NOT declared."""
        received: dict[str, Any] = {}

        class Srv:
            @mcp_tool()
            async def my_tool(self, audit: State[AuditLog]) -> dict:
                audit.entries.append("hello")
                received["entries"] = audit.entries
                return {}

        meta = _meta_for_fn(Srv.my_tool)
        srv = Srv()
        handler = make_tools_call_handler(srv, [meta])
        await handler(_make_req("my_tool"))
        assert received["entries"] == ["hello"]

    async def test_two_different_state_types(self):
        received: dict[str, Any] = {}

        class Srv:
            @mcp_tool()
            async def my_tool(
                self,
                audit: State[AuditLog],
                cache: State[RequestCache],
            ) -> dict:
                received["audit"] = audit
                received["cache"] = cache
                return {}

        meta = _meta_for_fn(Srv.my_tool)
        srv = Srv()
        handler = make_tools_call_handler(srv, [meta])
        await handler(_make_req("my_tool"))
        assert isinstance(received["audit"], AuditLog)
        assert isinstance(received["cache"], RequestCache)
        assert received["audit"] is not received["cache"]

    async def test_state_type_with_required_init_raises(self):
        class BadState:
            def __init__(self, required_arg: str) -> None:
                pass

        class Srv:
            @mcp_tool()
            async def my_tool(self, s: State[BadState]) -> dict:
                return {}

        meta = _meta_for_fn(Srv.my_tool)
        srv = Srv()
        handler = make_tools_call_handler(srv, [meta])
        with pytest.raises(TypeError, match="BadState"):
            await handler(_make_req("my_tool"))

    async def test_state_mutation_visible_in_ctx(self):
        """Mutating via state param is visible through ctx.state."""
        from lauren_mcp._server._context import McpToolContext

        received: dict[str, Any] = {}

        class Srv:
            @mcp_tool()
            async def my_tool(
                self,
                ctx: McpToolContext,
                audit: State[AuditLog],
            ) -> dict:
                audit.entries.append("step")
                received["ctx_entry"] = ctx.state["AuditLog"].entries
                return {}

        meta = _meta_for_fn(Srv.my_tool)
        srv = Srv()
        ctx_factory = make_context_factory()
        handler = make_tools_call_handler(srv, [meta], context_factory=ctx_factory)
        await handler(_make_req("my_tool"))
        assert received["ctx_entry"] == ["step"]
