"""msgspec.Struct support tests (skipped when msgspec is absent)."""

from __future__ import annotations

import pytest

from lauren_mcp import mcp_tool
from lauren_mcp._server._context import _convert_result, build_elicitation_schema
from lauren_mcp._types import JsonRpcRequest
from lauren_mcp.server._handlers import make_tools_call_handler
from lauren_mcp.server._meta import MCP_TOOL_META
from lauren_mcp.server._schema import SchemaBuilder

msgspec = pytest.importorskip("msgspec", reason="requires msgspec")


class Point(msgspec.Struct):
    x: int
    y: int
    label: str = "origin"


def req(method: str, **params) -> JsonRpcRequest:
    return JsonRpcRequest(method=method, id=1, params=params)


class TestMsgspecSchema:
    def test_struct_becomes_ref_with_def(self):
        builder = SchemaBuilder()
        assert builder.build(Point) == {"$ref": "#/$defs/Point"}
        definition = builder.defs["Point"]
        assert definition["properties"]["x"] == {"type": "integer"}
        assert "x" in definition.get("required", [])

    def test_struct_in_tool_signature(self):
        @mcp_tool()
        async def draw(self, point: Point) -> str:
            """Draw."""

        meta = getattr(draw, MCP_TOOL_META)
        assert meta.input_schema["properties"]["point"] == {"$ref": "#/$defs/Point"}
        assert "Point" in meta.input_schema["$defs"]

    def test_struct_output_schema(self):
        @mcp_tool(output_schema=Point)
        async def locate(self) -> dict:
            """Locate."""

        meta = getattr(locate, MCP_TOOL_META)
        assert meta.output_schema["properties"]["x"] == {"type": "integer"}


class TestMsgspecResults:
    async def test_struct_instance_result(self):
        class Server:
            @mcp_tool()
            async def get_point(self) -> Point:
                """Get a point."""
                return Point(x=1, y=2)

        meta = getattr(Server.get_point, MCP_TOOL_META)
        result = await make_tools_call_handler(Server(), [meta])(
            req("tools/call", name="get_point")
        )
        assert result["structuredContent"] == {"x": 1, "y": 2, "label": "origin"}

    def test_sample_result_conversion(self):
        point = _convert_result({"x": 3, "y": 4}, Point)
        assert point == Point(x=3, y=4)

    def test_sample_result_conversion_validates(self):
        with pytest.raises(Exception):  # noqa: B017 — msgspec.ValidationError
            _convert_result({"x": "not-an-int", "y": 4}, Point)


class TestMsgspecElicitation:
    def test_flat_struct(self):
        class Confirm(msgspec.Struct):
            reason: str
            force: bool = False

        schema = build_elicitation_schema(Confirm)
        assert schema["properties"]["reason"] == {"type": "string"}
        assert schema["required"] == ["reason"]
