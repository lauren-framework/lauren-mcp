"""WebSocket transport controller factory for MCP over WebSockets."""

from __future__ import annotations

import asyncio
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

from lauren_mcp._server._binding import CURRENT_BINDING, TransportBinding
from lauren_mcp._server._dispatcher import McpDispatcher
from lauren_mcp._server._propagate import _apply_server_metadata
from lauren_mcp._server._registry import McpConnectionRegistry
from lauren_mcp._types import (
    ClientCapabilities,
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

# Default timeout for server-initiated client RPCs (sampling / elicitation).
_CLIENT_RPC_TIMEOUT = 120.0


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def mcp_ws_controller(
    path: str,
    dispatcher_cls: type = McpDispatcher,
    *,
    source: Any | None = None,
    guard_classes: tuple[type, ...] = (),
    interceptor_classes: tuple[type, ...] = (),
    middleware_classes: tuple[type, ...] = (),
) -> type:
    """Return a ``@ws_controller`` class mounted at ``path + "/ws"``.

    The returned class is a fully-decorated Lauren WebSocket gateway that:

    1. Accepts the WebSocket upgrade and starts a message loop.
    2. Enforces ``@use_guards``, ``@use_interceptors``, ``@use_middlewares``,
       ``@use_encoder``, ``@use_exception_handlers``, and ``@set_metadata``
       from *source* (typically the ``@mcp_server`` class) via
       :func:`~lauren.propagate_metadata`.  Lauren's WS runtime then runs
       guards before ``@on_connect`` and interceptors wrap the connect hook.
    3. Enforces MCP's ``initialize`` / ``initialized`` handshake — any
       non-``initialize`` request received before the handshake completes
       is rejected with ``INVALID_REQUEST``.
    4. Forwards :class:`JsonRpcRequest` messages to the injected
       :class:`McpDispatcher` and sends the result back over the socket.
    5. Handles ``$/cancelRequest`` notifications by calling
       :meth:`McpDispatcher.cancel`.
    6. Supports server-initiated requests to the client (sampling /
       elicitation) by tracking ``srv-`` prefixed request ids and routing the
       client's response frames back to the awaiting coroutine.
    7. Registers with :class:`McpConnectionRegistry` so server-push
       notifications (``list_changed`` etc.) reach this connection.
    8. Cleans up on disconnect.

    Parameters
    ----------
    path:
        Base path prefix.  The gateway mounts at ``path + "/ws"``.
    dispatcher_cls:
        DI token to inject as the dispatcher; defaults to
        :class:`McpDispatcher` (the concrete singleton).
    source:
        Source class (typically the ``@mcp_server``-decorated class) whose
        Lauren ``@use_*`` metadata is propagated onto the generated
        controller via :func:`~lauren.propagate_metadata`.  All metadata
        categories are propagated: guards, interceptors, middlewares,
        exception handlers, encoder, and user metadata.  When *source* is
        provided, *guard_classes*, *interceptor_classes*, and
        *middleware_classes* are ignored.
    guard_classes:
        Explicit guard classes — used only when *source* is ``None``.
        Prefer *source* for new code.
    interceptor_classes:
        Explicit interceptor classes — used only when *source* is ``None``.
    middleware_classes:
        Explicit middleware classes — used only when *source* is ``None``.
    """
    ws_path = path.rstrip("/") + "/ws"

    @ws_controller(ws_path)
    class McpWsController:
        """MCP WebSocket gateway — one instance per connection (REQUEST scope)."""

        def __init__(
            self,
            dispatcher: McpDispatcher,
            registry: McpConnectionRegistry,
        ) -> None:
            self._dispatcher = dispatcher
            self._registry = registry
            # Per-connection state: True once the client has sent
            # ``notifications/initialized`` after the handshake.
            self._initialized: bool = False
            self._client_capabilities: ClientCapabilities | None = None
            self._registry_key: str | None = None
            # Server-initiated RPCs awaiting a client response.
            self._pending_client_rpcs: dict[str, asyncio.Future[Any]] = {}
            self._next_srv_id = 0

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

            async def _send(raw: str) -> None:
                await ws.send_text(raw)

            self._registry_key = self._registry.register(_send)

            async def _send_notification(payload: dict[str, Any]) -> None:
                import json

                await ws.send_text(json.dumps(payload))

            binding = TransportBinding(
                headers=getattr(ws, "headers", None),
                execution_context=None,  # WS is per-connection, not per-frame
                session_id=None,
                send_notification=_send_notification,
                client_rpc=self._make_client_rpc(ws),
                client_capabilities=None,  # filled in at initialize
            )
            self._binding = binding
            token = CURRENT_BINDING.set(binding)
            try:
                await self._message_loop(ws)
            finally:
                CURRENT_BINDING.reset(token)

        def _make_client_rpc(self, ws: Any) -> Any:
            """Build the server-to-client request callable for this connection."""

            async def client_rpc(method: str, params: dict[str, Any]) -> Any:
                import json

                req_id = f"srv-{self._next_srv_id}"
                self._next_srv_id += 1
                fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
                self._pending_client_rpcs[req_id] = fut
                try:
                    await ws.send_text(
                        json.dumps(
                            {
                                "jsonrpc": "2.0",
                                "id": req_id,
                                "method": method,
                                "params": params,
                            }
                        )
                    )
                    return await asyncio.wait_for(fut, timeout=_CLIENT_RPC_TIMEOUT)
                finally:
                    self._pending_client_rpcs.pop(req_id, None)

            return client_rpc

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

                if msg.method == "initialize":
                    self._capture_client_capabilities(msg)

                response: JsonRpcResponse | JsonRpcErrorResponse = await self._dispatcher.dispatch(
                    msg
                )
                await ws.send_text(response.to_json())
                return

            # JsonRpcResponse / JsonRpcErrorResponse — the client replying to
            # a server-initiated request (sampling / elicitation).
            if isinstance(msg, (JsonRpcResponse, JsonRpcErrorResponse)):
                fut = self._pending_client_rpcs.get(str(msg.id))
                if fut is not None and not fut.done():
                    if isinstance(msg, JsonRpcResponse):
                        fut.set_result(msg.result)
                    else:
                        fut.set_exception(
                            RuntimeError(
                                f"Client RPC failed ({msg.error.code}): {msg.error.message}"
                            )
                        )
                    return
                _logger.warning("MCP WS server received an unmatched response frame: %s", raw[:200])

        def _capture_client_capabilities(self, msg: JsonRpcRequest) -> None:
            params = msg.params if isinstance(msg.params, dict) else {}
            raw_caps = params.get("capabilities") or {}
            caps = ClientCapabilities(
                roots=raw_caps.get("roots"),
                sampling=raw_caps.get("sampling"),
                elicitation=raw_caps.get("elicitation"),
                experimental=raw_caps.get("experimental"),
            )
            self._client_capabilities = caps
            binding = getattr(self, "_binding", None)
            if binding is not None:
                binding.client_capabilities = caps

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
            if self._registry_key is not None:
                self._registry.unregister(self._registry_key)
                self._registry_key = None
            for fut in self._pending_client_rpcs.values():
                if not fut.done():
                    fut.set_exception(RuntimeError("Connection closed"))
            self._pending_client_rpcs.clear()
            _logger.debug("MCP WS: client disconnected")

    # Give the dynamically-created class a meaningful __name__ / __qualname__
    # so framework introspection and tracebacks are readable.
    McpWsController.__name__ = "McpWsController"
    McpWsController.__qualname__ = f"mcp_ws_controller.<locals>.McpWsController[{ws_path}]"

    # Apply Lauren cross-cutting metadata so the framework's native WS runtime
    # enforces guards/interceptors before @on_connect and propagates all other
    # @use_* annotations (encoder, exception_handlers, user_metadata).
    if source is not None:
        _apply_server_metadata(source, McpWsController)
    else:
        # Legacy explicit params — kept for backward compatibility.
        if guard_classes:
            use_guards(*guard_classes)(McpWsController)
        if interceptor_classes:
            use_interceptors(*interceptor_classes)(McpWsController)
        if middleware_classes:
            use_middlewares(*middleware_classes)(McpWsController)

    return McpWsController
