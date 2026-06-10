"""Per-call transport binding — bridges transports and the singleton dispatcher.

The :class:`McpDispatcher` is a SINGLETON shared by every connection, but tool
context (headers, session id, notification channel, client RPC channel) is
per-connection or per-request.  Transports set :data:`CURRENT_BINDING` before
calling ``dispatcher.dispatch()``; because ``contextvars`` values propagate
into tasks created afterwards, the handler task sees the right binding without
any re-registration or locking.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from lauren_mcp._types import ClientCapabilities

#: Sends a JSON-RPC notification dict to the connected client.
SendNotification = Callable[[dict[str, Any]], Awaitable[None]]

#: Sends a server-initiated JSON-RPC request to the client and awaits the result.
ClientRpc = Callable[[str, dict[str, Any]], Awaitable[Any]]


@dataclass
class TransportBinding:
    """Everything a transport knows about the current connection/request."""

    headers: Any = None
    execution_context: Any = None
    session_id: str | None = None
    send_notification: SendNotification | None = None
    client_rpc: ClientRpc | None = None
    client_capabilities: ClientCapabilities | None = None
    extras: dict[str, Any] = field(default_factory=dict)


CURRENT_BINDING: ContextVar[TransportBinding | None] = ContextVar(
    "mcp_transport_binding", default=None
)
