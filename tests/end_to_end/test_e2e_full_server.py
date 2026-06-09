"""End-to-end: full decorator → handler factory → dispatcher → JSON-RPC wire → client.

The subprocess runs a real @mcp_server class (with @mcp_tool, @mcp_resource,
@mcp_prompt methods) wired through the same handler-factory logic that
McpServerModule uses in production, then serves over stdin/stdout.
The test connects with McpStdioClient and exercises every protocol method.

Nothing is mocked: decorator metadata, schema generation, JSON serialisation,
subprocess I/O, client parsing, and result typing all run for real.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import textwrap

import pytest

from lauren_mcp import McpServer
from lauren_mcp._client._stdio import McpStdioClient
from lauren_mcp._types import PromptSchema, ResourceSchema, ToolSchema

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Subprocess server script — MathServer
# ---------------------------------------------------------------------------
# The script defines @mcp_server / @mcp_tool / @mcp_resource / @mcp_prompt
# classes exactly as library users would, wires them through the real handler
# factories, and serves JSON-RPC over stdin/stdout.

_MATH_SERVER_SCRIPT = textwrap.dedent("""\
    import sys, json, asyncio

    from lauren_mcp.server._decorators import mcp_server, mcp_tool, mcp_resource, mcp_prompt
    from lauren_mcp.server._meta import MCP_TOOL_META, MCP_RESOURCE_META, MCP_PROMPT_META
    from lauren_mcp.server._handlers import (
        make_tools_list_handler, make_tools_call_handler,
        make_resources_list_handler, make_resources_read_handler,
        make_prompts_list_handler, make_prompts_get_handler,
    )
    from lauren_mcp._server._dispatcher import McpDispatcher
    from lauren_mcp._types import JsonRpcRequest


    @mcp_server("/mcp")
    class MathServer:
        @mcp_tool()
        async def add(self, a: int, b: int) -> int:
            "Add two integers."
            return a + b

        @mcp_tool()
        async def multiply(self, a: int, b: int) -> int:
            "Multiply two integers."
            return a * b

        @mcp_resource("/data/{key}")
        async def get_data(self, key: str) -> str:
            "Read a data item by key."
            return f"value_of_{key}"

        @mcp_prompt()
        async def summarise(self, topic: str) -> list:
            "Summarise a topic."
            return [{"role": "user", "content": {"type": "text", "text": f"Summarise: {topic}"}}]


    async def main():
        dispatcher = McpDispatcher()
        dispatcher._register_builtins()
        server = MathServer()

        tools, resources, prompts = [], [], []
        for name in dir(MathServer):
            try:
                attr = getattr(MathServer, name)
            except AttributeError:
                continue
            if hasattr(attr, MCP_TOOL_META):
                tools.append(getattr(attr, MCP_TOOL_META))
            if hasattr(attr, MCP_RESOURCE_META):
                resources.append(getattr(attr, MCP_RESOURCE_META))
            if hasattr(attr, MCP_PROMPT_META):
                prompts.append(getattr(attr, MCP_PROMPT_META))

        async def _init(params):
            return {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                "serverInfo": {"name": "math-server", "version": "1.0.0"},
            }
        dispatcher.register("initialize", _init)

        tl = make_tools_list_handler(tools)
        tc = make_tools_call_handler(server, tools)
        async def _tl(p): return await tl(JsonRpcRequest(method="tools/list", params=p))
        async def _tc(p): return await tc(JsonRpcRequest(method="tools/call", params=p))
        dispatcher.register("tools/list", _tl)
        dispatcher.register("tools/call", _tc)

        rl = make_resources_list_handler(resources)
        rr = make_resources_read_handler(server, resources)
        async def _rl(p): return await rl(JsonRpcRequest(method="resources/list", params=p))
        async def _rr(p): return await rr(JsonRpcRequest(method="resources/read", params=p))
        dispatcher.register("resources/list", _rl)
        dispatcher.register("resources/read", _rr)

        pl = make_prompts_list_handler(prompts)
        pg = make_prompts_get_handler(server, prompts)
        async def _pl(p): return await pl(JsonRpcRequest(method="prompts/list", params=p))
        async def _pg(p): return await pg(JsonRpcRequest(method="prompts/get", params=p))
        dispatcher.register("prompts/list", _pl)
        dispatcher.register("prompts/get", _pg)

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
            id_ = msg.get("id")
            if id_ is None:
                continue   # notification — no response needed
            req = JsonRpcRequest(method=msg.get("method", ""), id=id_, params=msg.get("params"))
            resp = await dispatcher.dispatch(req)
            print(resp.to_json(), flush=True)


    asyncio.run(main())
""")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def math_server_command():
    """Return argv that launches the MathServer over stdin/stdout."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(_MATH_SERVER_SCRIPT)
        fname = f.name
    yield [sys.executable, fname]
    os.unlink(fname)


@pytest.fixture
async def math_client(math_server_command):
    """Connected McpStdioClient backed by the MathServer subprocess."""
    client: McpStdioClient = McpServer.stdio(math_server_command)
    await asyncio.wait_for(client.connect(), timeout=10.0)
    yield client
    await client.close()


# ---------------------------------------------------------------------------
# Tool discovery
# ---------------------------------------------------------------------------


class TestToolDiscovery:
    async def test_list_tools_returns_two_tools(self, math_client):
        tools = await asyncio.wait_for(math_client.list_tools(), timeout=5.0)
        assert len(tools) == 2

    async def test_list_tools_returns_tool_schema_instances(self, math_client):
        tools = await asyncio.wait_for(math_client.list_tools(), timeout=5.0)
        for t in tools:
            assert isinstance(t, ToolSchema)

    async def test_tool_names_are_add_and_multiply(self, math_client):
        tools = await asyncio.wait_for(math_client.list_tools(), timeout=5.0)
        names = {t.name for t in tools}
        assert "add" in names
        assert "multiply" in names

    async def test_add_tool_schema_has_a_and_b_properties(self, math_client):
        tools = await asyncio.wait_for(math_client.list_tools(), timeout=5.0)
        add_tool = next(t for t in tools if t.name == "add")
        props = add_tool.inputSchema.get("properties", {})
        assert "a" in props
        assert "b" in props

    async def test_add_tool_schema_marks_a_and_b_required(self, math_client):
        tools = await asyncio.wait_for(math_client.list_tools(), timeout=5.0)
        add_tool = next(t for t in tools if t.name == "add")
        required = add_tool.inputSchema.get("required", [])
        assert "a" in required
        assert "b" in required

    async def test_add_tool_schema_integer_types(self, math_client):
        tools = await asyncio.wait_for(math_client.list_tools(), timeout=5.0)
        add_tool = next(t for t in tools if t.name == "add")
        props = add_tool.inputSchema["properties"]
        assert props["a"]["type"] == "integer"
        assert props["b"]["type"] == "integer"

    async def test_tool_description_derived_from_docstring(self, math_client):
        tools = await asyncio.wait_for(math_client.list_tools(), timeout=5.0)
        add_tool = next(t for t in tools if t.name == "add")
        assert "Add" in add_tool.description or "integer" in add_tool.description.lower()

    async def test_schema_type_is_object(self, math_client):
        tools = await asyncio.wait_for(math_client.list_tools(), timeout=5.0)
        for t in tools:
            assert t.inputSchema.get("type") == "object"


# ---------------------------------------------------------------------------
# Tool invocation
# ---------------------------------------------------------------------------


class TestToolInvocation:
    async def test_add_3_plus_4_returns_7(self, math_client):
        result = await asyncio.wait_for(math_client.call_tool("add", {"a": 3, "b": 4}), timeout=5.0)
        content = result.get("content", [])
        text = next(c["text"] for c in content if c.get("type") == "text")
        assert "7" in text

    async def test_multiply_5_times_6_returns_30(self, math_client):
        result = await asyncio.wait_for(
            math_client.call_tool("multiply", {"a": 5, "b": 6}), timeout=5.0
        )
        content = result.get("content", [])
        text = next(c["text"] for c in content if c.get("type") == "text")
        assert "30" in text

    async def test_add_negative_numbers(self, math_client):
        result = await asyncio.wait_for(
            math_client.call_tool("add", {"a": -10, "b": 3}), timeout=5.0
        )
        content = result.get("content", [])
        text = next(c["text"] for c in content if c.get("type") == "text")
        assert "-7" in text

    async def test_add_zero_identity(self, math_client):
        result = await asyncio.wait_for(
            math_client.call_tool("add", {"a": 42, "b": 0}), timeout=5.0
        )
        content = result.get("content", [])
        text = next(c["text"] for c in content if c.get("type") == "text")
        assert "42" in text

    async def test_call_is_not_error(self, math_client):
        result = await asyncio.wait_for(
            math_client.call_tool("multiply", {"a": 2, "b": 8}), timeout=5.0
        )
        assert result.get("isError") is False

    async def test_content_list_is_nonempty(self, math_client):
        result = await asyncio.wait_for(math_client.call_tool("add", {"a": 1, "b": 1}), timeout=5.0)
        assert len(result.get("content", [])) >= 1

    async def test_sequential_calls_return_independent_results(self, math_client):
        r1 = await asyncio.wait_for(math_client.call_tool("add", {"a": 1, "b": 2}), timeout=5.0)
        r2 = await asyncio.wait_for(math_client.call_tool("add", {"a": 10, "b": 20}), timeout=5.0)
        t1 = next(c["text"] for c in r1["content"] if c.get("type") == "text")
        t2 = next(c["text"] for c in r2["content"] if c.get("type") == "text")
        assert "3" in t1
        assert "30" in t2


# ---------------------------------------------------------------------------
# Resource discovery and reading
# ---------------------------------------------------------------------------


class TestResources:
    async def test_list_resources_returns_one_resource(self, math_client):
        resources = await asyncio.wait_for(math_client.list_resources(), timeout=5.0)
        assert len(resources) == 1

    async def test_list_resources_returns_resource_schema_instances(self, math_client):
        resources = await asyncio.wait_for(math_client.list_resources(), timeout=5.0)
        for r in resources:
            assert isinstance(r, ResourceSchema)

    async def test_resource_uri_contains_data(self, math_client):
        resources = await asyncio.wait_for(math_client.list_resources(), timeout=5.0)
        uris = [r.uri for r in resources]
        assert any("data" in u for u in uris)

    async def test_read_resource_returns_value_of_key(self, math_client):
        result = await asyncio.wait_for(math_client.read_resource("/data/hello"), timeout=5.0)
        # result is raw dict from resources/read response
        contents = result.get("contents", [])
        assert len(contents) >= 1
        text_values = [c.get("text", "") for c in contents if "text" in c]
        assert any("value_of_hello" in t for t in text_values)

    async def test_read_resource_different_keys_give_different_values(self, math_client):
        r1 = await asyncio.wait_for(math_client.read_resource("/data/foo"), timeout=5.0)
        r2 = await asyncio.wait_for(math_client.read_resource("/data/bar"), timeout=5.0)
        t1 = r1["contents"][0].get("text", "")
        t2 = r2["contents"][0].get("text", "")
        assert "foo" in t1
        assert "bar" in t2


# ---------------------------------------------------------------------------
# Prompt discovery and retrieval
# ---------------------------------------------------------------------------


class TestPrompts:
    async def test_list_prompts_returns_one_prompt(self, math_client):
        prompts = await asyncio.wait_for(math_client.list_prompts(), timeout=5.0)
        assert len(prompts) == 1

    async def test_list_prompts_returns_prompt_schema_instances(self, math_client):
        prompts = await asyncio.wait_for(math_client.list_prompts(), timeout=5.0)
        for p in prompts:
            assert isinstance(p, PromptSchema)

    async def test_prompt_name_is_summarise(self, math_client):
        prompts = await asyncio.wait_for(math_client.list_prompts(), timeout=5.0)
        assert prompts[0].name == "summarise"

    async def test_get_prompt_returns_messages(self, math_client):
        result = await asyncio.wait_for(
            math_client.get_prompt("summarise", {"topic": "AI"}), timeout=5.0
        )
        messages = result.get("messages", [])
        assert len(messages) >= 1

    async def test_get_prompt_message_contains_topic(self, math_client):
        result = await asyncio.wait_for(
            math_client.get_prompt("summarise", {"topic": "quantum computing"}), timeout=5.0
        )
        messages = result.get("messages", [])
        assert any("quantum computing" in str(m) for m in messages)

    async def test_get_prompt_message_role_is_user(self, math_client):
        result = await asyncio.wait_for(
            math_client.get_prompt("summarise", {"topic": "test"}), timeout=5.0
        )
        messages = result.get("messages", [])
        assert messages[0].get("role") == "user"


# ---------------------------------------------------------------------------
# Ping
# ---------------------------------------------------------------------------


class TestPing:
    async def test_ping_completes_without_error(self, math_client):
        await asyncio.wait_for(math_client.ping(), timeout=5.0)

    async def test_ping_after_tool_calls_still_works(self, math_client):
        await asyncio.wait_for(math_client.call_tool("add", {"a": 1, "b": 1}), timeout=5.0)
        await asyncio.wait_for(math_client.ping(), timeout=5.0)
