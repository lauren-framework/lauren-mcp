"""End-to-end tests for new client features (set_logging_level, complete,
subscribe_resource, unsubscribe_resource) using a subprocess MCP server.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile

import pytest

from lauren_mcp import McpServer

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Subprocess server script — simple sync server that responds to all new methods
# ---------------------------------------------------------------------------

_SERVER_SCRIPT = """
import sys, json

def respond(id_, result):
    print(json.dumps({"jsonrpc": "2.0", "id": id_, "result": result}), flush=True)

def error(id_, code, msg):
    print(json.dumps({"jsonrpc": "2.0", "id": id_,
                      "error": {"code": code, "message": msg}}), flush=True)

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except Exception:
        continue
    method = msg.get("method")
    id_ = msg.get("id")
    params = msg.get("params") or {}
    if method == "initialize":
        respond(id_, {
            "protocolVersion": "2025-03-26",
            "capabilities": {"tools": {}, "prompts": {}},
            "serverInfo": {"name": "e2e-srv", "version": "1.0.0"},
        })
    elif method == "notifications/initialized":
        pass
    elif method == "ping":
        respond(id_, {})
    elif method == "logging/setLevel":
        respond(id_, {})
    elif method == "tools/list":
        respond(id_, {"tools": [
            {"name": "greet", "description": "Greet someone.",
             "inputSchema": {"type": "object",
                             "properties": {"name": {"type": "string"}},
                             "required": ["name"]}}
        ]})
    elif method == "tools/call":
        args = params.get("arguments", {})
        name = args.get("name", "World")
        respond(id_, {"content": [{"type": "text", "text": f"Hello, {name}!"}],
                      "isError": False})
    elif method == "prompts/list":
        respond(id_, {"prompts": [
            {"name": "greeting_prompt", "description": "Greeting prompt."}
        ]})
    elif method == "prompts/get":
        respond(id_, {"messages": [{"role": "user",
                                    "content": {"type": "text", "text": "Say hi."}}]})
    elif method == "completion/complete":
        respond(id_, {"completion": {"values": ["Alice", "Bob"], "hasMore": False}})
    elif method == "resources/subscribe":
        respond(id_, {})
    elif method == "resources/unsubscribe":
        respond(id_, {})
    elif method == "resources/list":
        respond(id_, {"resources": []})
    elif id_ is not None:
        error(id_, -32601, f"Method not found: {method}")
    sys.stdout.flush()
"""


@pytest.fixture
def server_command():
    """Return argv for the e2e server subprocess."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(_SERVER_SCRIPT)
        fname = f.name
    yield [sys.executable, fname]
    os.unlink(fname)


# ---------------------------------------------------------------------------
# Tests: set_logging_level
# ---------------------------------------------------------------------------


class TestSetLoggingLevelE2e:
    async def test_set_logging_level_warning_then_ping(self, server_command):
        """Client calls set_logging_level('warning') then ping without error."""
        client = McpServer.stdio(server_command, max_retries=0)
        try:
            await asyncio.wait_for(client.connect(), timeout=10.0)
            await client.set_logging_level("warning")
            await client.ping()
        finally:
            await client.close()

    async def test_set_logging_level_all_common_levels(self, server_command):
        """All standard levels succeed against the server."""
        client = McpServer.stdio(server_command, max_retries=0)
        try:
            await asyncio.wait_for(client.connect(), timeout=10.0)
            for level in ("debug", "info", "warning", "error"):
                await client.set_logging_level(level)
        finally:
            await client.close()

    async def test_set_logging_level_invalid_raises_locally(self):
        """Invalid log level raises ValueError without spawning subprocess."""
        client = McpServer.stdio([sys.executable, "-c", ""], max_retries=0)
        with pytest.raises(ValueError, match="Invalid log level"):
            await client.set_logging_level("notavalidlevel")


# ---------------------------------------------------------------------------
# Tests: complete()
# ---------------------------------------------------------------------------


class TestCompleteE2e:
    async def test_complete_returns_values(self, server_command):
        """Client calls complete() and receives completion values."""
        client = McpServer.stdio(server_command, max_retries=0)
        try:
            await asyncio.wait_for(client.connect(), timeout=10.0)
            result = await client.complete(
                ref={"type": "ref/prompt", "name": "greeting_prompt"},
                argument={"name": "name", "value": "Al"},
            )
            assert isinstance(result, dict)
            assert "completion" in result
            values = result["completion"]["values"]
            assert "Alice" in values
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# Tests: subscribe_resource / unsubscribe_resource
# ---------------------------------------------------------------------------


class TestSubscribeResourceE2e:
    async def test_subscribe_unsubscribe_no_crash(self, server_command):
        """subscribe_resource / unsubscribe_resource succeed against the server."""
        client = McpServer.stdio(server_command, max_retries=0)
        try:
            await asyncio.wait_for(client.connect(), timeout=10.0)
            await client.subscribe_resource("items://1")
            await client.unsubscribe_resource("items://1")
        finally:
            await client.close()

    async def test_resource_updated_handler_receives_notification(self, server_command):
        """on_resource_updated handler fires when a notification is delivered."""
        received: list[str] = []
        client = McpServer.stdio(
            server_command,
            max_retries=0,
            resource_updated_handler=received.append,
        )
        try:
            await asyncio.wait_for(client.connect(), timeout=10.0)
            # Inject a fake notification by dispatching directly (server can't push over stdio)
            from lauren_mcp._types import JsonRpcNotification

            client._dispatch(  # type: ignore[attr-defined]
                JsonRpcNotification(
                    method="notifications/resources/updated",
                    params={"uri": "items://1"},
                )
            )
            assert received == ["items://1"]
        finally:
            await client.close()
