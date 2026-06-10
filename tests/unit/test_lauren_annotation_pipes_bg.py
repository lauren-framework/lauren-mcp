"""Unit tests for _extract_lauren_annotation, _run_pipes, _run_bg_tasks,
BackgroundTasks parameter detection, FieldDescriptor constraint schema
generation, and McpToolMeta field tracking.

These tests exercise the functions in isolation with real Lauren imports but
no Lauren DI container or network transport.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

import pytest

# ---------------------------------------------------------------------------
# Conditional Lauren imports
# ---------------------------------------------------------------------------
lauren = pytest.importorskip("lauren", reason="requires lauren")
from lauren import BackgroundTasks, QueryField, pipe  # noqa: E402
from lauren.extractors import FieldDescriptor, _ParamSpec  # noqa: E402

from lauren_mcp._types import JsonRpcRequest  # noqa: E402
from lauren_mcp.server._decorators import (  # noqa: E402
    _extract_lauren_annotation,
    _is_bg_tasks_annotation,
    _is_context_annotation,
    mcp_server,
    mcp_tool,
)
from lauren_mcp.server._handlers import (  # noqa: E402
    McpInvalidParamsError,
    _run_bg_tasks,
    _run_pipes,
    _validate_param_specs,
    make_tools_call_handler,
)
from lauren_mcp.server._meta import MCP_TOOL_META, McpToolMeta  # noqa: E402

# ---------------------------------------------------------------------------
# Module-level pipe functions and server classes
# (must be at module level so that 'from __future__ import annotations'
# does not prevent get_type_hints from resolving the Annotated wrappers)
# ---------------------------------------------------------------------------


@pipe()
def _double_int(v: int, ctx: Any) -> int:
    """Multiply an integer by two."""
    return v * 2


@pipe()
async def _to_upper_str(v: str, ctx: Any) -> str:
    """Uppercase a string (async)."""
    return v.upper()


@pipe()
def _add_one(v: int, ctx: Any) -> int:
    return v + 1


@pipe()
def _triple(v: int, ctx: Any) -> int:
    return v * 3


# Server used by TestMcpToolMetaFields
@mcp_server("/mcp")
class _OrderServer:
    @mcp_tool()
    async def order(self, qty: Annotated[int, QueryField(ge=1)]) -> str:
        return f"ordered {qty}"

    @mcp_tool()
    async def score(self, value: Annotated[int, QueryField(le=100)]) -> str:
        return str(value)

    @mcp_tool()
    async def greet(self, name: Annotated[str, QueryField(min_length=2)]) -> str:
        return name

    @mcp_tool()
    async def work_bg(self, item: str, bg: BackgroundTasks) -> str:
        bg.add_task(lambda: None)
        return item

    @mcp_tool()
    async def plain(self, name: str) -> str:
        return name


# Server with pipe transformation (module-level so future annotations resolve)
_CALC_RECEIVED: list[int] = []


@mcp_server("/mcp-pipe")
class _CalcServer:
    @mcp_tool()
    async def calc(self, x: Annotated[int, QueryField(ge=0) | pipe(_double_int)]) -> str:
        _CALC_RECEIVED.append(x)
        return str(x)

    @mcp_tool()
    async def chained(
        self, x: Annotated[int, QueryField(ge=0) | pipe(_add_one) | pipe(_triple)]
    ) -> str:
        return str(x)

    @mcp_tool()
    async def order_validated(
        self, qty: Annotated[int, QueryField(ge=1) | pipe(_double_int)]
    ) -> str:
        return str(qty)


# Server with pure FieldDescriptor (no pipes) for validation tests
@mcp_server("/mcp-validate")
class _ValidateServer:
    @mcp_tool()
    async def take_qty(self, qty: Annotated[int, QueryField(ge=1)]) -> str:
        return f"qty={qty}"

    @mcp_tool()
    async def work_with_bg(self, name: str, bg: BackgroundTasks) -> str:
        bg.add_task(lambda: None)
        return f"done:{name}"

    @mcp_tool()
    async def raise_after_bg(self, name: str, bg: BackgroundTasks) -> str:
        bg.add_task(lambda: None)
        raise ValueError("tool error")


# ---------------------------------------------------------------------------
# _extract_lauren_annotation
# ---------------------------------------------------------------------------


class TestExtractLaurenAnnotation:
    def test_returns_field_descriptor_from_annotated_queryfield(self):
        annotation = Annotated[int, QueryField(ge=1)]
        result = _extract_lauren_annotation(annotation)
        assert isinstance(result, FieldDescriptor)

    def test_field_descriptor_has_correct_ge(self):
        annotation = Annotated[int, QueryField(ge=5)]
        fd = _extract_lauren_annotation(annotation)
        assert fd is not None
        assert fd.ge == 5

    def test_field_descriptor_has_correct_le(self):
        annotation = Annotated[int, QueryField(le=100)]
        fd = _extract_lauren_annotation(annotation)
        assert fd is not None
        assert fd.le == 100

    def test_returns_param_spec_from_pipe_chain(self):
        annotation = Annotated[str, QueryField(min_length=1) | pipe(_to_upper_str)]
        result = _extract_lauren_annotation(annotation)
        assert isinstance(result, _ParamSpec)

    def test_param_spec_contains_field_descriptor(self):
        annotation = Annotated[int, QueryField(ge=2) | pipe(_add_one)]
        ps = _extract_lauren_annotation(annotation)
        assert isinstance(ps, _ParamSpec)
        assert ps.field_descriptor is not None
        assert ps.field_descriptor.ge == 2

    def test_param_spec_contains_pipes(self):
        annotation = Annotated[int, QueryField(ge=0) | pipe(_add_one)]
        ps = _extract_lauren_annotation(annotation)
        assert isinstance(ps, _ParamSpec)
        assert len(ps.pipes) == 1

    def test_returns_none_for_plain_type(self):
        assert _extract_lauren_annotation(int) is None

    def test_returns_none_for_non_annotated_annotated(self):
        annotation = Annotated[int, "just a string"]
        assert _extract_lauren_annotation(annotation) is None

    def test_returns_none_for_str(self):
        assert _extract_lauren_annotation("int") is None

    def test_returns_none_for_none(self):
        assert _extract_lauren_annotation(None) is None


# ---------------------------------------------------------------------------
# _is_bg_tasks_annotation
# ---------------------------------------------------------------------------


class TestIsBgTasksAnnotation:
    def test_true_for_background_tasks_class(self):
        assert _is_bg_tasks_annotation(BackgroundTasks) is True

    def test_false_for_int(self):
        assert _is_bg_tasks_annotation(int) is False

    def test_false_for_string(self):
        assert _is_bg_tasks_annotation("not_a_bg_tasks") is False

    def test_false_for_none(self):
        assert _is_bg_tasks_annotation(None) is False

    def test_false_for_context_annotation(self):
        from lauren_mcp._server._context import McpToolContext  # noqa: PLC0415

        assert _is_bg_tasks_annotation(McpToolContext) is False

    def test_does_not_interfere_with_is_context_annotation(self):
        from lauren_mcp._server._context import McpToolContext  # noqa: PLC0415

        assert _is_bg_tasks_annotation(McpToolContext) is False
        assert _is_context_annotation(BackgroundTasks) is False


# ---------------------------------------------------------------------------
# McpToolMeta — bg_param_name and param_specs fields
# ---------------------------------------------------------------------------


class TestMcpToolMetaFields:
    def test_bg_param_name_set_when_background_tasks_in_signature(self):
        meta: McpToolMeta = getattr(_ValidateServer.work_with_bg, MCP_TOOL_META)
        assert meta.bg_param_name == "bg"

    def test_bg_param_name_none_when_no_background_tasks(self):
        meta: McpToolMeta = getattr(_ValidateServer.take_qty, MCP_TOOL_META)
        assert meta.bg_param_name is None

    def test_bg_param_excluded_from_input_schema(self):
        meta: McpToolMeta = getattr(_ValidateServer.work_with_bg, MCP_TOOL_META)
        assert "bg" not in meta.input_schema.get("properties", {})

    def test_param_specs_populated_for_queryfield_param(self):
        meta: McpToolMeta = getattr(_OrderServer.order, MCP_TOOL_META)
        assert "qty" in meta.param_specs
        assert isinstance(meta.param_specs["qty"], FieldDescriptor)

    def test_param_specs_empty_for_plain_params(self):
        meta: McpToolMeta = getattr(_OrderServer.plain, MCP_TOOL_META)
        assert meta.param_specs == {}

    def test_schema_shows_minimum_from_queryfield_ge(self):
        meta: McpToolMeta = getattr(_OrderServer.order, MCP_TOOL_META)
        prop = meta.input_schema["properties"]["qty"]
        assert prop.get("minimum") == 1

    def test_schema_shows_maximum_from_queryfield_le(self):
        meta: McpToolMeta = getattr(_OrderServer.score, MCP_TOOL_META)
        prop = meta.input_schema["properties"]["value"]
        assert prop.get("maximum") == 100

    def test_schema_shows_min_length_from_queryfield(self):
        meta: McpToolMeta = getattr(_OrderServer.greet, MCP_TOOL_META)
        prop = meta.input_schema["properties"]["name"]
        assert prop.get("minLength") == 2

    def test_param_specs_contains_param_spec_with_pipe(self):
        meta: McpToolMeta = getattr(_CalcServer.calc, MCP_TOOL_META)
        assert "x" in meta.param_specs
        assert isinstance(meta.param_specs["x"], _ParamSpec)

    def test_param_spec_has_pipe_attached(self):
        meta: McpToolMeta = getattr(_CalcServer.calc, MCP_TOOL_META)
        ps: _ParamSpec = meta.param_specs["x"]
        assert len(ps.pipes) == 1


# ---------------------------------------------------------------------------
# _validate_param_specs
# ---------------------------------------------------------------------------


class TestValidateParamSpecs:
    def _make_meta(self, param_specs: dict[str, Any]) -> McpToolMeta:
        return McpToolMeta(
            name="test",
            description="",
            input_schema={"type": "object", "properties": {}},
            method_name="test",
            param_specs=param_specs,
        )

    def test_valid_value_passes_ge_constraint(self):
        meta = self._make_meta({"qty": QueryField(ge=1)})
        result = _validate_param_specs({"qty": 5}, meta)
        assert result["qty"] == 5

    def test_invalid_value_raises_for_ge_constraint(self):
        meta = self._make_meta({"qty": QueryField(ge=1)})
        with pytest.raises(McpInvalidParamsError, match="qty"):
            _validate_param_specs({"qty": 0}, meta)

    def test_invalid_value_raises_for_le_constraint(self):
        meta = self._make_meta({"score": QueryField(le=100)})
        with pytest.raises(McpInvalidParamsError, match="score"):
            _validate_param_specs({"score": 101}, meta)

    def test_boundary_value_exactly_at_ge_passes(self):
        meta = self._make_meta({"qty": QueryField(ge=1)})
        result = _validate_param_specs({"qty": 1}, meta)
        assert result["qty"] == 1

    def test_param_not_in_arguments_skipped(self):
        meta = self._make_meta({"qty": QueryField(ge=1)})
        result = _validate_param_specs({}, meta)
        assert result == {}

    def test_unrelated_params_preserved(self):
        meta = self._make_meta({"qty": QueryField(ge=1)})
        result = _validate_param_specs({"qty": 3, "name": "bob"}, meta)
        assert result["name"] == "bob"

    def test_empty_param_specs_returns_arguments_unchanged(self):
        meta = self._make_meta({})
        args = {"x": 42, "y": "hello"}
        assert _validate_param_specs(args, meta) == args

    def test_min_length_constraint(self):
        meta = self._make_meta({"tag": QueryField(min_length=3)})
        with pytest.raises(McpInvalidParamsError):
            _validate_param_specs({"tag": "ab"}, meta)

    def test_min_length_passes_when_long_enough(self):
        meta = self._make_meta({"tag": QueryField(min_length=3)})
        result = _validate_param_specs({"tag": "abc"}, meta)
        assert result["tag"] == "abc"


# ---------------------------------------------------------------------------
# _run_pipes
# ---------------------------------------------------------------------------


class TestRunPipes:
    async def test_sync_pipe_transforms_value(self):
        meta = McpToolMeta(
            name="test",
            description="",
            input_schema={"type": "object", "properties": {}},
            method_name="test",
            param_specs={"x": QueryField(ge=0) | pipe(_double_int)},
        )
        result = await _run_pipes({"x": 5}, meta)
        assert result["x"] == 10

    async def test_async_pipe_transforms_value(self):
        meta = McpToolMeta(
            name="test",
            description="",
            input_schema={"type": "object", "properties": {}},
            method_name="test",
            param_specs={"word": QueryField(min_length=1) | pipe(_to_upper_str)},
        )
        result = await _run_pipes({"word": "hello"}, meta)
        assert result["word"] == "HELLO"

    async def test_no_pipes_returns_unchanged(self):
        meta = McpToolMeta(
            name="test",
            description="",
            input_schema={"type": "object", "properties": {}},
            method_name="test",
            param_specs={"qty": QueryField(ge=1)},
        )
        result = await _run_pipes({"qty": 3}, meta)
        assert result["qty"] == 3

    async def test_empty_param_specs_returns_unchanged(self):
        meta = McpToolMeta(
            name="test",
            description="",
            input_schema={"type": "object", "properties": {}},
            method_name="test",
            param_specs={},
        )
        args = {"x": 42}
        result = await _run_pipes(args, meta)
        assert result == args

    async def test_chained_pipes_apply_in_order(self):
        # (5 + 1) * 3 = 18
        meta = McpToolMeta(
            name="test",
            description="",
            input_schema={"type": "object", "properties": {}},
            method_name="test",
            param_specs={"x": QueryField(ge=0) | pipe(_add_one) | pipe(_triple)},
        )
        result = await _run_pipes({"x": 5}, meta)
        assert result["x"] == 18

    async def test_param_absent_from_args_skipped(self):
        meta = McpToolMeta(
            name="test",
            description="",
            input_schema={"type": "object", "properties": {}},
            method_name="test",
            param_specs={"x": QueryField(ge=0) | pipe(_double_int)},
        )
        result = await _run_pipes({}, meta)
        assert result == {}


# ---------------------------------------------------------------------------
# _run_bg_tasks
# ---------------------------------------------------------------------------


class TestRunBgTasks:
    async def test_task_runs_after_call(self):
        log: list[str] = []
        bg = BackgroundTasks()
        bg.add_task(lambda: log.append("ran"))
        await _run_bg_tasks(bg)
        assert "ran" in log

    async def test_multiple_tasks_all_run(self):
        log: list[str] = []
        bg = BackgroundTasks()
        bg.add_task(lambda: log.append("a"))
        bg.add_task(lambda: log.append("b"))
        bg.add_task(lambda: log.append("c"))
        await _run_bg_tasks(bg)
        assert log == ["a", "b", "c"]

    async def test_none_is_noop(self):
        await _run_bg_tasks(None)

    async def test_empty_background_tasks_is_noop(self):
        bg = BackgroundTasks()
        await _run_bg_tasks(bg)

    async def test_async_task_runs(self):
        log: list[str] = []

        async def async_task() -> None:
            log.append("async_ran")

        bg = BackgroundTasks()
        bg.add_task(async_task)
        await _run_bg_tasks(bg)
        assert "async_ran" in log

    async def test_failing_task_does_not_prevent_subsequent_tasks(self):
        """A bg task that raises must not prevent other tasks from running."""
        log: list[str] = []

        def bad() -> None:
            raise RuntimeError("boom")

        bg = BackgroundTasks()
        bg.add_task(bad)
        bg.add_task(lambda: log.append("after_bad"))
        # BackgroundTasks._run() catches exceptions and continues.
        # Our _run_bg_tasks() wrapper uses a null signals object.
        # This should not raise even though 'bad' raises.
        await _run_bg_tasks(bg)
        assert "after_bad" in log


# ---------------------------------------------------------------------------
# make_tools_call_handler — validation + bg_tasks + pipes end-to-end
# ---------------------------------------------------------------------------


class TestToolCallHandlerEndToEnd:
    async def test_valid_input_returns_result(self):
        meta = getattr(_ValidateServer.take_qty, MCP_TOOL_META)
        handler = make_tools_call_handler(_ValidateServer(), [meta])
        req = JsonRpcRequest(
            method="tools/call", id=1, params={"name": "take_qty", "arguments": {"qty": 5}}
        )
        result = await handler(req)
        assert "qty=5" in result["content"][0]["text"]

    async def test_invalid_input_raises_mcp_invalid_params_error(self):
        meta = getattr(_ValidateServer.take_qty, MCP_TOOL_META)
        handler = make_tools_call_handler(_ValidateServer(), [meta])
        req = JsonRpcRequest(
            method="tools/call", id=1, params={"name": "take_qty", "arguments": {"qty": 0}}
        )
        with pytest.raises(McpInvalidParamsError):
            await handler(req)

    async def test_bg_tasks_run_after_tool_returns(self):
        """BackgroundTasks injected by the handler run synchronously in the same event loop."""
        log: list[str] = []

        # Use a fresh server instance with a captured log list
        @mcp_server("/mcp-bg-test")
        class _BgSrv:
            pass

        # We can't define the tool with a closure here due to future annotations,
        # so build a minimal McpToolMeta that maps to a method on a local class.
        meta = McpToolMeta(
            name="work",
            description="",
            input_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
            method_name="_work",
            bg_param_name="bg",
        )

        class _FakeSrv:
            async def _work(self, name: str, bg: BackgroundTasks) -> str:
                bg.add_task(lambda: log.append(f"bg:{name}"))
                return f"done:{name}"

        handler = make_tools_call_handler(_FakeSrv(), [meta])
        req = JsonRpcRequest(
            method="tools/call", id=1, params={"name": "work", "arguments": {"name": "alice"}}
        )
        result = await handler(req)
        assert "done:alice" in result["content"][0]["text"]
        await asyncio.sleep(0)
        assert "bg:alice" in log

    async def test_pipe_transformation_applied_before_tool_call(self):
        """Pipe in the param spec transforms the value before the method sees it."""
        meta = getattr(_CalcServer.calc, MCP_TOOL_META)
        _CALC_RECEIVED.clear()
        handler = make_tools_call_handler(_CalcServer(), [meta])
        req = JsonRpcRequest(
            method="tools/call", id=1, params={"name": "calc", "arguments": {"x": 4}}
        )
        result = await handler(req)
        # x=4 doubled by _double_int pipe → 8
        assert _CALC_RECEIVED == [8]
        assert "8" in result["content"][0]["text"]

    async def test_chained_pipes_apply_in_order(self):
        """Multiple pipes in a chain apply left-to-right."""
        meta = getattr(_CalcServer.chained, MCP_TOOL_META)
        handler = make_tools_call_handler(_CalcServer(), [meta])
        req = JsonRpcRequest(
            method="tools/call", id=1, params={"name": "chained", "arguments": {"x": 5}}
        )
        result = await handler(req)
        # (5 + 1) * 3 = 18
        assert "18" in result["content"][0]["text"]

    async def test_validation_runs_before_pipes(self):
        """Field descriptor validation must happen before pipe execution.

        qty=0 violates ge=1, so McpInvalidParamsError should be raised
        before the pipe ever executes.
        """
        meta = getattr(_CalcServer.order_validated, MCP_TOOL_META)
        handler = make_tools_call_handler(_CalcServer(), [meta])
        req = JsonRpcRequest(
            method="tools/call", id=1, params={"name": "order_validated", "arguments": {"qty": 0}}
        )
        with pytest.raises(McpInvalidParamsError):
            await handler(req)
