"""Decorators: mcp_server, mcp_tool, mcp_resource, mcp_prompt, mcp_lifespan."""

from __future__ import annotations

import inspect
import re
import typing
import warnings
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from lauren_mcp._server._context import McpToolContext
from lauren_mcp._types import ToolAnnotations

from ._docstring import parse_docstring
from ._meta import (
    MCP_COMPLETION_META,
    MCP_LIFESPAN_META,
    MCP_PROMPT_META,
    MCP_RESOURCE_META,
    MCP_SERVER_META,
    MCP_TOOL_META,
    McpCompletionMeta,
    McpLifespanMeta,
    McpPromptMeta,
    McpResourceMeta,
    McpServerMeta,
    McpToolMeta,
)
from ._schema import SchemaBuilder

if TYPE_CHECKING:
    from lauren_mcp._types import ResourceAnnotations

_SENTINEL = object()

# ---------------------------------------------------------------------------
# Tool name validation
# ---------------------------------------------------------------------------

_TOOL_NAME_RE = re.compile(r"^[A-Za-z0-9_\-.]+$")
_TOOL_NAME_MAX = 128


def _validate_tool_name(name: str, strict: bool = True) -> None:
    """Validate *name* against the MCP tool-name specification (SEP-986).

    Raises:
        ValueError: when *name* is empty, exceeds 128 characters, or contains
            characters outside ``[A-Za-z0-9_\\-.]``.  Suppressed when
            ``strict=False``.
    Warns:
        UserWarning: when *name* starts or ends with ``.`` or ``-``.
            Always issued regardless of *strict*.
    """
    if not strict:
        return

    if not name:
        raise ValueError(
            "Tool name must not be empty.  "
            "Use the 'name' parameter on @mcp_tool to provide an explicit name."
        )

    if len(name) > _TOOL_NAME_MAX:
        raise ValueError(
            f"Tool name {name!r} is {len(name)} characters long; "
            f"the maximum allowed length is {_TOOL_NAME_MAX}."
        )

    if not _TOOL_NAME_RE.match(name):
        bad = sorted({c for c in name if not re.match(r"[A-Za-z0-9_\-.]", c)})
        raise ValueError(
            f"Tool name {name!r} contains invalid characters: "
            f"{bad!r}.  Only [A-Za-z0-9_\\-.] are allowed."
        )

    if name[0] in (".", "-") or name[-1] in (".", "-"):
        warnings.warn(
            f"Tool name {name!r} starts or ends with {name[0]!r} or {name[-1]!r}.  "
            "Leading/trailing '.' and '-' are discouraged per SEP-986.",
            UserWarning,
            stacklevel=4,  # surfaces at the @mcp_tool call site
        )


def _is_context_annotation(annotation: Any) -> bool:
    """True when *annotation* is McpToolContext or Optional[McpToolContext]."""
    if annotation is McpToolContext:
        return True
    if isinstance(annotation, str):
        stripped = annotation.replace(" ", "")
        return stripped in (
            "McpToolContext",
            "McpToolContext|None",
            "None|McpToolContext",
            "Optional[McpToolContext]",
            "typing.Optional[McpToolContext]",
        )
    origin = typing.get_origin(annotation)
    if origin is typing.Union or str(type(annotation)) == "<class 'types.UnionType'>":
        args = typing.get_args(annotation)
        non_none = [a for a in args if a is not type(None)]
        return len(non_none) == 1 and non_none[0] is McpToolContext
    return False


def _build_schema(
    fn: Callable[..., Any],
) -> tuple[str, str, dict[str, Any], str | None, dict[str, str]]:
    """Build ``(name, description, json_schema, context_param, param_descs)``.

    * Uses ``inspect.signature`` and ``typing.get_type_hints`` (with fallback).
    * Skips ``self`` and any parameter annotated with ``McpToolContext``.
    * Parameters without a default are marked as required.
    * Per-parameter descriptions come from the docstring (Google / Sphinx /
      NumPy styles); an explicit ``Field(description=...)`` wins.
    """
    name = fn.__name__
    description, param_descriptions = parse_docstring(fn)

    try:
        hints = typing.get_type_hints(fn, include_extras=True)
    except Exception:
        hints = {}

    sig = inspect.signature(fn)
    builder = SchemaBuilder()
    properties: dict[str, Any] = {}
    required: list[str] = []
    context_param_name: str | None = None

    for param_name, param in sig.parameters.items():
        if param_name == "self":
            continue
        annotation = hints.get(param_name, param.annotation)
        if _is_context_annotation(annotation):
            context_param_name = param_name
            continue
        prop = builder.build(annotation)
        doc_desc = param_descriptions.get(param_name)
        if doc_desc and "description" not in prop:
            prop["description"] = doc_desc
        if param.default is not inspect.Parameter.empty and "default" not in prop:
            default = param.default
            if default is None or isinstance(default, (str, int, float, bool, list, dict)):
                prop["default"] = default
        properties[param_name] = prop
        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required
    if builder.defs:
        schema["$defs"] = builder.defs

    return name, description, schema, context_param_name, param_descriptions


def _resolve_output_schema(output_schema: Any) -> dict[str, Any] | None:
    """Resolve an ``output_schema`` argument to a plain JSON Schema dict.

    Accepts a raw JSON Schema dict, a Pydantic model class, a
    ``msgspec.Struct`` subclass, a dataclass, or a ``TypedDict`` class.
    """
    if output_schema is None:
        return None
    if isinstance(output_schema, dict):
        return output_schema
    if hasattr(output_schema, "model_json_schema"):  # pydantic v2
        return dict(output_schema.model_json_schema())

    # msgspec.Struct / dataclass / TypedDict — build via the shared schema
    # builder and inline the top-level definition into a standalone schema.
    builder = SchemaBuilder()
    fragment = builder.build(output_schema)
    ref = fragment.get("$ref", "")
    if ref.startswith("#/$defs/"):
        name = ref.removeprefix("#/$defs/")
        resolved = dict(builder.defs.pop(name, {}))
        if builder.defs:
            resolved["$defs"] = builder.defs
        if resolved:
            return resolved
    raise TypeError(
        "output_schema must be a JSON Schema dict, a Pydantic model, a "
        f"msgspec.Struct, a dataclass, or a TypedDict — got {output_schema!r}"
    )


def _auto_output_schema(
    annotation: Any,
    structured_output: bool | None,
) -> dict[str, Any] | None:
    """Derive an output schema from a return-type annotation.

    Returns a JSON Schema dict, or None when no schema should be emitted.

    Rules:
    - structured_output=False  → always None
    - structured_output=True   → wrap primitives in {"result": <scalar>};
                                  pass structured types through _resolve_output_schema
    - structured_output=None   → auto-detect structured types only; primitives → None
    """
    if structured_output is False:
        return None

    if annotation is None or annotation is inspect.Parameter.empty:
        return None

    # Resolve string annotations (from __future__ import annotations)
    if isinstance(annotation, str):
        return None  # cannot resolve at decoration time; skip

    # Force-wrap primitives when structured_output=True
    if structured_output is True:
        from lauren_mcp._server._context import _scalar_schema

        scalar = _scalar_schema(annotation)
        if scalar is not None:
            return {
                "type": "object",
                "properties": {"result": scalar},
                "required": ["result"],
            }

    # Structured types — auto or forced
    try:
        schema = _resolve_output_schema(annotation)
        return schema
    except TypeError:
        return None


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------


def mcp_server(path: str, *, transport: str = "ws") -> Callable[[type], type]:
    """Class decorator that marks a class as an MCP server.

    Applies ``@injectable(scope=Scope.SINGLETON)`` from Lauren so the class
    participates in DI, and attaches :class:`McpServerMeta` as an attribute.

    Args:
        path: The mount path for the MCP server endpoint (e.g. ``"/mcp"``).
        transport: One of ``"ws"``, ``"sse"``, ``"streamable"``, ``"both"``,
            or ``"all"``.
    """

    def decorator(cls: type) -> type:
        from lauren import Scope, injectable

        injectable(scope=Scope.SINGLETON)(cls)
        setattr(cls, MCP_SERVER_META, McpServerMeta(path=path, transport=transport))
        return cls

    return decorator


def mcp_tool(
    *,
    name: str | None = None,
    description: str | None = None,
    title: str | None = None,
    annotations: ToolAnnotations | None = None,
    timeout: float | None = None,
    tags: frozenset[str] | set[str] | None = None,
    meta: dict[str, Any] | None = None,
    output_schema: Any = None,
    structured_output: bool | None = None,
    strict: bool = True,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Method decorator that exposes a coroutine as an MCP tool.

    Args:
        name: Override the tool name (defaults to the method name).
        description: Override the tool description (defaults to docstring).
        title: Human-readable display name shown in client UIs (distinct from
            the machine-readable ``name``).
        annotations: Behavioural hints (:class:`ToolAnnotations`) transmitted
            to clients.
        timeout: Per-call execution deadline in seconds; exceeding it fails
            the call with an internal error.
        tags: Categorical tags included in the tool's ``tools/list`` entry.
        meta: Opaque metadata forwarded to clients under ``_meta``.
        output_schema: JSON Schema dict or Pydantic model class describing the
            tool's structured output; advertised as ``outputSchema``.
        structured_output: Control auto-detection of output schema.  ``None``
            (default) auto-detects structured types (Pydantic, dataclass,
            TypedDict, msgspec.Struct); ``True`` forces schema generation even
            for primitives; ``False`` disables auto-detection entirely.
        strict: When ``True`` (default), validates the tool name against the
            MCP specification (SEP-986).  Set ``False`` to allow legacy names.
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        auto_name, auto_desc, schema, context_param, param_descs = _build_schema(fn)
        resolved_name = name if name is not None else auto_name
        resolved_desc = description if description is not None else auto_desc

        _validate_tool_name(resolved_name, strict=strict)

        # Resolve explicit output_schema first; fall back to auto-detection
        if output_schema is not None:
            resolved_output_schema = _resolve_output_schema(output_schema)
        else:
            try:
                hints = typing.get_type_hints(fn)
            except Exception:
                hints = {}
            return_annotation = hints.get("return", inspect.Parameter.empty)
            resolved_output_schema = _auto_output_schema(return_annotation, structured_output)

        tool_meta = McpToolMeta(
            name=resolved_name,
            description=resolved_desc,
            input_schema=schema,
            method_name=fn.__name__,
            context_param_name=context_param,
            reads_context=context_param is not None,
            annotations=annotations,
            output_schema=resolved_output_schema,
            timeout=timeout,
            tags=frozenset(tags) if tags else frozenset(),
            meta=dict(meta) if meta else {},
            param_descriptions=param_descs,
            structured_output=structured_output,
            title=title,
        )
        setattr(fn, MCP_TOOL_META, tool_meta)
        return fn

    return decorator


def mcp_resource(
    uri_template: str,
    *,
    name: str | None = None,
    description: str | None = None,
    title: str | None = None,
    mime_type: str | None = None,
    annotations: ResourceAnnotations | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Method decorator that exposes a coroutine as an MCP resource.

    Args:
        uri_template: A URI template with ``{param}`` placeholders.  Also
            supports ``{+param}`` / ``{param*}`` multi-segment placeholders
            and a ``{?p1,p2}`` optional query-parameter suffix.
        name: Resource name (defaults to the method name).
        description: Human-readable description (defaults to docstring).
        title: Human-readable display name shown in client UIs.
        mime_type: Optional MIME type hint (e.g. ``"text/plain"``).
        annotations: Audience and priority hints (:class:`ResourceAnnotations`)
            transmitted to clients.
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        from ._uri import compile_uri_template

        resolved_name = name if name is not None else fn.__name__
        top_desc, _ = parse_docstring(fn)
        resolved_desc = description if description is not None else top_desc

        compiled = compile_uri_template(uri_template)
        try:
            hints = typing.get_type_hints(fn)
        except Exception:
            hints = {}
        hints.pop("return", None)

        resource_meta = McpResourceMeta(
            uri_template=uri_template,
            name=resolved_name,
            description=resolved_desc,
            mime_type=mime_type,
            method_name=fn.__name__,
            query_params=list(compiled.query_params),
            param_type_hints=hints,
            annotations=annotations,
            title=title,
        )
        setattr(fn, MCP_RESOURCE_META, resource_meta)
        return fn

    return decorator


def mcp_prompt(
    name: str | None = None,
    *,
    description: str | None = None,
    title: str | None = None,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Method decorator that exposes a coroutine as an MCP prompt.

    Args:
        name: Prompt name (defaults to the method name).
        description: Human-readable description (defaults to docstring).
        title: Human-readable display name shown in client UIs.
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        resolved_name = name if name is not None else fn.__name__
        top_desc, param_descs = parse_docstring(fn)
        resolved_desc = description if description is not None else top_desc

        sig = inspect.signature(fn)
        arguments: list[dict[str, Any]] = []
        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue
            arg_entry: dict[str, Any] = {
                "name": param_name,
                "description": param_descs.get(param_name),
                "required": param.default is inspect.Parameter.empty,
            }
            arguments.append(arg_entry)

        prompt_meta = McpPromptMeta(
            name=resolved_name,
            description=resolved_desc,
            arguments=arguments,
            method_name=fn.__name__,
            title=title,
        )
        setattr(fn, MCP_PROMPT_META, prompt_meta)
        return fn

    return decorator


def mcp_lifespan(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Method decorator marking an async generator as the server's lifespan hook.

    The generator runs once at server startup; the dict it yields becomes
    ``McpToolContext.lifespan_context`` for every tool call.  Code after the
    yield (typically in a ``finally`` block) runs at server shutdown::

        @mcp_server("/api")
        class MyServer:
            @mcp_lifespan
            async def lifespan(self):
                session = make_session()
                try:
                    yield {"session": session}
                finally:
                    await session.close()
    """
    if not inspect.isasyncgenfunction(fn):
        raise TypeError(
            "@mcp_lifespan requires an async generator method (async def with a single yield)"
        )
    setattr(fn, MCP_LIFESPAN_META, McpLifespanMeta(method_name=fn.__name__))
    return fn


def mcp_completion(
    target: str,
    argument: str,
    *,
    ref_type: str = "ref/prompt",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Method decorator that registers a completion function for a prompt or resource.

    Parameters
    ----------
    target:
        The name of the prompt (for ``ref_type="ref/prompt"``) or the URI
        template of the resource (for ``ref_type="ref/resource"``).
    argument:
        The argument name within that prompt or resource template for which
        this function provides completions.
    ref_type:
        Either ``"ref/prompt"`` (default) or ``"ref/resource"``.

    The decorated method must be an ``async def`` accepting a single positional
    argument ``partial: str`` (the text typed so far) and returning either a
    ``list[str]`` or a :class:`~lauren_mcp._types.CompletionResult`.

    Example::

        @mcp_server("/mcp")
        class MyServer:
            ALL_NAMES = ["Alice", "Bob", "Carol"]

            @mcp_prompt()
            async def greet(self, name: str) -> str:
                return f"Hello {name}!"

            @mcp_completion("greet", "name")
            async def complete_greet_name(self, partial: str) -> list[str]:
                return [n for n in self.ALL_NAMES if n.lower().startswith(partial.lower())]
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        meta = McpCompletionMeta(
            ref_type=ref_type,
            target_name=target,
            argument_name=argument,
            method_name=fn.__name__,
        )
        setattr(fn, MCP_COMPLETION_META, meta)
        return fn

    return decorator
