"""Schema, output, and elicitation support for dataclasses, TypedDict, and msgspec."""

from __future__ import annotations

import dataclasses
from typing import NotRequired, TypedDict

from lauren_mcp import mcp_tool
from lauren_mcp._server._context import build_elicitation_schema
from lauren_mcp._types import JsonRpcRequest
from lauren_mcp.server._handlers import make_tools_call_handler, make_tools_list_handler
from lauren_mcp.server._meta import MCP_TOOL_META
from lauren_mcp.server._schema import SchemaBuilder


@dataclasses.dataclass
class Point:
    x: int
    y: int
    label: str = "origin"


@dataclasses.dataclass
class Shape:
    name: str
    centre: Point | None = None


class Movie(TypedDict):
    title: str
    year: int
    director: NotRequired[str]


def req(method: str, **params) -> JsonRpcRequest:
    return JsonRpcRequest(method=method, id=1, params=params)


class TestDataclassSchema:
    def test_dataclass_becomes_ref_with_def(self):
        builder = SchemaBuilder()
        assert builder.build(Point) == {"$ref": "#/$defs/Point"}
        definition = builder.defs["Point"]
        assert definition["type"] == "object"
        assert definition["properties"]["x"] == {"type": "integer"}
        assert definition["properties"]["label"]["default"] == "origin"
        assert definition["required"] == ["x", "y"]

    def test_nested_dataclass_hoisted(self):
        builder = SchemaBuilder()
        builder.build(Shape)
        assert "Point" in builder.defs
        centre = builder.defs["Shape"]["properties"]["centre"]
        assert centre["$ref"] == "#/$defs/Point"
        assert centre["default"] is None

    def test_dataclass_in_tool_signature(self):
        @mcp_tool()
        async def draw(self, shape: Shape) -> str:
            """Draw a shape."""

        meta = getattr(draw, MCP_TOOL_META)
        assert meta.input_schema["properties"]["shape"] == {"$ref": "#/$defs/Shape"}
        assert "Shape" in meta.input_schema["$defs"]
        assert "Point" in meta.input_schema["$defs"]


class TestTypedDictSchema:
    def test_typeddict_schema_with_not_required(self):
        builder = SchemaBuilder()
        assert builder.build(Movie) == {"$ref": "#/$defs/Movie"}
        definition = builder.defs["Movie"]
        assert definition["properties"]["title"] == {"type": "string"}
        assert definition["properties"]["director"] == {"type": "string"}
        assert sorted(definition["required"]) == ["title", "year"]

    def test_total_false_typeddict(self):
        class Partial(TypedDict, total=False):
            a: int
            b: str

        builder = SchemaBuilder()
        builder.build(Partial)
        assert "required" not in builder.defs["Partial"]


class TestOutputSchemaResolution:
    async def test_dataclass_output_schema(self):
        @mcp_tool(output_schema=Point)
        async def locate(self) -> dict:
            """Locate."""

        meta = getattr(locate, MCP_TOOL_META)
        assert meta.output_schema["type"] == "object"
        assert meta.output_schema["required"] == ["x", "y"]

    async def test_typeddict_output_schema_advertised(self):
        @mcp_tool(output_schema=Movie)
        async def film(self) -> dict:
            """Film."""

        meta = getattr(film, MCP_TOOL_META)
        entry = (await make_tools_list_handler([meta])(req("tools/list")))["tools"][0]
        assert entry["outputSchema"]["properties"]["title"] == {"type": "string"}


class TestStructuredResultCoercion:
    async def test_dataclass_instance_result(self):
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

    async def test_typeddict_instance_is_plain_dict(self):
        class Server:
            @mcp_tool()
            async def get_movie(self) -> Movie:
                """Get a movie."""
                return Movie(title="Arrival", year=2016)

        meta = getattr(Server.get_movie, MCP_TOOL_META)
        result = await make_tools_call_handler(Server(), [meta])(
            req("tools/call", name="get_movie")
        )
        assert result["structuredContent"] == {"title": "Arrival", "year": 2016}


class TestElicitationStructuredTypes:
    def test_flat_dataclass(self):
        @dataclasses.dataclass
        class Confirm:
            reason: str
            force: bool = False

        schema = build_elicitation_schema(Confirm)
        assert schema["properties"]["reason"] == {"type": "string"}
        assert schema["properties"]["force"] == {"type": "boolean"}
        assert schema["required"] == ["reason"]

    def test_flat_typeddict(self):
        class Form(TypedDict):
            name: str
            age: NotRequired[int]

        schema = build_elicitation_schema(Form)
        assert schema["properties"]["age"] == {"type": "integer"}
        assert schema["required"] == ["name"]

    def test_nested_dataclass_rejected(self):
        import pytest

        @dataclasses.dataclass
        class Nested:
            point: Point

        with pytest.raises(ValueError, match="flat"):
            build_elicitation_schema(Nested)


class TestSampleResultConversion:
    def test_dataclass_conversion(self):
        from lauren_mcp._server._context import _convert_result

        point = _convert_result({"x": 1, "y": 2}, Point)
        assert point == Point(x=1, y=2)

    def test_typeddict_conversion_checks_required(self):
        import pytest

        from lauren_mcp._server._context import _convert_result

        movie = _convert_result({"title": "Dune", "year": 2021}, Movie)
        assert movie == {"title": "Dune", "year": 2021}
        with pytest.raises(ValueError, match="Missing required"):
            _convert_result({"title": "Dune"}, Movie)
