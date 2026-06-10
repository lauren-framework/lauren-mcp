"""Docstring parsing — top-level description and per-parameter descriptions.

Supports the three common styles:

* Google:  ``Args:\\n    param: description``
* Sphinx:  ``:param param: description``
* NumPy:   ``Parameters\\n----------\\nparam : type\\n    description``
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

_GOOGLE_SECTION = re.compile(
    r"^(args|arguments|parameters|returns|raises|yields|examples?|notes?|attributes)\s*:\s*$",
    re.IGNORECASE,
)
_SPHINX_PARAM = re.compile(r"^:param\s+(?:[\w\[\]., |]+\s+)?(\w+)\s*:\s*(.*)$")
_NUMPY_UNDERLINE = re.compile(r"^-{3,}\s*$")
# "param (int): desc" / "param: desc" — type hints in parens are stripped
_GOOGLE_ARG = re.compile(r"^(\*{0,2}\w+)\s*(?:\(([^)]*)\))?\s*:\s*(.*)$")
# NumPy "param : int" header line
_NUMPY_ARG = re.compile(r"^(\w+)\s*(?::\s*(.*))?$")


def _normalise(text: str) -> str:
    """Collapse internal whitespace runs into single spaces."""
    return " ".join(text.split())


def _parse_google(lines: list[str]) -> dict[str, str]:
    """Extract param descriptions from a Google-style ``Args:`` section."""
    params: dict[str, str] = {}
    in_args = False
    current: str | None = None
    base_indent: int | None = None

    for line in lines:
        stripped = line.strip()
        section = _GOOGLE_SECTION.match(stripped)
        if section:
            in_args = section.group(1).lower() in ("args", "arguments", "parameters")
            current = None
            base_indent = None
            continue
        if not in_args or not stripped:
            current = None if not stripped else current
            continue

        indent = len(line) - len(line.lstrip())
        if base_indent is None:
            base_indent = indent

        m = _GOOGLE_ARG.match(stripped)
        if m and indent <= base_indent:
            current = m.group(1).lstrip("*")
            params[current] = _normalise(m.group(3))
        elif current is not None and indent > base_indent:
            # Continuation line for the current param.
            params[current] = _normalise(params[current] + " " + stripped)

    return params


def _parse_sphinx(lines: list[str]) -> dict[str, str]:
    """Extract ``:param name: description`` entries (with continuations)."""
    params: dict[str, str] = {}
    current: str | None = None

    for line in lines:
        stripped = line.strip()
        m = _SPHINX_PARAM.match(stripped)
        if m:
            current = m.group(1)
            params[current] = _normalise(m.group(2))
            continue
        if stripped.startswith(":"):
            current = None  # any other field (:returns:, :raises:, …)
            continue
        if current is not None and stripped:
            params[current] = _normalise(params[current] + " " + stripped)
        elif not stripped:
            current = None

    return params


def _parse_numpy(lines: list[str]) -> dict[str, str]:
    """Extract param descriptions from a NumPy-style ``Parameters`` section."""
    params: dict[str, str] = {}
    in_params = False
    current: str | None = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        # Detect a "Parameters" header followed by an underline.
        if (
            stripped.lower() in ("parameters", "params")
            and i + 1 < len(lines)
            and _NUMPY_UNDERLINE.match(lines[i + 1].strip())
        ):
            in_params = True
            current = None
            continue
        if _NUMPY_UNDERLINE.match(stripped):
            continue
        if not in_params:
            continue
        # A new (non-indented) section header ends the Parameters block.
        if (
            stripped
            and not line.startswith((" ", "\t"))
            and stripped.lower()
            in (
                "returns",
                "raises",
                "yields",
                "examples",
                "notes",
                "see also",
            )
        ):
            in_params = False
            continue
        if not stripped:
            continue

        indent = len(line) - len(line.lstrip())
        if indent == 0 or (current is None and indent <= 4):
            m = _NUMPY_ARG.match(stripped)
            if m and (m.group(2) is not None or stripped == m.group(1)):
                current = m.group(1)
                params[current] = ""
                continue
        if current is not None:
            existing = params[current]
            params[current] = _normalise((existing + " " + stripped).strip())

    return params


def parse_docstring(fn: Callable[..., Any]) -> tuple[str, dict[str, str]]:
    """Return ``(top_description, {param_name: description})`` for *fn*.

    The top description is the first paragraph (before any section header
    or ``:param`` field).  Parameter descriptions are merged from all three
    supported styles with priority Google > NumPy > Sphinx.
    """
    doc = fn.__doc__
    if not doc:
        return "", {}

    lines = doc.expandtabs().splitlines()
    # Strip uniform leading indentation (first line is usually unindented).
    if len(lines) > 1:
        indents = [len(line) - len(line.lstrip()) for line in lines[1:] if line.strip()]
        if indents:
            cut = min(indents)
            lines = [lines[0]] + [line[cut:] if line.strip() else "" for line in lines[1:]]

    # Top description: lines until a blank-line paragraph break, a section
    # header, or a Sphinx field.
    top_parts: list[str] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if (
            _GOOGLE_SECTION.match(stripped)
            or stripped.startswith(":")
            or (
                stripped.lower() in ("parameters", "params")
                and i + 1 < len(lines)
                and _NUMPY_UNDERLINE.match(lines[i + 1].strip())
            )
        ):
            break
        if not stripped:
            if top_parts:
                break
            continue
        top_parts.append(stripped)

    params: dict[str, str] = {}
    params.update(_parse_sphinx(lines))
    params.update(_parse_numpy(lines))
    params.update(_parse_google(lines))
    # Drop empty descriptions (e.g. a NumPy header with no body).
    params = {k: v for k, v in params.items() if v}

    return " ".join(top_parts), params
