"""End-to-end tests: FieldDescriptor validation, pipe transformations, and
BackgroundTasks support through the full subprocess MCP server stack.

Architecture
============
Each test spins up a **real subprocess** MCP server via
``McpServer.stdio(["python", "-c", "..."], max_retries=0)`` and connects
with :class:`~lauren_mcp._client._stdio.McpStdioClient`.  The server script
inside the subprocess uses ``@mcp_server``, ``@mcp_tool``, and wires everything
through the real handler factories + McpDispatcher (the same path that
McpServerModule.for_root() uses in production).

Coverage
========
- Pipe-validated tool: ``list_tools()`` shows ``minimum`` in the schema;
  ``call_tool()`` with invalid input raises :class:`~lauren_mcp.McpCallError`
  with ``code == -32602``; valid input returns the correct result.
- Pipe-transformation tool: the server-side pipe doubles the value; the
  client receives the transformed result.
- BackgroundTasks tool: the tool returns a result; bg tasks run server-side
  and their side effects persist (the test cannot observe server-side state
  directly, but verifies that the tool result is correct and no error is
  returned).
- Multiple bg tasks: tool schedules two tasks and returns; the result text
  is as expected.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import textwrap

import pytest
import pytest_asyncio

from lauren_mcp import McpServer
from lauren_mcp._client._stdio import McpCallError, McpStdioClient

pytestmark = pytest.mark.asyncio(loop_scope="session")

# ---------------------------------------------------------------------------
# Subprocess server script — ValidSrv
# ---------------------------------------------------------------------------
# The script uses the same handler-factory wiring as McpServerModule.for_root()
# but bypasses Lauren DI so the subprocess starts faster and doesn't need
# container.resolve() / TestClient.
#
# Inner strings use single-quotes to avoid ending the outer triple-quoted
# string literal (CLAUDE.md convention).

_VALID_SERVER_SCRIPT = textwrap.dedent("""\
    import sys, json, asyncio
    from typing import Annotated

    from lauren import QueryField, pipe, BackgroundTasks
    from lauren_mcp.server._decorators import mcp_server, mcp_tool
    from lauren_mcp.server._meta import MCP_TOOL_META
    from lauren_mcp.server._handlers import (
        make_tools_list_handler,
        make_tools_call_handler,
    )
    from lauren_mcp._server._dispatcher import McpDispatcher
    from lauren_mcp._types import JsonRpcRequest


    @pipe()
    def _double_int(v: int, ctx) -> int:
        return v * 2


    @mcp_server('/mcp')
    class ValidSrv:
        @mcp_tool()
        async def place_order(self, qty: Annotated[int, QueryField(ge=1)]) -> str:
            'Place an order (qty must be >= 1).'
            return f'ordered {qty}'

        @mcp_tool()
        async def doubled(self, x: Annotated[int, QueryField(ge=0) | pipe(_double_int)]) -> str:
            'Return double of x (x must be >= 0).'
            return str(x)

        @mcp_tool()
        async def process(self, name: str, bg: BackgroundTasks) -> str:
            'Schedule a bg task and return immediately.'
            bg.add_task(lambda: None)
            return f'scheduled:{name}'

        @mcp_tool()
        async def process_two(self, name: str, bg: BackgroundTasks) -> str:
            'Schedule two bg tasks and return.'
            bg.add_task(lambda: None)
            bg.add_task(lambda: None)
            return f'done:{name}'

        @mcp_tool()
        async def raise_with_bg(self, name: str, bg: BackgroundTasks) -> str:
            'Schedule a bg task then raise.'
            bg.add_task(lambda: None)
            raise ValueError(f'deliberate: {name}')


    async def main():
        server = ValidSrv()
        dispatcher = McpDispatcher()
        dispatcher._register_builtins()

        tools = []
        for attr_name in dir(ValidSrv):
            try:
                attr = getattr(ValidSrv, attr_name)
            except AttributeError:
                continue
            meta = getattr(attr, MCP_TOOL_META, None)
            if meta is not None:
                tools.append(meta)

        async def _initialize(params):
            return {
                'protocolVersion': '2025-03-26',
                'capabilities': {'tools': {}},
                'serverInfo': {'name': 'valid-srv', 'version': '1.0.0'},
            }
        dispatcher.register('initialize', _initialize)

        tl = make_tools_list_handler(tools)
        tc = make_tools_call_handler(server, tools)

        async def _tl(p):
            return await tl(JsonRpcRequest(method='tools/list', params=p))

        async def _tc(p):
            return await tc(JsonRpcRequest(method='tools/call', params=p))

        dispatcher.register('tools/list', _tl)
        dispatcher.register('tools/call', _tc)

        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

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
            id_ = msg.get('id')
            if id_ is None:
                continue
            req = JsonRpcRequest(method=msg.get('method', ''), id=id_, params=msg.get('params'))
            resp = await dispatcher.dispatch(req)
            print(resp.to_json(), flush=True)


    asyncio.run(main())
""")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def server_command():
    """Write the server script to a temp file and return the launch command."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(_VALID_SERVER_SCRIPT)
        fname = f.name
    yield [sys.executable, fname]
    os.unlink(fname)


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def client(server_command):
    """Connected McpStdioClient backed by ValidSrv subprocess."""
    c: McpStdioClient = McpServer.stdio(server_command, max_retries=0)
    await asyncio.wait_for(c.connect(), timeout=15.0)
    yield c
    await c.close()


# ---------------------------------------------------------------------------
# Tool discovery — list_tools
# ---------------------------------------------------------------------------


class TestE2EListTools:
    async def test_lists_five_tools(self, client):
        tools = await asyncio.wait_for(client.list_tools(), timeout=10.0)
        assert len(tools) == 5

    async def test_place_order_schema_has_minimum_1(self, client):
        tools = await asyncio.wait_for(client.list_tools(), timeout=10.0)
        t = next(t for t in tools if t.name == "place_order")
        assert t.inputSchema["properties"]["qty"]["minimum"] == 1

    async def test_doubled_schema_has_minimum_0(self, client):
        tools = await asyncio.wait_for(client.list_tools(), timeout=10.0)
        t = next(t for t in tools if t.name == "doubled")
        assert t.inputSchema["properties"]["x"]["minimum"] == 0

    async def test_process_tool_bg_param_absent_from_schema(self, client):
        """BackgroundTasks param must not appear in the wire schema."""
        tools = await asyncio.wait_for(client.list_tools(), timeout=10.0)
        t = next(t for t in tools if t.name == "process")
        assert "bg" not in t.inputSchema.get("properties", {})

    async def test_process_tool_name_param_present_in_schema(self, client):
        tools = await asyncio.wait_for(client.list_tools(), timeout=10.0)
        t = next(t for t in tools if t.name == "process")
        assert "name" in t.inputSchema["properties"]

    async def test_all_tools_have_input_schema_type_object(self, client):
        tools = await asyncio.wait_for(client.list_tools(), timeout=10.0)
        for t in tools:
            assert t.inputSchema.get("type") == "object"


# ---------------------------------------------------------------------------
# Validation error — call_tool with invalid params
# ---------------------------------------------------------------------------


class TestE2EValidationErrors:
    async def test_place_order_qty_zero_raises_mcp_call_error(self, client):
        """Invalid qty=0 must raise McpCallError with code -32602 (INVALID_PARAMS)."""
        with pytest.raises(McpCallError) as exc_info:
            await asyncio.wait_for(client.call_tool("place_order", {"qty": 0}), timeout=10.0)
        assert exc_info.value.code == -32602

    async def test_place_order_qty_negative_raises_mcp_call_error(self, client):
        with pytest.raises(McpCallError) as exc_info:
            await asyncio.wait_for(client.call_tool("place_order", {"qty": -10}), timeout=10.0)
        assert exc_info.value.code == -32602

    async def test_doubled_negative_x_raises_mcp_call_error(self, client):
        """Pipe tool: invalid x=-1 must raise McpCallError with code -32602."""
        with pytest.raises(McpCallError) as exc_info:
            await asyncio.wait_for(client.call_tool("doubled", {"x": -1}), timeout=10.0)
        assert exc_info.value.code == -32602

    async def test_error_message_mentions_field_name(self, client):
        with pytest.raises(McpCallError) as exc_info:
            await asyncio.wait_for(client.call_tool("place_order", {"qty": 0}), timeout=10.0)
        assert "qty" in str(exc_info.value)

    async def test_error_is_not_internal_error(self, client):
        """Validation error must map to INVALID_PARAMS (-32602), not INTERNAL_ERROR (-32603)."""
        with pytest.raises(McpCallError) as exc_info:
            await asyncio.wait_for(client.call_tool("place_order", {"qty": 0}), timeout=10.0)
        assert exc_info.value.code != -32603


# ---------------------------------------------------------------------------
# Valid calls — place_order and doubled
# ---------------------------------------------------------------------------


class TestE2EValidCalls:
    async def test_place_order_valid_qty_returns_ordered_text(self, client):
        result = await asyncio.wait_for(client.call_tool("place_order", {"qty": 3}), timeout=10.0)
        text = next(c["text"] for c in result["content"] if c.get("type") == "text")
        assert "ordered 3" in text

    async def test_place_order_boundary_qty_1_succeeds(self, client):
        result = await asyncio.wait_for(client.call_tool("place_order", {"qty": 1}), timeout=10.0)
        text = next(c["text"] for c in result["content"] if c.get("type") == "text")
        assert "ordered 1" in text

    async def test_place_order_result_is_not_error(self, client):
        result = await asyncio.wait_for(client.call_tool("place_order", {"qty": 5}), timeout=10.0)
        assert result.get("isError") is False

    async def test_doubled_valid_x_returns_doubled_value(self, client):
        """Pipe _double_int is applied server-side; client sees result (7 * 2 = 14)."""
        result = await asyncio.wait_for(client.call_tool("doubled", {"x": 7}), timeout=10.0)
        text = next(c["text"] for c in result["content"] if c.get("type") == "text")
        assert text == "14"

    async def test_doubled_x_zero_returns_zero(self, client):
        result = await asyncio.wait_for(client.call_tool("doubled", {"x": 0}), timeout=10.0)
        text = next(c["text"] for c in result["content"] if c.get("type") == "text")
        assert text == "0"

    async def test_doubled_multiple_calls_give_independent_results(self, client):
        r1 = await asyncio.wait_for(client.call_tool("doubled", {"x": 3}), timeout=10.0)
        r2 = await asyncio.wait_for(client.call_tool("doubled", {"x": 10}), timeout=10.0)
        t1 = next(c["text"] for c in r1["content"] if c.get("type") == "text")
        t2 = next(c["text"] for c in r2["content"] if c.get("type") == "text")
        assert t1 == "6"
        assert t2 == "20"

    async def test_valid_call_after_invalid_call_succeeds(self, client):
        """Server must remain functional after receiving an invalid-params call."""
        with pytest.raises(McpCallError):
            await asyncio.wait_for(client.call_tool("place_order", {"qty": 0}), timeout=10.0)
        # Subsequent valid call must succeed
        result = await asyncio.wait_for(client.call_tool("place_order", {"qty": 2}), timeout=10.0)
        text = next(c["text"] for c in result["content"] if c.get("type") == "text")
        assert "ordered 2" in text


# ---------------------------------------------------------------------------
# BackgroundTasks — tool returns, bg tasks run server-side
# ---------------------------------------------------------------------------


class TestE2EBackgroundTasks:
    async def test_process_returns_scheduled_text(self, client):
        """Client gets the tool result; bg tasks ran server-side (not observable)."""
        result = await asyncio.wait_for(
            client.call_tool("process", {"name": "alice"}), timeout=10.0
        )
        text = next(c["text"] for c in result["content"] if c.get("type") == "text")
        assert "scheduled:alice" in text

    async def test_process_result_is_not_error(self, client):
        result = await asyncio.wait_for(client.call_tool("process", {"name": "bob"}), timeout=10.0)
        assert result.get("isError") is False

    async def test_process_two_returns_done_text(self, client):
        result = await asyncio.wait_for(
            client.call_tool("process_two", {"name": "carol"}), timeout=10.0
        )
        text = next(c["text"] for c in result["content"] if c.get("type") == "text")
        assert "done:carol" in text

    async def test_raise_with_bg_raises_mcp_call_error(self, client):
        """When the tool raises after scheduling bg tasks, client gets INTERNAL_ERROR."""
        with pytest.raises(McpCallError) as exc_info:
            await asyncio.wait_for(
                client.call_tool("raise_with_bg", {"name": "dave"}), timeout=10.0
            )
        # Tool raised → INTERNAL_ERROR (-32603)
        assert exc_info.value.code == -32603

    async def test_sequential_bg_tool_calls_work_independently(self, client):
        r1 = await asyncio.wait_for(client.call_tool("process", {"name": "first"}), timeout=10.0)
        r2 = await asyncio.wait_for(client.call_tool("process", {"name": "second"}), timeout=10.0)
        t1 = next(c["text"] for c in r1["content"] if c.get("type") == "text")
        t2 = next(c["text"] for c in r2["content"] if c.get("type") == "text")
        assert "first" in t1
        assert "second" in t2
        assert t1 != t2

    async def test_bg_tool_result_content_is_non_empty(self, client):
        result = await asyncio.wait_for(client.call_tool("process", {"name": "eve"}), timeout=10.0)
        assert len(result.get("content", [])) >= 1
