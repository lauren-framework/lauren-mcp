"""MCP client over Streamable HTTP transport (MCP 2025-03-26)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from lauren_mcp._types import Implementation

from ._base_remote import _McpBaseRemoteClient
from ._stdio import McpCallError

_logger = logging.getLogger(__name__)

try:
    import httpx

    _HTTPX_AVAILABLE = True
except ImportError:
    _HTTPX_AVAILABLE = False

_SESSION_HEADER = "mcp-session-id"
_PROTOCOL_HEADER = "mcp-protocol-version"


class McpStreamableHttpClient(_McpBaseRemoteClient):
    """MCP client speaking the 2025-03-26 Streamable HTTP transport.

    All messages POST to the single MCP endpoint.  Responses arrive either
    as direct ``application/json`` bodies or as ``text/event-stream`` bodies
    (when the server streams notifications before the final response).  A
    background GET stream is opened after the handshake to receive
    server-push notifications.

    Requires ``httpx``::

        pip install 'lauren-mcp[sse]'
    """

    def __init__(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        max_retries: int = 3,
        startup_timeout: float = 10.0,
        client_info: Implementation | None = None,
        **feature_kwargs: Any,
    ) -> None:
        if not _HTTPX_AVAILABLE:
            raise ImportError(
                "Install lauren-mcp[sse] to use Streamable HTTP MCP transport: "
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
        self._session_id: str | None = None
        self._http_client: httpx.AsyncClient | None = None
        self._push_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Open the transport and complete the MCP handshake."""
        await self._start_connection()
        await self._handshake()
        # Open the optional server-push channel once a session exists.
        if self._session_id is not None:
            self._push_task = asyncio.create_task(self._push_loop())

    async def close(self) -> None:
        """Terminate the session and close the HTTP client."""
        self._fail_all_pending("Client closed")
        await self._close_connection()

    # ------------------------------------------------------------------
    # Transport hooks
    # ------------------------------------------------------------------

    async def _start_connection(self) -> None:
        self._http_client = httpx.AsyncClient(headers={**self._headers}, timeout=None)
        self._session_id = None

    async def _close_connection(self) -> None:
        if self._push_task and not self._push_task.done():
            self._push_task.cancel()
            try:  # noqa: SIM105
                await self._push_task
            except (asyncio.CancelledError, Exception):
                pass
            self._push_task = None

        if self._http_client is not None:
            if self._session_id is not None:
                try:  # noqa: SIM105
                    await self._http_client.delete(
                        f"{self._url}/", headers={_SESSION_HEADER: self._session_id}
                    )
                except Exception:
                    pass
            try:  # noqa: SIM105
                await self._http_client.aclose()
            except Exception:
                pass
            self._http_client = None

        self._session_id = None

    async def _send_raw(self, obj: dict[str, Any]) -> None:
        """POST *obj*; responses in the reply body are dispatched inline."""
        if self._http_client is None:
            raise McpCallError("HTTP client not connected", code=-32000)

        headers: dict[str, str] = {
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
        }
        if self._session_id is not None:
            headers[_SESSION_HEADER] = self._session_id
        headers[_PROTOCOL_HEADER] = self._requested_protocol_version

        is_initialize = obj.get("method") == "initialize"

        try:
            resp = await self._http_client.post(
                f"{self._url}/", content=json.dumps(obj).encode(), headers=headers
            )
        except Exception as exc:
            raise McpCallError(f"HTTP send failed: {exc}", code=-32000) from exc

        if is_initialize:
            session_id = resp.headers.get(_SESSION_HEADER)
            if session_id:
                self._session_id = session_id

        if resp.status_code in (202, 204):
            return
        if resp.status_code >= 400:
            raise McpCallError(f"HTTP {resp.status_code}: {resp.text[:200]}", code=-32000)

        content_type = resp.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            for data in _iter_sse_data(resp.text):
                if data.strip():
                    self._dispatch_message(data)
        elif resp.text.strip():
            self._dispatch_message(resp.text)

    # ------------------------------------------------------------------
    # Server-push channel
    # ------------------------------------------------------------------

    async def _push_loop(self) -> None:
        """Long-lived GET stream delivering server-push messages."""
        client = self._http_client
        if client is None or self._session_id is None:
            return
        try:
            async with client.stream(
                "GET",
                f"{self._url}/",
                headers={
                    "accept": "text/event-stream",
                    _SESSION_HEADER: self._session_id,
                },
            ) as resp:
                if resp.status_code != 200:
                    _logger.debug(
                        "MCP streamable client: push channel unavailable (%d)",
                        resp.status_code,
                    )
                    return
                buffer = ""
                async for chunk in resp.aiter_text():
                    buffer += chunk
                    while "\n\n" in buffer:
                        event, buffer = buffer.split("\n\n", 1)
                        for data in _iter_sse_data(event + "\n\n"):
                            if data.strip():
                                self._dispatch_message(data)
        except asyncio.CancelledError:
            raise
        except Exception:
            _logger.exception("MCP streamable client: push channel error")


def _iter_sse_data(text: str) -> list[str]:
    """Extract the ``data:`` payloads from a raw SSE body."""
    payloads: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith("data:"):
            current.append(line[5:].lstrip())
        elif not line.strip() and current:
            payloads.append("\n".join(current))
            current = []
    if current:
        payloads.append("\n".join(current))
    return payloads
