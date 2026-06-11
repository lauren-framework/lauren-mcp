"""Coverage tests for lauren_mcp.server._schema — targeting uncovered SchemaBuilder paths."""

from __future__ import annotations

import dataclasses
import enum
import typing
from typing import Any, NotRequired, Required

import pytest

from lauren_mcp.server._schema import SchemaBuilder, build_param_schema


def build(annotation: Any) -> dict:
    return SchemaBuilder().build(annotation)


# Module-level dataclasses for nested tests (avoids from __future__ import annotations issues)
@dataclasses.dataclass
class _InnerDC:
    value: int


@dataclasses.dataclass
class _OuterDC:
    inner: _InnerDC
    name: str


# ---------------------------------------------------------------------------
# Empty / inspect.Parameter.empty
# ---------------------------------------------------------------------------


class TestEmptyAnnotation:
    def test_empty_parameter_returns_string_type(self):
        import inspect

        result = build(inspect.Parameter.empty)
        assert result == {"type": "string"}


# ---------------------------------------------------------------------------
# TypedDict with NotRequired and Required wrappers
# ---------------------------------------------------------------------------


class TestTypedDict:
    def test_all_required_typeddict(self):
        class Config(typing.TypedDict):
            host: str
            port: int

        sb = SchemaBuilder()
        result = sb.build(Config)
        assert result == {"$ref": "#/$defs/Config"}
        schema = sb.defs["Config"]
        assert schema["type"] == "object"
        assert "host" in schema["required"]
        assert "port" in schema["required"]

    def test_not_required_fields(self):
        class Config(typing.TypedDict, total=False):
            host: str
            port: int

        sb = SchemaBuilder()
        result = sb.build(Config)
        schema = sb.defs["Config"]
        # total=False means no required fields
        assert "required" not in schema or schema.get("required") == []

    def test_mixed_required_notreq(self):
        class Config(typing.TypedDict):
            name: str
            age: NotRequired[int]

        sb = SchemaBuilder()
        result = sb.build(Config)
        schema = sb.defs["Config"]
        assert "name" in schema.get("required", [])
        assert "age" not in schema.get("required", [])

    def test_required_wrapper(self):
        class Config(typing.TypedDict, total=False):
            name: Required[str]
            age: int

        sb = SchemaBuilder()
        result = sb.build(Config)
        schema = sb.defs["Config"]
        assert "name" in schema.get("required", [])

    def test_typeddict_cached(self):
        class Config(typing.TypedDict):
            x: int

        sb = SchemaBuilder()
        r1 = sb.build(Config)
        r2 = sb.build(Config)
        assert r1 == r2
        assert list(sb.defs.keys()).count("Config") == 1

    def test_typeddict_properties_built(self):
        class Config(typing.TypedDict):
            name: str
            count: int

        sb = SchemaBuilder()
        sb.build(Config)
        schema = sb.defs["Config"]
        assert schema["properties"]["name"] == {"type": "string"}
        assert schema["properties"]["count"] == {"type": "integer"}


# ---------------------------------------------------------------------------
# Enum types
# ---------------------------------------------------------------------------


class TestEnumSchema:
    def test_str_enum_has_type_string(self):
        class Color(str, enum.Enum):
            RED = "red"
            GREEN = "green"

        result = build(Color)
        assert result["type"] == "string"
        assert "red" in result["enum"]

    def test_int_enum_has_type_integer(self):
        class Priority(enum.Enum):
            LOW = 1
            HIGH = 2

        result = build(Priority)
        assert result["type"] == "integer"
        assert 1 in result["enum"]

    def test_mixed_enum_no_type(self):
        class Mixed(enum.Enum):
            A = "string_val"
            B = 1

        result = build(Mixed)
        assert "type" not in result
        assert "enum" in result


# ---------------------------------------------------------------------------
# Dataclass schema
# ---------------------------------------------------------------------------


class TestDataclassSchema:
    def test_basic_dataclass(self):
        @dataclasses.dataclass
        class Point:
            x: float
            y: float

        sb = SchemaBuilder()
        result = sb.build(Point)
        assert result == {"$ref": "#/$defs/Point"}
        schema = sb.defs["Point"]
        assert schema["type"] == "object"
        assert "x" in schema["properties"]
        assert "y" in schema["properties"]
        assert "x" in schema["required"]
        assert "y" in schema["required"]

    def test_dataclass_with_defaults(self):
        @dataclasses.dataclass
        class Config:
            host: str = "localhost"
            port: int = 8080

        sb = SchemaBuilder()
        sb.build(Config)
        schema = sb.defs["Config"]
        # Fields with defaults are not required
        assert "required" not in schema or "host" not in schema.get("required", [])
        # Default values are set on the property schema
        assert schema["properties"]["host"].get("default") == "localhost"
        assert schema["properties"]["port"].get("default") == 8080

    def test_dataclass_with_default_factory(self):
        @dataclasses.dataclass
        class Config:
            tags: list = dataclasses.field(default_factory=list)

        sb = SchemaBuilder()
        sb.build(Config)
        schema = sb.defs["Config"]
        # default_factory means no default in schema, not required
        assert "tags" not in schema.get("required", [])

    def test_dataclass_cached(self):
        @dataclasses.dataclass
        class Item:
            name: str

        sb = SchemaBuilder()
        r1 = sb.build(Item)
        r2 = sb.build(Item)
        assert r1 == r2

    def test_nested_dataclass(self):
        """Builder produces valid schema for a dataclass with nested dataclass field."""
        # Use module-level dataclasses (not locally defined) to avoid __future__ annotations issue
        sb = SchemaBuilder()
        sb.build(_OuterDC)
        assert "_OuterDC" in sb.defs
        outer_schema = sb.defs["_OuterDC"]
        assert outer_schema["type"] == "object"
        assert "inner" in outer_schema["properties"]
        assert "name" in outer_schema["properties"]
        # _InnerDC should also be in defs (recursively built)
        assert "_InnerDC" in sb.defs


# ---------------------------------------------------------------------------
# Pydantic model schema
# ---------------------------------------------------------------------------


class TestPydanticSchema:
    def test_basic_pydantic_model(self):
        pydantic = pytest.importorskip("pydantic")

        class Item(pydantic.BaseModel):
            name: str
            count: int

        sb = SchemaBuilder()
        result = sb.build(Item)
        assert result == {"$ref": "#/$defs/Item"}
        assert "Item" in sb.defs

    def test_pydantic_model_cached(self):
        pydantic = pytest.importorskip("pydantic")

        class Widget(pydantic.BaseModel):
            size: float

        sb = SchemaBuilder()
        r1 = sb.build(Widget)
        r2 = sb.build(Widget)
        assert r1 == r2

    def test_pydantic_model_missing_no_pydantic(self):
        """When pydantic is unavailable, model_fields attr triggers fallback."""
        import sys
        from unittest.mock import patch

        # Simulate pydantic not installed by checking the warning path
        # We patch _PYDANTIC_AVAILABLE to False
        with patch("lauren_mcp.server._schema._PYDANTIC_AVAILABLE", False):

            class FakeModel:
                model_fields = {"x": None}

            result = build(FakeModel)
            assert result == {"type": "object"}


# ---------------------------------------------------------------------------
# msgspec.Struct schema
# ---------------------------------------------------------------------------


class TestMsgspecSchema:
    def test_basic_msgspec_struct(self):
        msgspec = pytest.importorskip("msgspec")

        class Point(msgspec.Struct):
            x: float
            y: float

        sb = SchemaBuilder()
        result = sb.build(Point)
        assert "$ref" in result
        assert "Point" in sb.defs

    def test_msgspec_missing(self):
        """When msgspec unavailable, __struct_fields__ triggers fallback warning + {} or object schema."""
        from unittest.mock import patch

        with patch("lauren_mcp.server._schema._MSGSPEC_AVAILABLE", False):

            class FakeStruct:
                __struct_fields__ = ("x",)

            result = build(FakeStruct)
            assert result == {"type": "object"}


# ---------------------------------------------------------------------------
# Annotated with metadata
# ---------------------------------------------------------------------------


class TestAnnotatedMetadata:
    def test_annotated_with_description(self):
        """Annotated[str, ...] with description metadata."""
        pydantic = pytest.importorskip("pydantic")
        from pydantic import Field

        annotation = typing.Annotated[str, Field(description="A name")]
        result = build(annotation)
        assert result.get("description") == "A name"

    def test_annotated_with_examples(self):
        pydantic = pytest.importorskip("pydantic")
        from pydantic import Field

        annotation = typing.Annotated[str, Field(examples=["foo", "bar"])]
        result = build(annotation)
        assert result.get("examples") == ["foo", "bar"]

    def test_annotated_with_constraints(self):
        """annotated_types-style constraints applied via _apply_metadata."""
        try:
            import annotated_types
        except ImportError:
            pytest.skip("annotated_types not installed")

        annotation = typing.Annotated[int, annotated_types.Ge(0), annotated_types.Le(100)]
        result = build(annotation)
        assert result.get("minimum") == 0
        assert result.get("maximum") == 100

    def test_annotated_base_schema_preserved(self):
        annotation = typing.Annotated[str, object()]
        result = build(annotation)
        assert result.get("type") == "string"


# ---------------------------------------------------------------------------
# Union types with nullable
# ---------------------------------------------------------------------------


class TestUnionTypes:
    def test_nullable_union_emits_null_variant(self):
        annotation = typing.Union[int, str, None]
        result = build(annotation)
        # Multiple non-None types → anyOf with null
        schemas = result["anyOf"]
        has_null = any(s == {"type": "null"} for s in schemas)
        assert has_null

    def test_union_two_types(self):
        annotation = typing.Union[int, str]
        result = build(annotation)
        assert "anyOf" in result

    def test_optional_str(self):
        annotation = typing.Optional[str]
        result = build(annotation)
        assert result == {"type": "string"}


# ---------------------------------------------------------------------------
# build_param_schema convenience wrapper
# ---------------------------------------------------------------------------


class TestBuildParamSchema:
    def test_builds_schema_for_str(self):
        result = build_param_schema(str)
        assert result == {"type": "string"}

    def test_accepts_external_builder(self):
        sb = SchemaBuilder()
        result = build_param_schema(int, builder=sb)
        assert result == {"type": "integer"}

    def test_creates_builder_when_none(self):
        result = build_param_schema(float)
        assert result == {"type": "number"}


# ---------------------------------------------------------------------------
# Frozenset / set handling
# ---------------------------------------------------------------------------


class TestSetSchema:
    def test_frozenset(self):
        result = build(frozenset[str])
        assert result["type"] == "array"
        assert result["uniqueItems"] is True

    def test_bare_set(self):
        result = build(set)
        assert result == {"type": "array"}

    def test_bare_frozenset(self):
        result = build(frozenset)
        assert result == {"type": "array"}


# ---------------------------------------------------------------------------
# Additional primitives
# ---------------------------------------------------------------------------


class TestAdditionalPrimitives:
    def test_none_type(self):
        result = build(type(None))
        assert result == {"type": "null"}

    def test_any_type(self):
        result = build(Any)
        assert result == {}

    def test_bytes_type(self):
        import pathlib

        result = build(bytes)
        assert result == {"type": "string", "format": "byte"}

    def test_path_type(self):
        import pathlib

        result = build(pathlib.Path)
        assert result == {"type": "string", "format": "path"}


# ---------------------------------------------------------------------------
# Tuple schemas
# ---------------------------------------------------------------------------


class TestTupleSchema:
    def test_empty_tuple(self):
        result = build(tuple[()])
        # tuple[()] is tuple[()], treated as empty args → {"type": "array"}
        assert result.get("type") == "array"

    def test_tuple_variadic(self):
        result = build(tuple[str, ...])
        assert result == {"type": "array", "items": {"type": "string"}}
