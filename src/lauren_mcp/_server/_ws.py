"""WebSocket transport controller factory for MCP over WebSockets."""

from __future__ import annotations

import logging
from typing import Any

from lauren import WebSocket, on_connect, on_disconnect, ws_controller

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

# Lauren decorator attribute names — mirrors lauren/decorators.py constants.
# Stored on McpWsController so Lauren's future WS guard support picks them up.
_USE_GUARDS = "__lauren_use_guards__"
_USE_INTERCEPTORS = "__lauren_use_interceptors__"
_USE_MIDDLEWARES = "__lauren_use_middlewares__"


# ---------------------------------------------------------------------------
# WS execution context — presented to guards at connection time
# ---------------------------------------------------------------------------


class _McpWsRequest:
    """Read-only view of the WebSocket upgrade data shaped like a Lauren Request.

    Guards that check ``ctx.request.headers`` or ``ctx.request.path`` work
    transparently because this class surfaces the same attributes.
    """

    def __init__(self, ws: Any) -> None:
        self._ws = ws

    @property
    def headers(self) -> Any:  # lauren.types.Headers
        return self._ws.headers

    @property
    def path(self) -> str:
        return self._ws.path

    @property
    def path_params(self) -> dict[str, str]:
        return self._ws.path_params

    @property
    def method(self) -> str:
        return "GET"  # WS upgrades are always GET requests

    def get_metadata(self, key: str, default: Any = None) -> Any:
        return default


class _McpWsExecutionContext:
    """Minimal ExecutionContext given to guards during a WS connection.

    Guards receive this as ``ctx`` and typically access ``ctx.request.headers``
    to check auth tokens — that works here because ``_McpWsRequest`` proxies
    the WebSocket's header collection.
    """

    def __init__(self, ws: Any, handler_class: type | None = None) -> None:
        self.request = _McpWsRequest(ws)
        self.handler_class = handler_class
        self.handler_func: Any = None
        self.route_template: str | None = ws.path if hasattr(ws, "path") else None
        self.metadata: dict[str, Any] = {}

    def get_metadata(self, key: str, default: Any = None) -> Any:
        return self.metadata.get(key, default)


# ---------------------------------------------------------------------------
# Dynamic __init__ builder for DI-injected guards
# ---------------------------------------------------------------------------


def _build_init_with_guards(
    guard_classes: tuple[type, ...],
) -> Any:
    """Return an ``__init__`` that accepts the dispatcher + one guard per class.

    Lauren's DI resolves constructor parameters by their type annotation.  We
    use ``exec()`` to create a function with both the correct parameter *names*
    (required by Python) and correct type *annotations* (required by Lauren's
    DI compiler).

    Example for two guard classes [AuthGuard, RateGuard]:
    ``def __init__(self, dispatcher, _mcpg0, _mcpg1): ...``
    with annotations ``{dispatcher: McpDispatcher, _mcpg0: AuthGuard, _mcpg1: RateGuard}``.
    """
    guard_names = [f"_mcpg{i}" for i in range(len(guard_classes))]
    params = ", ".join(["dispatcher"] + guard_names)
    guards_list = ", ".join(guard_names)

    code = (
        f"def __init__(self, {params}):\n"
        f"    self._dispatcher = dispatcher\n"
        f"    self._initialized = False\n"
        f"    self._mcp_guards = [{guards_list}]\n"
    )
    ns: dict[str, Any] = {}
    exec(code, ns)  # noqa: S102
    fn = ns["__init__"]

    fn.__annotations__ = {"dispatcher": McpDispatcher, "return": None}
    for i, cls in enumerate(guard_classes):
        fn.__annotations__[f"_mcpg{i}"] = cls

    return fn


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
    2. Optionally runs *guard_classes* at connection time — if any guard
       returns ``False``, the connection is closed with code 1008
       (policy violation) before the MCP handshake begins.
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
        Lauren guard classes (decorated with ``@injectable``) whose
        ``can_activate(ctx)`` is called before the MCP handshake.  Guards
        are resolved from Lauren's DI container (REQUEST scope — one
        instance per connection).  Rejected connections receive close
        code ``1008`` (policy violation).
    interceptor_classes:
        Lauren interceptor classes stored as metadata for future framework
        compatibility.  Not yet executed per-frame; use guards for auth.
    middleware_classes:
        Lauren middleware classes stored as metadata for future framework
        compatibility.  For per-request middleware use
        ``LaurenFactory.create(…, global_middlewares=[…])``.
    """
    ws_path = path.rstrip("/") + "/ws"
    _guard_classes = tuple(guard_classes)
    _interceptor_classes = tuple(interceptor_classes)
    _middleware_classes = tuple(middleware_classes)

    @ws_controller(ws_path)
    class McpWsController:
        """MCP WebSocket gateway — one instance per connection (REQUEST scope)."""

        def __init__(self, dispatcher: McpDispatcher) -> None:
            self._dispatcher = dispatcher
            # Per-connection state: True once the client has sent
            # ``notifications/initialized`` after the handshake.
            self._initialized: bool = False
            # Guards populated only when guard_classes are provided
            # (overridden by _build_init_with_guards below).
            self._mcp_guards: list[Any] = []

        @on_connect
        async def handle_connect(self, ws: WebSocket) -> None:
            """Run guards, accept the connection, then enter the MCP message loop.

            Guard check happens before ``ws.accept()`` so rejected clients
            receive close code 1008 rather than being accepted and then dropped.

            Awaiting ``_message_loop`` here keeps Lauren's built-in
            event-routing loop from starting — MCP uses raw JSON-RPC frames,
            not Lauren's ``event``-keyed dispatch format.
            """
            # --- Guard check (before accepting the connection) ---
            if self._mcp_guards:
                ctx = _McpWsExecutionContext(ws, handler_class=type(self))
                for guard in self._mcp_guards:
                    try:
                        allowed = await guard.can_activate(ctx)
                    except Exception:
                        _logger.exception("MCP WS: guard %r raised during check", guard)
                        allowed = False
                    if not allowed:
                        _logger.debug(
                            "MCP WS: connection rejected by guard %r at %s",
                            type(guard).__name__,
                            ws.path if hasattr(ws, "path") else "?",
                        )
                        await ws.close(1008)  # 1008 = Policy Violation
                        return

            # --- Accept and enter message loop ---
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

    # If guard classes were supplied, replace __init__ with a version that
    # accepts guard instances via Lauren's DI (resolved per connection).
    if _guard_classes:
        McpWsController.__init__ = _build_init_with_guards(_guard_classes)  # type: ignore[method-assign]

    # Store metadata using Lauren's decorator attribute names so that if
    # Lauren's WS runtime gains guard/interceptor/middleware support in a
    # future release, the controller is already annotated correctly.
    if _guard_classes:
        setattr(McpWsController, _USE_GUARDS, list(_guard_classes))
    if _interceptor_classes:
        setattr(McpWsController, _USE_INTERCEPTORS, list(_interceptor_classes))
    if _middleware_classes:
        setattr(McpWsController, _USE_MIDDLEWARES, list(_middleware_classes))

    return McpWsController
