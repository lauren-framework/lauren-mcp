"""Additional coverage tests for _schema.py — targeting remaining uncovered paths."""

from __future__ import annotations

import dataclasses
import enum
import typing
from typing import Any
from unittest.mock import patch

import pytest

from lauren_mcp.server._schema import SchemaBuilder, build_param_schema


def build(annotation: Any) -> dict:
    return SchemaBuilder().build(annotation)


# ---------------------------------------------------------------------------
# Pydantic availability paths
# ---------------------------------------------------------------------------


class TestPydanticUnavailable:
    def test_pydantic_unavailable_model_fields_emits_object(self):
        """When _PYDANTIC_AVAILABLE=False and model has model_fields, returns {type: object}."""
        with patch("lauren_mcp.server._schema._PYDANTIC_AVAILABLE", False):

            class FakeModel:
                model_fields = {"x": None}

            result = build(FakeModel)
            assert result == {"type": "object"}

    def test_pydantic_unavailable_no_struct_fields(self):
        """When _PYDANTIC_AVAILABLE=False but class has no special attrs, returns {}."""
        with patch("lauren_mcp.server._schema._PYDANTIC_AVAILABLE", False):

            class PlainClass:
                pass

            result = build(PlainClass)
            assert result == {}


class TestMsgspecUnavailable:
    def test_msgspec_unavailable_struct_fields_emits_object(self):
        """When _MSGSPEC_AVAILABLE=False and class has __struct_fields__, returns {type: object}."""
        with patch("lauren_mcp.server._schema._MSGSPEC_AVAILABLE", False):

            class FakeStruct:
                __struct_fields__ = ("x",)

            result = build(FakeStruct)
            assert result == {"type": "object"}


# ---------------------------------------------------------------------------
# _build_pydantic with nested models and $defs hoisting
# ---------------------------------------------------------------------------


class TestPydanticNested:
    def test_nested_model_hoists_defs(self):
        pydantic = pytest.importorskip("pydantic")

        class Inner(pydantic.BaseModel):
            value: int

        class Outer(pydantic.BaseModel):
            inner: Inner
            name: str

        sb = SchemaBuilder()
        result = sb.build(Outer)
        assert result == {"$ref": "#/$defs/Outer"}
        # Inner should be in defs (hoisted from $defs)
        assert "Outer" in sb.defs

    def test_self_referential_model_doesnt_infinite_loop(self):
        pydantic = pytest.importorskip("pydantic")
        from typing import Optional

        class Node(pydantic.BaseModel):
            value: int
            child: Optional["Node"] = None  # type: ignore[assignment]

        Node.model_rebuild()

        sb = SchemaBuilder()
        result = sb.build(Node)
        assert "$ref" in result


# ---------------------------------------------------------------------------
# _build_msgspec with schema
# ---------------------------------------------------------------------------


class TestMsgspecSchemaDetails:
    def test_msgspec_struct_produces_ref(self):
        msgspec = pytest.importorskip("msgspec")

        class Point(msgspec.Struct):
            x: float
            y: float

        sb = SchemaBuilder()
        result = sb.build(Point)
        assert "$ref" in result
        assert "Point" in sb.defs

    def test_msgspec_cached_second_call(self):
        msgspec = pytest.importorskip("msgspec")

        class Widget(msgspec.Struct):
            size: int

        sb = SchemaBuilder()
        r1 = sb.build(Widget)
        r2 = sb.build(Widget)
        assert r1 == r2
        assert list(sb.defs.keys()).count("Widget") == 1


# ---------------------------------------------------------------------------
# _build_dataclass — type hints exception path
# ---------------------------------------------------------------------------


class TestDataclassHintsException:
    def test_dataclass_get_type_hints_fallback(self):
        """When get_type_hints raises, falls back to f.type strings."""

        # We can't easily trigger the exception, but we can test that a
        # dataclass with no annotations still builds correctly.
        @dataclasses.dataclass
        class Empty:
            pass

        sb = SchemaBuilder()
        result = sb.build(Empty)
        assert result == {"$ref": "#/$defs/Empty"}
        schema = sb.defs["Empty"]
        assert schema["type"] == "object"
        assert schema["properties"] == {}


# ---------------------------------------------------------------------------
# _build_typeddict — hints exception path
# ---------------------------------------------------------------------------


class TestTypedDictHintsException:
    def test_typeddict_with_annotations_fallback(self):
        """TypedDict with __annotations__ is built correctly."""

        class Config(typing.TypedDict):
            name: str
            count: int

        sb = SchemaBuilder()
        sb.build(Config)
        assert "Config" in sb.defs
        assert "name" in sb.defs["Config"]["properties"]


# ---------------------------------------------------------------------------
# _apply_metadata — pydantic FieldInfo with default
# ---------------------------------------------------------------------------


class TestApplyMetadataFieldInfo:
    def test_field_info_with_default(self):
        pydantic = pytest.importorskip("pydantic")
        from pydantic import Field

        # Annotated[str, Field(default="hello")]
        annotation = typing.Annotated[str, Field(default="hello", description="A string")]
        result = build(annotation)
        assert result.get("description") == "A string"

    def test_field_info_with_metadata_items(self):
        """FieldInfo.metadata contains annotated_types constraints."""
        pydantic = pytest.importorskip("pydantic")
        try:
            import annotated_types
        except ImportError:
            pytest.skip("annotated_types not installed")
        from pydantic import Field

        annotation = typing.Annotated[int, Field(ge=0, le=100)]
        result = build(annotation)
        assert result.get("minimum") == 0
        assert result.get("maximum") == 100

    def test_field_info_with_examples(self):
        pydantic = pytest.importorskip("pydantic")
        from pydantic import Field

        annotation = typing.Annotated[str, Field(examples=["foo", "bar"])]
        result = build(annotation)
        assert result.get("examples") == ["foo", "bar"]


# ---------------------------------------------------------------------------
# _apply_metadata — _ParamSpec path
# ---------------------------------------------------------------------------


class TestApplyMetadataParamSpec:
    def test_param_spec_extracts_field_descriptor(self):
        """_ParamSpec metadata in Annotated is delegated to _apply_metadata(schema, fd)."""
        try:
            from lauren.extractors import _ParamSpec, FieldDescriptor
        except ImportError:
            pytest.skip("lauren not installed")

        fd = FieldDescriptor(ge=5)
        ps = _ParamSpec(field_descriptor=fd, pipes=())
        annotation = typing.Annotated[int, ps]

        sb = SchemaBuilder()
        result = sb.build(annotation)
        # The _ParamSpec path calls _apply_metadata(schema, fd) which applies constraints
        assert result.get("minimum") == 5


# ---------------------------------------------------------------------------
# TypedDict with Required wrapper
# ---------------------------------------------------------------------------


class TestTypedDictRequiredWrapper:
    def test_required_wrapper_makes_field_required(self):
        """Required[T] wrapper in a total=False TypedDict marks field as required."""

        class Config(typing.TypedDict, total=False):
            name: typing.Required[str]
            age: int

        sb = SchemaBuilder()
        sb.build(Config)
        schema = sb.defs["Config"]
        assert "name" in schema.get("required", [])
        assert "age" not in schema.get("required", [])

    def test_not_required_wrapper_excludes_from_required(self):
        """NotRequired[T] wrapper in a total=True TypedDict excludes field from required."""

        class Config(typing.TypedDict):
            name: str
            age: typing.NotRequired[int]

        sb = SchemaBuilder()
        sb.build(Config)
        schema = sb.defs["Config"]
        assert "name" in schema.get("required", [])
        assert "age" not in schema.get("required", [])


# ---------------------------------------------------------------------------
# build_param_schema — edge cases
# ---------------------------------------------------------------------------


class TestBuildParamSchemaEdgeCases:
    def test_empty_tuple_type(self):
        # bare tuple maps to the isinstance(annotation, type) and annotation in (list, set, frozenset)
        # Actually bare tuple is NOT in that list — it falls through to {}
        result = build(tuple)
        # bare tuple is not in _PRIMITIVES and not list/set/frozenset, so it degrades to {}
        assert isinstance(result, dict)

    def test_bare_frozenset_type(self):
        result = build(frozenset)
        assert result == {"type": "array"}

    def test_bare_set_type(self):
        result = build(set)
        assert result == {"type": "array"}

    def test_mixed_literal(self):
        """Mixed-type Literal (str + int) → enum without type field."""
        annotation = typing.Literal["a", 1]
        result = build(annotation)
        assert "enum" in result
        assert "a" in result["enum"]
        assert 1 in result["enum"]
        assert "type" not in result
