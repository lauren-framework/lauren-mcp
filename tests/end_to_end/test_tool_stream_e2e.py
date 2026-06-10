"""End-to-end tests for ToolStream over stdio transport.

A subprocess MCP server returns ToolStream from a tool; the client captures
progress notifications via on_progress and verifies the final call_tool result.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any

import pytest

from lauren_mcp import McpServer
from lauren_mcp._client._stdio import McpStdioClient

pytestmark = pytest.mark.asyncio

# The worktree src directory — subprocess must pick up the modified source.
_WORKTREE_SRC = str(Path(__file__).parent.parent.parent / "src")

# ---------------------------------------------------------------------------
# Subprocess server script
# ---------------------------------------------------------------------------
# Single-quoted docstrings to avoid terminating the outer triple-quoted string.

_STREAM_SERVER_SCRIPT = textwrap.dedent("""\
    import sys
    sys.path.insert(0, {worktree_src!r})
    import json, asyncio

    from lauren_mcp.server._decorators import mcp_server, mcp_tool
    from lauren_mcp.server._meta import MCP_TOOL_META
    from lauren_mcp.server._handlers import (
        make_tools_list_handler,
        make_tools_call_handler,
        make_context_factory,
    )
    from lauren_mcp._server._dispatcher import McpDispatcher
    from lauren_mcp._server._binding import CURRENT_BINDING, TransportBinding
    from lauren_mcp._types import JsonRpcRequest, ToolStream


    @mcp_server('/mcp')
    class StreamServer:
        @mcp_tool()
        async def count(self, n: int) -> ToolStream:
            'Count to n, yielding each number as a string.'
            async def gen():
                for i in range(n):
                    yield str(i)
            return ToolStream(gen(), total=n)

        @mcp_tool()
        async def words(self, text: str) -> ToolStream:
            'Split text into words and stream them.'
            async def gen():
                for w in text.split():
                    yield w
            return ToolStream(gen())


    async def main():
        async def send_notification(payload):
            print(json.dumps(payload), flush=True)

        binding = TransportBinding(send_notification=send_notification)
        dispatcher = McpDispatcher()
        dispatcher._register_builtins()
        server = StreamServer()

        tools = []
        for attr_name in dir(StreamServer):
            try:
                attr = getattr(StreamServer, attr_name)
            except AttributeError:
                continue
            if hasattr(attr, MCP_TOOL_META):
                tools.append(getattr(attr, MCP_TOOL_META))

        ctx_factory = make_context_factory()

        async def _init(params):
            return {{
                'protocolVersion': '2025-03-26',
                'capabilities': {{'tools': {{}}}},
                'serverInfo': {{'name': 'stream-server', 'version': '1.0.0'}},
            }}
        dispatcher.register('initialize', _init)

        tl = make_tools_list_handler(tools)
        tc = make_tools_call_handler(server, tools, context_factory=ctx_factory)

        async def _tl(p):
            return await tl(JsonRpcRequest(method='tools/list', params=p))

        async def _tc(p):
            return await tc(JsonRpcRequest(
                method='tools/call', id=p.get('_req_id'), params=p
            ))

        dispatcher.register('tools/list', _tl)
        dispatcher.register('tools/call', _tc)

        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        token = CURRENT_BINDING.set(binding)
        try:
            while True:
                try:
                    line = await asyncio.wait_for(reader.readline(), timeout=30.0)
                except asyncio.TimeoutError:
                    break
                if not line:
                    break
                raw = line.decode().strip()
                if not raw:
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                method = msg.get('method', '')
                id_ = msg.get('id')
                if id_ is None:
                    continue   # notification from client, ignore
                params = msg.get('params') or {{}}
                if isinstance(params, dict):
                    params['_req_id'] = id_
                req = JsonRpcRequest(method=method, id=id_, params=params)
                resp = await dispatcher.dispatch(req)
                print(resp.to_json(), flush=True)
        finally:
            CURRENT_BINDING.reset(token)


    asyncio.run(main())
""").format(worktree_src=_WORKTREE_SRC)


@pytest.fixture
def stream_server_command():
    """Write the server script to a temp file and return the argv."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(_STREAM_SERVER_SCRIPT)
        fname = f.name
    yield [sys.executable, fname]
    os.unlink(fname)


@pytest.fixture
async def stream_client(stream_server_command):
    """Connected McpStdioClient backed by StreamServer subprocess."""
    progress_chunks: list[dict[str, Any]] = []

    def on_progress(params: dict[str, Any]) -> None:
        progress_chunks.append(params)

    client: McpStdioClient = McpServer.stdio(
        stream_server_command,
        max_retries=0,
        progress_handler=on_progress,
    )
    await asyncio.wait_for(client.connect(), timeout=10.0)
    client._test_progress_chunks = progress_chunks  # type: ignore[attr-defined]
    yield client
    await client.close()


# ---------------------------------------------------------------------------
# Helper: call tool with optional progressToken via raw _request
# ---------------------------------------------------------------------------


async def _call_with_token(
    client: McpStdioClient, name: str, arguments: dict[str, Any], token: str | None = None
) -> Any:
    """Send tools/call with optional progressToken in _meta."""
    params: dict[str, Any] = {"name": name, "arguments": arguments}
    if token is not None:
        params["_meta"] = {"progressToken": token}
    return await client._request("tools/call", params)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStdioToolStreamProgress:
    async def test_count_n_notifications(self, stream_client: McpStdioClient) -> None:
        """count(3) with progressToken → 3 progress notifications."""
        chunks: list = stream_client._test_progress_chunks  # type: ignore[attr-defined]
        chunks.clear()

        await _call_with_token(stream_client, "count", {"n": 3}, token="tok")
        assert len(chunks) == 3

    async def test_chunks_in_order(self, stream_client: McpStdioClient) -> None:
        """Progress chunks arrive in generation order (0, 1, 2)."""
        chunks: list = stream_client._test_progress_chunks  # type: ignore[attr-defined]
        chunks.clear()

        await _call_with_token(stream_client, "count", {"n": 3}, token="tok")
        messages = [json.loads(c["message"]) for c in chunks]
        assert messages == ["0", "1", "2"]

    async def test_final_result_joined_string(self, stream_client: McpStdioClient) -> None:
        """call_tool result is accumulated string from all chunks."""
        chunks: list = stream_client._test_progress_chunks  # type: ignore[attr-defined]
        chunks.clear()

        result = await _call_with_token(stream_client, "count", {"n": 4}, token="tok")
        assert result["content"][0]["text"] == "0123"

    async def test_total_in_notifications(self, stream_client: McpStdioClient) -> None:
        """Each notification has total matching ToolStream(total=n)."""
        chunks: list = stream_client._test_progress_chunks  # type: ignore[attr-defined]
        chunks.clear()

        await _call_with_token(stream_client, "count", {"n": 3}, token="tok")
        for chunk in chunks:
            assert chunk.get("total") == 3

    async def test_without_progress_token_zero_notifications(
        self, stream_client: McpStdioClient
    ) -> None:
        """Calling without progressToken → zero notifications, correct result."""
        chunks: list = stream_client._test_progress_chunks  # type: ignore[attr-defined]
        chunks.clear()

        result = await _call_with_token(stream_client, "count", {"n": 3}, token=None)
        # No notifications because no progressToken
        assert chunks == []
        # But result is still correct
        assert result["content"][0]["text"] == "012"

    async def test_words_tool_stream(self, stream_client: McpStdioClient) -> None:
        """Words tool: str chunks joined by default."""
        chunks: list = stream_client._test_progress_chunks  # type: ignore[attr-defined]
        chunks.clear()

        result = await _call_with_token(
            stream_client, "words", {"text": "hello world foo"}, token="tok"
        )
        # 3 chunks: "hello", "world", "foo" → joined "helloworldfoo"
        assert len(chunks) == 3
        assert result["content"][0]["text"] == "helloworldfoo"
