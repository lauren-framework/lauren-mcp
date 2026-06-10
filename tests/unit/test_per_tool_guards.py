"""Unit tests for Phase 2 per-tool guard infrastructure.

Tests:
  - McpExecutionContext construction and get_metadata()
  - McpExecutionContext is frozen
  - McpForbiddenError attributes and inheritance
  - _run_tool_guards: container=None → no-op
  - _run_tool_guards: all guards pass → no exception
  - _run_tool_guards: first guard rejects → McpForbiddenError, second never called
  - _run_tool_guards: guard raises exception → McpForbiddenError (not original)
  - Dispatcher catches McpForbiddenError → INTERNAL_ERROR with FORBIDDEN data
  - make_tools_call_handler: guards skipped when container=None → method called
  - make_tools_call_handler: no guards → method called even with container
  - metadata merging: method-level overrides class-level
"""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from lauren_mcp._server._dispatcher import McpDispatcher, McpForbiddenError
from lauren_mcp._server._exec_context import McpExecutionContext
from lauren_mcp._types import JsonRpcErrorResponse, JsonRpcRequest, McpErrorCode
from lauren_mcp.server._handlers import _run_tool_guards, make_tools_call_handler
from lauren_mcp.server._meta import McpToolMeta

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_exec_ctx(**overrides: Any) -> McpExecutionContext:
    defaults: dict[str, Any] = dict(
        tool_name="test_tool",
        method_name="test_tool",
        server_class=object,
        headers=None,
        execution_context=None,
        session_id=None,
        metadata={},
        tool_use_id=1,
    )
    defaults.update(overrides)
    return McpExecutionContext(**defaults)


class _MockContainer:
    """Minimal container mock that resolves a single guard instance."""

    def __init__(self, guard_instance: Any) -> None:
        self._instance = guard_instance

    async def resolve(self, cls: type, **kwargs: Any) -> Any:
        return self._instance


class _MultiMockContainer:
    """Container mock mapping class → instance."""

    def __init__(self, mapping: dict[type, Any]) -> None:
        self._mapping = mapping

    async def resolve(self, cls: type, **kwargs: Any) -> Any:
        return self._mapping[cls]


# ---------------------------------------------------------------------------
# McpExecutionContext tests
# ---------------------------------------------------------------------------


class TestMcpExecutionContext:
    def test_construction_and_get_metadata(self) -> None:
        ctx = McpExecutionContext(
            tool_name="do_thing",
            method_name="do_thing",
            server_class=object,
            headers={"authorization": "Bearer tok"},
            execution_context=None,
            session_id="s-1",
            metadata={"required_role": "admin"},
            tool_use_id=42,
        )
        assert ctx.tool_name == "do_thing"
        assert ctx.method_name == "do_thing"
        assert ctx.session_id == "s-1"
        assert ctx.tool_use_id == 42
        assert ctx.get_metadata("required_role") == "admin"
        assert ctx.get_metadata("missing_key", "default") == "default"
        assert ctx.get_metadata("missing_key") is None

    def test_is_frozen(self) -> None:
        ctx = _make_exec_ctx()
        with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
            ctx.tool_name = "other"  # type: ignore[misc]

    def test_metadata_merge_semantics(self) -> None:
        """Method-level keys win over class-level on collision."""
        server_meta = {"role": "user", "env": "prod"}
        tool_meta = {"role": "admin"}
        merged = {**server_meta, **tool_meta}
        ctx = McpExecutionContext(
            tool_name="t",
            method_name="t",
            server_class=object,
            headers=None,
            execution_context=None,
            session_id=None,
            metadata=merged,
            tool_use_id=None,
        )
        assert ctx.get_metadata("role") == "admin"
        assert ctx.get_metadata("env") == "prod"

    def test_headers_can_be_none(self) -> None:
        ctx = _make_exec_ctx(headers=None)
        assert ctx.headers is None

    def test_tool_use_id_can_be_none(self) -> None:
        ctx = _make_exec_ctx(tool_use_id=None)
        assert ctx.tool_use_id is None


# ---------------------------------------------------------------------------
# McpForbiddenError tests
# ---------------------------------------------------------------------------


class TestMcpForbiddenError:
    def test_has_guard_name(self) -> None:
        exc = McpForbiddenError("denied", guard_name="AdminGuard")
        assert exc.guard_name == "AdminGuard"
        assert str(exc) == "denied"

    def test_default_guard_name_is_empty_string(self) -> None:
        exc = McpForbiddenError("denied")
        assert exc.guard_name == ""

    def test_is_runtime_error(self) -> None:
        assert isinstance(McpForbiddenError("x"), RuntimeError)

    def test_is_exception(self) -> None:
        assert isinstance(McpForbiddenError("x"), Exception)


# ---------------------------------------------------------------------------
# _run_tool_guards tests
# ---------------------------------------------------------------------------


class TestRunToolGuards:
    async def test_container_none_is_noop(self) -> None:
        """When container is None, guards are silently skipped."""
        called: list[bool] = []

        class ShouldNotBeCalled:
            async def can_activate(self, ctx: Any) -> bool:
                called.append(True)
                return False

        exec_ctx = _make_exec_ctx()
        await _run_tool_guards((ShouldNotBeCalled,), exec_ctx, None, None)
        assert called == []

    async def test_empty_guards_is_noop(self) -> None:
        """Empty tuple means no guards — no exception."""
        exec_ctx = _make_exec_ctx()
        container = _MockContainer(None)
        await _run_tool_guards((), exec_ctx, container, None)  # no exception

    async def test_all_guards_pass(self) -> None:
        class AllowGuard:
            async def can_activate(self, ctx: Any) -> bool:
                return True

        exec_ctx = _make_exec_ctx()
        container = _MockContainer(AllowGuard())
        await _run_tool_guards((AllowGuard,), exec_ctx, container, None)  # no exception

    async def test_first_guard_rejects_raises_forbidden(self) -> None:
        calls: list[str] = []

        class DenyGuard:
            async def can_activate(self, ctx: Any) -> bool:
                calls.append("deny")
                return False

        class NeverCalled:
            async def can_activate(self, ctx: Any) -> bool:
                calls.append("never")
                return True

        exec_ctx = _make_exec_ctx()
        container = _MultiMockContainer({DenyGuard: DenyGuard(), NeverCalled: NeverCalled()})

        with pytest.raises(McpForbiddenError) as exc_info:
            await _run_tool_guards((DenyGuard, NeverCalled), exec_ctx, container, None)

        assert "DenyGuard" in exc_info.value.guard_name
        assert calls == ["deny"]  # NeverCalled was NOT invoked (short-circuit)

    async def test_guard_exception_treated_as_rejection(self) -> None:
        class BrokenGuard:
            async def can_activate(self, ctx: Any) -> bool:
                raise RuntimeError("broken!")

        exec_ctx = _make_exec_ctx()
        container = _MockContainer(BrokenGuard())

        with pytest.raises(McpForbiddenError) as exc_info:
            await _run_tool_guards((BrokenGuard,), exec_ctx, container, None)

        # The original RuntimeError is NOT re-raised; McpForbiddenError is raised instead
        assert exc_info.value.guard_name == "BrokenGuard"

    async def test_multiple_guards_all_pass(self) -> None:
        calls: list[str] = []

        class GuardA:
            async def can_activate(self, ctx: Any) -> bool:
                calls.append("a")
                return True

        class GuardB:
            async def can_activate(self, ctx: Any) -> bool:
                calls.append("b")
                return True

        exec_ctx = _make_exec_ctx()
        container = _MultiMockContainer({GuardA: GuardA(), GuardB: GuardB()})
        await _run_tool_guards((GuardA, GuardB), exec_ctx, container, None)
        assert calls == ["a", "b"]

    async def test_guard_receives_correct_context(self) -> None:
        received: list[McpExecutionContext] = []

        class CapturingGuard:
            async def can_activate(self, ctx: Any) -> bool:
                received.append(ctx)
                return True

        exec_ctx = _make_exec_ctx(tool_name="my_tool", metadata={"key": "val"})
        container = _MockContainer(CapturingGuard())
        await _run_tool_guards((CapturingGuard,), exec_ctx, container, None)

        assert len(received) == 1
        assert received[0].tool_name == "my_tool"
        assert received[0].get_metadata("key") == "val"


# ---------------------------------------------------------------------------
# McpDispatcher catches McpForbiddenError → FORBIDDEN data
# ---------------------------------------------------------------------------


class TestDispatcherCatchesForbidden:
    async def test_forbidden_error_returns_internal_error_with_forbidden_data(
        self,
    ) -> None:
        dispatcher = McpDispatcher()
        dispatcher._register_builtins()

        async def _forbidden_handler(params: Any) -> dict[str, Any]:
            raise McpForbiddenError("denied by TestGuard", guard_name="TestGuard")

        dispatcher.register("tools/call", _forbidden_handler)

        req = JsonRpcRequest(method="tools/call", params={}, id=99)
        resp = await dispatcher.dispatch(req)

        assert isinstance(resp, JsonRpcErrorResponse)
        assert resp.error.code == McpErrorCode.INTERNAL_ERROR
        assert resp.error.data is not None
        assert resp.error.data["type"] == "FORBIDDEN"
        assert resp.error.data["guard"] == "TestGuard"

    async def test_forbidden_error_message_is_preserved(self) -> None:
        dispatcher = McpDispatcher()
        dispatcher._register_builtins()

        async def _handler(params: Any) -> dict[str, Any]:
            raise McpForbiddenError("Guard 'X' denied the call", guard_name="X")

        dispatcher.register("tools/call", _handler)

        req = JsonRpcRequest(method="tools/call", params={}, id=1)
        resp = await dispatcher.dispatch(req)

        assert isinstance(resp, JsonRpcErrorResponse)
        assert "denied" in resp.error.message


# ---------------------------------------------------------------------------
# make_tools_call_handler — guard integration
# ---------------------------------------------------------------------------


class TestMakeToolsCallHandlerGuards:
    async def test_guards_skipped_when_container_none(self) -> None:
        """When container=None, guards are not executed and the method is called."""
        called: list[bool] = []

        class FakeServer:
            async def my_tool(self) -> str:
                called.append(True)
                return "ok"

        meta = McpToolMeta(
            name="my_tool",
            description="",
            input_schema={"type": "object", "properties": {}},
            method_name="my_tool",
            guards=(object,),  # would fail if actually resolved
        )
        handler = make_tools_call_handler(
            FakeServer(),
            [meta],
            container=None,  # guards disabled
        )
        req = JsonRpcRequest(method="tools/call", params={"name": "my_tool"}, id=1)
        result = await handler(req)
        assert called == [True]
        assert result["isError"] is False

    async def test_no_guards_calls_method_directly(self) -> None:
        """A tool with no guards calls the method even with container provided."""
        called: list[bool] = []

        class FakeServer:
            async def no_guard_tool(self) -> str:
                called.append(True)
                return "called"

        meta = McpToolMeta(
            name="no_guard_tool",
            description="",
            input_schema={"type": "object", "properties": {}},
            method_name="no_guard_tool",
            guards=(),
        )

        fake_container = object()  # container provided but guards=() → ignored
        handler = make_tools_call_handler(FakeServer(), [meta], container=fake_container)
        req = JsonRpcRequest(method="tools/call", params={"name": "no_guard_tool"}, id=2)
        result = await handler(req)
        assert called == [True]
        assert result["isError"] is False

    async def test_allow_guard_allows_call(self) -> None:
        """A tool with an AllowGuard gets called normally."""
        result_holder: list[str] = []

        class FakeServer:
            async def guarded_tool(self) -> str:
                result_holder.append("called")
                return "success"

        class AllowGuard:
            async def can_activate(self, ctx: Any) -> bool:
                return True

        meta = McpToolMeta(
            name="guarded_tool",
            description="",
            input_schema={"type": "object", "properties": {}},
            method_name="guarded_tool",
            guards=(AllowGuard,),
        )
        container = _MockContainer(AllowGuard())
        handler = make_tools_call_handler(FakeServer(), [meta], container=container)
        req = JsonRpcRequest(method="tools/call", params={"name": "guarded_tool"}, id=3)
        result = await handler(req)
        assert result_holder == ["called"]
        assert result["isError"] is False

    async def test_deny_guard_raises_forbidden(self) -> None:
        """A tool with a DenyGuard raises McpForbiddenError."""

        class FakeServer:
            async def deny_tool(self) -> str:
                return "should not reach"

        class DenyGuard:
            async def can_activate(self, ctx: Any) -> bool:
                return False

        meta = McpToolMeta(
            name="deny_tool",
            description="",
            input_schema={"type": "object", "properties": {}},
            method_name="deny_tool",
            guards=(DenyGuard,),
        )
        container = _MockContainer(DenyGuard())
        handler = make_tools_call_handler(FakeServer(), [meta], container=container)
        req = JsonRpcRequest(method="tools/call", params={"name": "deny_tool"}, id=4)

        with pytest.raises(McpForbiddenError) as exc_info:
            await handler(req)

        assert exc_info.value.guard_name == "DenyGuard"

    async def test_metadata_available_to_guard(self) -> None:
        """Guard receives merged metadata from server_metadata and tool_metadata."""
        received_metadata: list[dict[str, Any]] = []

        class MetaCheckGuard:
            async def can_activate(self, ctx: Any) -> bool:
                received_metadata.append(dict(ctx.metadata))
                return True

        class FakeServer:
            async def meta_tool(self) -> str:
                return "ok"

        meta = McpToolMeta(
            name="meta_tool",
            description="",
            input_schema={"type": "object", "properties": {}},
            method_name="meta_tool",
            guards=(MetaCheckGuard,),
            tool_metadata={"tool_key": "tool_val", "shared": "tool"},
        )
        container = _MockContainer(MetaCheckGuard())
        handler = make_tools_call_handler(
            FakeServer(),
            [meta],
            container=container,
            server_metadata={"server_key": "server_val", "shared": "server"},
        )
        req = JsonRpcRequest(method="tools/call", params={"name": "meta_tool"}, id=5)
        await handler(req)

        assert len(received_metadata) == 1
        md = received_metadata[0]
        assert md["server_key"] == "server_val"
        assert md["tool_key"] == "tool_val"
        assert md["shared"] == "tool"  # method-level wins
