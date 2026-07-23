"""Newline-delimited JSON-RPC server for local MCP subprocesses.

The HTTP transports are exposed through Lauren controllers, while stdio is a
small process-level gateway.  Keeping the gateway here lets the CLI launch any
``@mcp_server`` class through the same Lauren module and handler registration
path as the network transports.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from lauren_mcp._server._dispatcher import McpDispatcher
from lauren_mcp._types import (
    JsonRpcNotification,
    JsonRpcRequest,
    McpErrorCode,
    build_error_response,
    parse_message,
)


async def run_stdio_server(app: Any) -> None:
    """Serve *app* over stdin/stdout until the client closes stdin.

    MCP stdio messages are one JSON-RPC object per line.  Notifications are
    handled without writing a response, as required by JSON-RPC 2.0.  Server
    output is written only to stdout as protocol messages; application logs
    should use stderr.
    """

    await app.startup()
    dispatcher: McpDispatcher = await app.container.resolve(McpDispatcher)

    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    loop = asyncio.get_running_loop()
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)

    try:
        while True:
            line = await reader.readline()
            if not line:
                break
            if not line.strip():
                continue

            try:
                message = parse_message(line)
            except Exception as exc:  # noqa: BLE001
                parse_error = build_error_response(
                    id=None,
                    code=McpErrorCode.PARSE_ERROR,
                    message=f"Parse error: {exc}",
                )
                _write_message(parse_error.to_json())
                continue

            if isinstance(message, JsonRpcRequest):
                response = await dispatcher.dispatch(message)
                _write_message(response.to_json())
            elif isinstance(message, JsonRpcNotification):
                await _handle_notification(dispatcher, message)
            # Responses are client-side messages and are not expected on the
            # server stdin; ignore them rather than echoing them back.
    finally:
        await app.shutdown()


async def _handle_notification(dispatcher: McpDispatcher, message: JsonRpcNotification) -> None:
    """Handle the stdio notifications that affect dispatcher state."""

    if message.method != "$/cancelRequest":
        return
    params = message.params if isinstance(message.params, dict) else {}
    request_id = params.get("requestId")
    if isinstance(request_id, (str, int)):
        dispatcher.cancel(request_id)


def _write_message(raw: str) -> None:
    """Write one protocol message without allowing stdout buffering."""

    sys.stdout.write(json.dumps(json.loads(raw), separators=(",", ":")) + "\n")
    sys.stdout.flush()
