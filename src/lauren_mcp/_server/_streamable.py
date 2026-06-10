"""Streamable HTTP transport (MCP 2025-03-26) — single-endpoint controller."""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

from lauren import Scope, controller, delete, get, injectable, post, use_guards
from lauren.sse import EventStream, ServerSentEvent
from lauren.types import ExecutionContext, Headers, Request, Response

from lauren_mcp._server._binding import CURRENT_BINDING, TransportBinding
from lauren_mcp._server._dispatcher import McpDispatcher
from lauren_mcp._server._event_store import EventStore
from lauren_mcp._server._handshake import negotiate_version
from lauren_mcp._server._propagate import _apply_server_metadata
from lauren_mcp._server._registry import McpConnectionRegistry
from lauren_mcp._server._transport_security import (
    McpTransportSecurityGuard,
    TransportSecuritySettings,
)
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
    #: Counter for SSE event IDs on the GET push channel.
    next_event_id: int = 0


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
    stateless: bool = False,
    event_store: EventStore | None = None,
    transport_security: TransportSecuritySettings | None = None,
    oauth_settings: Any | None = None,
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

        When *stateless* is ``True`` no session is created or required.

    ``GET <base_path>/``
        Optional server-push channel: an SSE stream delivering server
        notifications and server-initiated requests for the session.
        Returns ``405`` when *stateless* is ``True``.

    ``DELETE <base_path>/``
        Explicit session teardown.  Returns ``405`` when *stateless* is
        ``True``.

    ``GET <base_path>/.well-known/oauth-authorization-server``
        OAuth 2.1 authorization server discovery (RFC 8414).  Only
        available when *oauth_settings* is provided and its
        ``authorization_server_metadata`` field is set.

    ``GET <base_path>/.well-known/oauth-protected-resource``
        OAuth 2.1 protected resource discovery (RFC 9728).  Only
        available when *oauth_settings* is provided and its
        ``protected_resource_metadata`` field is set.
    """
    # Capture OAuth metadata from settings for use in handlers
    _oauth_as_meta = (
        None if oauth_settings is None else oauth_settings.authorization_server_metadata
    )
    _oauth_pr_meta = None if oauth_settings is None else oauth_settings.protected_resource_metadata

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
        async def handle_post(
            self, request: Request, execution_context: ExecutionContext
        ) -> Response | EventStream:
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

            if stateless:
                return await self._handle_stateless(
                    request, msg, execution_context=execution_context
                )

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
                return await self._dispatch_request(
                    request, msg, session, execution_context=execution_context
                )

            err = build_error_response(None, McpErrorCode.INVALID_REQUEST, "Unsupported message")
            return _json_response(err.to_json(), status=400)

        async def _handle_stateless(
            self, request: Request, msg: Any, *, execution_context: ExecutionContext | None = None
        ) -> Response | EventStream:
            """Process a single JSON-RPC message with no session state."""

            # Notifications in stateless mode: accept and discard.
            if isinstance(msg, JsonRpcNotification):
                return Response(body=b"", status=202)

            # Client response frames in stateless mode: unexpected, discard.
            if isinstance(msg, (JsonRpcResponse, JsonRpcErrorResponse)):
                return Response(body=b"", status=202)

            if not isinstance(msg, JsonRpcRequest):
                err = build_error_response(
                    None, McpErrorCode.INVALID_REQUEST, "Unsupported message"
                )
                return _json_response(err.to_json(), status=400)

            # Build a per-request binding with a local queue for notifications.
            local_queue: asyncio.Queue[str] = asyncio.Queue()

            async def _send_notification(payload: dict[str, Any]) -> None:
                await local_queue.put(json.dumps(payload))

            async def _client_rpc_unavailable(method: str, params: dict[str, Any]) -> Any:
                raise RuntimeError(
                    "Stateless mode does not support server-to-client requests "
                    f"(attempted: {method!r})"
                )

            binding = TransportBinding(
                headers=request.headers,
                execution_context=execution_context or ExecutionContext(request=request),
                session_id=None,
                send_notification=_send_notification,
                client_rpc=_client_rpc_unavailable,
                client_capabilities=None,
            )

            if not _accepts_sse(request):
                # Plain JSON: dispatch, return response; notifications silently dropped
                # (no push channel in stateless mode).
                token = CURRENT_BINDING.set(binding)
                try:
                    response = await self._dispatcher.dispatch(msg)
                finally:
                    CURRENT_BINDING.reset(token)
                return _json_response(response.to_json())

            # SSE: buffer notifications and return them before the final response.
            async def _run() -> str:
                tok = CURRENT_BINDING.set(binding)
                try:
                    resp = await self._dispatcher.dispatch(msg)
                finally:
                    CURRENT_BINDING.reset(tok)
                return resp.to_json()

            dispatch_task: asyncio.Task[str] = asyncio.create_task(_run())

            async def _stateless_generator() -> AsyncGenerator[ServerSentEvent, None]:
                try:
                    while True:
                        queue_get: asyncio.Task[str] = asyncio.create_task(local_queue.get())
                        done, _ = await asyncio.wait(
                            {queue_get, dispatch_task},
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        if queue_get in done:
                            yield ServerSentEvent(event="message", data=queue_get.result())
                            continue
                        queue_get.cancel()
                        while not local_queue.empty():
                            yield ServerSentEvent(event="message", data=local_queue.get_nowait())
                        yield ServerSentEvent(event="message", data=dispatch_task.result())
                        break
                except asyncio.CancelledError:
                    dispatch_task.cancel()
                    raise

            return EventStream(_stateless_generator())

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
            *,
            execution_context: ExecutionContext | None = None,
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
                execution_context=execution_context or ExecutionContext(request=request),
                session_id=session.session_id,
                send_notification=_send_notification,
                client_rpc=_client_rpc,
                client_capabilities=session.client_capabilities,
            )

        async def _dispatch_request(
            self,
            request: Request,
            msg: JsonRpcRequest,
            session: StreamableSession,
            *,
            execution_context: ExecutionContext | None = None,
        ) -> Response | EventStream:
            if not _accepts_sse(request):
                # Plain JSON mode: in-flight notifications go to the GET
                # push channel (if open); the response is returned directly.
                binding = self._make_binding(
                    request, session, None, execution_context=execution_context
                )
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
            binding = self._make_binding(
                request, session, stream_queue, execution_context=execution_context
            )

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
            if stateless:
                return Response(
                    body=json.dumps({"error": "GET is not supported in stateless mode"}).encode(),
                    status=405,
                    headers=Headers([("content-type", "application/json"), ("allow", "POST")]),
                )

            if not _accepts_sse(request):
                return _json_response(
                    json.dumps({"error": "GET requires 'Accept: text/event-stream'"}),
                    status=405,
                )
            session = self._require_session(request)
            if isinstance(session, Response):
                return session

            last_event_id: str | None = request.headers.get("last-event-id")
            queue = session.push_queue

            async def _push(raw: str) -> None:
                await queue.put(raw)

            registry_key = self._registry.register(_push)

            async def _push_generator() -> AsyncGenerator[ServerSentEvent, None]:
                # Replay missed events first if event_store is configured
                if event_store is not None and last_event_id is not None:
                    replayed: list[tuple[str, str]] = []

                    async def _collect(eid: str, data: str) -> None:
                        replayed.append((eid, data))

                    await event_store.replay_events_after(
                        session.session_id, last_event_id, _collect
                    )
                    for eid, data in replayed:
                        yield ServerSentEvent(event="message", data=data, id=eid)

                # Normal queue-drain loop (with event ID assignment if event_store set)
                try:
                    while True:
                        payload = await queue.get()
                        if payload is None:
                            break
                        if event_store is not None:
                            eid = f"{session.session_id}:{session.next_event_id}"
                            session.next_event_id += 1
                            await event_store.store_event(session.session_id, eid, payload)
                            yield ServerSentEvent(event="message", data=payload, id=eid)
                        else:
                            yield ServerSentEvent(event="message", data=payload)
                finally:
                    self._registry.unregister(registry_key)
                    if event_store is not None:
                        pass  # session eviction handled by StreamableSessionStore.remove

            return EventStream(_push_generator())

        # --------------------------------------------------------------
        # DELETE — explicit session teardown
        # --------------------------------------------------------------

        @delete("/")
        async def handle_delete(self, request: Request) -> Response:
            if stateless:
                return Response(
                    body=json.dumps(
                        {"error": "DELETE is not supported in stateless mode"}
                    ).encode(),
                    status=405,
                    headers=Headers([("content-type", "application/json"), ("allow", "POST")]),
                )

            session_id = request.headers.get(_SESSION_HEADER)
            if not session_id:
                return _json_response(
                    json.dumps({"error": f"Missing '{_SESSION_HEADER}' header"}), status=400
                )
            self._sessions.remove(session_id)
            return Response(body=b"", status=204)

        # --------------------------------------------------------------
        # OAuth 2.1 discovery endpoints (unauthenticated)
        # These are only active when oauth_settings is provided.
        # --------------------------------------------------------------

        @get("/.well-known/oauth-authorization-server")
        async def oauth_authorization_server(self, request: Request) -> Response:
            if _oauth_as_meta is None:
                return Response(body=b"", status=404)
            body = json.dumps(_oauth_as_meta.to_dict()).encode()
            return Response(
                body=body,
                status=200,
                headers=Headers([("content-type", "application/json")]),
            )

        @get("/.well-known/oauth-protected-resource")
        async def oauth_protected_resource(self, request: Request) -> Response:
            if _oauth_pr_meta is None:
                return Response(body=b"", status=404)
            body = json.dumps(_oauth_pr_meta.to_dict()).encode()
            return Response(
                body=body,
                status=200,
                headers=Headers([("content-type", "application/json")]),
            )

    McpStreamableController.__name__ = "McpStreamableController"
    McpStreamableController.__qualname__ = (
        f"mcp_streamable_http_controller.<locals>.McpStreamableController[{base_path}]"
    )

    if source is not None:
        _apply_server_metadata(source, McpStreamableController)

    # Apply transport security guard if configured.
    if transport_security is not None:
        _guard = McpTransportSecurityGuard()
        _guard.configure(transport_security)
        _ts = transport_security

        class _BoundTransportSecurityGuard:
            async def can_activate(self, ctx: ExecutionContext) -> bool:
                return await _guard.can_activate(ctx)

        McpStreamableController = use_guards(_BoundTransportSecurityGuard)(McpStreamableController)  # type: ignore[misc]

    return McpStreamableController
