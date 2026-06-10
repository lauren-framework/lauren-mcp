"""Recursive JSON Schema builder for tool parameter annotations.

Supports — beyond primitives, containers, ``Literal``, ``Enum``, and
``Annotated`` constraints — four structured-type families, each emitted as a
``$ref`` into a shared ``$defs`` map:

* Pydantic ``BaseModel`` (optional dependency)
* ``msgspec.Struct`` (optional dependency)
* ``@dataclasses.dataclass`` classes
* ``TypedDict`` classes (``NotRequired`` / ``total=False`` respected)
"""

from __future__ import annotations

import dataclasses
import datetime
import enum
import inspect
import logging
import pathlib
import types
import typing
import uuid
from typing import Any, Literal, Union

_logger = logging.getLogger(__name__)

try:
    from pydantic import BaseModel
    from pydantic.fields import FieldInfo

    _PYDANTIC_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised via the non-pydantic path
    BaseModel = None
    FieldInfo = None
    _PYDANTIC_AVAILABLE = False

try:
    import msgspec

    _MSGSPEC_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised via the non-msgspec path
    msgspec = None
    _MSGSPEC_AVAILABLE = False

# Primitive type → JSON Schema fragment
_PRIMITIVES: dict[Any, dict[str, Any]] = {
    str: {"type": "string"},
    int: {"type": "integer"},
    float: {"type": "number"},
    bool: {"type": "boolean"},
    type(None): {"type": "null"},
    Any: {},
    uuid.UUID: {"type": "string", "format": "uuid"},
    datetime.datetime: {"type": "string", "format": "date-time"},
    datetime.date: {"type": "string", "format": "date"},
    datetime.time: {"type": "string", "format": "time"},
    datetime.timedelta: {"type": "string", "format": "duration"},
    pathlib.Path: {"type": "string", "format": "path"},
    bytes: {"type": "string", "format": "byte"},
}

# Pydantic FieldInfo metadata attr → JSON Schema keyword (numeric constraints
# arrive via annotated_types instances; we read their canonical attributes).
_CONSTRAINT_KEYWORDS = {
    "gt": "exclusiveMinimum",
    "ge": "minimum",
    "lt": "exclusiveMaximum",
    "le": "maximum",
    "min_length": "minLength",
    "max_length": "maxLength",
    "multiple_of": "multipleOf",
    "pattern": "pattern",
}


class SchemaBuilder:
    """Builds JSON Schema fragments from Python type annotations.

    One builder instance is shared across all parameters of a function so
    Pydantic model definitions are accumulated once into ``defs`` and can be
    attached to the top-level schema as ``$defs``.
    """

    def __init__(self) -> None:
        self.defs: dict[str, dict[str, Any]] = {}

    def build(self, annotation: Any) -> dict[str, Any]:
        """Return a JSON Schema fragment for *annotation*.

        Unknown types degrade to ``{}`` (unconstrained) rather than raising.
        """
        if annotation is inspect.Parameter.empty:
            return {"type": "string"}

        # TypedDict must be checked before the generic isinstance(type) path:
        # its metaclass behaviour differs across Python versions.
        if typing.is_typeddict(annotation):
            return self._build_typeddict(annotation)

        # Annotated[T, Field(...), ...] — build T then layer constraints
        if typing.get_origin(annotation) is typing.Annotated:
            base, *extras = typing.get_args(annotation)
            schema = self.build(base)
            for extra in extras:
                self._apply_metadata(schema, extra)
            return schema

        origin = typing.get_origin(annotation)

        if origin in (Union, types.UnionType):
            return self._build_union(typing.get_args(annotation))

        if origin is Literal:
            return self._build_literal(typing.get_args(annotation))

        if origin in (list, typing.List):  # noqa: UP006
            args = typing.get_args(annotation)
            schema = {"type": "array"}
            if args:
                schema["items"] = self.build(args[0])
            return schema

        if origin in (set, frozenset, typing.Set, typing.FrozenSet):  # noqa: UP006
            args = typing.get_args(annotation)
            schema = {"type": "array", "uniqueItems": True}
            if args:
                schema["items"] = self.build(args[0])
            return schema

        if origin in (tuple, typing.Tuple):  # noqa: UP006
            return self._build_tuple(typing.get_args(annotation))

        if origin in (dict, typing.Dict):  # noqa: UP006
            args = typing.get_args(annotation)
            schema = {"type": "object"}
            if len(args) == 2:
                schema["additionalProperties"] = self.build(args[1])
            return schema

        if isinstance(annotation, type):
            if annotation in _PRIMITIVES:
                return dict(_PRIMITIVES[annotation])
            if issubclass(annotation, enum.Enum):
                return self._build_enum(annotation)
            if _PYDANTIC_AVAILABLE and issubclass(annotation, BaseModel):
                return self._build_pydantic(annotation)
            if _MSGSPEC_AVAILABLE and issubclass(annotation, msgspec.Struct):
                return self._build_msgspec(annotation)
            if dataclasses.is_dataclass(annotation):
                return self._build_dataclass(annotation)
            if annotation in (list, set, frozenset):
                return {"type": "array"}
            if annotation is dict:
                return {"type": "object"}
            if not _PYDANTIC_AVAILABLE and hasattr(annotation, "model_fields"):
                _logger.warning(
                    "Pydantic is not installed; emitting unconstrained object schema for %r",
                    annotation,
                )
                return {"type": "object"}
            if not _MSGSPEC_AVAILABLE and hasattr(annotation, "__struct_fields__"):
                _logger.warning(
                    "msgspec is not installed; emitting unconstrained object schema for %r",
                    annotation,
                )
                return {"type": "object"}

        return {}

    # ------------------------------------------------------------------
    # Compound type handlers
    # ------------------------------------------------------------------

    def _build_union(self, args: tuple[Any, ...]) -> dict[str, Any]:
        non_none = [a for a in args if a is not type(None)]
        nullable = len(non_none) < len(args)
        if len(non_none) == 1:
            # Optional[X] — emit X's schema; MCP clients treat absence of
            # "required" as the optionality signal, so "null" is not added.
            return self.build(non_none[0])
        variants = [self.build(a) for a in non_none]
        if nullable:
            variants.append({"type": "null"})
        return {"anyOf": variants}

    def _build_literal(self, args: tuple[Any, ...]) -> dict[str, Any]:
        schema: dict[str, Any] = {"enum": list(args)}
        kinds = {type(a) for a in args}
        if kinds == {str}:
            schema["type"] = "string"
        elif kinds == {int}:
            schema["type"] = "integer"
        elif kinds == {bool}:
            schema["type"] = "boolean"
        return schema

    def _build_tuple(self, args: tuple[Any, ...]) -> dict[str, Any]:
        if not args:
            return {"type": "array"}
        if len(args) == 2 and args[1] is Ellipsis:
            return {"type": "array", "items": self.build(args[0])}
        return {
            "type": "array",
            "prefixItems": [self.build(a) for a in args],
            "minItems": len(args),
            "maxItems": len(args),
        }

    def _build_enum(self, annotation: type[enum.Enum]) -> dict[str, Any]:
        values = [member.value for member in annotation]
        schema: dict[str, Any] = {"enum": values}
        kinds = {type(v) for v in values}
        if kinds == {str}:
            schema["type"] = "string"
        elif kinds == {int}:
            schema["type"] = "integer"
        return schema

    def _build_pydantic(self, model: type[Any]) -> dict[str, Any]:
        name = model.__name__
        if name not in self.defs:
            # Reserve the slot first so self-referential models terminate.
            self.defs[name] = {}
            try:
                model_schema = model.model_json_schema(ref_template="#/$defs/{model}")
            except AttributeError:  # pydantic v1
                model_schema = model.schema(ref_template="#/$defs/{model}")
            # Hoist nested definitions into the shared defs map.
            for key in ("$defs", "definitions"):
                for def_name, def_schema in model_schema.pop(key, {}).items():
                    self.defs.setdefault(def_name, def_schema)
            self.defs[name] = model_schema
        return {"$ref": f"#/$defs/{name}"}

    def _build_msgspec(self, struct: type[Any]) -> dict[str, Any]:
        name = struct.__name__
        if name not in self.defs:
            self.defs[name] = {}
            struct_schema = msgspec.json.schema(struct)
            # msgspec returns {"$ref": "#/$defs/Name", "$defs": {...}} —
            # hoist its definitions into the shared defs map.
            for def_name, def_schema in struct_schema.pop("$defs", {}).items():
                if def_name == name:
                    self.defs[name] = def_schema
                else:
                    self.defs.setdefault(def_name, def_schema)
            if not self.defs[name] and "$ref" not in struct_schema:
                # Inline schema (no defs emitted) — use it directly.
                self.defs[name] = struct_schema
        return {"$ref": f"#/$defs/{name}"}

    def _build_dataclass(self, cls: type[Any]) -> dict[str, Any]:
        name = cls.__name__
        if name not in self.defs:
            # Reserve the slot first so self-referential dataclasses terminate.
            self.defs[name] = {}
            try:
                hints = typing.get_type_hints(cls, include_extras=True)
            except Exception:
                hints = {}
            properties: dict[str, Any] = {}
            required: list[str] = []
            for f in dataclasses.fields(cls):
                prop = self.build(hints.get(f.name, f.type))
                if f.default is not dataclasses.MISSING and isinstance(
                    f.default, (str, int, float, bool, type(None))
                ):
                    prop.setdefault("default", f.default)
                properties[f.name] = prop
                if f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING:
                    required.append(f.name)
            schema: dict[str, Any] = {
                "type": "object",
                "title": name,
                "properties": properties,
            }
            if required:
                schema["required"] = required
            self.defs[name] = schema
        return {"$ref": f"#/$defs/{name}"}

    def _build_typeddict(self, cls: Any) -> dict[str, Any]:
        name = cls.__name__
        if name not in self.defs:
            self.defs[name] = {}
            try:
                hints = typing.get_type_hints(cls, include_extras=True)
            except Exception:
                hints = dict(getattr(cls, "__annotations__", {}))
            required_keys: frozenset[str] = getattr(cls, "__required_keys__", frozenset())
            properties = {}
            required: list[str] = []
            for field_name, annotation in hints.items():
                # The Required[...] / NotRequired[...] wrapper on the resolved
                # hint wins over __required_keys__ — under PEP 563 (string
                # annotations) __required_keys__ cannot see the wrappers.
                origin = typing.get_origin(annotation)
                if origin is typing.NotRequired:
                    annotation = typing.get_args(annotation)[0]
                    is_required = False
                elif origin is typing.Required:
                    annotation = typing.get_args(annotation)[0]
                    is_required = True
                else:
                    is_required = field_name in required_keys
                properties[field_name] = self.build(annotation)
                if is_required:
                    required.append(field_name)
            schema: dict[str, Any] = {
                "type": "object",
                "title": name,
                "properties": properties,
            }
            if required:
                schema["required"] = sorted(required)
            self.defs[name] = schema
        return {"$ref": f"#/$defs/{name}"}

    # ------------------------------------------------------------------
    # Annotated metadata (pydantic Field / annotated_types instances)
    # ------------------------------------------------------------------

    def _apply_metadata(self, schema: dict[str, Any], extra: Any) -> None:
        if _PYDANTIC_AVAILABLE and FieldInfo is not None and isinstance(extra, FieldInfo):
            if extra.description:
                schema["description"] = extra.description
            if extra.examples:
                schema["examples"] = list(extra.examples)
            default = getattr(extra, "default", None)
            if default is not None and repr(default) != "PydanticUndefined":
                schema["default"] = default
            for meta_item in getattr(extra, "metadata", []):
                self._apply_metadata(schema, meta_item)
            return
        # annotated_types constraint objects (Ge, Le, MinLen, …) and pydantic
        # v1 FieldInfo both expose the constraint values as attributes.
        for attr, keyword in _CONSTRAINT_KEYWORDS.items():
            value = getattr(extra, attr, None)
            if value is not None:
                schema[keyword] = value


def build_param_schema(annotation: Any, builder: SchemaBuilder | None = None) -> dict[str, Any]:
    """Convenience wrapper: build a schema for one annotation."""
    return (builder or SchemaBuilder()).build(annotation)
