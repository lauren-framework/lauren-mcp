"""Unit tests for Pipe/FieldDescriptor validation on @mcp_tool parameters."""

from __future__ import annotations

from typing import Annotated, Any

import pytest

from lauren_mcp._types import JsonRpcRequest
from lauren_mcp.server._decorators import _build_schema
from lauren_mcp.server._handlers import _run_pipes, make_tools_call_handler

# Import lauren components — skip tests if lauren not installed
lauren = pytest.importorskip("lauren", reason="lauren not installed")
extractors = pytest.importorskip("lauren.extractors", reason="lauren.extractors not available")

from lauren import PathField, QueryField, pipe  # noqa: E402
from lauren.exceptions import ExtractorFieldError  # noqa: E402
from lauren.extractors import PipeContext  # noqa: E402

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Pipe functions used in tests
# ---------------------------------------------------------------------------


@pipe()
def ensure_gt_zero(v: int, ctx: PipeContext) -> int:
    if v <= 0:
        raise ExtractorFieldError(f"{ctx.name} must be > 0")
    return v


@pipe()
def double_it(v: int) -> int:
    return v * 2


@pipe()
def to_upper(v: str) -> str:
    return v.upper()


@pipe()
async def async_double(v: int) -> int:
    return v * 2


# ---------------------------------------------------------------------------
# Schema mapping tests
# ---------------------------------------------------------------------------


class TestSchemaMapping:
    def test_ge_maps_to_minimum(self) -> None:
        class S:
            @staticmethod
            async def fn(qty: Annotated[int, QueryField(ge=1)]) -> dict:
                return {}

        _, _, schema, _, _, pipe_chains, _, _, _, _ = _build_schema(S.fn)
        assert schema["properties"]["qty"]["minimum"] == 1

    def test_le_maps_to_maximum(self) -> None:
        class S:
            @staticmethod
            async def fn(qty: Annotated[int, QueryField(le=1000)]) -> dict:
                return {}

        _, _, schema, _, _, _, _, _, _, _ = _build_schema(S.fn)
        assert schema["properties"]["qty"]["maximum"] == 1000

    def test_min_length_max_length(self) -> None:
        class S:
            @staticmethod
            async def fn(tag: Annotated[str, PathField(min_length=1, max_length=100)]) -> dict:
                return {}

        _, _, schema, _, _, _, _, _, _, _ = _build_schema(S.fn)
        prop = schema["properties"]["tag"]
        assert prop["minLength"] == 1
        assert prop["maxLength"] == 100

    def test_pattern_maps_to_pattern(self) -> None:
        class S:
            @staticmethod
            async def fn(tag: Annotated[str, QueryField(pattern=r"^[a-z]+$")]) -> dict:
                return {}

        _, _, schema, _, _, _, _, _, _, _ = _build_schema(S.fn)
        assert schema["properties"]["tag"]["pattern"] == r"^[a-z]+$"

    def test_description_maps_to_description(self) -> None:
        class S:
            @staticmethod
            async def fn(item_id: Annotated[str, PathField(description="Order ID")]) -> dict:
                return {}

        _, _, schema, _, _, _, _, _, _, _ = _build_schema(S.fn)
        assert schema["properties"]["item_id"]["description"] == "Order ID"

    def test_base_type_is_not_annotated(self) -> None:
        """The property type must be 'string', not 'Path' or 'Annotated'."""

        class S:
            @staticmethod
            async def fn(name: Annotated[str, PathField(min_length=1)]) -> dict:
                return {}

        _, _, schema, _, _, _, _, _, _, _ = _build_schema(S.fn)
        assert schema["properties"]["name"]["type"] == "string"

    def test_no_pipe_key_in_schema(self) -> None:
        """Pipe callables must not appear as JSON Schema keys."""

        class S:
            @staticmethod
            async def fn(qty: Annotated[int, QueryField(ge=1)]) -> dict:
                return {}

        _, _, schema, _, _, _, _, _, _, _ = _build_schema(S.fn)
        for key in schema["properties"]["qty"]:
            assert "pipe" not in key.lower()

    def test_plain_annotation_no_constraints(self) -> None:
        """Plain int → no minimum/maximum in schema."""

        class S:
            @staticmethod
            async def fn(qty: int) -> dict:
                return {}

        _, _, schema, _, _, _, _, _, _, _ = _build_schema(S.fn)
        prop = schema["properties"]["qty"]
        assert "minimum" not in prop
        assert "maximum" not in prop


# ---------------------------------------------------------------------------
# Pipe chain extraction tests
# ---------------------------------------------------------------------------


class TestPipeChainExtraction:
    def test_annotated_with_pipe_extracted(self) -> None:
        class S:
            @staticmethod
            async def fn(qty: Annotated[int, QueryField(ge=1), ensure_gt_zero]) -> dict:
                return {}

        _, _, _, _, _, pipe_chains, _, _, _, _ = _build_schema(S.fn)
        assert "qty" in pipe_chains
        # 2 entries: FD validator + ensure_gt_zero
        assert len(pipe_chains["qty"]) == 2

    def test_annotated_no_custom_pipe_fd_validator_in_pipe_chains(self) -> None:
        """QueryField(ge=1) with no @pipe → pipe_chains gets an FD-validator for enforcement."""

        class S:
            @staticmethod
            async def fn(qty: Annotated[int, QueryField(ge=1)]) -> dict:
                return {}

        _, _, _, _, _, pipe_chains, _, _, _, _ = _build_schema(S.fn)
        # The FD validator is added as a synthetic pipe for runtime enforcement
        assert "qty" in pipe_chains
        assert len(pipe_chains["qty"]) == 1  # just the FD validator, no custom pipes

    def test_plain_int_not_in_pipe_chains(self) -> None:
        class S:
            @staticmethod
            async def fn(qty: int) -> dict:
                return {}

        _, _, _, _, _, pipe_chains, _, _, _, _ = _build_schema(S.fn)
        assert "qty" not in pipe_chains

    def test_default_syntax_pipe_extracted(self) -> None:
        class S:
            @staticmethod
            async def fn(qty: int = QueryField(ge=1) | pipe(ensure_gt_zero)) -> dict:  # type: ignore[assignment]
                return {}

        _, _, _, _, _, pipe_chains, _, _, _, _ = _build_schema(S.fn)
        assert "qty" in pipe_chains
        assert len(pipe_chains["qty"]) >= 1

    def test_default_syntax_fd_constraint_in_schema(self) -> None:
        class S:
            @staticmethod
            async def fn(qty: int = QueryField(ge=1, le=100) | pipe(ensure_gt_zero)) -> dict:  # type: ignore[assignment]
                return {}

        _, _, schema, _, _, _, _, _, _, _ = _build_schema(S.fn)
        prop = schema["properties"]["qty"]
        assert prop["minimum"] == 1
        assert prop["maximum"] == 100


# ---------------------------------------------------------------------------
# _run_pipes tests
# ---------------------------------------------------------------------------


class TestRunPipes:
    async def test_single_arg_pipe_transforms(self) -> None:
        result = await _run_pipes("qty", 5, [double_it])
        assert result == 10

    async def test_ctx_pipe_transforms(self) -> None:
        result = await _run_pipes("qty", 3, [ensure_gt_zero])
        assert result == 3

    async def test_ctx_pipe_raises_on_invalid(self) -> None:
        with pytest.raises(ExtractorFieldError):
            await _run_pipes("qty", 0, [ensure_gt_zero])

    async def test_async_pipe_transforms(self) -> None:
        result = await _run_pipes("n", 4, [async_double])
        assert result == 8

    async def test_str_pipe_transforms(self) -> None:
        result = await _run_pipes("name", "hello", [to_upper])
        assert result == "HELLO"

    async def test_chained_pipes(self) -> None:
        result = await _run_pipes("n", 3, [double_it, ensure_gt_zero])
        assert result == 6

    async def test_ctx_name_in_error_message(self) -> None:
        try:
            await _run_pipes("myfield", 0, [ensure_gt_zero])
            pytest.fail("Should have raised")
        except ExtractorFieldError as exc:
            assert "myfield" in str(exc)


# ---------------------------------------------------------------------------
# INVALID_PARAMS error mapping in handler
# ---------------------------------------------------------------------------


class TestInvalidParamsMapping:
    """Pipe failures must produce INVALID_PARAMS (-32602), not INTERNAL_ERROR."""

    async def test_pipe_failure_returns_invalid_params(self) -> None:
        from lauren_mcp._server._dispatcher import McpDispatcher  # noqa: PLC0415
        from lauren_mcp._types import JsonRpcRequest as _Req
        from lauren_mcp._types import McpErrorCode  # noqa: PLC0415
        from lauren_mcp.server._decorators import mcp_tool  # noqa: PLC0415

        class MyServer:
            @mcp_tool()
            async def do_it(self, qty: Annotated[int, QueryField(ge=1), ensure_gt_zero]) -> str:
                return "ok"

        server = MyServer()
        meta = MyServer.do_it.__mcp_tool_meta__

        dispatcher = McpDispatcher()
        dispatcher._register_builtins()

        _inner = make_tools_call_handler(server, [meta])

        async def _tools_call(params: dict[str, Any] | None) -> dict[str, Any]:
            return await _inner(_Req(method="tools/call", params=params))

        dispatcher.register("tools/call", _tools_call)

        req = JsonRpcRequest(
            method="tools/call",
            id=1,
            params={"name": "do_it", "arguments": {"qty": 0}},
        )
        resp = await dispatcher.dispatch(req)
        assert hasattr(resp, "error"), f"Expected error response, got: {resp}"
        assert resp.error.code == McpErrorCode.INVALID_PARAMS
        assert resp.error.data["field"] == "qty"

    async def test_pipe_success_returns_result(self) -> None:
        from lauren_mcp._server._dispatcher import McpDispatcher  # noqa: PLC0415
        from lauren_mcp._types import JsonRpcRequest as _Req  # noqa: PLC0415
        from lauren_mcp.server._decorators import mcp_tool  # noqa: PLC0415

        class MyServer:
            @mcp_tool()
            async def do_it(self, qty: Annotated[int, QueryField(ge=1), ensure_gt_zero]) -> str:
                return f"qty={qty}"

        server = MyServer()
        meta = MyServer.do_it.__mcp_tool_meta__

        dispatcher = McpDispatcher()
        dispatcher._register_builtins()
        _inner = make_tools_call_handler(server, [meta])

        async def _tools_call(params: dict[str, Any] | None) -> dict[str, Any]:
            return await _inner(_Req(method="tools/call", params=params))

        dispatcher.register("tools/call", _tools_call)

        req = JsonRpcRequest(
            method="tools/call",
            id=2,
            params={"name": "do_it", "arguments": {"qty": 5}},
        )
        resp = await dispatcher.dispatch(req)
        assert hasattr(resp, "result"), f"Expected result, got: {resp}"
        assert "qty=5" in resp.result["content"][0]["text"]
