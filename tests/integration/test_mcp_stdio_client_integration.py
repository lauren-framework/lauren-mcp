"""Integration tests: McpStdioClient with a real Python subprocess MCP server."""
from __future__ import annotations

import asyncio
import pytest

from lauren_mcp import McpServer
from lauren_mcp._client._stdio import McpStdioClient, McpCallError
from lauren_mcp._types import ToolSchema


# All tests are async and use the real subprocess echo server.
pytestmark = pytest.mark.asyncio


@pytest.fixture
async def connected_client(echo_server_command):
    """Return a connected McpStdioClient backed by the echo server subprocess."""
    client: McpStdioClient = McpServer.stdio(echo_server_command)
    await client.connect()
    yield client
    await client.close()


class TestHandshake:
    async def test_connect_completes_handshake(self, echo_server_command):
        """connect() should complete without raising."""
        client: McpStdioClient = McpServer.stdio(echo_server_command)
        try:
            await asyncio.wait_for(client.connect(), timeout=5.0)
        finally:
            await client.close()


class TestListTools:
    async def test_list_tools_returns_echo_tool(self, connected_client):
        tools = await asyncio.wait_for(connected_client.list_tools(), timeout=5.0)
        assert len(tools) >= 1
        tool_names = [t.name for t in tools]
        assert "echo" in tool_names

    async def test_list_tools_returns_tool_schema_instances(self, connected_client):
        tools = await asyncio.wait_for(connected_client.list_tools(), timeout=5.0)
        for tool in tools:
            assert isinstance(tool, ToolSchema)

    async def test_echo_tool_has_text_in_input_schema(self, connected_client):
        tools = await asyncio.wait_for(connected_client.list_tools(), timeout=5.0)
        echo = next(t for t in tools if t.name == "echo")
        assert "text" in echo.inputSchema.get("properties", {})


class TestCallTool:
    async def test_call_echo_tool_returns_text(self, connected_client):
        result = await asyncio.wait_for(
            connected_client.call_tool("echo", {"text": "hello world"}),
            timeout=5.0,
        )
        # result is the raw dict from tools/call
        content = result.get("content", [])
        assert len(content) >= 1
        text_items = [c for c in content if c.get("type") == "text"]
        assert any("hello world" in item.get("text", "") for item in text_items)

    async def test_call_echo_tool_empty_string(self, connected_client):
        result = await asyncio.wait_for(
            connected_client.call_tool("echo", {"text": ""}),
            timeout=5.0,
        )
        content = result.get("content", [])
        assert any(item.get("type") == "text" for item in content)

    async def test_call_echo_tool_unicode_text(self, connected_client):
        text = "Hello, 世界! 🎉"
        result = await asyncio.wait_for(
            connected_client.call_tool("echo", {"text": text}),
            timeout=5.0,
        )
        content = result.get("content", [])
        text_items = [c for c in content if c.get("type") == "text"]
        assert any(text in item.get("text", "") for item in text_items)


class TestPing:
    async def test_ping_succeeds(self, connected_client):
        """ping() should complete without raising."""
        await asyncio.wait_for(connected_client.ping(), timeout=5.0)


class TestListResources:
    async def test_list_resources_returns_empty(self, connected_client):
        resources = await asyncio.wait_for(connected_client.list_resources(), timeout=5.0)
        assert isinstance(resources, list)
        assert len(resources) == 0


class TestListPrompts:
    async def test_list_prompts_returns_empty(self, connected_client):
        prompts = await asyncio.wait_for(connected_client.list_prompts(), timeout=5.0)
        assert isinstance(prompts, list)
        assert len(prompts) == 0


class TestFactoryCreation:
    async def test_factory_creates_connected_client(self, echo_server_command):
        """McpServer.stdio() should return a usable client."""
        client = McpServer.stdio(echo_server_command)
        assert isinstance(client, McpStdioClient)
        try:
            await asyncio.wait_for(client.connect(), timeout=5.0)
            tools = await asyncio.wait_for(client.list_tools(), timeout=5.0)
            assert len(tools) >= 1
        finally:
            await client.close()


class TestMultipleCalls:
    async def test_multiple_calls_after_single_connect(self, connected_client):
        """Multiple sequential calls should all succeed on a single connection."""
        tools1 = await asyncio.wait_for(connected_client.list_tools(), timeout=5.0)
        resources = await asyncio.wait_for(connected_client.list_resources(), timeout=5.0)
        prompts = await asyncio.wait_for(connected_client.list_prompts(), timeout=5.0)
        tools2 = await asyncio.wait_for(connected_client.list_tools(), timeout=5.0)

        assert len(tools1) >= 1
        assert resources == []
        assert prompts == []
        assert [t.name for t in tools1] == [t.name for t in tools2]

    async def test_concurrent_calls_succeed(self, connected_client):
        """Multiple concurrent calls should all return valid results."""
        results = await asyncio.gather(
            connected_client.list_tools(),
            connected_client.list_resources(),
            connected_client.list_prompts(),
        )
        tools, resources, prompts = results
        assert len(tools) >= 1
        assert isinstance(resources, list)
        assert isinstance(prompts, list)


class TestClosedClient:
    async def test_client_closed_raises_on_call(self, echo_server_command):
        """After close(), subsequent protocol calls should raise."""
        client: McpStdioClient = McpServer.stdio(echo_server_command)
        await asyncio.wait_for(client.connect(), timeout=5.0)
        await client.close()

        with pytest.raises(Exception):
            await asyncio.wait_for(client.list_tools(), timeout=2.0)
