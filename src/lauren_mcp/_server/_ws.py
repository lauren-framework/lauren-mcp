"""WebSocket transport controller factory for MCP over WebSockets."""

from __future__ import annotations

import logging
from typing import Any

from lauren import (
    WebSocket,
    on_connect,
    on_disconnect,
    use_guards,
    use_interceptors,
    use_middlewares,
    ws_controller,
)

from lauren_mcp._server._dispatcher import McpDispatcher
from lauren_mcp._types import (
    JsonRpcErrorResponse,
    JsonRpcNotification,
    JsonRpcRequest,
    JsonRpcResponse,
    McpErrorCode,
    McpParseError,
    build_error_response,
    parse_message,
)

_logger = logging.getLogger(__name__)

# MCP notification methods handled specially by the transport layer
_METHOD_INITIALIZED = "notifications/initialized"
_METHOD_CANCEL = "$/cancelRequest"


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def mcp_ws_controller(
    path: str,
    dispatcher_cls: type = McpDispatcher,
    *,
    guard_classes: tuple[type, ...] = (),
    interceptor_classes: tuple[type, ...] = (),
    middleware_classes: tuple[type, ...] = (),
) -> type:
    """Return a ``@ws_controller`` class mounted at ``path + "/ws"``.

    The returned class is a fully-decorated Lauren WebSocket gateway that:

    1. Accepts the WebSocket upgrade and starts a message loop.
    2. Optionally enforces *guard_classes* at connection time — Lauren's WS
       runtime calls each guard's ``can_activate(ctx)`` before the ``@on_connect``
       hook runs; if any guard returns ``False`` the connection is closed with
       code 1008 (policy violation) before the MCP handshake begins.
    3. Enforces MCP's ``initialize`` / ``initialized`` handshake — any
       non-``initialize`` request received before the handshake completes
       is rejected with ``INVALID_REQUEST``.
    4. Forwards :class:`JsonRpcRequest` messages to the injected
       :class:`McpDispatcher` and sends the result back over the socket.
    5. Handles ``$/cancelRequest`` notifications by calling
       :meth:`McpDispatcher.cancel`.
    6. Cleans up on disconnect.

    Parameters
    ----------
    path:
        Base path prefix.  The gateway mounts at ``path + "/ws"``.
    dispatcher_cls:
        DI token to inject as the dispatcher; defaults to
        :class:`McpDispatcher` (the concrete singleton).
    guard_classes:
        Lauren guard classes whose ``can_activate(ctx)`` is called by the
        framework before ``@on_connect``.  Guards are resolved from Lauren's
        DI container.  Rejected connections receive close code ``1008``.
    interceptor_classes:
        Lauren interceptor classes that wrap the ``@on_connect`` lifecycle
        hook.  Applied by the framework's native interceptor chain.
    middleware_classes:
        Lauren middleware classes stored as metadata.  For per-request
        middleware use ``LaurenFactory.create(…, global_middlewares=[…])``.
    """
    ws_path = path.rstrip("/") + "/ws"

    @ws_controller(ws_path)
    class McpWsController:
        """MCP WebSocket gateway — one instance per connection (REQUEST scope)."""

        def __init__(self, dispatcher: McpDispatcher) -> None:
            self._dispatcher = dispatcher
            # Per-connection state: True once the client has sent
            # ``notifications/initialized`` after the handshake.
            self._initialized: bool = False

        @on_connect
        async def handle_connect(self, ws: WebSocket) -> None:
            """Accept the connection and enter the MCP message loop.

            Guard checks and interceptors are handled by Lauren's WS runtime
            before this hook is called — no manual guard loop needed here.

            Awaiting ``_message_loop`` keeps Lauren's built-in event-routing
            loop from starting — MCP uses raw JSON-RPC frames, not Lauren's
            ``event``-keyed dispatch format.
            """
            await ws.accept()
            await self._message_loop(ws)

        async def _message_loop(self, ws: Any) -> None:
            """Continuously receive frames and dispatch them until the socket closes."""
            while True:
                try:
                    raw: str = await ws.receive_text()
                except Exception:
                    # WebSocketDisconnect or any transport error — exit cleanly.
                    break
                try:
                    await self._handle_frame(ws, raw)
                except Exception:
                    _logger.exception("Unhandled error in MCP frame handler")
                    break

        async def _handle_frame(self, ws: Any, raw: str) -> None:
            """Parse *raw* and route it to the correct handler."""
            # --- Parse ---
            try:
                msg = parse_message(raw)
            except McpParseError as exc:
                err = build_error_response(
                    id=None,
                    code=McpErrorCode.PARSE_ERROR,
                    message=str(exc),
                )
                await ws.send_text(err.to_json())
                return

            # --- Notifications (no id, no response needed) ---
            if isinstance(msg, JsonRpcNotification):
                await self._handle_notification(msg)
                return

            # --- Requests ---
            if isinstance(msg, JsonRpcRequest):
                # Enforce initialize-first protocol: the very first request
                # must be ``initialize``; everything else must wait until
                # ``notifications/initialized`` has been received.
                if not self._initialized and msg.method != "initialize":
                    err = build_error_response(
                        id=msg.id,
                        code=McpErrorCode.INVALID_REQUEST,
                        message=("Server has not been initialized. Send 'initialize' first."),
                    )
                    await ws.send_text(err.to_json())
                    return

                response: JsonRpcResponse | JsonRpcErrorResponse = await self._dispatcher.dispatch(
                    msg
                )
                await ws.send_text(response.to_json())
                return

            # JsonRpcResponse / JsonRpcErrorResponse arriving on the server
            # side are unexpected — log and ignore.
            _logger.warning("MCP WS server received a response frame (unexpected): %s", raw[:200])

        async def _handle_notification(self, notification: JsonRpcNotification) -> None:
            """Handle a JSON-RPC notification from the client."""
            method = notification.method

            if method == _METHOD_INITIALIZED:
                # Client signals it's ready — unlock the dispatch gate.
                self._initialized = True
                return

            if method == _METHOD_CANCEL:
                params = notification.params or {}
                if isinstance(params, dict):
                    request_id = params.get("id")
                    if request_id is not None:
                        cancelled = self._dispatcher.cancel(request_id)
                        if not cancelled:
                            _logger.debug(
                                "$/cancelRequest: no in-flight task for id=%r",
                                request_id,
                            )
                return

            # All other notifications are silently accepted (spec says
            # unknown notifications MUST be ignored).
            _logger.debug("MCP WS: unhandled notification method=%r", method)

        @on_disconnect
        async def handle_disconnect(self, ws: WebSocket) -> None:
            """Perform cleanup when the WebSocket connection closes."""
            _logger.debug("MCP WS: client disconnected")

    # Give the dynamically-created class a meaningful __name__ / __qualname__
    # so framework introspection and tracebacks are readable.
    McpWsController.__name__ = "McpWsController"
    McpWsController.__qualname__ = f"mcp_ws_controller.<locals>.McpWsController[{ws_path}]"

    # Apply Lauren cross-cutting decorators so the framework's native WS
    # runtime handles guards, interceptors, and middlewares automatically.
    if guard_classes:
        use_guards(*guard_classes)(McpWsController)
    if interceptor_classes:
        use_interceptors(*interceptor_classes)(McpWsController)
    if middleware_classes:
        use_middlewares(*middleware_classes)(McpWsController)

    return McpWsController
