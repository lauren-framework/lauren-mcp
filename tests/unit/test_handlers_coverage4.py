"""Even more coverage tests for _handlers.py — targeting final uncovered paths."""

from __future__ import annotations

import asyncio
import dataclasses
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lauren_mcp._types import (
    JsonRpcRequest,
    TextContent,
    ToolOutput,
    ToolStream,
)
from lauren_mcp.server._handlers import (
    _resolve_di,
    _run_pipes,
    _run_tool_exception_handlers,
    make_resources_read_handler,
    make_tools_call_handler,
)
from lauren_mcp.server._meta import (
    HeaderParamSpec,
    McpResourceMeta,
    McpToolMeta,
)


def _req(method: str, params: dict | None = None, req_id: Any = 1) -> JsonRpcRequest:
    return JsonRpcRequest(method=method, params=params, id=req_id)


def _make_tool_meta(name: str, method_name: str, **kwargs: Any) -> McpToolMeta:
    defaults: dict[str, Any] = {
        "description": "test",
        "input_schema": {"type": "object", "properties": {}},
    }
    defaults.update(kwargs)
    return McpToolMeta(name=name, method_name=method_name, **defaults)


def _make_resource_meta(
    uri_template: str, name: str, method_name: str, **kwargs: Any
) -> McpResourceMeta:
    defaults: dict[str, Any] = {
        "description": None,
        "mime_type": None,
    }
    defaults.update(kwargs)
    return McpResourceMeta(
        uri_template=uri_template, name=name, method_name=method_name, **defaults
    )


# ---------------------------------------------------------------------------
# _resolve_di — fallback paths (lines 325-330)
# ---------------------------------------------------------------------------


class TestResolveDiFallback:
    async def test_none_container_returns_direct_instance(self):
        class MyClass:
            pass

        result = await _resolve_di(None, MyClass, None)
        assert isinstance(result, MyClass)

    async def test_container_resolve_raises_falls_back_to_sync(self):
        """When async resolve fails, tries sync resolution."""

        class MyClass:
            pass

        instance = MyClass()
        container = AsyncMock()
        container.resolve = AsyncMock(side_effect=RuntimeError("async fail"))
        container.resolve_sync = MagicMock(return_value=instance)

        result = await _resolve_di(container, MyClass, None)
        assert result is instance

    async def test_container_both_fail_falls_back_to_direct(self):
        """When both resolve methods fail, falls back to cls()."""

        class MyClass:
            pass

        container = AsyncMock()
        container.resolve = AsyncMock(side_effect=RuntimeError("async fail"))
        container.resolve_sync = MagicMock(side_effect=RuntimeError("sync fail"))

        result = await _resolve_di(container, MyClass, None)
        assert isinstance(result, MyClass)


# ---------------------------------------------------------------------------
# _run_tool_exception_handlers — ToolOutput coercion (lines 485-501)
# ---------------------------------------------------------------------------


class TestExceptionHandlerToolOutputCoercion:
    async def test_handler_returning_tool_output_coerced(self):
        """Handler returning ToolOutput is coerced to dict."""
        try:
            from lauren.decorators import EXCEPTION_HANDLER_META
        except ImportError:
            pytest.skip("lauren not installed")

        class FakeHandlerMeta:
            exceptions = (ValueError,)

        class ToolOutputHandler:
            def catch(self, exc: Exception, ctx: Any) -> ToolOutput:
                return ToolOutput(
                    content=[TextContent(type="text", text="tool_output_handled")],
                    is_error=True,
                )

        setattr(ToolOutputHandler, EXCEPTION_HANDLER_META, FakeHandlerMeta())

        result = await _run_tool_exception_handlers(
            ValueError("err"), (ToolOutputHandler,), exec_ctx=None
        )
        assert result is not None
        assert result["isError"] is True
        # Content items that are not dicts get str()-ified by the coercion
        # The result dict has content with text containing the content
        assert len(result["content"]) > 0

    async def test_handler_returning_tool_output_with_structured(self):
        """ToolOutput with structured_content is coerced correctly."""
        try:
            from lauren.decorators import EXCEPTION_HANDLER_META
        except ImportError:
            pytest.skip("lauren not installed")

        class FakeHandlerMeta:
            exceptions = (ValueError,)

        class StructuredHandler:
            def catch(self, exc: Exception, ctx: Any) -> ToolOutput:
                return ToolOutput(
                    content=[TextContent(type="text", text="msg")],
                    is_error=False,
                    structured_content={"error_code": 42},
                )

        setattr(StructuredHandler, EXCEPTION_HANDLER_META, FakeHandlerMeta())

        result = await _run_tool_exception_handlers(
            ValueError("err"), (StructuredHandler,), exec_ctx=None
        )
        assert result is not None
        assert result["structuredContent"] == {"error_code": 42}


# ---------------------------------------------------------------------------
# _run_pipes — old API with _ParamSpec
# ---------------------------------------------------------------------------


class TestRunPipesOldApiParamSpec:
    async def test_old_api_with_paramspec_pipes(self):
        """Old API _run_pipes(args, meta) with _ParamSpec applying pipe transforms."""
        try:
            from lauren.extractors import _ParamSpec, FieldDescriptor
        except ImportError:
            pytest.skip("lauren not installed")

        def double(v: Any, ctx: Any = None) -> Any:
            return v * 2

        ps = _ParamSpec(field_descriptor=None, pipes=[double])
        meta = _make_tool_meta("t", "t")
        meta.param_specs = {"x": ps}
        args = {"x": 5}
        result = await _run_pipes(args, meta)
        assert result["x"] == 10

    async def test_old_api_class_pipe_transform(self):
        """Old API _run_pipes with class-based pipe."""
        try:
            from lauren.extractors import _ParamSpec
        except ImportError:
            pytest.skip("lauren not installed")

        class UpperPipe:
            def transform(self, v: Any, ctx: Any = None) -> Any:
                return str(v).upper()

        ps = _ParamSpec(field_descriptor=None, pipes=[UpperPipe])
        meta = _make_tool_meta("t", "t")
        meta.param_specs = {"name": ps}
        args = {"name": "hello"}
        result = await _run_pipes(args, meta)
        assert result["name"] == "HELLO"

    async def test_old_api_awaitable_pipe(self):
        """Old API _run_pipes with async pipe in _ParamSpec."""
        try:
            from lauren.extractors import _ParamSpec
        except ImportError:
            pytest.skip("lauren not installed")

        async def async_double(v: Any, ctx: Any = None) -> Any:
            return v * 2

        ps = _ParamSpec(field_descriptor=None, pipes=[async_double])
        meta = _make_tool_meta("t", "t")
        meta.param_specs = {"x": ps}
        args = {"x": 3}
        result = await _run_pipes(args, meta)
        assert result["x"] == 6


# ---------------------------------------------------------------------------
# make_resources_read_handler — cleanup on exception (lines 1270-1275)
# ---------------------------------------------------------------------------


class FakeResCleanupServer:
    async def get_item(self, item_id: str) -> str:
        return f"item:{item_id}"


class TestResourceCleanupOnError:
    async def test_cleanup_called_when_method_raises(self):
        """Cleanup (finally block) is called even when the resource method raises."""
        cleanup_called = []

        async def get_db():
            try:
                yield "db"
            finally:
                cleanup_called.append("cleanup")

        meta = _make_resource_meta(
            "/items/{item_id}",
            "items",
            "get_item",
            depends_params={"db": get_db},
        )

        class BrokenServer:
            async def get_item(self, item_id: str, db: Any = None) -> str:
                raise RuntimeError("method failed")

        server = BrokenServer()
        handler = make_resources_read_handler(server, [meta])
        with pytest.raises(RuntimeError, match="method failed"):
            await handler(_req("resources/read", {"uri": "/items/42"}))

        assert cleanup_called == ["cleanup"]

    async def test_cleanup_exception_logged_not_propagated(self):
        """Even if cleanup raises, it doesn't propagate."""

        async def bad_provider():
            try:
                yield "val"
            finally:
                raise RuntimeError("cleanup failed")

        meta = _make_resource_meta(
            "/items/{item_id}",
            "items",
            "get_item",
            depends_params={"db": bad_provider},
        )

        class BasicServer:
            async def get_item(self, item_id: str, db: Any = None) -> str:
                return f"item:{item_id}"

        server = BasicServer()
        handler = make_resources_read_handler(server, [meta])
        # Should not raise — cleanup exception is logged
        result = await handler(_req("resources/read", {"uri": "/items/5"}))
        assert "5" in result["contents"][0]["text"]


# ---------------------------------------------------------------------------
# make_tools_call_handler — tool call cleanup raises (line 1021-1022)
# ---------------------------------------------------------------------------


class TestToolCallCleanupRaises:
    async def test_cleanup_exception_logged_not_propagated(self):
        """If Depends cleanup raises, it's logged and doesn't propagate."""

        async def bad_cleanup():
            try:
                yield "val"
            finally:
                raise RuntimeError("cleanup boom")

        class SimpleServer:
            async def tool(self, db: Any = None) -> str:
                return "ok"

        meta = _make_tool_meta("tool", "tool")
        meta.depends_params = {"db": bad_cleanup}

        server = SimpleServer()
        handler = make_tools_call_handler(server, [meta])
        # Should not raise — cleanup exception is logged
        result = await handler(_req("tools/call", {"name": "tool", "arguments": {}}))
        assert result["content"][0]["text"] == "ok"


# ---------------------------------------------------------------------------
# make_tools_call_handler — state_params (line 858-878)
# ---------------------------------------------------------------------------


class StateServer:
    async def tool_with_state(self, state_val: Any = None) -> str:
        return f"state:{type(state_val).__name__}"


class TestStateParamsInjection:
    async def test_state_param_injected(self):
        """State[T] params inject a T() instance."""

        class MyState:
            data: str = "initial"

        meta = _make_tool_meta("tool_with_state", "tool_with_state")
        meta.state_params = {"state_val": MyState}

        server = StateServer()
        handler = make_tools_call_handler(server, [meta])
        result = await handler(_req("tools/call", {"name": "tool_with_state", "arguments": {}}))
        assert "MyState" in result["content"][0]["text"]


# ---------------------------------------------------------------------------
# Resources read handler — resource bg_tasks_param
# ---------------------------------------------------------------------------


class FakeResBgServer:
    async def get_item(self, item_id: str, bg: Any = None) -> str:
        if bg is not None:

            async def task():
                pass

            try:
                bg.add_task(task)
            except Exception:
                pass
        return f"item:{item_id}"


class TestResourceBgTasksParam:
    async def test_resource_bg_tasks_injected(self):
        """BackgroundTasks is injected into resource method if requested."""
        try:
            from lauren import BackgroundTasks  # noqa: F401
        except ImportError:
            pytest.skip("lauren not installed")

        meta = _make_resource_meta(
            "/items/{item_id}",
            "items",
            "get_item",
            bg_tasks_param="bg",
        )
        server = FakeResBgServer()
        handler = make_resources_read_handler(server, [meta])
        result = await handler(_req("resources/read", {"uri": "/items/42"}))
        assert result["contents"][0]["text"] == "item:42"
