"""MCP client over WebSocket transport."""

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
# Optional dependency guard — only evaluated at import time, never raises.
# Raising happens lazily in __init__ so the module can always be imported.
# ---------------------------------------------------------------------------
try:
    import websockets  # noqa: F401
    import websockets.asyncio.client as ws_client

    _WS_AVAILABLE = True
except ImportError:
    _WS_AVAILABLE = False


class McpWebSocketClient(_McpBaseRemoteClient):
    """MCP client that communicates with an MCP server over WebSocket.

    Requires the ``websockets`` package::

        pip install 'lauren-mcp[ws]'

    Parameters
    ----------
    url:
        Full WebSocket URL, e.g. ``"ws://localhost:8000/mcp/ws"``.
    headers:
        Optional extra HTTP headers sent during the WebSocket upgrade.
    max_retries:
        How many times to reconnect after an unexpected disconnect.
    startup_timeout:
        Seconds to wait for the ``initialize`` response.
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
        if not _WS_AVAILABLE:
            raise ImportError(
                "Install lauren-mcp[ws] to use WebSocket MCP transport: "
                "pip install 'lauren-mcp[ws]'"
            )
        super().__init__(
            client_info=client_info,
            headers=headers,
            max_retries=max_retries,
            startup_timeout=startup_timeout,
            **feature_kwargs,
        )
        self._url = url
        self._ws = None  # The live websockets connection object

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Open the WebSocket connection and complete the MCP handshake."""
        await self._start_connection()
        await self._handshake()

    async def close(self) -> None:
        """Close the WebSocket connection and cancel the reader task."""
        self._fail_all_pending("Client closed")
        await self._close_connection()

    # ------------------------------------------------------------------
    # Transport hooks
    # ------------------------------------------------------------------

    async def _start_connection(self) -> None:
        """Connect the WebSocket and start the background reader task."""
        extra_headers = list(self._headers.items()) if self._headers else None
        self._ws = await ws_client.connect(
            self._url,
            additional_headers=extra_headers,
        )
        self._reader_task = asyncio.create_task(self._read_loop())

    async def _close_connection(self) -> None:
        """Cancel the reader task and close the WebSocket."""
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:  # noqa: SIM105
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reader_task = None

        if self._ws is not None:
            try:  # noqa: SIM105
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def _send_raw(self, obj: dict[str, Any]) -> None:
        """Serialise *obj* to JSON and send it as a WebSocket text frame."""
        if self._ws is None:
            raise McpCallError("WebSocket not connected", code=-32000)
        await self._ws.send(json.dumps(obj))

    async def _read_loop(self) -> None:
        """Receive WebSocket text frames and dispatch them until disconnect."""
        ws = self._ws
        if ws is None:
            return
        try:
            async for message in ws:
                raw: str = (
                    message
                    if isinstance(message, str)
                    else message.decode("utf-8", errors="replace")
                )
                if raw.strip():
                    self._dispatch_message(raw)
        except asyncio.CancelledError:
            raise
        except Exception:
            _logger.exception("MCP WS client: error in read loop")

        # Connection dropped — fail pending futures
        self._fail_all_pending("WebSocket connection closed unexpectedly")

        # Retry logic
        if self._retry_count < self._max_retries:
            self._retry_count += 1
            _logger.warning(
                "MCP WS client: connection lost — retrying (%d/%d)",
                self._retry_count,
                self._max_retries,
            )
            try:
                await self._start_connection()
                await self._handshake()
            except Exception:
                _logger.exception("MCP WS client: reconnect attempt failed")
        else:
            _logger.error(
                "MCP WS client: connection lost and max retries (%d) exceeded",
                self._max_retries,
            )
