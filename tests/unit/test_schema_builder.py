"""Unit tests for the recursive JSON Schema builder."""

from __future__ import annotations

import datetime
import enum
import uuid
from typing import Any, Literal, Optional, Union

import pytest

from lauren_mcp.server._schema import SchemaBuilder


class Colour(enum.StrEnum):
    RED = "red"
    BLUE = "blue"


class Level(enum.Enum):
    LOW = 1
    HIGH = 2


def build(annotation: Any) -> dict:
    return SchemaBuilder().build(annotation)


class TestPrimitives:
    @pytest.mark.parametrize(
        ("annotation", "expected"),
        [
            (str, {"type": "string"}),
            (int, {"type": "integer"}),
            (float, {"type": "number"}),
            (bool, {"type": "boolean"}),
            (uuid.UUID, {"type": "string", "format": "uuid"}),
            (datetime.datetime, {"type": "string", "format": "date-time"}),
            (datetime.date, {"type": "string", "format": "date"}),
            (datetime.time, {"type": "string", "format": "time"}),
        ],
    )
    def test_primitive_mapping(self, annotation, expected):
        assert build(annotation) == expected

    def test_unknown_type_degrades_to_unconstrained(self):
        class Custom:
            pass

        assert build(Custom) == {}


class TestContainers:
    def test_list_of_str(self):
        assert build(list[str]) == {"type": "array", "items": {"type": "string"}}

    def test_bare_list(self):
        assert build(list) == {"type": "array"}

    def test_dict_with_value_type(self):
        assert build(dict[str, int]) == {
            "type": "object",
            "additionalProperties": {"type": "integer"},
        }

    def test_bare_dict(self):
        assert build(dict) == {"type": "object"}

    def test_set_of_str(self):
        assert build(set[str]) == {
            "type": "array",
            "uniqueItems": True,
            "items": {"type": "string"},
        }

    def test_fixed_tuple(self):
        schema = build(tuple[str, int])
        assert schema["type"] == "array"
        assert schema["prefixItems"] == [{"type": "string"}, {"type": "integer"}]
        assert schema["minItems"] == 2
        assert schema["maxItems"] == 2

    def test_variadic_tuple(self):
        assert build(tuple[int, ...]) == {"type": "array", "items": {"type": "integer"}}

    def test_nested_list(self):
        assert build(list[list[int]]) == {
            "type": "array",
            "items": {"type": "array", "items": {"type": "integer"}},
        }


class TestUnionsAndLiterals:
    def test_optional_unwraps(self):
        assert build(Optional[int]) == {"type": "integer"}  # noqa: UP045

    def test_pep_604_optional_unwraps(self):
        assert build(int | None) == {"type": "integer"}

    def test_multi_union_any_of(self):
        schema = build(Union[int, str])  # noqa: UP007
        assert schema == {"anyOf": [{"type": "integer"}, {"type": "string"}]}

    def test_string_literal(self):
        assert build(Literal["a", "b"]) == {"enum": ["a", "b"], "type": "string"}

    def test_int_literal(self):
        assert build(Literal[1, 2]) == {"enum": [1, 2], "type": "integer"}


class TestEnums:
    def test_str_enum(self):
        assert build(Colour) == {"enum": ["red", "blue"], "type": "string"}

    def test_int_enum(self):
        assert build(Level) == {"enum": [1, 2], "type": "integer"}


class TestDecoratorIntegration:
    def test_tool_schema_includes_rich_types(self):
        from lauren_mcp import mcp_tool
        from lauren_mcp.server._meta import MCP_TOOL_META

        @mcp_tool()
        async def search(
            self,
            query: str,
            mode: Literal["fast", "deep"] = "fast",
            tags: list[str] | None = None,
        ) -> list:
            """Search for things."""

        meta = getattr(search, MCP_TOOL_META)
        props = meta.input_schema["properties"]
        assert props["mode"]["enum"] == ["fast", "deep"]
        assert props["tags"]["type"] == "array"
        assert props["tags"]["items"] == {"type": "string"}
        assert props["tags"]["default"] is None
        assert meta.input_schema["required"] == ["query"]
