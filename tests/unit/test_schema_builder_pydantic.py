"""Pydantic-dependent schema builder tests (skipped when pydantic is absent)."""

from __future__ import annotations

from typing import Annotated, Literal

import pytest

from lauren_mcp.server._schema import SchemaBuilder

pydantic = pytest.importorskip("pydantic", reason="requires pydantic")
BaseModel = pydantic.BaseModel
Field = pydantic.Field


class Address(BaseModel):
    street: str
    zip_code: str


class Person(BaseModel):
    name: str
    age: int = 0
    address: Address | None = None


def build(annotation):
    return SchemaBuilder().build(annotation)


class TestAnnotatedConstraints:
    def test_field_numeric_constraints(self):
        schema = build(Annotated[int, Field(ge=0, le=100)])
        assert schema["type"] == "integer"
        assert schema["minimum"] == 0
        assert schema["maximum"] == 100

    def test_field_description(self):
        schema = build(Annotated[str, Field(description="A name")])
        assert schema["description"] == "A name"

    def test_field_pattern(self):
        schema = build(Annotated[str, Field(pattern=r"^\d+$")])
        assert schema["pattern"] == r"^\d+$"

    def test_field_length_constraints(self):
        schema = build(Annotated[str, Field(min_length=1, max_length=8)])
        assert schema["minLength"] == 1
        assert schema["maxLength"] == 8


class TestPydanticModels:
    def test_model_becomes_ref_with_defs(self):
        builder = SchemaBuilder()
        schema = builder.build(Person)
        assert schema == {"$ref": "#/$defs/Person"}
        assert "Person" in builder.defs
        person_def = builder.defs["Person"]
        assert person_def["properties"]["name"]["type"] == "string"

    def test_nested_model_defs_hoisted(self):
        builder = SchemaBuilder()
        builder.build(Person)
        assert "Address" in builder.defs

    def test_defs_deduplicated_across_params(self):
        builder = SchemaBuilder()
        builder.build(Person)
        builder.build(Person)
        assert list(builder.defs).count("Person") == 1


class TestDecoratorIntegration:
    def test_tool_schema_includes_model_and_constraints(self):
        from lauren_mcp import mcp_tool
        from lauren_mcp.server._meta import MCP_TOOL_META

        @mcp_tool()
        async def search(
            self,
            query: str,
            mode: Literal["fast", "deep"] = "fast",
            limit: Annotated[int, Field(ge=1, le=50)] = 10,
            person: Person | None = None,
        ) -> list:
            """Search for things."""

        meta = getattr(search, MCP_TOOL_META)
        props = meta.input_schema["properties"]
        assert props["limit"]["minimum"] == 1
        assert props["person"]["$ref"] == "#/$defs/Person"
        assert props["person"]["default"] is None
        assert "Person" in meta.input_schema["$defs"]

    def test_field_description_wins_over_docstring(self):
        from lauren_mcp import mcp_tool
        from lauren_mcp.server._meta import MCP_TOOL_META

        @mcp_tool()
        async def search(self, query: Annotated[str, Field(description="From Field")]) -> list:
            """Search.

            Args:
                query: From docstring.
            """

        meta = getattr(search, MCP_TOOL_META)
        assert meta.input_schema["properties"]["query"]["description"] == "From Field"
