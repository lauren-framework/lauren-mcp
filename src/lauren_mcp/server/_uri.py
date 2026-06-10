"""URI template compilation and matching (RFC 6570 subset).

Supported operators:

* ``{param}``   — single path segment (no slashes)
* ``{+param}``  — reserved expansion: matches across slashes
* ``{param*}``  — explode modifier: same multi-segment behaviour
* ``{?p1,p2}``  — optional query parameters (must be the template suffix)
"""

from __future__ import annotations

import re
import typing
from typing import Any, NamedTuple
from urllib.parse import parse_qs

_QUERY_BLOCK = re.compile(r"\{\?([\w,]+)\}\s*$")
_PLACEHOLDER = re.compile(r"\{(\+?)(\w+)(\*?)\}")


class CompiledTemplate(NamedTuple):
    """A URI template compiled to a path regex plus declared query params."""

    path_pattern: re.Pattern[str]
    query_params: tuple[str, ...]


def compile_uri_template(template: str) -> CompiledTemplate:
    """Compile *template* into a :class:`CompiledTemplate`."""
    query_params: tuple[str, ...] = ()
    m = _QUERY_BLOCK.search(template)
    if m:
        query_params = tuple(m.group(1).split(","))
        template = template[: m.start()]

    # Escape the literal parts only — re.escape would mangle the +/* inside
    # the placeholders themselves.
    parts: list[str] = []
    last = 0
    for m in _PLACEHOLDER.finditer(template):
        parts.append(re.escape(template[last : m.start()]))
        plus, name, star = m.groups()
        if plus or star:
            parts.append(f"(?P<{name}>.+)")
        else:
            parts.append(f"(?P<{name}>[^/]+)")
        last = m.end()
    parts.append(re.escape(template[last:]))
    return CompiledTemplate(re.compile(f"^{''.join(parts)}$"), query_params)


def match_uri(compiled: CompiledTemplate, uri: str) -> dict[str, str] | None:
    """Match *uri* against *compiled*; return merged path+query vars or None."""
    if compiled.query_params:
        # Split on the first '?' directly — urlsplit treats custom schemes
        # (e.g. items://) inconsistently across Python versions.
        path, _, query = uri.partition("?")
    else:
        path, query = uri, ""

    m = compiled.path_pattern.match(path)
    if m is None:
        return None
    variables: dict[str, str] = dict(m.groupdict())

    if compiled.query_params and query:
        parsed = parse_qs(query, keep_blank_values=True)
        for name in compiled.query_params:
            if name in parsed:
                variables[name] = parsed[name][0]
    return variables


def coerce_params(variables: dict[str, str], type_hints: dict[str, Any]) -> dict[str, Any]:
    """Coerce string URI variables using the resource method's annotations."""
    coerced: dict[str, Any] = {}
    for name, value in variables.items():
        annotation = type_hints.get(name)
        coerced[name] = _coerce_value(value, annotation)
    return coerced


def _coerce_value(value: str, annotation: Any) -> Any:
    if annotation is None or annotation is str:
        return value
    origin = typing.get_origin(annotation)
    if origin is typing.Union or str(origin) == "<class 'types.UnionType'>":
        for arg in typing.get_args(annotation):
            if arg is type(None):
                continue
            try:
                return _coerce_value(value, arg)
            except (ValueError, TypeError):
                continue
        return value
    if annotation is bool:
        return value.lower() in ("1", "true", "yes", "on")
    if annotation in (int, float):
        return annotation(value)
    return value


__all__ = ["CompiledTemplate", "compile_uri_template", "match_uri", "coerce_params"]
