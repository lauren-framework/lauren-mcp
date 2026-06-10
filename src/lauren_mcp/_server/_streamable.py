"""Streamable HTTP transport (MCP 2025-03-26) — single-endpoint controller."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

from lauren import Scope, controller, delete, get, injectable, post
from lauren.sse import EventStream, ServerSentEvent
from lauren.types import ExecutionContext, Headers, Request, Response

from lauren_mcp._server._binding import CURRENT_BINDING, TransportBinding
from lauren_mcp._server._dispatcher import McpDispatcher
from lauren_mcp._server._handshake import negotiate_version
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

_SESSION_HEADER = "mcp-session-id"
_PROTOCOL_HEADER = "mcp-protocol-version"
_CLIENT_RPC_TIMEOUT = 120.0


@dataclass
class StreamableSession:
    """State for one Streamable HTTP session."""

    session_id: str
    protocol_version: str
    client_capabilities: ClientCapabilities | None = None
    initialized: bool = False
    #: Queue feeding the optional GET push channel.
    push_queue: asyncio.Queue[str | None] = field(default_factory=asyncio.Queue)
    #: Server-initiated RPCs awaiting a client response (via a later POST).
    pending_client_rpcs: dict[str, asyncio.Future[Any]] = field(default_factory=dict)
    next_srv_id: int = 0


@injectable(scope=Scope.SINGLETON)
class StreamableSessionStore:
    """SINGLETON store of live Streamable HTTP sessions."""

    def __init__(self) -> None:
        self._sessions: dict[str, StreamableSession] = {}

    def create(self, protocol_version: str) -> StreamableSession:
        session_id = secrets.token_urlsafe(16)
        session = StreamableSession(session_id=session_id, protocol_version=protocol_version)
        self._sessions[session_id] = session
        return session

    def get(self, session_id: str) -> StreamableSession | None:
        return self._sessions.get(session_id)

    def remove(self, session_id: str) -> None:
        session = self._sessions.pop(session_id, None)
        if session is not None:
            session.push_queue.put_nowait(None)
            for fut in session.pending_client_rpcs.values():
                if not fut.done():
                    fut.set_exception(RuntimeError("Session terminated"))


def _json_response(
    payload: str, status: int = 200, headers: list[tuple[str, str]] | None = None
) -> Response:
    all_headers = [("content-type", "application/json"), *(headers or [])]
    return Response(body=payload.encode(), status=status, headers=Headers(all_headers))


def _accepts_sse(request: Request) -> bool:
    accept = request.headers.get("accept") or ""
    return "text/event-stream" in accept


def mcp_streamable_http_controller(
    base_path: str,
    *,
    source: Any | None = None,
) -> type:
    """Return a ``@controller(base_path)`` implementing Streamable HTTP.

    Endpoints (all on the single MCP endpoint per the 2025-03-26 spec):

    ``POST <base_path>/``
        Receives one JSON-RPC message.  ``initialize`` creates a session and
        returns the ``mcp-session-id`` header.  Requests return either a
        direct ``application/json`` response or — when the client sends
        ``Accept: text/event-stream`` — an SSE response body carrying any
        notifications generated during the call followed by the final
        response.  Notifications return ``202``.  JSON-RPC *responses* from
        the client resolve pending server-initiated RPCs.

    ``GET <base_path>/``
        Optional server-push channel: an SSE stream delivering server
        notifications and server-initiated requests for the session.

    ``DELETE <base_path>/``
        Explicit session teardown.
    """

    @controller(base_path)
    class McpStreamableController:
        """MCP Streamable HTTP transport controller."""

        def __init__(
            self,
            dispatcher: McpDispatcher,
            sessions: StreamableSessionStore,
            registry: McpConnectionRegistry,
        ) -> None:
            self._dispatcher = dispatcher
            self._sessions = sessions
            self._registry = registry

        # --------------------------------------------------------------
        # POST — the main MCP endpoint
        # --------------------------------------------------------------

        @post("/")
        async def handle_post(self, request: Request) -> Response | EventStream:
            try:
                raw_body = await request.body()
                msg = parse_message(raw_body)
            except McpParseError as exc:
                err = build_error_response(None, McpErrorCode.PARSE_ERROR, str(exc))
                return _json_response(err.to_json(), status=400)
            except Exception as exc:  # noqa: BLE001
                err = build_error_response(
                    None, McpErrorCode.INTERNAL_ERROR, f"Could not read request body: {exc}"
                )
                return _json_response(err.to_json(), status=400)

            # --- Client responses to server-initiated RPCs ---
            if isinstance(msg, (JsonRpcResponse, JsonRpcErrorResponse)):
                session = self._require_session(request)
                if isinstance(session, Response):
                    return session
                fut = session.pending_client_rpcs.get(str(msg.id))
                if fut is not None and not fut.done():
                    if isinstance(msg, JsonRpcResponse):
                        fut.set_result(msg.result)
                    else:
                        fut.set_exception(
                            RuntimeError(
                                f"Client RPC failed ({msg.error.code}): {msg.error.message}"
                            )
                        )
                return Response(body=b"", status=202)

            # --- Notifications ---
            if isinstance(msg, JsonRpcNotification):
                session = self._require_session(request)
                if isinstance(session, Response):
                    return session
                if msg.method == "notifications/initialized":
                    session.initialized = True
                elif msg.method == "$/cancelRequest" and isinstance(msg.params, dict):
                    request_id = msg.params.get("id")
                    if request_id is not None:
                        self._dispatcher.cancel(request_id)
                return Response(body=b"", status=202)

            # --- Requests ---
            if isinstance(msg, JsonRpcRequest):
                if msg.method == "initialize":
                    return await self._handle_initialize(request, msg)
                session = self._require_session(request)
                if isinstance(session, Response):
                    return session
                return await self._dispatch_request(request, msg, session)

            err = build_error_response(None, McpErrorCode.INVALID_REQUEST, "Unsupported message")
            return _json_response(err.to_json(), status=400)

        async def _handle_initialize(self, request: Request, msg: JsonRpcRequest) -> Response:
            params = msg.params if isinstance(msg.params, dict) else {}
            client_version = params.get("protocolVersion") or (
                request.headers.get(_PROTOCOL_HEADER) or ""
            )
            version = negotiate_version(client_version)
            session = self._sessions.create(version)
            raw_caps = params.get("capabilities") or {}
            session.client_capabilities = ClientCapabilities(
                roots=raw_caps.get("roots"),
                sampling=raw_caps.get("sampling"),
                elicitation=raw_caps.get("elicitation"),
                experimental=raw_caps.get("experimental"),
            )
            response = await self._dispatcher.dispatch(msg)
            return _json_response(
                response.to_json(),
                headers=[(_SESSION_HEADER, session.session_id), (_PROTOCOL_HEADER, version)],
            )

        def _require_session(self, request: Request) -> StreamableSession | Response:
            session_id = request.headers.get(_SESSION_HEADER)
            if not session_id:
                return _json_response(
                    json.dumps({"error": f"Missing '{_SESSION_HEADER}' header"}), status=400
                )
            session = self._sessions.get(session_id)
            if session is None:
                return _json_response(
                    json.dumps({"error": f"Unknown session: {session_id!r}"}), status=404
                )
            return session

        def _make_binding(
            self,
            request: Request,
            session: StreamableSession,
            notification_queue: asyncio.Queue[str] | None,
        ) -> TransportBinding:
            async def _send_notification(payload: dict[str, Any]) -> None:
                raw = json.dumps(payload)
                if notification_queue is not None:
                    await notification_queue.put(raw)
                else:
                    await session.push_queue.put(raw)

            async def _client_rpc(method: str, params: dict[str, Any]) -> Any:
                req_id = f"srv-{session.next_srv_id}"
                session.next_srv_id += 1
                fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
                session.pending_client_rpcs[req_id] = fut
                raw = json.dumps(
                    {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
                )
                try:
                    if notification_queue is not None:
                        await notification_queue.put(raw)
                    else:
                        await session.push_queue.put(raw)
                    return await asyncio.wait_for(fut, timeout=_CLIENT_RPC_TIMEOUT)
                finally:
                    session.pending_client_rpcs.pop(req_id, None)

            return TransportBinding(
                headers=request.headers,
                execution_context=ExecutionContext(request=request),
                session_id=session.session_id,
                send_notification=_send_notification,
                client_rpc=_client_rpc,
                client_capabilities=session.client_capabilities,
            )

        async def _dispatch_request(
            self, request: Request, msg: JsonRpcRequest, session: StreamableSession
        ) -> Response | EventStream:
            if not _accepts_sse(request):
                # Plain JSON mode: in-flight notifications go to the GET
                # push channel (if open); the response is returned directly.
                binding = self._make_binding(request, session, None)
                token = CURRENT_BINDING.set(binding)
                try:
                    response = await self._dispatcher.dispatch(msg)
                finally:
                    CURRENT_BINDING.reset(token)
                return _json_response(
                    response.to_json(),
                    headers=[(_PROTOCOL_HEADER, session.protocol_version)],
                )

            # SSE mode: notifications generated during the call stream onto
            # the response body, followed by the final response.
            stream_queue: asyncio.Queue[str] = asyncio.Queue()
            binding = self._make_binding(request, session, stream_queue)

            async def _run() -> str:
                token = CURRENT_BINDING.set(binding)
                try:
                    response = await self._dispatcher.dispatch(msg)
                finally:
                    CURRENT_BINDING.reset(token)
                return response.to_json()

            dispatch_task: asyncio.Task[str] = asyncio.create_task(_run())

            async def _generator() -> AsyncGenerator[ServerSentEvent, None]:
                try:
                    while True:
                        queue_get: asyncio.Task[str] = asyncio.create_task(stream_queue.get())
                        done, _ = await asyncio.wait(
                            {queue_get, dispatch_task},
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        if queue_get in done:
                            yield ServerSentEvent(event="message", data=queue_get.result())
                            continue
                        queue_get.cancel()
                        # Dispatch finished — drain any remaining notifications
                        # then emit the final response.
                        while not stream_queue.empty():
                            yield ServerSentEvent(event="message", data=stream_queue.get_nowait())
                        yield ServerSentEvent(event="message", data=dispatch_task.result())
                        break
                except asyncio.CancelledError:
                    dispatch_task.cancel()
                    raise

            return EventStream(_generator())

        # --------------------------------------------------------------
        # GET — optional server-push channel
        # --------------------------------------------------------------

        @get("/")
        async def handle_get(self, request: Request) -> Response | EventStream:
            if not _accepts_sse(request):
                return _json_response(
                    json.dumps({"error": "GET requires 'Accept: text/event-stream'"}),
                    status=405,
                )
            session = self._require_session(request)
            if isinstance(session, Response):
                return session

            queue = session.push_queue

            async def _push(raw: str) -> None:
                await queue.put(raw)

            registry_key = self._registry.register(_push)

            async def _generator() -> AsyncGenerator[ServerSentEvent, None]:
                try:
                    while True:
                        payload = await queue.get()
                        if payload is None:
                            break
                        yield ServerSentEvent(event="message", data=payload)
                finally:
                    self._registry.unregister(registry_key)

            return EventStream(_generator())

        # --------------------------------------------------------------
        # DELETE — explicit session teardown
        # --------------------------------------------------------------

        @delete("/")
        async def handle_delete(self, request: Request) -> Response:
            session_id = request.headers.get(_SESSION_HEADER)
            if not session_id:
                return _json_response(
                    json.dumps({"error": f"Missing '{_SESSION_HEADER}' header"}), status=400
                )
            self._sessions.remove(session_id)
            return Response(body=b"", status=204)

    McpStreamableController.__name__ = "McpStreamableController"
    McpStreamableController.__qualname__ = (
        f"mcp_streamable_http_controller.<locals>.McpStreamableController[{base_path}]"
    )

    if source is not None:
        _apply_server_metadata(source, McpStreamableController)

    return McpStreamableController
