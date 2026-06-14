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
    HeaderParamSpec,
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
# Per-method Lauren decorator metadata reader
# ---------------------------------------------------------------------------


def _read_method_decorators(fn: Callable[..., Any]) -> dict[str, Any]:
    """Read ``@use_guards``, ``@use_interceptors``, ``@use_exception_handlers``, and
    ``@set_metadata`` attributes from *fn*, as stored by Lauren's decorators.

    Returns a dict with keys: ``guards``, ``interceptors``, ``exception_handlers``,
    ``tool_metadata`` — all empty when lauren is not installed.

    Also validates that ``@use_middlewares`` has not been applied to *fn*; raises
    ``TypeError`` if it has.

    Note: Lauren decorators are applied bottom-up (innermost first).  The canonical
    ordering is::

        @set_metadata("role", "admin")   # applied 3rd (outermost)
        @use_guards(AdminGuard)          # applied 2nd
        @mcp_tool()                      # applied 1st (innermost)
        async def delete_all(self) -> dict: ...

    When ``@mcp_tool()`` is the outermost decorator, Lauren attributes will not have
    been set yet and this function will return empty defaults.
    """
    try:
        from lauren.decorators import (  # noqa: PLC0415
            SET_METADATA,
            USE_EXCEPTION_HANDLERS,
            USE_GUARDS,
            USE_INTERCEPTORS,
            USE_MIDDLEWARES,
        )
    except ImportError:
        # lauren not installed — nothing to read, nothing to validate
        return {
            "guards": (),
            "interceptors": (),
            "exception_handlers": (),
            "tool_metadata": {},
        }

    # Validate: @use_middlewares is meaningless at MCP tool/resource/prompt level
    if getattr(fn, USE_MIDDLEWARES, None):
        raise TypeError(
            f"@use_middlewares cannot be applied to {fn.__name__!r} — MCP tool, "
            "resource, and prompt methods have no HTTP request/response lifecycle. "
            "Apply @use_middlewares to the @mcp_server class or a transport "
            "controller instead."
        )

    guards = tuple(getattr(fn, USE_GUARDS, []))
    interceptors = tuple(getattr(fn, USE_INTERCEPTORS, []))
    exception_handlers = tuple(getattr(fn, USE_EXCEPTION_HANDLERS, []))
    tool_metadata = dict(getattr(fn, SET_METADATA, {}) or {})

    return {
        "guards": guards,
        "interceptors": interceptors,
        "exception_handlers": exception_handlers,
        "tool_metadata": tool_metadata,
    }


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


# ---------------------------------------------------------------------------
# Lauren extractor hint helpers (for pipe/FieldDescriptor validation)
# ---------------------------------------------------------------------------

_FD_TO_JSON_SCHEMA: dict[str, str] = {
    "ge": "minimum",
    "gt": "exclusiveMinimum",
    "le": "maximum",
    "lt": "exclusiveMaximum",
    "min_length": "minLength",
    "max_length": "maxLength",
    "pattern": "pattern",
    "description": "description",
}


def _extract_lauren_hint(
    annotation: Any,
) -> tuple[Any, Any | None, tuple[Any, ...]]:
    """Strip Lauren extractor markers from *annotation*.

    Returns ``(base_type, field_descriptor_or_None, pipe_tuple)``.

    Works with:
    * ``Annotated[T, ExtractionMarker, FieldDescriptor, pipe1, ...]``
    * ``Annotated[T, FieldDescriptor, pipe1, ...]``  (no ExtractionMarker)
    * ``Path[T, FieldDescriptor, pipe1, ...]`` (expanded to Annotated by Lauren)
    * Plain ``T`` with no extras

    Returns the annotation unchanged when lauren is not installed.
    """
    if typing.get_origin(annotation) is not typing.Annotated:
        return annotation, None, ()

    try:
        from lauren.extractors import FieldDescriptor, is_pipe  # noqa: PLC0415
    except ImportError:
        # Lauren not installed — return as-is
        return annotation, None, ()

    try:
        from lauren.extractors import parse_extractor_hint  # noqa: PLC0415

        _source, inner, _reads_body, _marker_cls, fd, pipes = parse_extractor_hint(annotation)
        if _source is not None:
            # Extractor marker present — full result from parse_extractor_hint
            return inner, fd, pipes
    except Exception:
        pass

    # No ExtractionMarker (source is None) — manually scan the Annotated extras
    # for FieldDescriptor, _ParamSpec, and pipe callables.
    args = typing.get_args(annotation)
    if not args:
        return annotation, None, ()

    base = args[0]
    fd = None
    pipes_list: list[Any] = []

    try:
        from lauren.extractors import _ParamSpec as _LParamSpec  # noqa: PLC0415
    except ImportError:
        _LParamSpec = None  # type: ignore[assignment,no-redef]

    for extra in args[1:]:
        if isinstance(extra, FieldDescriptor):
            fd = extra
        elif _LParamSpec is not None and isinstance(extra, _LParamSpec):
            # _ParamSpec holds both a FieldDescriptor and pipe callables
            _ps: Any = extra
            if _ps.field_descriptor is not None and fd is None:
                fd = _ps.field_descriptor
            if _ps.pipes:
                pipes_list.extend(_ps.pipes)
        elif is_pipe(extra):
            pipes_list.append(extra)
        # ExtractionMarker instances/classes are silently ignored for MCP context

    return base, fd, tuple(pipes_list)


def _apply_field_descriptor(schema: dict[str, Any], fd: Any) -> None:
    """Apply FieldDescriptor constraint attributes to a JSON Schema fragment."""
    for attr, keyword in _FD_TO_JSON_SCHEMA.items():
        value = getattr(fd, attr, None)
        if value is not None:
            schema[keyword] = value
    alias = getattr(fd, "alias", None)
    if alias:
        schema["title"] = alias
    default = getattr(fd, "default", None)
    if default is not None and default is not ... and isinstance(default, (str, int, float, bool)):
        schema.setdefault("default", default)


# ---------------------------------------------------------------------------
# BackgroundTasks annotation helper
# ---------------------------------------------------------------------------


def _is_background_tasks_annotation(annotation: Any) -> bool:
    """True when *annotation* is BackgroundTasks or a string alias for it."""
    try:
        from lauren import BackgroundTasks as _BackgroundTasks  # noqa: PLC0415

        if annotation is _BackgroundTasks:
            return True
    except ImportError:
        pass
    if isinstance(annotation, str):
        stripped = annotation.replace(" ", "")
        return stripped in (
            "BackgroundTasks",
            "lauren.BackgroundTasks",
        )
    return False


# ---------------------------------------------------------------------------
# McpToolContext annotation helper
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Depends[callable] helpers
#
# Lauren's ExtractionMarker.__class_getitem__ returns Annotated[X, Depends]
# for Depends[X].  So the wire shape is:
#   typing.get_origin(annotation) is Annotated
#   typing.get_args(annotation)[1] is Depends
#   typing.get_args(annotation)[0] is the provider callable
# ---------------------------------------------------------------------------


def _is_depends_annotation(annotation: Any) -> bool:
    """True when *annotation* is ``Depends[X]`` for any *X*.

    ``Depends[X]`` expands to ``Annotated[X, Depends]`` via
    :meth:`ExtractionMarker.__class_getitem__`.
    """
    try:
        from lauren import Depends  # noqa: PLC0415
    except ImportError:
        return False
    # String annotation fallback (from __future__ import annotations)
    if isinstance(annotation, str):
        stripped = annotation.replace(" ", "")
        return stripped.startswith("Depends[")
    # Annotated[callable, Depends]
    if typing.get_origin(annotation) is typing.Annotated:
        args = typing.get_args(annotation)
        return len(args) >= 2 and args[1] is Depends
    return False


def _extract_depends_callable(annotation: Any) -> Any:
    """Return the provider callable *X* from ``Annotated[X, Depends]``, or ``None``."""
    try:
        from lauren import Depends  # noqa: PLC0415
    except ImportError:
        return None
    if typing.get_origin(annotation) is typing.Annotated:
        args = typing.get_args(annotation)
        if len(args) >= 2 and args[1] is Depends:
            return args[0]
    return None


# ---------------------------------------------------------------------------
# Header[T] helpers
#
# ``Header[T]`` expands to ``Annotated[T, Header]`` where the metadata marker
# is the ``Header`` class itself (not an instance).  Pipe arguments become
# additional metadata: ``Header[T, pipe1]`` → ``Annotated[T, Header, pipe1]``.
# ``Optional[Header[T]]`` = ``Union[Annotated[T, Header], None]``.
# ---------------------------------------------------------------------------


def _get_annotated_header_marker(annotation: Any) -> Any | None:
    """Return the ``Header`` class if *annotation* is ``Annotated[T, Header, ...]``,
    else ``None``."""
    try:
        from lauren import Header  # noqa: PLC0415
    except ImportError:
        return None
    if typing.get_origin(annotation) is typing.Annotated:
        args = typing.get_args(annotation)
        if len(args) >= 2 and args[1] is Header:
            return Header
    return None


def _is_header_annotation(annotation: Any) -> bool:
    """True when *annotation* is ``Header[T]`` or ``Optional[Header[T]]``."""
    try:
        from lauren import Header as _Header  # noqa: PLC0415,F401
    except ImportError:
        return False
    if _get_annotated_header_marker(annotation) is not None:
        return True
    # Optional[Header[T]] — unwrap Union[Annotated[T, Header], None]
    origin = typing.get_origin(annotation)
    if origin is typing.Union or str(type(annotation)) == "<class 'types.UnionType'>":
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        return len(args) == 1 and _get_annotated_header_marker(args[0]) is not None
    # String annotation fallback (from __future__ import annotations)
    if isinstance(annotation, str):
        stripped = annotation.replace(" ", "")
        return stripped.startswith("Header[") or "Optional[Header[" in stripped
    return False


def _extract_header_type(annotation: Any) -> type:
    """Return *T* from ``Annotated[T, Header]`` or ``Optional[Annotated[T, Header]]``."""
    # Unwrap Optional first
    origin = typing.get_origin(annotation)
    if origin is typing.Union or str(type(annotation)) == "<class 'types.UnionType'>":
        non_none = [a for a in typing.get_args(annotation) if a is not type(None)]
        if non_none:
            annotation = non_none[0]
    # Annotated[T, Header, ...] — T is args[0]
    if typing.get_origin(annotation) is typing.Annotated:
        args = typing.get_args(annotation)
        return args[0] if args else str
    return str


def _extract_header_pipe_chain(annotation: Any) -> list[Any]:
    """Return pipe objects from ``Annotated[T, Header, pipe1, pipe2, ...]``."""
    # Unwrap Optional first
    origin = typing.get_origin(annotation)
    if origin is typing.Union or str(type(annotation)) == "<class 'types.UnionType'>":
        non_none = [a for a in typing.get_args(annotation) if a is not type(None)]
        if non_none:
            annotation = non_none[0]
    if typing.get_origin(annotation) is typing.Annotated:
        args = typing.get_args(annotation)
        # args[0] = T, args[1] = Header, args[2:] = pipes
        return list(args[2:]) if len(args) > 2 else []
    return []


def _is_optional_header(annotation: Any) -> bool:
    """True when *annotation* is ``Optional[Header[T]]``."""
    try:
        from lauren import Header as _Header  # noqa: PLC0415,F401
    except ImportError:
        return False
    origin = typing.get_origin(annotation)
    if origin is typing.Union or str(type(annotation)) == "<class 'types.UnionType'>":
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        return len(args) == 1 and _get_annotated_header_marker(args[0]) is not None
    return False


def _param_to_header_name(param_name: str) -> str:
    """Convert a Python parameter name to an HTTP header name.

    Underscores become hyphens: ``x_user_id`` → ``"x-user-id"``.
    """
    return param_name.replace("_", "-")


# ---------------------------------------------------------------------------
# State[T] helpers
#
# ``State[T]`` expands to ``Annotated[T, State]`` via ExtractionMarker.
# ---------------------------------------------------------------------------


def _is_state_annotation(annotation: Any) -> bool:
    """True when *annotation* is ``State[T]`` (i.e. ``Annotated[T, State]``).

    Accepts the ``State`` class from either ``lauren.extractors`` or the
    ``StateExtractor`` alias exported from ``lauren``.
    """
    try:
        from lauren.extractors import State  # noqa: PLC0415
    except ImportError:
        return False
    if typing.get_origin(annotation) is typing.Annotated:
        args = typing.get_args(annotation)
        return len(args) >= 2 and args[1] is State
    if isinstance(annotation, str):
        stripped = annotation.replace(" ", "")
        return stripped.startswith("State[") or stripped.startswith("StateExtractor[")
    return False


def _extract_state_type(annotation: Any) -> type:
    """Return *T* from ``Annotated[T, State]``."""
    if typing.get_origin(annotation) is typing.Annotated:
        args = typing.get_args(annotation)
        return args[0] if args else dict
    return dict


def _build_schema(
    fn: Callable[..., Any],
) -> tuple[
    str,
    str,
    dict[str, Any],
    str | None,
    dict[str, str],
    dict[str, list[Any]],
    str | None,
    dict[str, Any],
    dict[str, HeaderParamSpec],
    dict[str, type],
]:
    """Build ``(name, description, json_schema, context_param, param_descs,
    pipe_chains, bg_tasks_param, depends_params, header_params, state_params)``.

    * Uses ``inspect.signature`` and ``typing.get_type_hints`` (with fallback).
    * Skips ``self`` and any parameter annotated with ``McpToolContext``,
      ``Depends[X]``, ``Header[T]``, ``State[T]``, or ``BackgroundTasks``.
    * Parameters without a default are marked as required.
    * Per-parameter descriptions come from the docstring (Google / Sphinx /
      NumPy styles); an explicit ``Field(description=...)`` wins.
    * Lauren FieldDescriptor constraints are mapped to JSON Schema keywords.
    * Pipe chains per parameter are accumulated in pipe_chains.
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
    pipe_chains: dict[str, list[Any]] = {}
    bg_tasks_param: str | None = None
    _seen_bg_params: list[str] = []
    depends_params: dict[str, Any] = {}
    header_params: dict[str, HeaderParamSpec] = {}
    state_params: dict[str, type] = {}

    for param_name, param in sig.parameters.items():
        if param_name == "self":
            continue
        annotation = hints.get(param_name, param.annotation)

        if _is_context_annotation(annotation):
            context_param_name = param_name
            continue

        if _is_background_tasks_annotation(annotation):
            # Multiple BackgroundTasks params → same instance (first one wins for injection)
            _seen_bg_params.append(param_name)
            if bg_tasks_param is None:
                bg_tasks_param = param_name
            continue

        if _is_depends_annotation(annotation):
            provider = _extract_depends_callable(annotation)
            if provider is not None:
                depends_params[param_name] = provider
            continue

        if _is_header_annotation(annotation):
            coerce_to = _extract_header_type(annotation)
            is_optional = _is_optional_header(annotation)
            default = param.default  # may be inspect.Parameter.empty
            pipe_chain = _extract_header_pipe_chain(annotation)
            header_params[param_name] = HeaderParamSpec(
                header_name=_param_to_header_name(param_name),
                coerce_to=coerce_to,
                default=default,
                is_optional=is_optional,
                pipe_chain=pipe_chain,
            )
            continue

        if _is_state_annotation(annotation):
            state_type = _extract_state_type(annotation)
            state_params[param_name] = state_type
            continue

        # Extract Lauren hint (pipe chains + FieldDescriptor)
        base_type, fd, pipes = _extract_lauren_hint(annotation)
        fd_validator: Any = None
        if fd is not None:
            _has_constraints = any(
                getattr(fd, attr, None) is not None
                for attr in ("ge", "gt", "le", "lt", "min_length", "max_length", "pattern")
            )
            if _has_constraints:
                # Create a closure that calls fd.validate(param_name, value)
                # This is prepended to the pipe chain so constraints run before custom pipes
                def _make_fd_validator(field_descriptor: Any, field_name: str) -> Any:
                    def _validate(v: Any) -> Any:
                        field_descriptor.validate(field_name, v)
                        return v

                    return _validate

                fd_validator = _make_fd_validator(fd, param_name)

        # Build the pipe chain: FD validator first, then custom pipes
        all_pipes: list[Any] = []
        if fd_validator is not None:
            all_pipes.append(fd_validator)
        if pipes:
            all_pipes.extend(pipes)
        if all_pipes:
            pipe_chains[param_name] = all_pipes

        # Also check the "default syntax": param.default may be a _ParamSpec or FieldDescriptor
        # produced by ``QueryField(...) | pipe(fn)``
        if param.default is not inspect.Parameter.empty:
            default_val = param.default
            try:
                from lauren.extractors import _ParamSpec  # noqa: PLC0415

                if isinstance(default_val, _ParamSpec):
                    if default_val.pipes:
                        existing = pipe_chains.get(param_name, [])
                        pipe_chains[param_name] = existing + list(default_val.pipes)
                    if fd is None and default_val.field_descriptor is not None:
                        fd = default_val.field_descriptor
            except ImportError:
                pass

        # Build from the full annotation so pydantic Field constraints (ge, le,
        # description, etc.) are preserved by SchemaBuilder._apply_metadata.
        # Lauren extractor markers have no schema attributes so they are safely
        # ignored by _apply_metadata's constraint loop.
        prop = builder.build(annotation if annotation is not base_type else base_type)

        # Apply FieldDescriptor constraints to the schema fragment
        if fd is not None:
            _apply_field_descriptor(prop, fd)

        doc_desc = param_descriptions.get(param_name)
        if doc_desc and "description" not in prop:
            prop["description"] = doc_desc
        if param.default is not inspect.Parameter.empty and "default" not in prop:
            default = param.default
            # Skip FieldDescriptor / _ParamSpec objects stored as defaults
            if default is None or isinstance(default, (str, int, float, bool, list, dict)):
                prop["default"] = default
        properties[param_name] = prop
        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    # If multiple BackgroundTasks params, store all names so handler can share the instance.
    if len(_seen_bg_params) > 1:
        bg_tasks_param = ",".join(_seen_bg_params)
    elif _seen_bg_params:
        bg_tasks_param = _seen_bg_params[0]

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
    }
    if required:
        schema["required"] = required
    if builder.defs:
        schema["$defs"] = builder.defs

    return (
        name,
        description,
        schema,
        context_param_name,
        param_descriptions,
        pipe_chains,
        bg_tasks_param,
        depends_params,
        header_params,
        state_params,
    )


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
        (
            auto_name,
            auto_desc,
            schema,
            context_param,
            param_descs,
            pipe_chains,
            bg_tasks_param,
            depends_params,
            header_params,
            state_params,
        ) = _build_schema(fn)
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

        # Backward-compat: also populate param_specs with raw FieldDescriptor /
        # _ParamSpec objects for code that still accesses meta.param_specs.
        _param_specs: dict[str, Any] = {}
        try:
            _hints_extra = typing.get_type_hints(fn, include_extras=True)
        except Exception:
            _hints_extra = {}
        _sig = inspect.signature(fn)
        for _pname, _param in _sig.parameters.items():
            if _pname == "self":
                continue
            _ann = _hints_extra.get(_pname, _param.annotation)
            _spec = _extract_lauren_annotation(_ann)
            if _spec is not None:
                _param_specs[_pname] = _spec

        # Read @use_guards / @use_interceptors / @use_exception_handlers / @set_metadata
        _method_deco = _read_method_decorators(fn)

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
            pipe_chains=pipe_chains,
            bg_tasks_param=bg_tasks_param,
            depends_params=depends_params,
            header_params=header_params,
            state_params=state_params,
            param_specs=_param_specs,
            guards=_method_deco["guards"],
            interceptors=_method_deco["interceptors"],
            exception_handlers=_method_deco["exception_handlers"],
            tool_metadata=_method_deco["tool_metadata"],
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
            hints = typing.get_type_hints(fn, include_extras=True)
        except Exception:
            hints = {}
        hints.pop("return", None)

        # Extract pipe chains, BackgroundTasks, Depends, Header, State from hints
        pipe_chains: dict[str, list[Any]] = {}
        bg_tasks_param: str | None = None
        depends_params: dict[str, Any] = {}
        header_params: dict[str, HeaderParamSpec] = {}
        state_params: dict[str, type] = {}
        clean_hints: dict[str, Any] = {}

        sig = inspect.signature(fn)
        for param_name, annotation in hints.items():
            if param_name == "self":
                continue
            if _is_context_annotation(annotation):
                continue
            if _is_background_tasks_annotation(annotation):
                if bg_tasks_param is None:
                    bg_tasks_param = param_name
                # Don't include in clean_hints — handler injects this
                continue
            if _is_depends_annotation(annotation):
                provider = _extract_depends_callable(annotation)
                if provider is not None:
                    depends_params[param_name] = provider
                continue
            if _is_header_annotation(annotation):
                coerce_to = _extract_header_type(annotation)
                is_optional = _is_optional_header(annotation)
                param = sig.parameters.get(param_name)
                default = param.default if param is not None else inspect.Parameter.empty
                pipe_chain = _extract_header_pipe_chain(annotation)
                header_params[param_name] = HeaderParamSpec(
                    header_name=_param_to_header_name(param_name),
                    coerce_to=coerce_to,
                    default=default,
                    is_optional=is_optional,
                    pipe_chain=pipe_chain,
                )
                continue
            if _is_state_annotation(annotation):
                state_type = _extract_state_type(annotation)
                state_params[param_name] = state_type
                continue
            base_type, fd, pipes = _extract_lauren_hint(annotation)
            if pipes:
                pipe_chains[param_name] = list(pipes)
            # Store the base type (stripped of Lauren markers) for coerce_params
            clean_hints[param_name] = base_type

        # Read @use_guards / @use_interceptors / @use_exception_handlers / @set_metadata
        _method_deco = _read_method_decorators(fn)

        resource_meta = McpResourceMeta(
            uri_template=uri_template,
            name=resolved_name,
            description=resolved_desc,
            mime_type=mime_type,
            method_name=fn.__name__,
            query_params=list(compiled.query_params),
            param_type_hints=clean_hints,
            annotations=annotations,
            title=title,
            pipe_chains=pipe_chains,
            bg_tasks_param=bg_tasks_param,
            depends_params=depends_params,
            header_params=header_params,
            state_params=state_params,
            guards=_method_deco["guards"],
            interceptors=_method_deco["interceptors"],
            exception_handlers=_method_deco["exception_handlers"],
            tool_metadata=_method_deco["tool_metadata"],
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

        # Read @use_guards / @use_interceptors / @use_exception_handlers / @set_metadata
        _method_deco = _read_method_decorators(fn)

        prompt_meta = McpPromptMeta(
            name=resolved_name,
            description=resolved_desc,
            arguments=arguments,
            method_name=fn.__name__,
            title=title,
            guards=_method_deco["guards"],
            interceptors=_method_deco["interceptors"],
            exception_handlers=_method_deco["exception_handlers"],
            tool_metadata=_method_deco["tool_metadata"],
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


# ---------------------------------------------------------------------------
# Backward-compat aliases (for tests written against the original main API)
# ---------------------------------------------------------------------------


def _extract_lauren_annotation(annotation: Any) -> Any | None:
    """Return the FieldDescriptor or _ParamSpec embedded in *annotation*.

    Backward-compat alias for older test code.  The merged implementation uses
    ``_extract_lauren_hint`` which returns ``(base_type, fd, pipes)`` instead.
    """
    if not _is_context_annotation(annotation) and typing.get_origin(annotation) is typing.Annotated:
        try:
            from lauren.extractors import FieldDescriptor, _ParamSpec  # noqa: PLC0415

            args = typing.get_args(annotation)
            # Check if any arg is a _ParamSpec (pipe chain) or FieldDescriptor
            for extra in args[1:]:
                if isinstance(extra, _ParamSpec):
                    return extra
                if isinstance(extra, FieldDescriptor):
                    return extra
        except ImportError:
            pass
    return None


#: Backward-compat alias.
_is_bg_tasks_annotation = _is_background_tasks_annotation
