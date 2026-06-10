"""McpToolContext — per-call context injected into @mcp_tool methods."""

from __future__ import annotations

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

LogLevel = Literal["debug", "info", "warning", "error"]
_LEVEL_RANK: dict[str, int] = {"debug": 0, "info": 1, "warning": 2, "error": 3}


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
    return None


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

    def get_metadata(self, key: str, default: Any = None) -> Any:
        return self.metadata.get(key, default)

    # ------------------------------------------------------------------
    # Progress
    # ------------------------------------------------------------------

    async def report_progress(
        self, progress: float | int, total: float | int | None = None
    ) -> None:
        """Send ``notifications/progress`` to the client.

        No-op when the client did not supply a ``progressToken`` in the
        ``tools/call`` request, or when the transport has no notification
        channel.
        """
        if self._progress_token is None or self._send_notification is None:
            return
        params: dict[str, Any] = {
            "progressToken": self._progress_token,
            "progress": progress,
        }
        if total is not None:
            params["total"] = total
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

    async def warning(self, message: str, data: dict[str, Any] | None = None) -> None:
        await self.log("warning", message, data)

    async def error(self, message: str, data: dict[str, Any] | None = None) -> None:
        await self.log("error", message, data)

    # ------------------------------------------------------------------
    # Sampling
    # ------------------------------------------------------------------

    async def sample(
        self,
        messages: str | list[SamplingMessage],
        *,
        max_tokens: int = 1024,
        system_prompt: str | None = None,
        temperature: float | None = None,
        stop_sequences: list[str] | None = None,
        model_preferences: dict[str, Any] | None = None,
        include_context: Literal["none", "thisServer", "allServers"] = "none",
        result_type: type[Any] | None = None,
    ) -> Any:
        """Ask the connected MCP client to run an LLM call on our behalf.

        Returns a :class:`CreateMessageResult`, or — when *result_type* is a
        Pydantic model class — an instance of that model parsed from the
        reply text.

        Raises :class:`McpSamplingNotAvailable` when the client did not
        advertise the ``sampling`` capability or the transport cannot carry
        server-to-client requests (legacy SSE).
        """
        if self._client_rpc is None:
            raise McpSamplingNotAvailable("This transport cannot deliver server-to-client requests")
        caps = self._client_capabilities
        if caps is None or caps.sampling is None:
            raise McpSamplingNotAvailable(
                "The connected client did not advertise the 'sampling' capability"
            )

        if isinstance(messages, str):
            messages = [SamplingMessage(role="user", content=TextContent(text=messages))]

        params = CreateMessageParams(
            messages=messages,
            maxTokens=max_tokens,
            systemPrompt=system_prompt,
            includeContext=include_context,
            temperature=temperature,
            stopSequences=stop_sequences or [],
            modelPreferences=model_preferences,
        )
        raw = await self._client_rpc("sampling/createMessage", params.to_dict())
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
        ``int``, ``float``, a ``Literal[...]``, an ``Enum`` subclass, or a
        flat Pydantic model.

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
