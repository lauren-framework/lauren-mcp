"""MCP client over stdio (subprocess) transport."""
from __future__ import annotations

import asyncio
import json
import logging
import signal
from asyncio.subprocess import DEVNULL, PIPE
from typing import Any, Callable

from lauren_mcp._types import (
    Implementation,
    JsonRpcErrorResponse,
    JsonRpcNotification,
    JsonRpcRequest,
    JsonRpcResponse,
    PromptSchema,
    ResourceSchema,
    ToolSchema,
    parse_message,
)
from ._protocol import McpClientProtocol

_logger = logging.getLogger(__name__)


class McpCallError(Exception):
    """Raised when the MCP server returns a JSON-RPC error response."""

    def __init__(self, message: str, code: int = -32000) -> None:
        super().__init__(message)
        self.code = code


class McpStdioClient(McpClientProtocol):
    """MCP client that communicates with a subprocess over stdin/stdout.

    Each JSON-RPC message is a single newline-terminated JSON line.
    The subprocess is started fresh on :meth:`connect`; on :meth:`close`
    it receives SIGTERM followed (after 3 s) by SIGKILL if it has not
    already exited.

    Parameters
    ----------
    command:
        Sequence of strings forming the subprocess command, e.g.
        ``["python", "-m", "my_mcp_server"]``.
    client_info:
        Optional :class:`~lauren_mcp._types.Implementation` describing
        this client sent in the ``initialize`` handshake.
    max_retries:
        How many times to restart the subprocess after EOF before giving
        up.  Defaults to ``3``.
    startup_timeout:
        Seconds to wait for the ``initialize`` response before raising
        ``asyncio.TimeoutError``.  Defaults to ``10.0``.
    """

    def __init__(
        self,
        command: list[str] | tuple[str, ...],
        *,
        client_info: Implementation | None = None,
        max_retries: int = 3,
        startup_timeout: float = 10.0,
    ) -> None:
        self._command = command
        self._client_info = client_info or Implementation(
            name="lauren-mcp-stdio-client", version="1.0.0"
        )
        self._max_retries = max_retries
        self._startup_timeout = startup_timeout

        # Internal state (reset by _start_process)
        self._proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._pending: dict[int, asyncio.Future] = {}
        self._notification_listeners: list[Callable[[JsonRpcNotification], None]] = []
        self._next_id: int = 0
        self._initialized: bool = False
        self._retry_count: int = 0

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Start the subprocess and complete the MCP initialize handshake."""
        await self._start_process()
        await self._handshake()

    async def close(self) -> None:
        """Terminate the subprocess and cancel the reader task."""
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass
            self._reader_task = None

        proc = self._proc
        if proc is not None and proc.returncode is None:
            try:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=3.0)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
            except ProcessLookupError:
                pass
        self._proc = None
        self._initialized = False

        # Fail any lingering pending futures
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(McpCallError("Client closed", code=-32000))
        self._pending.clear()

    # ------------------------------------------------------------------
    # Internal: process management
    # ------------------------------------------------------------------

    async def _start_process(self) -> None:
        """Launch the subprocess and start the background reader task."""
        self._proc = await asyncio.create_subprocess_exec(
            *self._command,
            stdin=PIPE,
            stdout=PIPE,
            stderr=DEVNULL,
        )
        self._pending = {}
        self._next_id = 0
        self._initialized = False
        self._reader_task = asyncio.create_task(self._read_loop())

    # ------------------------------------------------------------------
    # Internal: handshake
    # ------------------------------------------------------------------

    async def _handshake(self) -> None:
        """Send ``initialize`` and await the response, then confirm with notification."""
        result = await asyncio.wait_for(
            self._request(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": self._client_info.name,
                        "version": self._client_info.version,
                    },
                },
            ),
            timeout=self._startup_timeout,
        )
        _logger.debug("MCP stdio handshake complete: %s", result)
        self._initialized = True
        # Send the initialized notification (no response expected)
        await self._send_raw(
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            }
        )

    # ------------------------------------------------------------------
    # Internal: request / send / read loop
    # ------------------------------------------------------------------

    async def _request(self, method: str, params: Any = None) -> Any:
        """Send a JSON-RPC request and await its response future."""
        loop = asyncio.get_running_loop()
        req_id = self._next_id
        self._next_id += 1
        fut: asyncio.Future = loop.create_future()
        self._pending[req_id] = fut
        await self._send_raw(
            {
                "jsonrpc": "2.0",
                "method": method,
                "id": req_id,
                **({"params": params} if params is not None else {}),
            }
        )
        return await fut

    async def _send_raw(self, obj: dict) -> None:
        """Encode *obj* as JSON + newline and write it to the process stdin."""
        if self._proc is None or self._proc.stdin is None:
            raise McpCallError("Not connected", code=-32000)
        line = json.dumps(obj) + "\n"
        self._proc.stdin.write(line.encode())
        await self._proc.stdin.drain()

    async def _read_loop(self) -> None:
        """Read newline-delimited JSON from stdout and dispatch messages."""
        proc = self._proc
        if proc is None or proc.stdout is None:
            return

        try:
            while True:
                line_bytes = await proc.stdout.readline()
                if not line_bytes:
                    # EOF — process exited or closed stdout
                    break
                raw = line_bytes.decode("utf-8", errors="replace").strip()
                if not raw:
                    continue
                try:
                    msg = parse_message(raw)
                except Exception as exc:
                    _logger.warning("MCP stdio: parse error — %s", exc)
                    continue
                self._dispatch(msg)
        except asyncio.CancelledError:
            raise
        except Exception:
            _logger.exception("MCP stdio: unexpected error in read loop")

        # EOF reached — fail all pending futures
        _error = McpCallError("Subprocess exited unexpectedly", code=-32000)
        for fut in list(self._pending.values()):
            if not fut.done():
                fut.set_exception(_error)
        self._pending.clear()

        # Attempt reconnect if budget allows
        if self._retry_count < self._max_retries:
            self._retry_count += 1
            _logger.warning(
                "MCP stdio: subprocess EOF — retrying (%d/%d)",
                self._retry_count,
                self._max_retries,
            )
            try:
                await self._start_process()
                await self._handshake()
            except Exception:
                _logger.exception("MCP stdio: reconnect attempt failed")
        else:
            _logger.error(
                "MCP stdio: subprocess exited and max retries (%d) exceeded",
                self._max_retries,
            )

    def _dispatch(
        self,
        msg: JsonRpcRequest | JsonRpcNotification | JsonRpcResponse | JsonRpcErrorResponse,
    ) -> None:
        """Route a parsed message to the appropriate future or listener."""
        if isinstance(msg, JsonRpcResponse):
            fut = self._pending.pop(msg.id, None)  # type: ignore[arg-type]
            if fut is not None and not fut.done():
                fut.set_result(msg.result)
            return

        if isinstance(msg, JsonRpcErrorResponse):
            fut = self._pending.pop(msg.id, None)  # type: ignore[arg-type]
            if fut is not None and not fut.done():
                err = McpCallError(msg.error.message, code=msg.error.code)
                fut.set_exception(err)
            return

        if isinstance(msg, JsonRpcNotification):
            for listener in self._notification_listeners:
                try:
                    listener(msg)
                except Exception:
                    _logger.exception("MCP stdio: notification listener error")
            return

        # JsonRpcRequest from the server — not expected in normal usage
        _logger.debug("MCP stdio: received server-side request (ignored): %s", msg)

    # ------------------------------------------------------------------
    # McpClientProtocol implementation
    # ------------------------------------------------------------------

    async def list_tools(self) -> list[ToolSchema]:
        result = await self._request("tools/list")
        return [
            ToolSchema(
                name=t["name"],
                description=t.get("description", ""),
                inputSchema=t.get("inputSchema", {}),
            )
            for t in result.get("tools", [])
        ]

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        result = await self._request(
            "tools/call",
            {"name": name, "arguments": arguments or {}},
        )
        return result

    async def list_resources(self) -> list[ResourceSchema]:
        result = await self._request("resources/list")
        return [
            ResourceSchema(
                uri=r["uri"],
                name=r.get("name", r["uri"]),
                description=r.get("description"),
                mimeType=r.get("mimeType"),
            )
            for r in result.get("resources", [])
        ]

    async def read_resource(self, uri: str) -> Any:
        result = await self._request("resources/read", {"uri": uri})
        return result

    async def list_prompts(self) -> list[PromptSchema]:
        result = await self._request("prompts/list")
        return [
            PromptSchema(
                name=p["name"],
                description=p.get("description"),
            )
            for p in result.get("prompts", [])
        ]

    async def get_prompt(
        self,
        name: str,
        arguments: dict[str, str] | None = None,
    ) -> Any:
        result = await self._request(
            "prompts/get",
            {"name": name, "arguments": arguments or {}},
        )
        return result

    async def ping(self) -> None:
        await self._request("ping")
