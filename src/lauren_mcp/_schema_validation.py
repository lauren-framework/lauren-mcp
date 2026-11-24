"""JSON Schema validation helpers for declared MCP tool output schemas."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any

from jsonschema import FormatChecker, validators


def _build_validator(schema: dict[str, Any]) -> Any:
    """Build a validator and reject malformed schemas before serving requests."""
    if not isinstance(schema, dict):
        raise TypeError("output_schema must resolve to a JSON Schema object")

    validator_type = validators.validator_for(schema)
    validator_type.check_schema(schema)
    return validator_type(schema, format_checker=FormatChecker())


@lru_cache(maxsize=128)
def _cached_validator(schema_json: str) -> Any:
    """Cache compiled validators by their canonical JSON representation."""
    return _build_validator(json.loads(schema_json))


def validate_schema(schema: dict[str, Any]) -> None:
    """Validate a schema declaration, raising when it is invalid or not JSON data."""
    try:
        json.dumps(schema, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"output_schema must be JSON-serialisable: {exc}") from exc
    _build_validator(schema)


def validate_output(value: Any, schema: dict[str, Any], tool_name: str) -> None:
    """Validate one structured tool result against its declared JSON Schema."""
    try:
        schema_json = json.dumps(
            schema,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"Tool {tool_name!r} outputSchema is not JSON-serialisable: {exc}"
        ) from exc

    validator = _cached_validator(schema_json)
    error = next(validator.iter_errors(value), None)
    if error is None:
        return

    location = ".".join(str(part) for part in error.absolute_path)
    target = f" at {location}" if location else ""
    raise ValueError(
        f"Tool {tool_name!r} structured output{target} does not satisfy "
        f"its outputSchema: {error.message}"
    ) from error
