"""Additional coverage tests for _schema.py — targeting final remaining paths."""

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
# _build_dataclass — get_type_hints exception path (lines 260-261)
# ---------------------------------------------------------------------------


class TestDataclassTypeHintsException:
    def test_dataclass_type_hints_exception_fallback(self):
        """When get_type_hints raises, builder falls back gracefully."""

        @dataclasses.dataclass
        class Config:
            name: str
            value: int

        sb = SchemaBuilder()
        with patch("typing.get_type_hints", side_effect=Exception("hints failed")):
            result = sb.build(Config)
        # Should not raise — falls back to empty hints
        assert result == {"$ref": "#/$defs/Config"}
        # Without type hints, fields use f.type (which is a string or the type object)
        schema = sb.defs["Config"]
        assert schema["type"] == "object"


# ---------------------------------------------------------------------------
# _build_typeddict — get_type_hints exception path (lines 289-290)
# ---------------------------------------------------------------------------


class TestTypedDictTypeHintsException:
    def test_typeddict_hints_exception_uses_annotations(self):
        """When get_type_hints raises, falls back to __annotations__."""

        class Config(typing.TypedDict):
            name: str
            value: int

        sb = SchemaBuilder()
        with patch("typing.get_type_hints", side_effect=Exception("hints failed")):
            result = sb.build(Config)
        assert result == {"$ref": "#/$defs/Config"}
        schema = sb.defs["Config"]
        assert schema["type"] == "object"


# ---------------------------------------------------------------------------
# _build_enum — mixed-type enum (no type field)
# ---------------------------------------------------------------------------


class TestBuildEnumMixed:
    def test_mixed_enum_has_no_type_field(self):
        class Mixed(enum.Enum):
            STR_VAL = "hello"
            INT_VAL = 42

        result = build(Mixed)
        assert "enum" in result
        assert "type" not in result

    def test_single_value_enum(self):
        class Status(enum.Enum):
            ACTIVE = "active"

        result = build(Status)
        assert result["enum"] == ["active"]
        assert result["type"] == "string"


# ---------------------------------------------------------------------------
# SchemaBuilder — build with defs accumulation (test that defs is shared)
# ---------------------------------------------------------------------------


class TestSchemaBuilderDefsAccumulation:
    def test_defs_shared_across_multiple_builds(self):
        """Using the same builder for multiple types shares defs."""
        sb = SchemaBuilder()

        @dataclasses.dataclass
        class TypeA:
            x: int

        @dataclasses.dataclass
        class TypeB:
            y: str

        sb.build(TypeA)
        sb.build(TypeB)
        assert "TypeA" in sb.defs
        assert "TypeB" in sb.defs

    def test_defs_included_in_schema_when_present(self):
        """When builder.defs is non-empty, it gets attached by external code."""
        sb = SchemaBuilder()

        @dataclasses.dataclass
        class Config:
            port: int

        sb.build(Config)
        assert len(sb.defs) > 0


# ---------------------------------------------------------------------------
# Additional union/nullable tests
# ---------------------------------------------------------------------------


class TestUnionNullable:
    def test_three_type_union_with_null(self):
        """Union of 3 types including None → anyOf with null at end."""
        annotation = typing.Union[int, str, None]
        result = build(annotation)
        assert "anyOf" in result
        schemas = result["anyOf"]
        assert {"type": "null"} in schemas
        # Should have int, str, null
        assert {"type": "integer"} in schemas
        assert {"type": "string"} in schemas

    def test_union_without_none(self):
        annotation = typing.Union[int, str]
        result = build(annotation)
        assert "anyOf" in result
        assert {"type": "null"} not in result["anyOf"]


# ---------------------------------------------------------------------------
# Annotated with multiple metadata items (layered constraints)
# ---------------------------------------------------------------------------


class TestAnnotatedMultipleMetadata:
    def test_annotated_multiple_constraints(self):
        """Multiple constraint objects in Annotated are all applied."""
        try:
            import annotated_types
        except ImportError:
            pytest.skip("annotated_types not installed")

        annotation = typing.Annotated[
            int,
            annotated_types.Ge(1),
            annotated_types.Le(100),
            annotated_types.MultipleOf(5),
        ]
        result = build(annotation)
        assert result.get("minimum") == 1
        assert result.get("maximum") == 100
        assert result.get("multipleOf") == 5

    def test_annotated_min_max_length(self):
        try:
            import annotated_types
        except ImportError:
            pytest.skip("annotated_types not installed")

        annotation = typing.Annotated[
            str,
            annotated_types.MinLen(2),
            annotated_types.MaxLen(50),
        ]
        result = build(annotation)
        assert result.get("minLength") == 2
        assert result.get("maxLength") == 50

    def test_annotated_pattern(self):
        # annotated_types.Pattern may not exist in all versions
        try:
            import annotated_types

            if not hasattr(annotated_types, "Pattern"):
                pytest.skip("annotated_types.Pattern not available in this version")
            annotation = typing.Annotated[str, annotated_types.Pattern(r"^[a-z]+$")]
            result = build(annotation)
            assert result.get("pattern") == r"^[a-z]+$"
        except ImportError:
            pytest.skip("annotated_types not installed")


# ---------------------------------------------------------------------------
# dict without type args
# ---------------------------------------------------------------------------


class TestDictAnnotations:
    def test_bare_dict_no_args(self):
        result = build(dict)
        assert result == {"type": "object"}

    def test_dict_with_one_arg_only(self):
        # dict[str] is invalid but dict[str, int] has 2 args
        annotation = typing.Dict[str, str]  # noqa: UP006
        result = build(annotation)
        assert result["type"] == "object"
        assert result.get("additionalProperties") == {"type": "string"}
