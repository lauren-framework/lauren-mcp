"""MCP request dispatcher — routes JSON-RPC requests to registered handlers."""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from lauren import injectable, Scope, post_construct
from lauren_mcp._types import (
    JsonRpcRequest,
    JsonRpcResponse,
    JsonRpcErrorResponse,
    McpErrorCode,
    build_error_response,
)

# Type alias for an async handler: receives the request params dict (or None)
# and returns a plain Python value that will be placed in `result`.
AsyncHandler = Callable[[dict[str, Any] | None], Awaitable[Any]]


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

    @post_construct
    def _register_builtins(self) -> None:
        """Register built-in MCP method handlers."""

        async def _ping(params: dict[str, Any] | None) -> dict[str, Any]:
            return {}

        self.register("ping", _ping)

    def register(self, method: str, handler: AsyncHandler) -> None:
        """Register *handler* for *method*.

        Overwrites any previously registered handler for the same method
        name.  Handlers must be coroutine functions (``async def``).
        """
        self._handlers[method] = handler

    async def dispatch(
        self, request: JsonRpcRequest
    ) -> JsonRpcResponse | JsonRpcErrorResponse:
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

        params: dict[str, Any] | None = (
            request.params if isinstance(request.params, dict) else None
        )

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

    def cancel(self, request_id: str | int) -> bool:
        """Cancel the in-flight task for *request_id*.

        Returns ``True`` if a task was found and cancelled, ``False``
        if the request was already complete or never registered.
        """
        task = self._in_flight.get(request_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True
