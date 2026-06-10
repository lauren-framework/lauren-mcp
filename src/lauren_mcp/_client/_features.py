"""Shared client features — version negotiation, notification handlers, roots.

Mixed into both :class:`McpStdioClient` and :class:`_McpBaseRemoteClient` so
every transport gets the same handler registration API and server-request
handling (``roots/list``, ``sampling/createMessage``, ``elicitation/create``).
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from lauren_mcp._mcp_version import LATEST
from lauren_mcp._types import (
    JsonRpcNotification,
    JsonRpcRequest,
    McpErrorCode,
    Root,
)

_logger = logging.getLogger(__name__)

#: Handler for one notification; sync or async.
NotificationHandler = Callable[[dict[str, Any]], Awaitable[None] | None]
#: Handler invoked with "tools" | "resources" | "prompts".
ListChangedHandler = Callable[[str], Awaitable[None] | None]
#: Returns the current roots; sync or async.
RootsProvider = Callable[[], "list[Root] | Awaitable[list[Root]]"]
#: Responds to a server-initiated request; returns the result dict.
ServerRequestHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]] | dict[str, Any]]
#: Zero-arg unsubscribe function returned by on_* registrations.
Unsubscribe = Callable[[], None]

_LIST_CHANGED_METHODS = {
    "notifications/tools/list_changed": "tools",
    "notifications/resources/list_changed": "resources",
    "notifications/prompts/list_changed": "prompts",
}


class _ClientFeaturesMixin:
    """Notification handlers, roots, and protocol-version state for clients.

    Consuming classes must provide ``_send_raw(obj) -> Awaitable[None]``.
    """

    def _init_features(
        self,
        *,
        protocol_version: str | None = None,
        roots: list[Root] | RootsProvider | None = None,
        progress_handler: NotificationHandler | None = None,
        log_handler: NotificationHandler | None = None,
        list_changed_handler: ListChangedHandler | None = None,
        sampling_handler: ServerRequestHandler | None = None,
        elicitation_handler: ServerRequestHandler | None = None,
    ) -> None:
        self._requested_protocol_version: str = protocol_version or LATEST
        self._negotiated_protocol_version: str | None = None
        self._roots = roots
        self._progress_handlers: list[NotificationHandler] = (
            [progress_handler] if progress_handler else []
        )
        self._log_handlers: list[NotificationHandler] = [log_handler] if log_handler else []
        self._list_changed_handlers: list[ListChangedHandler] = (
            [list_changed_handler] if list_changed_handler else []
        )
        self._sampling_handler = sampling_handler
        self._elicitation_handler = elicitation_handler

    # ------------------------------------------------------------------
    # Protocol version
    # ------------------------------------------------------------------

    @property
    def protocol_version(self) -> str:
        """The protocol version negotiated with the server.

        Raises ``RuntimeError`` before :meth:`connect` completes.
        """
        if self._negotiated_protocol_version is None:
            raise RuntimeError("protocol_version is only available after connect()")
        return self._negotiated_protocol_version

    # ------------------------------------------------------------------
    # Handler registration
    # ------------------------------------------------------------------

    def on_progress(self, handler: NotificationHandler) -> Unsubscribe:
        """Register a handler for ``notifications/progress``."""
        self._progress_handlers.append(handler)
        return lambda: self._discard(self._progress_handlers, handler)

    def on_log(self, handler: NotificationHandler) -> Unsubscribe:
        """Register a handler for ``notifications/message`` (server logs)."""
        self._log_handlers.append(handler)
        return lambda: self._discard(self._log_handlers, handler)

    def on_list_changed(self, handler: ListChangedHandler) -> Unsubscribe:
        """Register a handler for tool/resource/prompt ``list_changed``."""
        self._list_changed_handlers.append(handler)
        return lambda: self._discard(self._list_changed_handlers, handler)

    @staticmethod
    def _discard(handlers: list[Any], handler: Any) -> None:
        import contextlib

        with contextlib.suppress(ValueError):
            handlers.remove(handler)

    # ------------------------------------------------------------------
    # Capabilities / handshake support
    # ------------------------------------------------------------------

    def _build_client_capabilities(self) -> dict[str, Any]:
        caps: dict[str, Any] = {}
        if self._roots is not None:
            caps["roots"] = {"listChanged": callable(self._roots)}
        if self._sampling_handler is not None:
            caps["sampling"] = {}
        if self._elicitation_handler is not None:
            caps["elicitation"] = {}
        return caps

    # ------------------------------------------------------------------
    # Notification routing
    # ------------------------------------------------------------------

    def _route_notification(self, msg: JsonRpcNotification) -> None:
        params = msg.params if isinstance(msg.params, dict) else {}
        if msg.method == "notifications/progress":
            self._invoke_all(self._progress_handlers, params)
        elif msg.method == "notifications/message":
            self._invoke_all(self._log_handlers, params)
        elif msg.method in _LIST_CHANGED_METHODS:
            self._invoke_all(self._list_changed_handlers, _LIST_CHANGED_METHODS[msg.method])

    @staticmethod
    def _invoke_all(handlers: list[Any], arg: Any) -> None:
        for handler in list(handlers):
            try:
                result = handler(arg)
                if inspect.isawaitable(result):
                    asyncio.ensure_future(result)
            except Exception:
                _logger.exception("MCP client: notification handler error")

    # ------------------------------------------------------------------
    # Server-initiated requests
    # ------------------------------------------------------------------

    def _handle_server_request(self, msg: JsonRpcRequest) -> None:
        """Reply to a server-initiated request in a background task."""
        asyncio.ensure_future(self._reply_server_request(msg))

    async def _reply_server_request(self, msg: JsonRpcRequest) -> None:
        params = msg.params if isinstance(msg.params, dict) else {}
        try:
            if msg.method == "ping":
                result: dict[str, Any] = {}
            elif msg.method == "roots/list" and self._roots is not None:
                result = {"roots": [r.to_dict() for r in await self._resolve_roots()]}
            elif msg.method == "sampling/createMessage" and self._sampling_handler is not None:
                result = await self._call_handler(self._sampling_handler, params)
            elif msg.method == "elicitation/create" and self._elicitation_handler is not None:
                result = await self._call_handler(self._elicitation_handler, params)
            else:
                await self._send_raw(  # type: ignore[attr-defined]
                    {
                        "jsonrpc": "2.0",
                        "id": msg.id,
                        "error": {
                            "code": int(McpErrorCode.METHOD_NOT_FOUND),
                            "message": f"Client does not handle: {msg.method!r}",
                        },
                    }
                )
                return
            await self._send_raw(  # type: ignore[attr-defined]
                {"jsonrpc": "2.0", "id": msg.id, "result": result}
            )
        except Exception as exc:
            _logger.exception("MCP client: server request handler failed")
            try:  # noqa: SIM105
                await self._send_raw(  # type: ignore[attr-defined]
                    {
                        "jsonrpc": "2.0",
                        "id": msg.id,
                        "error": {
                            "code": int(McpErrorCode.INTERNAL_ERROR),
                            "message": str(exc),
                        },
                    }
                )
            except Exception:
                pass

    @staticmethod
    async def _call_handler(
        handler: ServerRequestHandler, params: dict[str, Any]
    ) -> dict[str, Any]:
        result = handler(params)
        if inspect.isawaitable(result):
            result = await result
        return result

    async def _resolve_roots(self) -> list[Root]:
        roots = self._roots
        if roots is None:
            return []
        if callable(roots):
            resolved = roots()
            if inspect.isawaitable(resolved):
                resolved = await resolved
            return list(resolved)
        return list(roots)

    # ------------------------------------------------------------------
    # Roots change notification
    # ------------------------------------------------------------------

    async def notify_roots_changed(self) -> None:
        """Send ``notifications/roots/list_changed`` to the server.

        Only meaningful when dynamic roots (a callable) were supplied.
        """
        if self._roots is None:
            raise RuntimeError("notify_roots_changed() requires roots to be configured")
        await self._send_raw(  # type: ignore[attr-defined]
            {"jsonrpc": "2.0", "method": "notifications/roots/list_changed"}
        )
