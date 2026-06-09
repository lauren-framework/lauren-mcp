"""HTTP + SSE transport controller factory for MCP over Server-Sent Events."""

from __future__ import annotations

import json
import logging
import secrets
from collections.abc import AsyncGenerator

from lauren import controller, get, post
from lauren.sse import EventStream, ServerSentEvent
from lauren.types import Request, Response

from lauren_mcp._server._dispatcher import McpDispatcher
from lauren_mcp._server._session import SseSessionStore
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

# Header name carrying the SSE session token
_SESSION_HEADER = "mcp-session-id"


def mcp_http_sse_controller(base_path: str) -> type:
    """Return a ``@controller(base_path)`` class implementing the MCP HTTP+SSE transport.

    The returned controller exposes two endpoints:

    ``GET  <base_path>/sse``
        Opens the SSE stream for a new client.  Generates a ``session_id``,
        yields an ``endpoint`` event carrying that id, then blocks on the
        session queue — forwarding each enqueued payload as a ``message``
        event until the sentinel ``None`` is received or the client
        disconnects.

    ``POST <base_path>/``
        Receives a JSON-RPC message from the client, identified by the
        ``mcp-session-id`` header.  Notifications are handled locally;
        requests are dispatched and the serialised response is put onto the
        session queue so the SSE stream delivers it asynchronously.
        Always returns ``202 Accepted``.

    Parameters
    ----------
    base_path:
        URL prefix for both endpoints (e.g. ``"/mcp"``).
    """

    @controller(base_path)
    class McpSseController:
        """MCP HTTP + SSE transport controller."""

        def __init__(
            self,
            dispatcher: McpDispatcher,
            sessions: SseSessionStore,
        ) -> None:
            self._dispatcher = dispatcher
            self._sessions = sessions

        @get("/sse")
        async def open_stream(self, request: Request) -> EventStream:
            """Open a new SSE stream and return the session endpoint event."""
            session_id = secrets.token_urlsafe(16)
            queue = self._sessions.create(session_id)

            async def _generator() -> AsyncGenerator[ServerSentEvent, None]:
                # First event: tell the client its session id so it can
                # address subsequent POST requests.
                yield ServerSentEvent(
                    event="endpoint",
                    data=json.dumps({"session_id": session_id}),
                )
                try:
                    while True:
                        payload = await queue.get()
                        if payload is None:
                            # Sentinel — server is closing the stream.
                            break
                        yield ServerSentEvent(event="message", data=payload)
                finally:
                    self._sessions.remove(session_id)

            return EventStream(_generator())

        @post("/")
        async def handle_rpc(self, request: Request) -> Response:
            """Handle an inbound JSON-RPC message from the MCP client.

            Reads the ``mcp-session-id`` header to locate the correct SSE
            queue, then:

            * Notifications are handled locally (no queue write needed).
            * Requests are dispatched asynchronously; the serialised
              response is pushed onto the session queue so the open SSE
              stream delivers it to the client.

            Always returns ``202 Accepted`` — the actual response travels
            over the SSE channel.
            """
            session_id: str | None = request.headers.get(_SESSION_HEADER)
            if not session_id:
                return Response(
                    body=json.dumps({"error": f"Missing '{_SESSION_HEADER}' header"}).encode(),
                    status=400,
                    headers=[("content-type", "application/json")],
                )

            queue = self._sessions.get(session_id)
            if queue is None:
                return Response(
                    body=json.dumps({"error": f"Unknown session: {session_id!r}"}).encode(),
                    status=404,
                    headers=[("content-type", "application/json")],
                )

            # Read and parse the request body.
            try:
                raw_body = await request.body()
                msg = parse_message(raw_body)
            except McpParseError as exc:
                err = build_error_response(
                    id=None,
                    code=McpErrorCode.PARSE_ERROR,
                    message=str(exc),
                )
                await queue.put(err.to_json())
                return Response(body=b"", status=202)
            except Exception as exc:  # noqa: BLE001
                _logger.exception("MCP SSE: error reading/parsing request body")
                err = build_error_response(
                    id=None,
                    code=McpErrorCode.INTERNAL_ERROR,
                    message=f"Could not read request body: {exc}",
                )
                await queue.put(err.to_json())
                return Response(body=b"", status=202)

            # Notifications do not generate a response.
            if isinstance(msg, JsonRpcNotification):
                _logger.debug(
                    "MCP SSE: received notification method=%r session=%s",
                    msg.method,
                    session_id,
                )
                return Response(body=b"", status=202)

            if isinstance(msg, JsonRpcRequest):
                response: JsonRpcResponse | JsonRpcErrorResponse = await self._dispatcher.dispatch(
                    msg
                )
                await queue.put(response.to_json())
                return Response(body=b"", status=202)

            # Received a response frame from the client — unexpected, ignore.
            _logger.warning(
                "MCP SSE: client sent a response frame (unexpected), session=%s",
                session_id,
            )
            return Response(body=b"", status=202)

    McpSseController.__name__ = "McpSseController"
    McpSseController.__qualname__ = (
        f"mcp_http_sse_controller.<locals>.McpSseController[{base_path}]"
    )

    return McpSseController
