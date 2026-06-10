"""MCP request dispatcher — routes JSON-RPC requests to registered handlers."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from lauren import Scope, injectable, post_construct

from lauren_mcp._types import (
    JsonRpcErrorResponse,
    JsonRpcRequest,
    JsonRpcResponse,
    McpErrorCode,
    build_error_response,
)

# Type alias for an async handler: receives the request params dict (or None)
# and returns a plain Python value that will be placed in `result`.
AsyncHandler = Callable[[dict[str, Any] | None], Coroutine[Any, Any, Any]]


@injectable(scope=Scope.SINGLETON)
class McpDispatcher:
    """SINGLETON request dispatcher for MCP JSON-RPC messages.

    Handlers are registered by method name and called asynchronously via
    ``asyncio.Task`` so long-running tool invocations can be cancelled
    individually without blocking the connection loop.

    Built-in ``ping`` handler is registered during ``@post_construct``
    so it is always available regardless of what the application registers.
    """

    def __init__(self) -> None:
        self._handlers: dict[str, AsyncHandler] = {}
        self._in_flight: dict[str | int, asyncio.Task[Any]] = {}
        # Per-request context registry: request_id → McpToolContext
        # Used by cancel() to set the cooperative cancel_requested event.
        self._contexts: dict[str | int, Any] = {}

    @post_construct
    def _register_builtins(self) -> None:
        """Register built-in MCP method handlers."""

        async def _ping(params: dict[str, Any] | None) -> dict[str, Any]:
            return {}

        self.register("ping", _ping)

    def register_context(self, request_id: str | int, ctx: Any) -> None:
        """Register the tool context for *request_id* so :meth:`cancel` can signal it.

        Called by ``make_tools_call_handler`` after building the
        :class:`~lauren_mcp._server._context.McpToolContext` for a request.
        """
        self._contexts[request_id] = ctx

    def register(self, method: str, handler: AsyncHandler) -> None:
        """Register *handler* for *method*.

        Overwrites any previously registered handler for the same method
        name.  Handlers must be coroutine functions (``async def``).
        """
        self._handlers[method] = handler

    async def dispatch(self, request: JsonRpcRequest) -> JsonRpcResponse | JsonRpcErrorResponse:
        """Dispatch *request* to its registered handler.

        The handler is wrapped in an ``asyncio.Task`` so it can be
        cancelled by a concurrent ``$/cancelRequest`` notification via
        :meth:`cancel`.  The task is tracked in ``_in_flight`` by
        request id for the duration of its execution.

        Error handling:
        - ``asyncio.CancelledError``  → ``REQUEST_CANCELLED`` error response
        - any other ``Exception``     → ``INTERNAL_ERROR`` error response
        - method not registered       → ``METHOD_NOT_FOUND`` error response
        """
        handler = self._handlers.get(request.method)
        if handler is None:
            return build_error_response(
                id=request.id,
                code=McpErrorCode.METHOD_NOT_FOUND,
                message=f"Method not found: {request.method!r}",
            )

        params: dict[str, Any] | None = request.params if isinstance(request.params, dict) else None

        task: asyncio.Task[Any] = asyncio.create_task(handler(params))

        request_id = request.id
        if request_id is not None:
            self._in_flight[request_id] = task

        try:
            result = await task
            return JsonRpcResponse(id=request.id, result=result)
        except asyncio.CancelledError:
            return build_error_response(
                id=request.id,
                code=McpErrorCode.REQUEST_CANCELLED,
                message=f"Request {request.id!r} was cancelled",
            )
        except Exception as exc:  # noqa: BLE001
            return build_error_response(
                id=request.id,
                code=McpErrorCode.INTERNAL_ERROR,
                message=f"Internal error: {exc}",
                data={"type": type(exc).__name__},
            )
        finally:
            if request_id is not None:
                self._in_flight.pop(request_id, None)
                self._contexts.pop(request_id, None)

    def cancel(self, request_id: str | int) -> bool:
        """Cancel the in-flight task for *request_id*.

        Before hard-cancelling the task, sets the cooperative
        ``cancel_requested`` event on the registered
        :class:`~lauren_mcp._server._context.McpToolContext` (if any) so
        tool code can detect cancellation and clean up gracefully.

        Returns ``True`` if a task was found and cancelled, ``False``
        if the request was already complete or never registered.
        """
        # Signal the cooperative cancel event first (if the tool accessed it).
        # Uses getattr with a default of None so this is safe whether or not
        # McpToolContext has the _cancel_event field (added by a parallel change).
        ctx = self._contexts.get(request_id)
        if ctx is not None:
            cancel_event = getattr(ctx, "_cancel_event", None)
            if cancel_event is not None:
                cancel_event.set()

        task = self._in_flight.get(request_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True
