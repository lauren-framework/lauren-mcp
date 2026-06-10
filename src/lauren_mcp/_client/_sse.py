"""MCP client over HTTP + Server-Sent Events (SSE) transport."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from lauren_mcp._types import Implementation

from ._base_remote import _McpBaseRemoteClient
from ._stdio import McpCallError

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional dependency guard
# ---------------------------------------------------------------------------
try:
    import httpx
    import httpx_sse

    _SSE_AVAILABLE = True
except ImportError:
    _SSE_AVAILABLE = False

_SESSION_HEADER = "mcp-session-id"


class McpHttpSseClient(_McpBaseRemoteClient):
    """MCP client that communicates via HTTP POST + Server-Sent Events.

    The client:

    1. Opens ``GET {url}/sse`` — an infinite SSE stream.
    2. Reads the first ``endpoint`` event to discover its ``session_id``.
    3. Uses ``POST {url}/`` with the ``mcp-session-id`` header for all
       outbound JSON-RPC messages.
    4. Receives JSON-RPC responses as ``message`` SSE events.

    Requires ``httpx`` and ``httpx-sse``::

        pip install 'lauren-mcp[sse]'

    Parameters
    ----------
    url:
        Base URL of the MCP HTTP+SSE server, e.g.
        ``"http://localhost:8000/mcp"``.
    headers:
        Optional extra HTTP headers included in every request.
    max_retries:
        Reconnect attempts after an unexpected SSE stream close.
    startup_timeout:
        Seconds to wait for the ``initialize`` response.
    """

    def __init__(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        auth: Any = None,
        max_retries: int = 3,
        startup_timeout: float = 10.0,
        client_info: Implementation | None = None,
        **feature_kwargs: Any,
    ) -> None:
        if not _SSE_AVAILABLE:
            raise ImportError(
                "Install lauren-mcp[sse] to use HTTP+SSE MCP transport: "
                "pip install 'lauren-mcp[sse]'"
            )
        super().__init__(
            client_info=client_info,
            headers=headers,
            max_retries=max_retries,
            startup_timeout=startup_timeout,
            **feature_kwargs,
        )
        self._url = url.rstrip("/")
        self._auth = auth
        self._session_id: str | None = None
        self._http_client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Open the SSE stream and complete the MCP handshake."""
        await self._start_connection()
        await self._handshake()

    async def close(self) -> None:
        """Terminate the SSE stream and close the HTTP client."""
        self._fail_all_pending("Client closed")
        await self._close_connection()

    # ------------------------------------------------------------------
    # Transport hooks
    # ------------------------------------------------------------------

    async def _start_connection(self) -> None:
        """Create the httpx client and start the SSE reader loop."""
        self._http_client = httpx.AsyncClient(
            headers={**self._headers},
            auth=self._auth,
            timeout=None,  # SSE streams are long-lived
        )
        self._session_id = None

        # Signal used to unblock _handshake until session_id is known
        session_ready: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._reader_task = asyncio.create_task(self._sse_loop(session_ready))

        # Wait until the SSE endpoint event delivers the session_id
        try:
            await asyncio.wait_for(
                asyncio.shield(session_ready),
                timeout=self._startup_timeout,
            )
        except TimeoutError:
            raise McpCallError("Timed out waiting for SSE endpoint event", code=-32000) from None

    async def _close_connection(self) -> None:
        """Cancel the SSE reader task and close the HTTP client."""
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:  # noqa: SIM105
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reader_task = None

        if self._http_client is not None:
            try:  # noqa: SIM105
                await self._http_client.aclose()
            except Exception:
                pass
            self._http_client = None

        self._session_id = None

    async def _send_raw(self, obj: dict[str, Any]) -> None:
        """POST a JSON-RPC message to ``{url}/`` with the session-id header."""
        if self._http_client is None:
            raise McpCallError("HTTP client not connected", code=-32000)
        if self._session_id is None:
            raise McpCallError("SSE session not yet established", code=-32000)
        body = json.dumps(obj)
        try:
            resp = await self._http_client.post(
                f"{self._url}/",
                content=body.encode(),
                headers={
                    "content-type": "application/json",
                    _SESSION_HEADER: self._session_id,
                },
            )
            if resp.status_code not in (200, 202):
                _logger.warning(
                    "MCP SSE client: POST returned unexpected status %d",
                    resp.status_code,
                )
        except Exception as exc:
            raise McpCallError(f"HTTP send failed: {exc}", code=-32000) from exc

    # ------------------------------------------------------------------
    # SSE reader loop
    # ------------------------------------------------------------------

    async def _sse_loop(self, session_ready: asyncio.Future[str]) -> None:
        """Connect to ``{url}/sse``, extract the session_id, then relay messages.

        The first SSE event must be of type ``endpoint`` and contain a JSON
        payload with a ``session_id`` key.  Subsequent ``message`` events are
        dispatched via :meth:`_dispatch_message`.
        """
        client = self._http_client
        if client is None:
            return
        try:
            async with httpx_sse.aconnect_sse(
                client,
                "GET",
                f"{self._url}/sse",
            ) as event_source:
                async for event in event_source.aiter_sse():
                    if event.event == "endpoint":
                        # Extract session_id from the payload
                        try:
                            data = json.loads(event.data)
                            self._session_id = data.get("session_id") or data.get("sessionId")
                        except (json.JSONDecodeError, AttributeError):
                            # Fallback: treat raw data as session_id string
                            self._session_id = event.data.strip()
                        if not session_ready.done():
                            session_ready.set_result(self._session_id)
                        continue

                    if event.event == "message":
                        raw = event.data
                        if raw.strip():
                            self._dispatch_message(raw)
                        continue

                    _logger.debug("MCP SSE client: unhandled event type=%r", event.event)

        except asyncio.CancelledError:
            raise
        except Exception:
            _logger.exception("MCP SSE client: error in SSE loop")

        # SSE stream closed unexpectedly
        if not session_ready.done():
            session_ready.set_exception(
                McpCallError("SSE stream closed before endpoint event", code=-32000)
            )
        self._fail_all_pending("SSE stream closed unexpectedly")

        # Retry logic
        if self._retry_count < self._max_retries:
            self._retry_count += 1
            _logger.warning(
                "MCP SSE client: stream closed — retrying (%d/%d)",
                self._retry_count,
                self._max_retries,
            )
            try:
                await self._start_connection()
                await self._handshake()
            except Exception:
                _logger.exception("MCP SSE client: reconnect attempt failed")
        else:
            _logger.error(
                "MCP SSE client: stream closed and max retries (%d) exceeded",
                self._max_retries,
            )
