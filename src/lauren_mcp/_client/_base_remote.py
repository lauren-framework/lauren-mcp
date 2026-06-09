"""Shared ABC mixin for remote (network) MCP transports (WebSocket and HTTP+SSE)."""

from __future__ import annotations

import asyncio
import logging
from abc import abstractmethod
from collections.abc import Callable
from typing import Any

from lauren_mcp._types import (
    Implementation,
    JsonRpcErrorResponse,
    JsonRpcNotification,
    JsonRpcResponse,
    PromptSchema,
    ResourceSchema,
    ToolSchema,
    parse_message,
)

from ._protocol import McpClientProtocol
from ._stdio import McpCallError  # reuse the same error class

_logger = logging.getLogger(__name__)


class _McpBaseRemoteClient(McpClientProtocol):
    """Abstract mixin with shared state and logic for WebSocket and HTTP+SSE clients.

    Subclasses must implement:
    - :meth:`_send_raw`        — serialise and transmit a dict over the wire.
    - :meth:`_start_connection` — open the transport and start :meth:`_read_loop`.
    - :meth:`_close_connection` — tear down the transport.
    - :meth:`connect`           — orchestrate _start_connection + _handshake.
    - :meth:`close`             — orchestrate cleanup + _close_connection.

    The ``_read_loop`` must be started by ``_start_connection`` as a background
    task and must call :meth:`_dispatch_message` for each raw line it receives.
    """

    def __init__(
        self,
        *,
        client_info: Implementation | None = None,
        headers: dict[str, str] | None = None,
        max_retries: int = 3,
        startup_timeout: float = 10.0,
    ) -> None:
        self._client_info = client_info or Implementation(
            name="lauren-mcp-remote-client", version="1.0.0"
        )
        self._headers = headers or {}
        self._max_retries = max_retries
        self._startup_timeout = startup_timeout

        # Shared state
        self._pending: dict[int, asyncio.Future] = {}
        self._notification_listeners: list[Callable[[JsonRpcNotification], None]] = []
        self._reader_task: asyncio.Task | None = None
        self._next_id: int = 0
        self._initialized: bool = False
        self._retry_count: int = 0

    # ------------------------------------------------------------------
    # Abstract transport hooks
    # ------------------------------------------------------------------

    @abstractmethod
    async def _send_raw(self, obj: dict) -> None:
        """Serialise *obj* to JSON and write it to the transport."""

    @abstractmethod
    async def _start_connection(self) -> None:
        """Open the underlying transport and start the ``_read_loop`` task."""

    @abstractmethod
    async def _close_connection(self) -> None:
        """Close the underlying transport."""

    # ------------------------------------------------------------------
    # Shared: handshake
    # ------------------------------------------------------------------

    async def _handshake(self) -> None:
        """Execute the MCP initialize handshake."""
        result = await asyncio.wait_for(
            self._request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": self._client_info.name,
                        "version": self._client_info.version,
                    },
                },
            ),
            timeout=self._startup_timeout,
        )
        _logger.debug("MCP remote handshake complete: %s", result)
        self._initialized = True
        # Send the initialized notification (no response expected)
        await self._send_raw(
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            }
        )

    # ------------------------------------------------------------------
    # Shared: request / dispatch
    # ------------------------------------------------------------------

    async def _request(self, method: str, params: Any = None) -> Any:
        """Send a JSON-RPC request and await its response future."""
        loop = asyncio.get_running_loop()
        req_id = self._next_id
        self._next_id += 1
        fut: asyncio.Future = loop.create_future()
        self._pending[req_id] = fut
        await self._send_raw(
            {
                "jsonrpc": "2.0",
                "method": method,
                "id": req_id,
                **({"params": params} if params is not None else {}),
            }
        )
        return await fut

    def _dispatch_message(self, raw: str) -> None:
        """Parse *raw* JSON-RPC text and route to pending futures or listeners."""
        try:
            msg = parse_message(raw)
        except Exception as exc:
            _logger.warning("MCP remote: parse error — %s (raw=%r)", exc, raw[:200])
            return

        if isinstance(msg, JsonRpcResponse):
            fut = self._pending.pop(msg.id, None)  # type: ignore[arg-type]
            if fut is not None and not fut.done():
                fut.set_result(msg.result)
            return

        if isinstance(msg, JsonRpcErrorResponse):
            fut = self._pending.pop(msg.id, None)  # type: ignore[arg-type]
            if fut is not None and not fut.done():
                err = McpCallError(msg.error.message, code=msg.error.code)
                fut.set_exception(err)
            return

        if isinstance(msg, JsonRpcNotification):
            for listener in self._notification_listeners:
                try:
                    listener(msg)
                except Exception:
                    _logger.exception("MCP remote: notification listener error")
            return

        # Server-initiated requests — not expected for clients
        _logger.debug("MCP remote: received server-side request (ignored): %s", msg)

    def _fail_all_pending(self, reason: str = "Connection lost") -> None:
        """Fail all pending futures with a McpCallError."""
        error = McpCallError(reason, code=-32000)
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.set_exception(error)
        self._pending.clear()

    # ------------------------------------------------------------------
    # McpClientProtocol implementation
    # ------------------------------------------------------------------

    async def list_tools(self) -> list[ToolSchema]:
        result = await self._request("tools/list")
        return [
            ToolSchema(
                name=t["name"],
                description=t.get("description", ""),
                inputSchema=t.get("inputSchema", {}),
            )
            for t in result.get("tools", [])
        ]

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        return await self._request(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
        )

    async def list_resources(self) -> list[ResourceSchema]:
        result = await self._request("resources/list")
        return [
            ResourceSchema(
                uri=r["uri"],
                name=r.get("name", r["uri"]),
                description=r.get("description"),
                mimeType=r.get("mimeType"),
            )
            for r in result.get("resources", [])
        ]

    async def read_resource(self, uri: str) -> Any:
        return await self._request("resources/read", {"uri": uri})

    async def list_prompts(self) -> list[PromptSchema]:
        result = await self._request("prompts/list")
        return [
            PromptSchema(
                name=p["name"],
                description=p.get("description"),
            )
            for p in result.get("prompts", [])
        ]

    async def get_prompt(
        self,
        name: str,
        arguments: dict[str, str] | None = None,
    ) -> Any:
        return await self._request(
            "prompts/get",
            {"name": name, "arguments": arguments or {}},
        )

    async def ping(self) -> None:
        await self._request("ping")
