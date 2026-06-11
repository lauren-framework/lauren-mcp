"""Additional coverage tests for _handlers.py — targeting remaining uncovered paths."""

from __future__ import annotations

import asyncio
import dataclasses
import inspect
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lauren_mcp._types import (
    BlobResource,
    ImageContent,
    JsonRpcRequest,
    TextContent,
    ToolOutput,
    ToolStream,
)
from lauren_mcp.server._handlers import (
    McpCallHandler,
    _coerce_tool_result,
    _model_dump,
    _run_pipes,
    _serialize_chunk,
    _validate_output,
    _validate_param_specs,
    make_resources_read_handler,
    make_tools_call_handler,
    make_tools_list_handler,
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
# _serialize_chunk
# ---------------------------------------------------------------------------


class TestSerializeChunk:
    def test_serializes_dict(self):
        result = _serialize_chunk({"key": "val"})
        assert '"key"' in result

    def test_serializes_string(self):
        result = _serialize_chunk("hello")
        assert result == '"hello"'

    def test_serializes_number(self):
        result = _serialize_chunk(42)
        assert result == "42"

    def test_fallback_on_unserializable(self):
        class Unserializable:
            def __str__(self):
                return "special"

        # Should not raise
        result = _serialize_chunk(Unserializable())
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# _model_dump
# ---------------------------------------------------------------------------


class TestModelDump:
    def test_pydantic_v2_model_dump(self):
        pydantic = pytest.importorskip("pydantic")

        class Item(pydantic.BaseModel):
            name: str
            count: int

        item = Item(name="widget", count=5)
        result = _model_dump(item)
        assert result["name"] == "widget"

    def test_raises_on_non_pydantic_object(self):
        class NotPydantic:
            pass

        with pytest.raises(TypeError, match="Cannot serialise"):
            _model_dump(NotPydantic())


# ---------------------------------------------------------------------------
# _validate_output
# ---------------------------------------------------------------------------


class TestValidateOutput:
    def test_no_schema_no_validation(self):
        meta = _make_tool_meta("t", "t")
        # Should not raise
        _validate_output({"x": 1}, meta)

    def test_none_structured_no_validation(self):
        meta = _make_tool_meta("t", "t", output_schema={"required": ["x"]})
        # None structured content → no validation
        _validate_output(None, meta)

    def test_raises_on_missing_required_key(self):
        meta = _make_tool_meta(
            "t",
            "t",
            output_schema={"type": "object", "required": ["x", "y"], "properties": {}},
        )
        with pytest.raises(ValueError, match="missing required key"):
            _validate_output({"x": 1}, meta)  # missing "y"

    def test_passes_when_all_required_keys_present(self):
        meta = _make_tool_meta(
            "t",
            "t",
            output_schema={"type": "object", "required": ["x"], "properties": {}},
        )
        _validate_output({"x": 1, "y": 2}, meta)


# ---------------------------------------------------------------------------
# _coerce_tool_result — msgspec struct
# ---------------------------------------------------------------------------


class TestCoerceToolResultMsgspec:
    def test_msgspec_struct_result(self):
        msgspec = pytest.importorskip("msgspec")

        class Point(msgspec.Struct):
            x: float
            y: float

        meta = _make_tool_meta("t", "t")
        result = _coerce_tool_result(Point(x=1.0, y=2.0), meta)
        assert result["structuredContent"]["x"] == 1.0

    def test_pydantic_model_result(self):
        pydantic = pytest.importorskip("pydantic")

        class Item(pydantic.BaseModel):
            name: str

        meta = _make_tool_meta("t", "t")
        result = _coerce_tool_result(Item(name="widget"), meta)
        assert result["structuredContent"]["name"] == "widget"


# ---------------------------------------------------------------------------
# _validate_param_specs
# ---------------------------------------------------------------------------


class TestValidateParamSpecs:
    def test_no_param_specs_returns_args(self):
        meta = _make_tool_meta("t", "t")
        args = {"x": 1, "y": 2}
        result = _validate_param_specs(args, meta)
        assert result is args

    def test_with_field_descriptor_when_lauren_available(self):
        try:
            from lauren.extractors import FieldDescriptor
        except ImportError:
            pytest.skip("lauren not installed")

        meta = _make_tool_meta("t", "t")
        fd = FieldDescriptor(ge=0)
        meta.param_specs = {"x": fd}
        args = {"x": 5}
        result = _validate_param_specs(args, meta)
        assert result["x"] == 5


# ---------------------------------------------------------------------------
# _run_pipes
# ---------------------------------------------------------------------------


class TestRunPipes:
    async def test_new_api_three_args(self):
        """_run_pipes(name, value, pipes) → transformed value."""

        def double(v: Any) -> Any:
            return v * 2

        try:
            from lauren.extractors import PipeContext  # noqa: F401
        except ImportError:
            pytest.skip("lauren not installed")

        result = await _run_pipes("x", 5, [double])
        assert result == 10

    async def test_old_api_two_args_no_specs(self):
        """_run_pipes(arguments, meta) with no param_specs returns args unchanged."""
        meta = _make_tool_meta("t", "t")
        args = {"x": 1}
        result = await _run_pipes(args, meta)
        assert result == args

    async def test_old_api_with_pipe_chain(self):
        """_run_pipes old API applies pipe_chains."""
        try:
            from lauren.extractors import PipeContext  # noqa: F401
        except ImportError:
            pytest.skip("lauren not installed")

        def add_one(v: Any) -> Any:
            return v + 1

        meta = _make_tool_meta("t", "t")
        meta.pipe_chains = {"x": [add_one]}
        args = {"x": 5}
        result = await _run_pipes(args, meta)
        assert result["x"] == 6


# ---------------------------------------------------------------------------
# make_tools_call_handler — exception handler paths
# ---------------------------------------------------------------------------


class FakeServerExc:
    async def failing_tool(self) -> str:
        raise ValueError("tool error")

    async def ok_tool(self) -> str:
        return "ok"


FAKE_EXC_SERVER = FakeServerExc()


class TestExceptionHandlerPaths:
    async def test_exception_handler_with_no_container(self):
        """Exception handler without container catches ValueError."""
        try:
            from lauren.decorators import EXCEPTION_HANDLER_META
        except ImportError:
            pytest.skip("lauren not installed")

        class FakeHandlerMeta:
            exceptions = (ValueError,)

        class MyHandler:
            def catch(self, exc: Exception, ctx: Any) -> dict:
                return {"content": [{"type": "text", "text": f"caught:{exc}"}], "isError": True}

        setattr(MyHandler, EXCEPTION_HANDLER_META, FakeHandlerMeta())

        meta = _make_tool_meta(
            "failing_tool",
            "failing_tool",
            exception_handlers=(MyHandler,),
        )
        handler = make_tools_call_handler(FAKE_EXC_SERVER, [meta])
        result = await handler(_req("tools/call", {"name": "failing_tool", "arguments": {}}))
        assert result["isError"] is True
        assert "caught:tool error" in result["content"][0]["text"]

    async def test_exception_not_handled_reraises(self):
        """When no handler matches, the exception is re-raised."""
        try:
            from lauren.decorators import EXCEPTION_HANDLER_META
        except ImportError:
            pytest.skip("lauren not installed")

        class FakeHandlerMeta:
            exceptions = (TypeError,)  # Only handles TypeError, not ValueError

        class WrongHandler:
            def catch(self, exc: Exception, ctx: Any) -> dict:
                return {"content": [], "isError": True}

        setattr(WrongHandler, EXCEPTION_HANDLER_META, FakeHandlerMeta())

        meta = _make_tool_meta(
            "failing_tool",
            "failing_tool",
            exception_handlers=(WrongHandler,),
        )
        handler = make_tools_call_handler(FAKE_EXC_SERVER, [meta])
        with pytest.raises(ValueError):
            await handler(_req("tools/call", {"name": "failing_tool", "arguments": {}}))


# ---------------------------------------------------------------------------
# make_tools_call_handler — guard execution
# ---------------------------------------------------------------------------


class TestGuardExecution:
    async def test_guard_allows_call(self):
        """When guard allows, tool is called normally."""
        from unittest.mock import AsyncMock

        class FakeGuard:
            async def can_activate(self, ctx: Any) -> bool:
                return True

        meta = _make_tool_meta("ok_tool", "ok_tool", guards=(FakeGuard,))

        container = AsyncMock()
        container.resolve = AsyncMock(return_value=FakeGuard())

        handler = make_tools_call_handler(FAKE_EXC_SERVER, [meta], container=container)
        result = await handler(_req("tools/call", {"name": "ok_tool", "arguments": {}}))
        assert result["isError"] is False

    async def test_guard_denies_call(self):
        """When guard denies, McpForbiddenError is raised."""
        from lauren_mcp._server._dispatcher import McpForbiddenError

        class FakeGuard:
            async def can_activate(self, ctx: Any) -> bool:
                return False

        meta = _make_tool_meta("ok_tool", "ok_tool", guards=(FakeGuard,))

        container = AsyncMock()
        container.resolve = AsyncMock(return_value=FakeGuard())

        handler = make_tools_call_handler(FAKE_EXC_SERVER, [meta], container=container)
        with pytest.raises(McpForbiddenError):
            await handler(_req("tools/call", {"name": "ok_tool", "arguments": {}}))


# ---------------------------------------------------------------------------
# make_tools_call_handler — depends params
# ---------------------------------------------------------------------------


class FakeDependsServer:
    async def tool_with_dep(self, db: str) -> str:
        return f"got:{db}"


class TestDependsParams:
    async def test_depends_injected_into_tool(self):
        """Depends[callable] parameters are resolved and injected."""
        try:
            from lauren import Depends
        except ImportError:
            pytest.skip("lauren not installed")

        async def get_db() -> str:
            return "db_connection"

        meta = _make_tool_meta("tool_with_dep", "tool_with_dep")
        meta.depends_params = {"db": get_db}

        server = FakeDependsServer()
        handler = make_tools_call_handler(server, [meta])
        result = await handler(_req("tools/call", {"name": "tool_with_dep", "arguments": {}}))
        assert "db_connection" in result["content"][0]["text"]


# ---------------------------------------------------------------------------
# make_tools_call_handler — with dispatcher (register_context)
# ---------------------------------------------------------------------------


class FakeContextServer:
    async def get_tool(self) -> str:
        return "done"


class TestDispatcherRegistration:
    async def test_dispatcher_register_context_called(self):
        """When dispatcher provided and tool reads context, register_context is called."""
        from lauren_mcp._server._context import McpToolContext

        dispatcher = MagicMock()
        dispatcher.register_context = MagicMock()

        factory = MagicMock()
        ctx = MagicMock(spec=McpToolContext)
        ctx.tool_name = "get_tool"
        factory.return_value = ctx

        meta = _make_tool_meta("get_tool", "get_tool")
        meta.reads_context = True
        meta.context_param_name = "ctx"

        server = FakeContextServer()

        # Need to patch so that get_tool accepts ctx kwarg
        async def get_tool_with_ctx(ctx=None) -> str:
            return "done"

        server.get_tool = get_tool_with_ctx

        handler = make_tools_call_handler(
            server,
            [meta],
            context_factory=factory,
            dispatcher=dispatcher,
        )
        await handler(_req("tools/call", {"name": "get_tool", "arguments": {}}, req_id=42))
        dispatcher.register_context.assert_called_once_with(42, ctx)


# ---------------------------------------------------------------------------
# make_tools_list_handler — with tool annotations
# ---------------------------------------------------------------------------


class TestToolsListWithAnnotations:
    async def test_tool_with_annotations_included(self):
        from lauren_mcp._types import ToolAnnotations

        meta = _make_tool_meta(
            "t",
            "t",
            annotations=ToolAnnotations(readOnlyHint=True),
        )
        handler = make_tools_list_handler([meta])
        result = await handler(_req("tools/list"))
        assert "annotations" in result["tools"][0]


# ---------------------------------------------------------------------------
# make_resources_read_handler — callable resources
# ---------------------------------------------------------------------------


class FakeResourceServer2:
    async def get_item(self, item_id: str) -> str:
        return f"item:{item_id}"


FAKE_RS2 = FakeResourceServer2()


class TestResourcesReadCallable:
    async def test_callable_resources_getter(self):
        """make_resources_read_handler accepts a callable resources getter."""
        meta = _make_resource_meta("/items/{item_id}", "items", "get_item")
        handler = make_resources_read_handler(FAKE_RS2, lambda: [meta])
        result = await handler(_req("resources/read", {"uri": "/items/99"}))
        assert result["contents"][0]["text"] == "item:99"


# ---------------------------------------------------------------------------
# make_tools_call_handler — structured output validation
# ---------------------------------------------------------------------------


class FakeStructuredServer:
    async def structured_tool(self) -> dict:
        return {"x": 1, "y": 2}

    async def missing_key_tool(self) -> dict:
        return {"x": 1}  # Missing required "y"


class TestStructuredOutputValidation:
    async def test_valid_structured_output_passes(self):
        meta = _make_tool_meta(
            "structured_tool",
            "structured_tool",
            output_schema={"type": "object", "required": ["x"], "properties": {}},
        )
        server = FakeStructuredServer()
        handler = make_tools_call_handler(server, [meta])
        result = await handler(_req("tools/call", {"name": "structured_tool", "arguments": {}}))
        assert result["isError"] is False

    async def test_invalid_structured_output_raises(self):
        meta = _make_tool_meta(
            "missing_key_tool",
            "missing_key_tool",
            output_schema={"type": "object", "required": ["y"], "properties": {}},
        )
        server = FakeStructuredServer()
        handler = make_tools_call_handler(server, [meta])
        with pytest.raises(ValueError, match="missing required key"):
            await handler(_req("tools/call", {"name": "missing_key_tool", "arguments": {}}))
