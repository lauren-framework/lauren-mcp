"""Handler factories that generate async callables for the MCP dispatcher."""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import inspect
import json
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from lauren_mcp._server._binding import CURRENT_BINDING
from lauren_mcp._server._context import LogLevelState, McpToolContext
from lauren_mcp._types import (
    BlobResource,
    EmbeddedResource,
    ImageContent,
    JsonRpcRequest,
    ResourceContent,
    ResourceResult,
    TextContent,
    ToolOutput,
    ToolStream,
)

from ._meta import (
    _HEADER_NO_DEFAULT,
    McpCompletionMeta,
    McpPromptMeta,
    McpResourceMeta,
    McpToolMeta,
)
from ._uri import coerce_params, compile_uri_template, match_uri

_logger = logging.getLogger(__name__)

_Handler = Callable[[JsonRpcRequest], Coroutine[Any, Any, dict[str, Any]]]


# ---------------------------------------------------------------------------
# Pipe validation helpers
# ---------------------------------------------------------------------------


async def _run_pipe_chain(name: str, value: Any, pipes: list[Any]) -> Any:
    """Run a pipe chain on *value*, passing PipeContext(name=name) when requested.

    Imports PipeContext from lauren.extractors lazily -- returns *value*
    unchanged when lauren is not installed.
    """
    try:
        from lauren.extractors import PipeContext  # noqa: PLC0415
    except ImportError:
        return value

    for p in pipes:
        # Class-based pipe: has a transform method
        if isinstance(p, type) and hasattr(p, "transform"):
            instance = p()
            sig = inspect.signature(instance.transform)
            params = [k for k in sig.parameters if k not in ("self",)]
            wants_ctx = len(params) >= 2
            ctx = PipeContext(
                request=None,  # type: ignore[arg-type]
                name=name,
                source="mcp",
                inner_type=type(value),
                container=None,
                request_cache=None,
                owning_module=None,
                field_descriptor=None,
            )
            if asyncio.iscoroutinefunction(instance.transform):
                value = (
                    await instance.transform(value, ctx)
                    if wants_ctx
                    else await instance.transform(value)
                )
            else:
                value = instance.transform(value, ctx) if wants_ctx else instance.transform(value)
            continue

        # Function-based pipe (callable, not a class)
        sig = inspect.signature(p)
        params_list = list(sig.parameters.values())
        wants_ctx = len(params_list) >= 2

        ctx = PipeContext(
            request=None,  # type: ignore[arg-type]
            name=name,
            source="mcp",
            inner_type=type(value),
            container=None,
            request_cache=None,
            owning_module=None,
            field_descriptor=None,
        )

        if asyncio.iscoroutinefunction(p):
            result = await p(value, ctx) if wants_ctx else await p(value)
        else:
            result = p(value, ctx) if wants_ctx else p(value)

        if asyncio.iscoroutine(result):
            value = await result
        else:
            value = result

    return value


# ---------------------------------------------------------------------------
# BackgroundTasks helpers
# ---------------------------------------------------------------------------


async def _run_background_tasks(bg: Any) -> None:
    """Execute all tasks queued in a BackgroundTasks instance.

    Mirrors BackgroundTasks._run() without requiring signals/logger
    arguments tied to the Lauren app object.  Errors are logged but never
    propagate -- all tasks run regardless of individual failures.
    """
    for func, args, kwargs, handle in getattr(bg, "_queue", []):
        handle.status = "running"
        try:
            if asyncio.iscoroutinefunction(func):
                await func(*args, **kwargs)
            else:
                import anyio.to_thread  # noqa: PLC0415

                _func, _a, _kw = func, args, kwargs
                await anyio.to_thread.run_sync(lambda: _func(*_a, **_kw))  # noqa: B023
            handle.status = "done"
        except Exception:  # noqa: BLE001
            handle.status = "failed"
            _logger.exception("MCP tool background task %r failed", func)


# ---------------------------------------------------------------------------
# Depends[callable] resolution
# ---------------------------------------------------------------------------


async def _resolve_depends(
    provider: Any,
    resolved: dict[int, Any],
    cleanup: list[Any],
) -> Any:
    """Resolve one Depends[provider] callable.

    Memoizes by id(provider) within a single tool call.
    Supports sync functions, async functions, async generators (yield-based
    context managers), and objects that implement __aenter__ / __aexit__.
    """
    key = id(provider)
    if key in resolved:
        return resolved[key]

    # Async generator function (yield-based pattern) -- check BEFORE __aenter__
    # because async generator instances also have __aenter__ in Python >= 3.10.
    if inspect.isasyncgenfunction(provider):
        gen = provider()
        try:
            obj = await gen.__anext__()
        except StopAsyncIteration:
            obj = None
        cleanup.append(gen.aclose)
        resolved[key] = obj
        return obj

    # Async context manager object (already instantiated with __aenter__)
    if hasattr(provider, "__aenter__") and not inspect.isclass(provider):
        obj = await provider.__aenter__()
        aexit = provider.__aexit__
        cleanup.append(lambda: aexit(None, None, None))
        resolved[key] = obj
        return obj

    # Async callable
    if asyncio.iscoroutinefunction(provider):
        result = await provider()
        resolved[key] = result
        return result

    # Sync callable
    result = provider()
    resolved[key] = result
    return result


# ---------------------------------------------------------------------------
# Header[T] coercion
# ---------------------------------------------------------------------------


def _coerce_header_value(raw: str, T: type) -> Any:
    """Coerce a raw header string to type T."""
    if T is str:
        return raw
    if T is int:
        return int(raw)
    if T is float:
        return float(raw)
    if T is bool:
        return raw.lower() not in ("0", "false", "no", "")
    return T(raw)


def _state_key(T: type) -> str:
    """Return the ctx.state key for type T (uses __qualname__)."""
    return T.__qualname__


# ---------------------------------------------------------------------------
# Per-tool guard execution
# ---------------------------------------------------------------------------


async def _run_tool_guards(
    guards: tuple[type, ...],
    exec_ctx: Any,  # McpExecutionContext
    container: Any,  # Lauren DI container, or None
    owning_module: Any,  # module type, or None
) -> None:
    """Resolve and call each guard in order.

    Raises :exc:`McpForbiddenError` on the first rejection.
    Guard exceptions are caught, logged at ERROR level, and treated as
    rejections — consistent with ``lauren.reflect.apply_guards`` semantics.

    When *container* is ``None`` (e.g. in unit tests without full DI),
    guards are silently skipped so the tool method is always called.
    """
    if not guards or container is None:
        return

    from lauren_mcp._server._dispatcher import McpForbiddenError  # noqa: PLC0415

    for guard_cls in guards:
        try:
            guard = await container.resolve(
                guard_cls,
                request_cache={},
                framework_values={},
                owning_module=owning_module,
            )
            allowed: bool = await guard.can_activate(exec_ctx)
        except Exception:  # noqa: BLE001
            _logger.exception(
                "Guard %r raised during tool call check for %r — treating as rejection",
                guard_cls.__name__,
                exec_ctx.tool_name,
            )
            allowed = False

        if not allowed:
            _logger.debug(
                "Tool call %r rejected by guard %r",
                exec_ctx.tool_name,
                guard_cls.__name__,
            )
            raise McpForbiddenError(
                f"Guard {guard_cls.__name__!r} denied the tool call for {exec_ctx.tool_name!r}",
                guard_name=guard_cls.__name__,
            )


# ---------------------------------------------------------------------------
# McpCallHandler — interceptor chain handle
# ---------------------------------------------------------------------------


class McpCallHandler:
    """Represents the next step in the MCP tool interceptor chain.

    Passed to every ``@interceptor``-decorated class as the second argument
    to ``intercept(ctx, call_handler)``.  Call :meth:`handle` to advance
    to the next interceptor or, for the innermost interceptor, to execute
    the tool method and return the coerced result dict.

    The return type is ``dict[str, Any]`` — the tools/call result shape
    ``{"content": [...], "isError": bool, "structuredContent": {...}}``.
    For resources, ``handle()`` returns ``{"contents": [...]}``.
    For prompts, ``handle()`` returns ``{"description": "...", "messages": [...]}``.

    Unlike ``lauren.types.CallHandler`` (which returns a ``Response``),
    ``McpCallHandler`` returns a plain dict.  Interceptors written for
    MCP tools must not attempt to call ``.status_code`` or ``.headers``
    on the return value.
    """

    def __init__(self, next_fn: Callable[[], Any]) -> None:
        self._next = next_fn

    async def handle(self) -> dict[str, Any]:
        """Invoke the next stage in the pipeline and return the result dict."""
        result = self._next()
        if asyncio.iscoroutine(result):
            return await result  # type: ignore[no-any-return]
        return result  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# DI resolution helper
# ---------------------------------------------------------------------------


async def _resolve_di(
    container: Any,
    cls: type,
    owning_module: type | None,
) -> Any:
    """Resolve *cls* from the Lauren DI container.

    Falls back to direct instantiation when no container is available
    (e.g. in unit tests that call the handler directly).
    """
    if container is None:
        return cls()
    try:
        return await container.resolve(cls, module=owning_module)
    except Exception:  # noqa: BLE001
        # Fallback: try sync resolution then bare construction.
        try:
            return container.resolve_sync(cls, module=owning_module)
        except Exception:  # noqa: BLE001
            return cls()


# ---------------------------------------------------------------------------
# Interceptor chain executor
# ---------------------------------------------------------------------------


async def _execute_with_interceptors(
    meta: McpToolMeta,
    method: Any,
    kwargs: dict[str, Any],
    exec_ctx: Any,  # McpExecutionContext or None
    container: Any,
    owning_module: type | None,
    tool_ctx: McpToolContext | None = None,
) -> dict[str, Any]:
    """Invoke *method* wrapped by the interceptor chain declared in *meta*.

    When ``meta.interceptors`` is empty this is equivalent to calling the
    method directly and coercing the result — no overhead beyond the function
    call.

    The chain is built inside-out: the last interceptor in ``meta.interceptors``
    is innermost (closest to the method); the first is outermost.

    Parameters
    ----------
    tool_ctx:
        The ``McpToolContext`` for this call.  Used by ``base()`` when draining
        a ``ToolStream`` to emit progress notifications, even when the tool does
        not declare a ``McpToolContext`` parameter.
    """

    async def base() -> dict[str, Any]:
        result = await method(**kwargs)
        if isinstance(result, ToolStream):
            ctx_obj: McpToolContext | None = (
                kwargs.get(meta.context_param_name) if meta.context_param_name else None
            ) or tool_ctx
            return await _drain_tool_stream(result, meta, ctx_obj)
        return _coerce_tool_result(result, meta)

    interceptors = getattr(meta, "interceptors", ())
    if not interceptors:
        return await base()

    # Build chain: reversed so the last declared interceptor is innermost.
    current_fn: Callable[[], Any] = base
    for interceptor_cls in reversed(interceptors):
        instance = await _resolve_di(container, interceptor_cls, owning_module)
        # Capture loop variables via default args to avoid the Python
        # late-binding closure bug.
        _ic = instance
        _inner: Callable[[], Any] = current_fn

        async def _make_next(
            ic: Any = _ic,
            inner: Callable[[], Any] = _inner,
        ) -> dict[str, Any]:
            return await ic.intercept(exec_ctx, McpCallHandler(inner))  # type: ignore[no-any-return]

        current_fn = _make_next

    return await current_fn()  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Per-tool exception handler pipeline
# ---------------------------------------------------------------------------


async def _run_tool_exception_handlers(
    exc: Exception,
    handlers: tuple[Any, ...],
    exec_ctx: Any,
    container: Any | None = None,
    owning_module: type | None = None,
) -> dict[str, Any] | None:
    """Walk the per-tool exception handler chain for *exc*.

    Returns the result dict from the first matching handler, or ``None`` if no
    handler matched or every matching handler returned ``None``.  Re-raises if a
    handler re-raises or throws a new exception.

    Parameters
    ----------
    exc:
        The exception that escaped the tool method.
    handlers:
        Tuple of handler classes decorated with ``@exception_handler``.
        Order matters: first match wins.
    exec_ctx:
        The context object passed to ``handler_instance.catch(exc, exec_ctx)``.
    container:
        Optional Lauren DI container.  When provided, handlers are resolved via
        DI (supporting ``__init__`` dependencies).  Falls back to no-arg
        instantiation when ``None``.
    owning_module:
        Optional module type forwarded to ``container.resolve``.
    """
    if not handlers:
        return None

    try:
        from lauren.decorators import EXCEPTION_HANDLER_META  # noqa: PLC0415
    except ImportError:
        return None

    for handler_cls in handlers:
        meta_obj = getattr(handler_cls, EXCEPTION_HANDLER_META, None)
        if meta_obj is None:
            continue
        handled_types: tuple[type, ...] = getattr(meta_obj, "exceptions", (Exception,))
        if not isinstance(exc, handled_types):
            continue

        # Match — instantiate (via DI if available, else direct)
        if container is not None:
            instance = await container.resolve(
                handler_cls,
                owning_module=owning_module,
            )
        else:
            if not isinstance(handler_cls, type):
                # Function-form handler — call directly
                result = handler_cls(exc, exec_ctx)
                if inspect.isawaitable(result):
                    result = await result
                if result is not None:
                    if isinstance(result, dict) and "content" not in result:
                        continue
                    return result  # type: ignore[no-any-return]
                continue

            try:
                instance = handler_cls()
            except TypeError:
                _logger.warning(
                    "Per-tool exception handler %r requires DI constructor arguments "
                    "but no container is available; skipping. "
                    "Pass a DI container to make_tools_call_handler to enable DI resolution.",
                    handler_cls.__name__,
                )
                continue

        result = instance.catch(exc, exec_ctx)
        if inspect.isawaitable(result):
            result = await result
        if result is not None:
            if isinstance(result, dict) and "content" not in result:
                # Malformed return (missing required key) — treat as unhandled
                continue
            # Coerce ToolOutput if returned
            if hasattr(result, "content") and not isinstance(result, dict):
                try:
                    from lauren_mcp._types import ToolOutput as _ToolOutput  # noqa: PLC0415

                    if isinstance(result, _ToolOutput):
                        content = [
                            c if isinstance(c, dict) else {"type": "text", "text": str(c)}
                            for c in (result.content or [])
                        ]
                        out: dict[str, Any] = {
                            "content": content,
                            "isError": bool(result.is_error),
                        }
                        if result.structured_content is not None:
                            out["structuredContent"] = result.structured_content
                        return out
                except ImportError:
                    pass
            return result  # type: ignore[no-any-return]
        # Handler returned None → try next handler
    return None


#: Builds an McpToolContext for one tool call.
# The factory accepts 3 positional args plus an optional tool_metadata keyword arg.
# We type it as Any to avoid mypy issues with the extended keyword signature.
ContextFactory = Any


def make_context_factory(
    metadata: dict[str, Any] | None = None,
    *,
    lifespan_getter: Callable[[], dict[str, Any]] | None = None,
    log_level_state: LogLevelState | None = None,
) -> ContextFactory:
    """Build a ContextFactory that merges server-level state with the
    per-call transport binding (CURRENT_BINDING).

    The returned factory accepts ``(tool_name, tool_use_id, progress_token)`` as
    positional args plus an optional ``tool_metadata`` keyword arg containing
    per-tool ``@set_metadata`` entries.  When ``tool_metadata`` is supplied, it is
    merged with the server-class metadata: tool-level keys win for the same key.
    """
    _server_meta = dict(metadata or {})

    def factory(
        tool_name: str,
        tool_use_id: str | int | None,
        progress_token: str | int | None,
        *,
        tool_metadata: dict[str, Any] | None = None,
    ) -> McpToolContext:
        merged_meta = {**_server_meta, **(tool_metadata or {})}
        binding = CURRENT_BINDING.get()
        return McpToolContext(
            tool_name=tool_name,
            tool_use_id=tool_use_id,
            headers=binding.headers if binding else None,
            execution_context=binding.execution_context if binding else None,
            session_id=binding.session_id if binding else None,
            metadata=merged_meta,
            state={},
            extras=dict(binding.extras) if binding else {},
            lifespan_context=lifespan_getter() if lifespan_getter else {},
            _progress_token=progress_token,
            _send_notification=binding.send_notification if binding else None,
            _client_rpc=binding.client_rpc if binding else None,
            _client_capabilities=binding.client_capabilities if binding else None,
            _log_level_state=log_level_state,
        )

    return factory


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


def _tool_list_entry(t: McpToolMeta) -> dict[str, Any]:
    entry: dict[str, Any] = {"name": t.name}
    if t.title is not None:
        entry["title"] = t.title
    entry["description"] = t.description
    entry["inputSchema"] = t.input_schema
    if t.annotations is not None:
        entry["annotations"] = t.annotations.to_dict()
    if t.output_schema is not None:
        entry["outputSchema"] = t.output_schema
    if t.tags:
        entry["tags"] = sorted(t.tags)
    if t.meta:
        entry["_meta"] = t.meta
    return entry


def make_tools_list_handler(
    tools: list[McpToolMeta] | Callable[[], list[McpToolMeta]],
) -> _Handler:
    """Return an async handler for tools/list.

    *tools* may be a static list or a zero-arg callable returning the current
    catalogue (used by the dynamic catalog manager).
    """
    get_tools = tools if callable(tools) else (lambda: tools)

    async def handler(req: JsonRpcRequest) -> dict[str, Any]:
        return {"tools": [_tool_list_entry(t) for t in get_tools()]}

    return handler


def _coerce_content_block(item: Any) -> dict[str, Any]:
    """Normalise one content item to its wire dict."""
    if isinstance(item, dict):
        return item
    if isinstance(item, TextContent):
        return {"type": "text", "text": item.text}
    if isinstance(item, ImageContent):
        return {"type": "image", "data": item.data, "mimeType": item.mimeType}
    if isinstance(item, EmbeddedResource):
        return {"type": "resource", "resource": item.resource}
    return {"type": "text", "text": str(item)}


def _is_msgspec_struct(obj: Any) -> bool:
    if not hasattr(type(obj), "__struct_fields__"):
        return False
    try:
        import msgspec
    except ImportError:
        return False
    return isinstance(obj, msgspec.Struct)


def _model_dump(obj: Any) -> dict[str, Any]:
    if hasattr(obj, "model_dump"):  # pydantic v2
        return dict(obj.model_dump(mode="json"))
    if hasattr(obj, "dict"):  # pydantic v1
        return dict(obj.dict())
    raise TypeError(f"Cannot serialise {type(obj).__name__} to structured content")


def _coerce_tool_result(result: Any, meta: McpToolMeta) -> dict[str, Any]:
    """Coerce a tool's raw return value into the tools/call result shape."""
    structured: dict[str, Any] | None = None
    is_error = False

    if isinstance(result, ToolOutput):
        content = [_coerce_content_block(c) for c in (result.content or [])]
        structured = result.structured_content
        is_error = result.is_error
        if not content and structured is not None:
            content = [{"type": "text", "text": json.dumps(structured)}]
    elif isinstance(result, (TextContent, ImageContent, EmbeddedResource)):
        content = [_coerce_content_block(result)]
    elif isinstance(result, str):
        content = [{"type": "text", "text": result}]
    elif isinstance(result, dict):
        content = [{"type": "text", "text": json.dumps(result)}]
        structured = result
    elif isinstance(result, list):
        content = [{"type": "text", "text": json.dumps(result)}]
        structured = {"result": result}
    elif dataclasses.is_dataclass(result) and not isinstance(result, type):
        structured = dataclasses.asdict(result)
        content = [{"type": "text", "text": json.dumps(structured)}]
    elif _is_msgspec_struct(result):
        import msgspec

        structured = msgspec.to_builtins(result)
        content = [{"type": "text", "text": json.dumps(structured)}]
    elif hasattr(result, "model_dump") or hasattr(result, "dict"):
        structured = _model_dump(result)
        content = [{"type": "text", "text": json.dumps(structured)}]
    else:
        content = [{"type": "text", "text": str(result)}]

    # When structured_output=True wraps a primitive, produce the {"result": ...} dict
    if structured is None and meta.structured_output is True:
        raw_text = content[0]["text"] if content else str(result)
        try:
            structured = {"result": json.loads(raw_text)}
        except (json.JSONDecodeError, TypeError):
            structured = {"result": raw_text}

    out: dict[str, Any] = {"content": content, "isError": is_error}
    if structured is not None:
        out["structuredContent"] = structured
    return out


def _validate_output(structured: dict[str, Any] | None, meta: McpToolMeta) -> None:
    """Validate structured content against the declared output schema.

    Only the cheap top-level checks are done in-process (type/object,
    required keys) -- full JSON Schema validation would need an extra
    dependency.
    """
    schema = meta.output_schema
    if schema is None or structured is None:
        return
    for key in schema.get("required", []):
        if key not in structured:
            raise ValueError(
                f"Tool {meta.name!r} structured output is missing required "
                f"key {key!r} declared in its outputSchema"
            )


def _serialize_chunk(chunk: Any) -> str:
    """Serialise a ToolStream chunk to a JSON string for the progress message field."""
    try:
        return json.dumps(chunk, default=str)
    except Exception:
        return str(chunk)


async def _drain_tool_stream(
    stream: ToolStream[Any],
    meta: McpToolMeta,
    ctx: McpToolContext | None,
) -> dict[str, Any]:
    """Drain a ToolStream generator, sending progress notifications per chunk."""
    chunks: list[Any] = []
    i = 0
    async for chunk in stream.generator:
        chunks.append(chunk)
        if ctx is not None:
            try:  # noqa: SIM105
                await ctx.report_progress(
                    i,
                    total=stream.total,
                    message=_serialize_chunk(chunk),
                )
            except Exception:  # noqa: BLE001
                pass  # notification failure must not abort the tool
        i += 1

    # Accumulate
    if stream.accumulate is not None:
        final: Any = stream.accumulate(chunks)
    elif chunks and all(isinstance(c, str) for c in chunks):
        final = "".join(chunks)
    elif chunks:
        final = chunks[-1]
    else:
        final = None

    return _coerce_tool_result(final, meta)


def make_tools_call_handler(
    server_instance: Any,
    tools: list[McpToolMeta] | Callable[[], list[McpToolMeta]],
    *,
    context_factory: ContextFactory | None = None,
    dispatcher: Any | None = None,
    container: Any | None = None,
    owning_module: type | None = None,
    server_metadata: dict[str, Any] | None = None,
) -> _Handler:
    """Return an async handler for tools/call.

    Dispatches to server_instance.<method_name>(**arguments).  When a tool
    declares a McpToolContext parameter and context_factory is supplied,
    the context is injected under the declared parameter name.

    Parameters
    ----------
    dispatcher:
        Optional McpDispatcher reference.  When provided, the built context
        is registered via dispatcher.register_context(req.id, ctx) so that
        $/cancelRequest can set the cooperative cancel_requested event on the
        context before hard-cancelling the task.
    container:
        Optional Lauren DI container.  When provided and a tool declares
        ``meta.guards`` or ``meta.interceptors``, they are resolved and
        executed.  When ``None``, guards and interceptors are silently skipped.
    owning_module:
        The Lauren module class that owns this server; used for DI provider
        visibility when resolving guards and interceptors.
    server_metadata:
        Class-level ``@set_metadata`` dict from the ``@mcp_server`` class;
        merged with the per-tool metadata before being passed to guards and
        interceptors.
    """
    get_tools = tools if callable(tools) else (lambda: tools)

    async def handler(req: JsonRpcRequest) -> dict[str, Any]:
        from lauren_mcp._server._dispatcher import McpInvalidParamsError  # noqa: PLC0415

        params: dict[str, Any] = req.params if isinstance(req.params, dict) else {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        tool_map = {t.name: t for t in get_tools()}
        if name not in tool_map:
            raise ValueError(f"Unknown tool: {name!r}")
        meta = tool_map[name]
        target = getattr(meta, "_bound_instance", None) or server_instance
        method = getattr(target, meta.method_name)

        # 1. Start with plain JSON-RPC arguments.
        kwargs = dict(arguments)

        # 2. Pipe-transform plain arguments (FieldDescriptor + custom pipes).
        if meta.pipe_chains:
            try:
                from lauren.exceptions import ExtractorFieldError  # noqa: PLC0415

                _extractor_field_error: type | None = ExtractorFieldError
            except ImportError:
                _extractor_field_error = None

            for param_name, pipes in meta.pipe_chains.items():
                if not pipes or param_name not in kwargs:
                    continue
                try:
                    new_val = await _run_pipe_chain(param_name, kwargs[param_name], pipes)
                    kwargs[param_name] = new_val
                except Exception as exc:  # noqa: BLE001
                    if (
                        _extractor_field_error is not None
                        and isinstance(exc, _extractor_field_error)
                        or isinstance(exc, (ValueError, TypeError))
                    ):
                        raise McpInvalidParamsError(param_name, str(exc)) from exc
                    raise

        # 3. Inject McpToolContext (optional).
        # Also build ctx for ToolStream progress notifications even when the
        # tool does not declare a McpToolContext parameter.
        request_meta = params.get("_meta") or {}
        progress_token = (
            request_meta.get("progressToken") if isinstance(request_meta, dict) else None
        )
        ctx: McpToolContext | None = None
        if context_factory is not None:
            ctx = context_factory(
                meta.name,
                req.id,
                progress_token,
                tool_metadata=meta.tool_metadata if meta.tool_metadata else None,
            )
        if meta.reads_context and meta.context_param_name and ctx is not None:
            kwargs[meta.context_param_name] = ctx
            # Register the context so cancel() can signal it cooperatively.
            if dispatcher is not None and req.id is not None:
                dispatcher.register_context(req.id, ctx)

        # 4. Inject Header[T] params.
        if meta.header_params:
            binding = CURRENT_BINDING.get()
            headers = binding.headers if binding is not None else None
            for param_name, spec in meta.header_params.items():
                raw: str | None = headers.get(spec.header_name) if headers is not None else None
                if raw is None:
                    if spec.is_optional:
                        kwargs[param_name] = None
                    elif spec.default is not _HEADER_NO_DEFAULT:
                        kwargs[param_name] = spec.default
                    else:
                        # No default, no value -- coerce empty string to T
                        try:
                            kwargs[param_name] = _coerce_header_value("", spec.coerce_to)
                        except (ValueError, TypeError):
                            kwargs[param_name] = None
                else:
                    try:
                        value: Any = _coerce_header_value(raw, spec.coerce_to)
                    except (ValueError, TypeError):
                        value = spec.default if spec.default is not _HEADER_NO_DEFAULT else None
                    kwargs[param_name] = value

        # 5. Inject State[T] params.
        if meta.state_params:
            # Obtain or create a transient state dict
            ctx_obj: McpToolContext | None = (
                kwargs.get(meta.context_param_name)
                if meta.context_param_name and meta.reads_context
                else None
            )
            state_dict: dict[str, Any] = ctx_obj.state if ctx_obj is not None else {}

            for param_name, T in meta.state_params.items():
                key = _state_key(T)
                if key not in state_dict:
                    try:
                        state_dict[key] = T()
                    except TypeError as exc:
                        raise TypeError(
                            f"State[{T.__qualname__}] requires {T.__qualname__}() to be "
                            f"callable with no arguments, but it raised: {exc}"
                        ) from exc
                kwargs[param_name] = state_dict[key]

        # 6. Resolve and inject Depends[X] params / 7. Inject BackgroundTasks.
        resolved: dict[int, Any] = {}  # id(provider) -> resolved value
        cleanup: list[Any] = []  # callables to run in finally

        bg: Any = None
        if meta.bg_tasks_param:
            try:
                from lauren import BackgroundTasks  # noqa: PLC0415

                bg = BackgroundTasks()
                # Support multiple BG params (comma-separated) -- same instance
                for bg_param in meta.bg_tasks_param.split(","):
                    bg_param = bg_param.strip()
                    if bg_param:
                        kwargs[bg_param] = bg
            except ImportError:
                pass

        # Build McpExecutionContext when guards or interceptors or exception
        # handlers are present.
        _guards = getattr(meta, "guards", ())
        _interceptors = getattr(meta, "interceptors", ())
        _exc_handlers = getattr(meta, "exception_handlers", ())
        exec_ctx: Any = None
        if _guards or _interceptors or _exc_handlers:
            from lauren_mcp._server._exec_context import McpExecutionContext  # noqa: PLC0415

            binding = CURRENT_BINDING.get()
            _tool_metadata: dict[str, Any] = {
                **(server_metadata or {}),
                **getattr(meta, "tool_metadata", {}),
            }
            # Merge metadata in priority order:
            # 1. server @set_metadata (from _McpHandlerRegistrar._server_metadata)
            # 2. ExecutionContext.metadata — same values but from the REAL Lauren
            #    instance (correctly populated by Lauren's ASGI dispatcher from
            #    the transport controller's @set_metadata); only differs from
            #    server_metadata when EC carries extra route-level metadata.
            # 3. per-tool @set_metadata (highest priority)
            _ec = binding.execution_context if binding else None
            _ec_meta: dict[str, Any] = {}
            if _ec is not None:
                try:  # noqa: SIM105
                    _ec_meta = dict(_ec.metadata)
                except Exception:  # noqa: BLE001
                    pass
            # Also merge WS connection-level metadata from extras (set by _ws.py
            # from WsConnectionContext.metadata when @set_metadata is on the server).
            _extras_meta: dict[str, Any] = dict(binding.extras) if binding else {}

            _merged_metadata: dict[str, Any] = {
                **_extras_meta,  # WS @set_metadata via extras
                **(server_metadata or {}),  # server-level @set_metadata
                **_ec_meta,  # real EC.metadata (HTTP transports)
                **getattr(meta, "tool_metadata", {}),  # per-tool @set_metadata wins
            }

            exec_ctx = McpExecutionContext(
                tool_name=meta.name,
                method_name=meta.method_name,
                server_class=type(server_instance),
                headers=(
                    _ec.request.headers
                    if _ec is not None
                    else (binding.headers if binding else None)
                ),
                execution_context=_ec,
                session_id=binding.session_id if binding else None,
                metadata=_merged_metadata,
                tool_use_id=req.id,
            )

        try:
            for param_name, provider in meta.depends_params.items():
                kwargs[param_name] = await _resolve_depends(provider, resolved, cleanup)

            # 4c. Per-tool guard execution (before method call).
            if _guards:
                await _run_tool_guards(_guards, exec_ctx, container, owning_module)

            # 8. Call the method, wrapped in interceptors and exception handlers.
            try:
                if meta.timeout is not None:
                    try:
                        out = await asyncio.wait_for(
                            _execute_with_interceptors(
                                meta,
                                method,
                                kwargs,
                                exec_ctx,
                                container,
                                owning_module,
                                tool_ctx=ctx,
                            ),
                            timeout=meta.timeout,
                        )
                    except TimeoutError:
                        raise ValueError(
                            f"Tool {meta.name!r} execution timed out after {meta.timeout}s"
                        ) from None
                else:
                    out = await _execute_with_interceptors(
                        meta,
                        method,
                        kwargs,
                        exec_ctx,
                        container,
                        owning_module,
                        tool_ctx=ctx,
                    )

                _validate_output(out.get("structuredContent"), meta)
                return out

            except Exception as exc:
                if not _exc_handlers:
                    raise

                handled = await _run_tool_exception_handlers(
                    exc,
                    _exc_handlers,
                    exec_ctx,
                    container=container,
                    owning_module=owning_module,
                )
                if handled is not None:
                    return handled
                raise  # no handler matched or all returned None

        finally:
            # 9b. Run background tasks — await them so they complete before
            # the response is sent (consistent with the original main behaviour).
            if bg is not None and bg._has_tasks():
                await _run_background_tasks(bg)

            # 10. Cleanup Depends providers in LIFO order.
            for teardown in reversed(cleanup):
                try:
                    coro = teardown()
                    if asyncio.iscoroutine(coro):
                        await coro
                except Exception:
                    _logger.exception("Depends cleanup raised; ignoring")

    return handler


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


def make_resources_list_handler(
    resources: list[McpResourceMeta] | Callable[[], list[McpResourceMeta]],
) -> _Handler:
    """Return an async handler for resources/list."""
    get_resources = resources if callable(resources) else (lambda: resources)

    async def handler(req: JsonRpcRequest) -> dict[str, Any]:
        result = []
        for r in get_resources():
            entry: dict[str, Any] = {
                "uri": r.uri_template,
                "name": r.name,
            }
            if r.title is not None:
                entry["title"] = r.title
            if r.description is not None:
                entry["description"] = r.description
            if r.mime_type is not None:
                entry["mimeType"] = r.mime_type
            if r.annotations is not None:
                ann_dict = r.annotations.to_dict()
                if ann_dict:
                    entry["annotations"] = ann_dict
            result.append(entry)
        return {"resources": result}

    return handler


def _coerce_resource_item(item: Any, uri: str, meta: McpResourceMeta) -> dict[str, Any]:
    """Normalise one resource content item to its wire dict."""
    if isinstance(item, dict):
        return item
    if isinstance(item, ResourceContent):
        out: dict[str, Any] = {"uri": item.uri or uri}
        if item.mimeType is not None:
            out["mimeType"] = item.mimeType
        if item.text is not None:
            out["text"] = item.text
        if item.blob is not None:
            out["blob"] = item.blob
        return out
    if isinstance(item, BlobResource):
        return {
            "uri": uri,
            "mimeType": meta.mime_type or item.mime_type,
            "blob": base64.b64encode(item.data).decode("ascii"),
        }
    if isinstance(item, bytes):
        return {
            "uri": uri,
            "mimeType": meta.mime_type or "application/octet-stream",
            "blob": base64.b64encode(item).decode("ascii"),
        }
    if isinstance(item, str):
        out = {"uri": uri, "text": item}
        if meta.mime_type:
            out["mimeType"] = meta.mime_type
        return out
    return {"uri": uri, "text": json.dumps(item)}


def _coerce_resource_result(result: Any, uri: str, meta: McpResourceMeta) -> list[dict[str, Any]]:
    if isinstance(result, ResourceResult):
        return [_coerce_resource_item(item, uri, meta) for item in result.contents]
    if isinstance(result, list):
        return [_coerce_resource_item(item, uri, meta) for item in result]
    return [_coerce_resource_item(result, uri, meta)]


def make_resources_read_handler(
    server_instance: Any,
    resources: list[McpResourceMeta] | Callable[[], list[McpResourceMeta]],
    *,
    container: Any | None = None,
    owning_module: type | None = None,
    server_metadata: dict[str, Any] | None = None,
) -> _Handler:
    """Return an async handler for resources/read.

    Matches the requested URI against compiled URI-template patterns and
    calls the corresponding method with extracted (and type-coerced) path
    and query variables.
    """
    get_resources = resources if callable(resources) else (lambda: resources)

    async def handler(req: JsonRpcRequest) -> dict[str, Any]:
        from lauren_mcp._server._dispatcher import McpInvalidParamsError  # noqa: PLC0415

        params: dict[str, Any] = req.params if isinstance(req.params, dict) else {}
        uri = params.get("uri", "")
        for meta in get_resources():
            compiled = compile_uri_template(meta.uri_template)
            variables = match_uri(compiled, uri)
            if variables is None:
                continue
            kwargs = coerce_params(variables, meta.param_type_hints)

            # --- Pipe validation ---
            if meta.pipe_chains:
                try:
                    from lauren.exceptions import ExtractorFieldError  # noqa: PLC0415

                    _extractor_field_error: type | None = ExtractorFieldError
                except ImportError:
                    _extractor_field_error = None

                for param_name, pipes in meta.pipe_chains.items():
                    if not pipes or param_name not in kwargs:
                        continue
                    try:
                        kwargs[param_name] = await _run_pipe_chain(
                            param_name, kwargs[param_name], pipes
                        )
                    except Exception as exc:  # noqa: BLE001
                        if (
                            _extractor_field_error is not None
                            and isinstance(exc, _extractor_field_error)
                            or isinstance(exc, (ValueError, TypeError))
                        ):
                            raise McpInvalidParamsError(param_name, str(exc)) from exc
                        raise

            # --- Header[T] injection ---
            if meta.header_params:
                binding = CURRENT_BINDING.get()
                headers = binding.headers if binding is not None else None
                for param_name, spec in meta.header_params.items():
                    raw: str | None = headers.get(spec.header_name) if headers is not None else None
                    if raw is None:
                        if spec.is_optional:
                            kwargs[param_name] = None
                        elif spec.default is not _HEADER_NO_DEFAULT:
                            kwargs[param_name] = spec.default
                        else:
                            try:
                                kwargs[param_name] = _coerce_header_value("", spec.coerce_to)
                            except (ValueError, TypeError):
                                kwargs[param_name] = None
                    else:
                        try:
                            kwargs[param_name] = _coerce_header_value(raw, spec.coerce_to)
                        except (ValueError, TypeError):
                            kwargs[param_name] = (
                                spec.default if spec.default is not _HEADER_NO_DEFAULT else None
                            )

            # --- State[T] injection (transient dict per resource call) ---
            if meta.state_params:
                state_dict: dict[str, Any] = {}
                for param_name, T in meta.state_params.items():
                    key = _state_key(T)
                    if key not in state_dict:
                        try:
                            state_dict[key] = T()
                        except TypeError as exc:
                            raise TypeError(
                                f"State[{T.__qualname__}] requires {T.__qualname__}() to be "
                                f"callable with no arguments, but it raised: {exc}"
                            ) from exc
                    kwargs[param_name] = state_dict[key]

            # --- BackgroundTasks injection ---
            bg: Any = None
            if meta.bg_tasks_param:
                try:
                    from lauren import BackgroundTasks  # noqa: PLC0415

                    bg = BackgroundTasks()
                    for bg_param in meta.bg_tasks_param.split(","):
                        bg_param = bg_param.strip()
                        if bg_param:
                            kwargs[bg_param] = bg
                except ImportError:
                    pass

            # --- Depends[callable] injection ---
            resolved: dict[int, Any] = {}
            cleanup: list[Any] = []

            target = getattr(meta, "_bound_instance", None) or server_instance
            method = getattr(target, meta.method_name)

            try:
                for param_name, provider in meta.depends_params.items():
                    kwargs[param_name] = await _resolve_depends(provider, resolved, cleanup)

                res_interceptors = getattr(meta, "interceptors", ())
                if res_interceptors and container is not None:
                    from lauren_mcp._server._exec_context import (
                        McpExecutionContext,  # noqa: PLC0415
                    )

                    binding = CURRENT_BINDING.get()
                    exec_ctx = McpExecutionContext(
                        tool_name=meta.name,
                        method_name=meta.method_name,
                        server_class=type(server_instance),
                        headers=binding.headers if binding else None,
                        execution_context=binding.execution_context if binding else None,
                        session_id=binding.session_id if binding else None,
                        metadata={**(server_metadata or {}), **getattr(meta, "tool_metadata", {})},
                        tool_use_id=None,
                    )

                    async def _resource_base(
                        _method: Any = method,
                        _kwargs: dict[str, Any] = kwargs,
                        _uri: str = uri,
                        _meta: McpResourceMeta = meta,
                    ) -> dict[str, Any]:
                        _result = await _method(**_kwargs)
                        return {"contents": _coerce_resource_result(_result, _uri, _meta)}

                    current_fn: Any = _resource_base
                    for ic_cls in reversed(res_interceptors):
                        _ic = await _resolve_di(container, ic_cls, owning_module)
                        _inner = current_fn

                        async def _make_next(
                            _ic: Any = _ic, _inner: Any = _inner, _ctx: Any = exec_ctx
                        ) -> dict[str, Any]:
                            result: dict[str, Any] = await _ic.intercept(
                                _ctx, McpCallHandler(_inner)
                            )
                            return result

                        current_fn = _make_next
                    return await current_fn()  # type: ignore[no-any-return]

                result = await method(**kwargs)
                return {"contents": _coerce_resource_result(result, uri, meta)}
            finally:
                # Run background tasks synchronously before response is sent.
                if bg is not None and bg._has_tasks():
                    await _run_background_tasks(bg)
                # Cleanup Depends providers LIFO
                for teardown in reversed(cleanup):
                    try:
                        coro = teardown()
                        if asyncio.iscoroutine(coro):
                            await coro
                    except Exception:
                        _logger.exception("Depends cleanup raised; ignoring")

        raise ValueError(f"No resource matches URI: {uri!r}")

    return handler


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


def make_prompts_list_handler(
    prompts: list[McpPromptMeta] | Callable[[], list[McpPromptMeta]],
) -> _Handler:
    """Return an async handler for prompts/list."""
    get_prompts = prompts if callable(prompts) else (lambda: prompts)

    async def handler(req: JsonRpcRequest) -> dict[str, Any]:
        schemas: list[dict[str, Any]] = []
        for p in get_prompts():
            entry: dict[str, Any] = {"name": p.name}
            if p.title is not None:
                entry["title"] = p.title
            if p.description is not None:
                entry["description"] = p.description
            if p.arguments:
                entry["arguments"] = p.arguments
            schemas.append(entry)
        return {"prompts": schemas}

    return handler


def make_prompts_get_handler(
    server_instance: Any,
    prompts: list[McpPromptMeta] | Callable[[], list[McpPromptMeta]],
) -> _Handler:
    """Return an async handler for prompts/get.

    Dispatches to server_instance.<method_name>(**arguments) and
    expects the method to return either a string (turned into a single
    user message) or a dict/list matching the MCP GetPromptResult shape.
    """
    get_prompts = prompts if callable(prompts) else (lambda: prompts)

    async def handler(req: JsonRpcRequest) -> dict[str, Any]:
        params: dict[str, Any] = req.params if isinstance(req.params, dict) else {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        prompt_map = {p.name: p for p in get_prompts()}
        if name not in prompt_map:
            raise ValueError(f"Unknown prompt: {name!r}")
        meta = prompt_map[name]
        target = getattr(meta, "_bound_instance", None) or server_instance
        method = getattr(target, meta.method_name)
        result = await method(**arguments)
        # Normalise to GetPromptResult shape
        if isinstance(result, str):
            return {
                "description": meta.description or name,
                "messages": [{"role": "user", "content": {"type": "text", "text": result}}],
            }
        elif isinstance(result, dict):
            # Already a GetPromptResult-like dict
            return result
        else:
            return {
                "description": meta.description or name,
                "messages": [{"role": "user", "content": {"type": "text", "text": str(result)}}],
            }

    return handler


# ---------------------------------------------------------------------------
# Completion
# ---------------------------------------------------------------------------


def make_completion_handler(
    server_instance: Any,
    completions: list[McpCompletionMeta],
) -> _Handler:
    """Return an async handler for completion/complete.

    Dispatches to the registered completion method based on
    ref.type + ref.name/uri + argument.name.

    Returns an empty list when no matching completion handler is registered
    (per spec: not an error, just no suggestions).
    """
    # Build a lookup: (ref_type, target_name, argument_name) -> meta
    lookup: dict[tuple[str, str, str], McpCompletionMeta] = {
        (c.ref_type, c.target_name, c.argument_name): c for c in completions
    }

    async def handler(req: JsonRpcRequest) -> dict[str, Any]:
        params: dict[str, Any] = req.params if isinstance(req.params, dict) else {}
        ref = params.get("ref") or {}
        argument = params.get("argument") or {}

        ref_type: str = ref.get("type", "")
        ref_name: str = ref.get("name") or ref.get("uri") or ""
        arg_name: str = argument.get("name", "")
        partial: str = argument.get("value", "")

        key = (ref_type, ref_name, arg_name)
        meta = lookup.get(key)
        if meta is None:
            return {"completion": {"values": [], "total": 0, "hasMore": False}}

        target = getattr(meta, "_bound_instance", None) or server_instance
        method = getattr(target, meta.method_name)
        raw_result = await method(partial)

        # CompletionResult dataclass -- has .values, .total, .has_more
        if hasattr(raw_result, "values") and hasattr(raw_result, "has_more"):
            result_dict: dict[str, Any] = {
                "values": list(raw_result.values),
                "hasMore": bool(raw_result.has_more),
            }
            if raw_result.total is not None:
                result_dict["total"] = raw_result.total
            else:
                result_dict["total"] = len(raw_result.values)
            return {"completion": result_dict}

        # list[str]
        values: list[str] = list(raw_result)
        return {"completion": {"values": values, "total": len(values), "hasMore": False}}

    return handler


# ---------------------------------------------------------------------------
# Backward-compat aliases and shims (for tests written against the original
# main API)
# ---------------------------------------------------------------------------

# Re-export McpInvalidParamsError from dispatcher for backward compat.
from lauren_mcp._server._dispatcher import McpInvalidParamsError  # noqa: E402


async def _run_bg_tasks(bg: Any) -> None:
    """Backward-compat alias for ``_run_background_tasks``.

    The original main had a version that used Lauren's logger/signals shim.
    This version delegates to the merged implementation.
    """
    if bg is None:
        return
    if not getattr(bg, "_has_tasks", lambda: False)():
        return
    await _run_background_tasks(bg)


def _validate_param_specs(arguments: dict[str, Any], meta: McpToolMeta) -> dict[str, Any]:
    """Validate *arguments* against ``meta.param_specs`` using ``FieldDescriptor.validate()``.

    Backward-compat shim.  Raises :class:`McpInvalidParamsError` on failure.
    """
    param_specs: dict[str, Any] = getattr(meta, "param_specs", {})
    if not param_specs:
        return arguments

    try:
        from lauren.extractors import FieldDescriptor, _ParamSpec  # noqa: PLC0415
    except ImportError:
        return arguments

    validated = dict(arguments)
    for param_name, spec in param_specs.items():
        if param_name not in validated:
            continue
        fd: Any = None
        if isinstance(spec, FieldDescriptor):
            fd = spec
        elif isinstance(spec, _ParamSpec) and spec.field_descriptor is not None:
            fd = spec.field_descriptor
        if fd is not None:
            try:
                validated[param_name] = fd.validate(param_name, validated[param_name])
            except Exception as exc:  # noqa: BLE001
                raise McpInvalidParamsError(param_name, str(exc)) from exc
    return validated


async def _run_pipes(
    name_or_arguments: Any,
    value_or_meta: Any,
    pipes: list[Any] | None = None,
) -> Any:
    """Unified _run_pipes that supports both the old and new calling conventions.

    New API (3 args):  ``_run_pipes(name, value, pipes)`` → transformed value
    Old API (2 args):  ``_run_pipes(arguments, meta)`` → transformed arguments dict
    """
    if pipes is not None:
        # New 3-arg API: _run_pipes(name, value, pipes)
        return await _run_pipe_chain(name_or_arguments, value_or_meta, pipes)

    # Old 2-arg API: _run_pipes(arguments, meta)
    arguments: dict[str, Any] = name_or_arguments
    meta: McpToolMeta = value_or_meta

    param_specs: dict[str, Any] = getattr(meta, "param_specs", {})
    pipe_chain_map: dict[str, list[Any]] = getattr(meta, "pipe_chains", {})

    result = dict(arguments)

    # Run pipes from param_specs (_ParamSpec objects)
    if param_specs:
        try:
            from lauren.extractors import _ParamSpec  # noqa: PLC0415
        except ImportError:
            return result
        for param_name, spec in param_specs.items():
            if param_name not in result:
                continue
            if isinstance(spec, _ParamSpec) and spec.pipes:
                for pipe_fn in spec.pipes:
                    val = result[param_name]
                    if isinstance(pipe_fn, type) and hasattr(pipe_fn, "transform"):
                        instance = pipe_fn()
                        raw = instance.transform(val, None)
                    else:
                        raw = pipe_fn(val, None)  # type: ignore[call-arg,arg-type]
                    if inspect.isawaitable(raw):
                        raw = await raw
                    result[param_name] = raw

    # Also run explicit pipe_chains
    for param_name, chain in pipe_chain_map.items():
        if param_name not in result or not chain:
            continue
        result[param_name] = await _run_pipe_chain(param_name, result[param_name], chain)

    return result
