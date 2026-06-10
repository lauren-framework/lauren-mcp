"""Unit tests for per-tool interceptor chain (Phase 3).

All tests are pure unit tests: no subprocess, no network, no Lauren DI.
The interceptor chain helpers are called directly.
"""

from __future__ import annotations

import pytest

from lauren_mcp import McpCallHandler
from lauren_mcp.server._handlers import _execute_with_interceptors
from lauren_mcp.server._meta import McpToolMeta

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool_meta(
    *,
    name: str = "test_tool",
    interceptors: tuple[type, ...] = (),
    structured_output: bool | None = None,
) -> McpToolMeta:
    """Build a minimal McpToolMeta for tests."""
    return McpToolMeta(
        name=name,
        description="test",
        input_schema={"type": "object", "properties": {}},
        method_name=name,
        interceptors=interceptors,
        structured_output=structured_output,
    )


def _make_exec_ctx(tool_name: str = "test_tool") -> object:
    """Build a minimal McpExecutionContext-like object for tests."""
    from lauren_mcp._server._exec_context import McpExecutionContext

    return McpExecutionContext(
        tool_name=tool_name,
        method_name=tool_name,
        server_class=type("FakeServer", (), {}),
    )


# ---------------------------------------------------------------------------
# McpCallHandler tests
# ---------------------------------------------------------------------------


async def test_mcp_call_handler_calls_wrapped_fn() -> None:
    """McpCallHandler.handle() invokes the inner function and returns its result."""

    async def inner() -> dict:
        return {"content": [], "isError": False}

    handler = McpCallHandler(inner)
    result = await handler.handle()
    assert result == {"content": [], "isError": False}


async def test_mcp_call_handler_propagates_exception() -> None:
    """Exceptions from the inner function propagate through handle()."""

    async def inner() -> dict:
        raise ValueError("boom")

    handler = McpCallHandler(inner)
    with pytest.raises(ValueError, match="boom"):
        await handler.handle()


async def test_mcp_call_handler_in_all() -> None:
    """McpCallHandler is exported from the top-level lauren_mcp package."""
    import lauren_mcp

    assert hasattr(lauren_mcp, "McpCallHandler")
    assert "McpCallHandler" in lauren_mcp.__all__


# ---------------------------------------------------------------------------
# _execute_with_interceptors — no interceptors fast-path
# ---------------------------------------------------------------------------


async def test_no_interceptors_calls_method_directly() -> None:
    """When interceptors=(), the method is called directly without wrapping."""
    meta = _make_tool_meta(interceptors=())
    call_count: list[bool] = []

    async def method() -> str:
        call_count.append(True)
        return "result"

    out = await _execute_with_interceptors(meta, method, {}, None, None, None)
    assert len(call_count) == 1
    assert out["content"][0]["text"] == "result"


async def test_no_interceptors_container_none_fast_path() -> None:
    """container=None with no interceptors still works (fast path)."""
    meta = _make_tool_meta(interceptors=())

    async def method() -> str:
        return "hello"

    out = await _execute_with_interceptors(meta, method, {}, _make_exec_ctx(), None, None)
    assert out["content"][0]["text"] == "hello"


# ---------------------------------------------------------------------------
# Single interceptor
# ---------------------------------------------------------------------------


async def test_single_interceptor_called_with_correct_args() -> None:
    """The interceptor's intercept() receives exec_ctx and McpCallHandler."""
    received: list[tuple[object, object]] = []

    class RecordingInterceptor:
        async def intercept(self, ctx: object, call_handler: object) -> dict:
            received.append((ctx, call_handler))
            return await call_handler.handle()  # type: ignore[union-attr]

    meta = _make_tool_meta(interceptors=(RecordingInterceptor,))
    exec_ctx = _make_exec_ctx()
    method_called: list[bool] = []

    async def method() -> dict:
        method_called.append(True)
        return {"value": 42}

    out = await _execute_with_interceptors(meta, method, {}, exec_ctx, None, None)
    assert len(received) == 1
    ctx_arg, handler_arg = received[0]
    assert ctx_arg is exec_ctx
    assert isinstance(handler_arg, McpCallHandler)
    assert len(method_called) == 1
    assert out.get("structuredContent", {}).get("value") == 42


# ---------------------------------------------------------------------------
# Two interceptors — ordering A(B(method))
# ---------------------------------------------------------------------------


async def test_two_interceptors_a_outermost() -> None:
    """Given @use_interceptors(A, B), execution order is A → B → method → B → A."""
    order: list[str] = []

    class A:
        async def intercept(self, ctx: object, ch: McpCallHandler) -> dict:
            order.append("A_before")
            result = await ch.handle()
            order.append("A_after")
            return result

    class B:
        async def intercept(self, ctx: object, ch: McpCallHandler) -> dict:
            order.append("B_before")
            result = await ch.handle()
            order.append("B_after")
            return result

    meta = _make_tool_meta(interceptors=(A, B))
    exec_ctx = _make_exec_ctx()

    async def method() -> str:
        order.append("method")
        return "hello"

    await _execute_with_interceptors(meta, method, {}, exec_ctx, None, None)
    assert order == ["A_before", "B_before", "method", "B_after", "A_after"]


# ---------------------------------------------------------------------------
# Interceptor modifies structuredContent
# ---------------------------------------------------------------------------


async def test_interceptor_can_modify_structured_content() -> None:
    """An interceptor can add keys to structuredContent before returning."""

    class AddFlagInterceptor:
        async def intercept(self, ctx: object, ch: McpCallHandler) -> dict:
            result = await ch.handle()
            sc = result.get("structuredContent")
            if isinstance(sc, dict):
                sc["_intercepted"] = True
            return result

    meta = _make_tool_meta(interceptors=(AddFlagInterceptor,))
    exec_ctx = _make_exec_ctx()

    async def method() -> dict:
        return {"key": "value"}  # dict → structuredContent = {"key": "value"}

    out = await _execute_with_interceptors(meta, method, {}, exec_ctx, None, None)
    assert out["structuredContent"]["_intercepted"] is True
    assert out["structuredContent"]["key"] == "value"


# ---------------------------------------------------------------------------
# Interceptor exception propagates
# ---------------------------------------------------------------------------


async def test_interceptor_exception_propagates() -> None:
    """An exception raised inside intercept() propagates out of the chain."""

    class BoomInterceptor:
        async def intercept(self, ctx: object, ch: McpCallHandler) -> dict:
            raise RuntimeError("interceptor failed")

    meta = _make_tool_meta(interceptors=(BoomInterceptor,))

    async def method() -> dict:
        return {}

    with pytest.raises(RuntimeError, match="interceptor failed"):
        await _execute_with_interceptors(meta, method, {}, _make_exec_ctx(), None, None)


# ---------------------------------------------------------------------------
# ToolStream tool — interceptors see the final accumulated dict
# ---------------------------------------------------------------------------


async def test_interceptor_sees_final_stream_result() -> None:
    """Interceptors receive the fully accumulated ToolStream result dict."""
    seen_results: list[dict] = []

    class RecordInterceptor:
        async def intercept(self, ctx: object, ch: McpCallHandler) -> dict:
            result = await ch.handle()
            seen_results.append(result)
            return result

    meta = _make_tool_meta(interceptors=(RecordInterceptor,))

    async def gen_fn():  # type: ignore[return]
        yield "chunk_a"
        yield "chunk_b"

    async def method() -> object:
        from lauren_mcp._types import ToolStream

        return ToolStream(generator=gen_fn())

    out = await _execute_with_interceptors(meta, method, {}, _make_exec_ctx(), None, None)
    # Interceptor received exactly one dict — the accumulated final result.
    assert len(seen_results) == 1
    # The joined string from ["chunk_a", "chunk_b"] is "chunk_achunk_b".
    assert seen_results[0]["content"][0]["text"] == "chunk_achunk_b"
    assert out["content"][0]["text"] == "chunk_achunk_b"


# ---------------------------------------------------------------------------
# Closure ordering test
# ---------------------------------------------------------------------------


async def test_closure_ordering_use_interceptors() -> None:
    """@use_interceptors(A, B) → A is outermost, B is innermost (closure-safe).

    Note: interceptors are patched onto meta in for_root() because Python's
    decorator ordering means @use_interceptors is applied AFTER @mcp_tool()
    has already built the meta.  This test uses _patch_interceptors_from_fn
    to simulate that patching.
    """
    order: list[str] = []

    class IcA:
        async def intercept(self, ctx: object, ch: McpCallHandler) -> dict:
            order.append("A")
            result = await ch.handle()
            order.append("A_post")
            return result

    class IcB:
        async def intercept(self, ctx: object, ch: McpCallHandler) -> dict:
            order.append("B")
            result = await ch.handle()
            order.append("B_post")
            return result

    from lauren import use_interceptors

    from lauren_mcp.server._decorators import mcp_tool
    from lauren_mcp.server._meta import MCP_TOOL_META

    @use_interceptors(IcB)
    @use_interceptors(IcA)
    @mcp_tool()
    async def my_tool(self: object) -> str:
        order.append("method")
        return "ok"

    meta = getattr(my_tool, MCP_TOOL_META)

    # Simulate the patching that for_root() does.
    from lauren.decorators import USE_INTERCEPTORS

    raw_ics = list(getattr(my_tool, USE_INTERCEPTORS, []) or [])
    meta.interceptors = tuple(raw_ics)
    assert meta.interceptors == (IcA, IcB)

    exec_ctx = _make_exec_ctx()

    async def bound_method() -> str:
        order.append("method")
        return "ok"

    # Reset and run through the chain
    order.clear()
    await _execute_with_interceptors(meta, bound_method, {}, exec_ctx, None, None)
    assert order == ["A", "B", "method", "B_post", "A_post"]


# ---------------------------------------------------------------------------
# McpExecutionContext export
# ---------------------------------------------------------------------------


async def test_mcp_execution_context_in_all() -> None:
    """McpExecutionContext is exported from the top-level lauren_mcp package."""
    import lauren_mcp

    assert hasattr(lauren_mcp, "McpExecutionContext")
    assert "McpExecutionContext" in lauren_mcp.__all__


async def test_mcp_execution_context_fields() -> None:
    """McpExecutionContext carries the expected attributes."""
    from lauren_mcp import McpExecutionContext

    ctx = McpExecutionContext(
        tool_name="my_tool",
        method_name="my_tool",
        server_class=type("S", (), {}),
        headers={"x-user": "alice"},
        session_id="sess-1",
        metadata={"env": "prod"},
        tool_use_id="req-42",
    )
    assert ctx.tool_name == "my_tool"
    assert ctx.headers == {"x-user": "alice"}
    assert ctx.session_id == "sess-1"
    assert ctx.metadata["env"] == "prod"
    assert ctx.tool_use_id == "req-42"


# ---------------------------------------------------------------------------
# _read_method_decorators — Phase 1 decorator reader
# ---------------------------------------------------------------------------


async def test_read_method_decorators_reads_use_interceptors() -> None:
    """After for_root() patching, McpToolMeta.interceptors contains @use_interceptors classes.

    Note: @use_interceptors applied AFTER @mcp_tool() (outer decorator), so the
    interceptors are stored on the function's __lauren_use_interceptors__ attribute.
    for_root() patches the meta when it discovers the class methods.
    """
    from lauren import use_interceptors
    from lauren.decorators import USE_INTERCEPTORS

    from lauren_mcp.server._decorators import mcp_tool
    from lauren_mcp.server._meta import MCP_TOOL_META

    class MyInterceptor:
        async def intercept(self, ctx: object, ch: object) -> dict:
            return await ch.handle()  # type: ignore[union-attr]

    @use_interceptors(MyInterceptor)
    @mcp_tool()
    async def decorated_tool(self: object) -> str:
        return "ok"

    # Verify the decorator set the attribute on the function
    assert MyInterceptor in getattr(decorated_tool, USE_INTERCEPTORS, [])

    # Simulate for_root() patching
    meta: McpToolMeta = getattr(decorated_tool, MCP_TOOL_META)
    raw_ics = list(getattr(decorated_tool, USE_INTERCEPTORS, []) or [])
    meta.interceptors = tuple(raw_ics)
    assert MyInterceptor in meta.interceptors


async def test_read_method_decorators_rejects_use_middlewares() -> None:
    """@use_middlewares on a tool method raises TypeError when for_root() processes it."""
    from lauren import middleware, use_middlewares

    from lauren_mcp.server._decorators import _read_method_decorators, mcp_tool

    @middleware()
    class MyMiddleware:
        async def dispatch(self, ctx: object, call_next: object) -> object:
            return await call_next()  # type: ignore[operator]

    @use_middlewares(MyMiddleware)
    @mcp_tool()
    async def bad_tool(self: object) -> str:
        return "fail"

    # _read_method_decorators raises TypeError when USE_MIDDLEWARES is set
    with pytest.raises(TypeError, match="use_middlewares"):
        _read_method_decorators(bad_tool)


async def test_meta_interceptors_default_empty() -> None:
    """McpToolMeta.interceptors defaults to empty tuple when no @use_interceptors."""
    from lauren_mcp.server._decorators import mcp_tool
    from lauren_mcp.server._meta import MCP_TOOL_META

    @mcp_tool()
    async def plain_tool(self: object) -> str:
        return "ok"

    meta: McpToolMeta = getattr(plain_tool, MCP_TOOL_META)
    assert meta.interceptors == ()
