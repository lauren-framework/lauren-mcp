"""McpToolContext — per-call context injected into @mcp_tool methods."""

from __future__ import annotations

import asyncio
import enum
import json
import logging
import typing
from dataclasses import dataclass, field
from typing import Any, Literal

from lauren_mcp._server._binding import ClientRpc, SendNotification
from lauren_mcp._types import (
    ClientCapabilities,
    CreateMessageParams,
    CreateMessageResult,
    ElicitResult,
    McpElicitationNotAvailable,
    McpSamplingNotAvailable,
    SamplingMessage,
    TextContent,
)

_logger = logging.getLogger(__name__)

LogLevel = Literal["debug", "info", "notice", "warning", "error", "critical", "alert", "emergency"]
_LEVEL_RANK: dict[str, int] = {
    "debug": 0,
    "info": 1,
    "notice": 2,
    "warning": 3,
    "error": 4,
    "critical": 5,
    "alert": 6,
    "emergency": 7,
}

#: Frozenset of all valid MCP log level strings (all 8 syslog-aligned levels).
VALID_LOG_LEVELS: frozenset[str] = frozenset(_LEVEL_RANK.keys())


class McpSamplingLoopError(RuntimeError):
    """Raised by tool authors to signal the agentic sampling loop should stop.

    ``ctx.sample()`` does not raise this automatically — it is provided for
    tool authors to use in their own loop guards::

        for _ in range(max_tool_iterations):
            result = await ctx.sample(messages, tools=[...])
            if not isinstance(result.content, ToolUseContent):
                return result.text
            # handle tool call ...
        raise McpSamplingLoopError(
            f"Tool loop exceeded {max_tool_iterations} iterations"
        )
    """


class LogLevelState:
    """Mutable server-wide minimum level for client-bound log notifications.

    A shared cell (rather than a plain value) so the ``logging/setLevel``
    handler can adjust the threshold after tool contexts have been built.
    """

    def __init__(self, level: str = "debug") -> None:
        self.level = level

    def allows(self, level: str) -> bool:
        return _LEVEL_RANK.get(level, 0) >= _LEVEL_RANK.get(self.level, 0)


def _structured_fields(response_type: Any) -> list[tuple[str, Any, bool, str | None]] | None:
    """Extract ``(name, annotation, required, description)`` field tuples.

    Supports flat Pydantic models, ``msgspec.Struct`` subclasses, dataclasses,
    and ``TypedDict`` classes.  Returns ``None`` when *response_type* is not a
    structured type.
    """
    import dataclasses

    if hasattr(response_type, "model_fields"):  # pydantic v2 model
        return [
            (name, info.annotation, info.is_required(), info.description)
            for name, info in response_type.model_fields.items()
        ]

    if typing.is_typeddict(response_type):
        try:
            hints = typing.get_type_hints(response_type, include_extras=True)
        except Exception:
            hints = dict(getattr(response_type, "__annotations__", {}))
        required_keys: frozenset[str] = getattr(response_type, "__required_keys__", frozenset())
        out: list[tuple[str, Any, bool, str | None]] = []
        for name, annotation in hints.items():
            # The wrapper on the resolved hint wins over __required_keys__ —
            # under PEP 563 __required_keys__ cannot see the wrappers.
            origin = typing.get_origin(annotation)
            if origin is typing.NotRequired:
                annotation = typing.get_args(annotation)[0]
                is_required = False
            elif origin is typing.Required:
                annotation = typing.get_args(annotation)[0]
                is_required = True
            else:
                is_required = name in required_keys
            out.append((name, annotation, is_required, None))
        return out

    if isinstance(response_type, type) and dataclasses.is_dataclass(response_type):
        try:
            hints = typing.get_type_hints(response_type)
        except Exception:
            hints = {}
        return [
            (
                f.name,
                hints.get(f.name, f.type),
                f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING,
                None,
            )
            for f in dataclasses.fields(response_type)
        ]

    if isinstance(response_type, type) and hasattr(response_type, "__struct_fields__"):
        try:
            import msgspec.structs
        except ImportError:
            return None
        return [
            (
                f.name,
                f.type,
                f.required,
                None,
            )
            for f in msgspec.structs.fields(response_type)
        ]

    return None


def build_elicitation_schema(response_type: Any) -> dict[str, Any] | None:
    """Map *response_type* to the shallow JSON Schema MCP elicitation allows.

    ``None`` (approval-only) produces ``None``; scalars and ``Literal`` /
    ``Enum`` options produce a single-property object schema; flat Pydantic
    models, ``msgspec.Struct`` subclasses, dataclasses, and ``TypedDict``
    classes produce a multi-property object schema.  Nested objects/arrays
    raise ``ValueError`` per the MCP spec constraint.
    """
    if response_type is None:
        return None

    scalar = _scalar_schema(response_type)
    if scalar is not None:
        return {
            "type": "object",
            "properties": {"value": scalar},
            "required": ["value"],
        }

    fields = _structured_fields(response_type)
    if fields is not None:
        properties: dict[str, Any] = {}
        required: list[str] = []
        for name, annotation, is_required, description in fields:
            prop = _scalar_schema(annotation)
            if prop is None:
                raise ValueError(
                    f"Elicitation schemas must be flat: field {name!r} of "
                    f"{response_type.__name__} has unsupported type "
                    f"{annotation!r}"
                )
            if description:
                prop["description"] = description
            properties[name] = prop
            if is_required:
                required.append(name)
        schema: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        return schema

    raise ValueError(f"Unsupported elicitation response type: {response_type!r}")


def _convert_result(data: Any, result_type: type[Any]) -> Any:
    """Convert parsed JSON *data* into *result_type*.

    Supports Pydantic models, ``msgspec.Struct`` subclasses (via
    ``msgspec.convert``, with validation), ``TypedDict`` classes (shallow
    required-key check), dataclasses, and any ``cls(**data)``-constructible
    type.
    """
    if hasattr(result_type, "model_validate"):  # pydantic v2
        return result_type.model_validate(data)
    if hasattr(result_type, "__struct_fields__"):  # msgspec.Struct
        import msgspec

        return msgspec.convert(data, type=result_type)
    if typing.is_typeddict(result_type):
        required = {
            name for name, _, is_required, _ in _structured_fields(result_type) or [] if is_required
        }
        missing = required - set(data)
        if missing:
            raise ValueError(f"Missing required keys: {sorted(missing)}")
        return data
    return result_type(**data)


def _scalar_schema(annotation: Any) -> dict[str, Any] | None:
    """Return a primitive JSON Schema for *annotation*, or None if not scalar."""
    if annotation is str:
        return {"type": "string"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if typing.get_origin(annotation) is Literal:
        values = list(typing.get_args(annotation))
        return {"type": "string", "enum": values}
    if isinstance(annotation, type) and issubclass(annotation, enum.Enum):
        return {"type": "string", "enum": [m.value for m in annotation]}
    # list[str] is explicitly allowed in MCP elicitation spec
    origin = typing.get_origin(annotation)
    if origin is list:
        args = typing.get_args(annotation)
        if args == (str,):
            return {"type": "array", "items": {"type": "string"}}
    return None


def _coerce_tools(tools: list[Any]) -> list[dict[str, Any]]:
    """Normalise tool descriptors to wire dicts.

    Accepts :class:`~lauren_mcp._types.ToolSchema`,
    :class:`~lauren_mcp.server._meta.McpToolMeta` (duck-typed), or plain
    ``dict`` entries.  Raises ``TypeError`` for unrecognised types.
    """
    from lauren_mcp._types import ToolSchema  # local import to avoid cycle

    result: list[dict[str, Any]] = []
    for item in tools:
        if isinstance(item, dict):
            result.append(item)
        elif isinstance(item, ToolSchema):
            entry: dict[str, Any] = {
                "name": item.name,
                "description": item.description,
                "inputSchema": item.inputSchema,
            }
            result.append(entry)
        elif hasattr(item, "name") and hasattr(item, "input_schema"):
            # McpToolMeta duck-type check (avoids import cycle via server._meta)
            entry = {
                "name": item.name,
                "description": item.description,
                "inputSchema": item.input_schema,
            }
            result.append(entry)
        else:
            raise TypeError(
                f"Unsupported tool descriptor type: {type(item).__name__}. "
                "Expected ToolSchema, McpToolMeta, or dict."
            )
    return result


@dataclass(frozen=True)
class McpToolContext:
    """Context injected into an ``@mcp_tool`` method when a parameter is
    annotated with ``McpToolContext``.

    The object is immutable so tool authors cannot accidentally mutate shared
    transport state.  The ``state`` bag is mutable per-call scratch space and
    ``extras`` is the extension bag for integrations (``lauren-ai`` stores its
    ``AgentContext`` under ``extras["agent_context"]``).
    """

    # ---------- identity ----------
    tool_name: str
    tool_use_id: str | int | None = None

    # ---------- transport ----------
    headers: Any = None
    execution_context: Any = None  # lauren.ExecutionContext | None
    session_id: str | None = None

    # ---------- metadata / scratch ----------
    metadata: dict[str, Any] = field(default_factory=dict)
    state: dict[str, Any] = field(default_factory=dict)
    extras: dict[str, Any] = field(default_factory=dict)
    lifespan_context: dict[str, Any] = field(default_factory=dict)

    # ---------- plumbing (supplied by the transport binding) ----------
    _progress_token: str | int | None = None
    _send_notification: SendNotification | None = None
    _client_rpc: ClientRpc | None = None
    _client_capabilities: ClientCapabilities | None = None
    _log_level_state: LogLevelState | None = None

    # ---------- cancellation ----------
    # Private — set by the dispatcher when $/cancelRequest arrives.
    # The frozen dataclass can be constructed without specifying it;
    # the property allocates the event on first access.
    _cancel_event: asyncio.Event | None = field(default=None, repr=False)

    def get_metadata(self, key: str, default: Any = None) -> Any:
        return self.metadata.get(key, default)

    # ------------------------------------------------------------------
    # Cancellation
    # ------------------------------------------------------------------

    @property
    def cancel_requested(self) -> asyncio.Event:
        """An ``asyncio.Event`` set when the client cancels this call.

        The event is created lazily on first access and stored in the
        (normally immutable) dataclass via ``object.__setattr__``.  This is
        safe because the event is local to this call instance and is only
        written once (by the dispatcher, before ``task.cancel()`` is called).

        Tools should treat this as a *read-only* hint: check
        ``cancel_requested.is_set()`` between work units and return early for
        graceful shutdown.  The containing ``asyncio.Task`` will still be
        hard-cancelled shortly after the event fires.

        .. note::
            The event is never set on the legacy HTTP+SSE transport (which
            does not implement ``$/cancelRequest``).
        """
        if self._cancel_event is None:
            object.__setattr__(self, "_cancel_event", asyncio.Event())
        return self._cancel_event  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Progress
    # ------------------------------------------------------------------

    async def report_progress(
        self,
        progress: float | int,
        total: float | int | None = None,
        message: str | None = None,
    ) -> None:
        """Send ``notifications/progress`` to the client.

        No-op when the client did not supply a ``progressToken`` in the
        ``tools/call`` request, or when the transport has no notification
        channel.

        Args:
            progress: Current progress value (e.g. number of items processed).
            total: Optional upper bound.  When omitted the client treats
                progress as indeterminate.
            message: Optional human-readable status string displayed alongside
                the progress indicator (e.g. ``"Scanning 3 of 10 files"``).
        """
        if self._progress_token is None or self._send_notification is None:
            return
        params: dict[str, Any] = {
            "progressToken": self._progress_token,
            "progress": progress,
        }
        if total is not None:
            params["total"] = total
        if message is not None:
            params["message"] = message
        await self._send_notification(
            {"jsonrpc": "2.0", "method": "notifications/progress", "params": params}
        )

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    async def log(self, level: LogLevel, message: str, data: dict[str, Any] | None = None) -> None:
        """Send a structured ``notifications/message`` log entry to the client.

        Dropped silently when below the server's minimum level or when the
        transport has no notification channel.
        """
        if self._send_notification is None:
            return
        if self._log_level_state is not None and not self._log_level_state.allows(level):
            return
        payload: dict[str, Any] = {"message": message}
        if data:
            payload["extra"] = data
        await self._send_notification(
            {
                "jsonrpc": "2.0",
                "method": "notifications/message",
                "params": {"level": level, "logger": self.tool_name, "data": payload},
            }
        )

    async def debug(self, message: str, data: dict[str, Any] | None = None) -> None:
        await self.log("debug", message, data)

    async def info(self, message: str, data: dict[str, Any] | None = None) -> None:
        await self.log("info", message, data)

    async def notice(self, message: str, data: dict[str, Any] | None = None) -> None:
        """Send a ``notice``-level log notification.

        Use for normal but significant conditions that operators should be aware
        of (e.g. a configuration override taking effect, a fallback path used).
        """
        await self.log("notice", message, data)

    async def warning(self, message: str, data: dict[str, Any] | None = None) -> None:
        await self.log("warning", message, data)

    async def error(self, message: str, data: dict[str, Any] | None = None) -> None:
        await self.log("error", message, data)

    async def critical(self, message: str, data: dict[str, Any] | None = None) -> None:
        """Send a ``critical``-level log notification.

        Use for conditions that require immediate attention but have not yet
        caused complete service failure (e.g. a primary data source is down and
        a fallback is active).
        """
        await self.log("critical", message, data)

    # ------------------------------------------------------------------
    # Sampling
    # ------------------------------------------------------------------

    async def sample(
        self,
        messages: str | list[Any],  # list[SamplingMessage]
        *,
        max_tokens: int = 1024,
        system_prompt: str | None = None,
        temperature: float | None = None,
        stop_sequences: list[str] | None = None,
        model_preferences: dict[str, Any] | None = None,
        include_context: Literal["none", "thisServer", "allServers"] = "none",
        result_type: type[Any] | None = None,
        # New agentic loop parameters:
        tools: list[Any] | None = None,
        tool_choice: dict[str, Any] | None = None,
        max_tool_iterations: int = 10,
    ) -> Any:
        """Ask the connected MCP client to run an LLM call on our behalf.

        Returns a :class:`CreateMessageResult`, or — when *result_type* is a
        Pydantic model class — an instance of that model parsed from the
        reply text.

        When *tools* is supplied the client's LLM may respond with a
        ``ToolUseContent`` block instead of a ``TextContent`` block.
        ``ctx.sample()`` does **not** execute tools automatically.  The caller
        is responsible for handling ``ToolUseContent`` responses and building
        the agentic loop.

        Parameters
        ----------
        tools:
            Tool descriptors to pass to the LLM.  Each entry may be a
            :class:`~lauren_mcp._types.ToolSchema`, a
            :class:`~lauren_mcp.server._meta.McpToolMeta` (auto-converted), or a
            raw ``dict`` with ``name``, ``description``, and ``inputSchema`` keys.
            ``None`` means no tools are passed (single-turn text/image only).
        tool_choice:
            Forwarded to the client as-is.  ``None`` omits the field (client default).
        max_tool_iterations:
            Advisory upper bound on agentic loop iterations passed to the client
            in ``CreateMessageParams.metadata["max_tool_iterations"]``.  Default: 10.

        Raises
        ------
        McpSamplingNotAvailable
            Client did not advertise ``sampling`` capability, or did not advertise
            ``tools`` support within ``sampling`` when ``tools=`` is supplied, or
            the transport does not support server-to-client requests.
        """
        if self._client_rpc is None:
            raise McpSamplingNotAvailable("This transport cannot deliver server-to-client requests")
        caps = self._client_capabilities
        if caps is None or caps.sampling is None:
            raise McpSamplingNotAvailable(
                "The connected client did not advertise the 'sampling' capability"
            )

        # Capability check for tool-enabled sampling
        if tools is not None:
            sampling_caps = caps.sampling
            if not (isinstance(sampling_caps, dict) and sampling_caps.get("tools")):
                raise McpSamplingNotAvailable(
                    "The connected client does not support tool-enabled sampling "
                    "('tools' not set in sampling capability). "
                    "Pass tools=None or upgrade the client."
                )

        if isinstance(messages, str):
            messages = [SamplingMessage(role="user", content=TextContent(text=messages))]

        # Build metadata: include max_tool_iterations advisory when tools are used
        metadata: dict[str, Any] | None = model_preferences
        if tools is not None:
            metadata = {**(model_preferences or {}), "max_tool_iterations": max_tool_iterations}

        # Coerce tools to wire dicts
        coerced_tools = _coerce_tools(tools) if tools is not None else None

        params = CreateMessageParams(
            messages=messages,
            maxTokens=max_tokens,
            systemPrompt=system_prompt,
            includeContext=include_context,
            temperature=temperature,
            stopSequences=stop_sequences or [],
            modelPreferences=model_preferences,
            metadata=metadata,
        )
        params_dict = params.to_dict()
        # Add tools / toolChoice to the wire dict (not yet in CreateMessageParams dataclass)
        if coerced_tools is not None:
            params_dict["tools"] = coerced_tools
        if tool_choice is not None:
            params_dict["toolChoice"] = tool_choice
        raw = await self._client_rpc("sampling/createMessage", params_dict)
        result = CreateMessageResult.from_dict(raw if isinstance(raw, dict) else {})
        if result_type is None:
            return result
        try:
            data = json.loads(result.text)
            return _convert_result(data, result_type)
        except Exception as exc:
            raise ValueError(
                f"Sampling reply could not be parsed as {result_type.__name__}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Elicitation
    # ------------------------------------------------------------------

    async def elicit(
        self,
        message: str,
        response_type: Any = None,
    ) -> ElicitResult:
        """Ask the connected MCP client to prompt its user for input.

        *response_type* may be ``None`` (approval only), ``str``, ``bool``,
        ``int``, ``float``, a ``Literal[...]``, an ``Enum`` subclass,
        ``list[str]`` (multi-select string array), or a flat Pydantic model /
        dataclass / TypedDict whose fields are all of the above scalar types.

        Raises :class:`McpElicitationNotAvailable` when the client did not
        advertise the ``elicitation`` capability or the transport cannot carry
        server-to-client requests (legacy SSE).
        """
        if self._client_rpc is None:
            raise McpElicitationNotAvailable(
                "This transport cannot deliver server-to-client requests"
            )
        caps = self._client_capabilities
        if caps is None or caps.elicitation is None:
            raise McpElicitationNotAvailable(
                "The connected client did not advertise the 'elicitation' capability"
            )

        params: dict[str, Any] = {"message": message}
        schema = build_elicitation_schema(response_type)
        if schema is not None:
            params["requestedSchema"] = schema
        raw = await self._client_rpc("elicitation/create", params)
        return ElicitResult.from_dict(raw if isinstance(raw, dict) else {})

    async def elicit_url(
        self,
        message: str,
        url: str,
        *,
        elicitation_id: str | None = None,
    ) -> Any:  # returns UrlElicitResult
        """Direct the user to an external URL and await completion.

        The server sends ``elicitation/create`` with ``requestedUrl`` (and
        ``elicitationId``) rather than ``requestedSchema``.  The client opens
        the URL in a browser; the user completes the external flow; the client
        responds with ``{"action": "accept"}`` or ``{"action": "cancel"}``.

        Parameters
        ----------
        message:
            Human-readable prompt shown to the user before the URL is opened.
        url:
            The URL to open.
        elicitation_id:
            An opaque string identifying this elicitation instance.
            Auto-generated as a UUID4 hex string when not provided.

        Returns
        -------
        UrlElicitResult
            ``action`` is ``"accept"`` (flow completed) or ``"cancel"``
            (user dismissed or flow was abandoned).

        Raises
        ------
        McpUrlElicitationNotAvailable
            Client did not advertise the ``urlElicitation`` sub-capability,
            ``elicitation`` capability is absent, or the transport does not
            support server-to-client requests (e.g. legacy HTTP+SSE).
        """
        from lauren_mcp._types import (  # noqa: PLC0415
            McpUrlElicitationNotAvailable,
            UrlElicitResult,
        )

        # -- capability gate --
        caps = self._client_capabilities
        if caps is None or caps.elicitation is None:
            raise McpUrlElicitationNotAvailable(
                "The connected client did not advertise the 'elicitation' capability"
            )
        elicitation_caps = caps.elicitation
        if not (isinstance(elicitation_caps, dict) and elicitation_caps.get("urlElicitation")):
            raise McpUrlElicitationNotAvailable(
                "The connected client does not support URL elicitation "
                "('urlElicitation' not set in elicitation capability)"
            )
        if self._client_rpc is None:
            raise McpUrlElicitationNotAvailable(
                "This transport cannot deliver server-to-client requests"
            )

        import uuid  # noqa: PLC0415

        eid = elicitation_id if elicitation_id is not None else uuid.uuid4().hex

        rpc_params: dict[str, Any] = {
            "message": message,
            "requestedUrl": url,
            "elicitationId": eid,
        }
        raw = await self._client_rpc("elicitation/create", rpc_params)
        return UrlElicitResult.from_dict(raw if isinstance(raw, dict) else {})
