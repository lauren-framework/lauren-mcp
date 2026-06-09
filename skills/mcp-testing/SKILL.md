---
skill: mcp-testing
version: 1.0.0
tags: [mcp, testing, pytest, echo-server, mock, lauren-mcp]
summary: Test MCP servers with the echo server subprocess pattern and mock McpClientProtocol.
---

# Skill: MCP Testing

## When to use this skill

Use this skill when you need to:
- Write integration tests for an MCP server using a real subprocess
- Write unit tests that mock `McpClientProtocol` without spawning processes
- Set up pytest fixtures for MCP clients
- Use `pytest.mark.eval` for live-network tests

## Pattern 1: Echo server subprocess

### 1a. Create the echo server script

```python
# tests/fixtures/echo_server.py
"""Minimal MCP server for testing — echoes inputs and does simple arithmetic."""
from __future__ import annotations

from lauren import Lauren
from lauren_mcp import mcp_server, mcp_tool, McpServerModule


@mcp_server("/mcp")
class EchoServer:
    @mcp_tool()
    async def echo(self, message: str) -> str:
        """Echo the message back unchanged.

        Args:
            message: Any string to echo.
        """
        return message

    @mcp_tool()
    async def add(self, a: float, b: float) -> float:
        """Add two numbers.

        Args:
            a: First operand.
            b: Second operand.
        """
        return a + b

    @mcp_tool()
    async def fail(self) -> str:
        """Always raise an error (for testing error handling)."""
        raise ValueError("Intentional failure")


app = Lauren()
app.include(McpServerModule.for_root(transports=["stdio"]))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, transport="stdio")
```

### 1b. Write tests against the echo server

```python
# tests/integration/test_echo_server.py
from __future__ import annotations
import sys
import pytest
from lauren_mcp import McpServer, McpToolError


@pytest.fixture
async def echo_client():
    client = McpServer.stdio(
        [sys.executable, "tests/fixtures/echo_server.py"],
        timeout=10.0,
    )
    async with client:
        yield client


async def test_echo_tool(echo_client):
    result = await echo_client.call_tool("echo", {"message": "hello world"})
    assert len(result) == 1
    assert result[0].text == "hello world"


async def test_add_tool(echo_client):
    result = await echo_client.call_tool("add", {"a": 2.5, "b": 3.5})
    assert float(result[0].text) == 6.0


async def test_list_tools(echo_client):
    tools = await echo_client.list_tools()
    names = {t.name for t in tools}
    assert {"echo", "add", "fail"} <= names


async def test_tool_error(echo_client):
    with pytest.raises(McpToolError):
        await echo_client.call_tool("fail", {})
```

## Pattern 2: Mock `McpClientProtocol`

For unit tests that should not spawn processes:

```python
# tests/unit/test_tool_bridge.py
from __future__ import annotations
from unittest.mock import AsyncMock
import pytest

from lauren_mcp import McpServerConfig, McpToolBridge, McpServer
from lauren_mcp._types import ToolSchema, TextContent


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.list_tools = AsyncMock(
        return_value=[
            ToolSchema(
                name="greet",
                description="Greet someone.",
                inputSchema={
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            )
        ]
    )
    client.call_tool = AsyncMock(
        return_value=[TextContent(type="text", text="Hello, Alice!")]
    )
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


async def test_bridge_tool_names(mock_client):
    config = McpServerConfig(alias="svc", client=mock_client)
    bridge = McpToolBridge(config)
    async with bridge:
        names = bridge.get_tool_names()
        assert "svc__greet" in names


async def test_bridge_call_tool(mock_client):
    config = McpServerConfig(alias="svc", client=mock_client)
    bridge = McpToolBridge(config)
    async with bridge:
        result = await bridge.call("svc__greet", {"name": "Alice"})
        assert result[0].text == "Hello, Alice!"
        mock_client.call_tool.assert_awaited_once_with("greet", {"name": "Alice"})
```

## Pattern 3: `pytest.mark.eval` for live tests

```python
# tests/integration/test_filesystem_server.py
import sys
import pytest
from lauren_mcp import McpServer


@pytest.mark.eval
async def test_list_tmp():
    """Requires: npx, @modelcontextprotocol/server-filesystem installed."""
    client = McpServer.stdio(
        ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    )
    async with client:
        result = await client.call_tool("list_directory", {"path": "/tmp"})
        assert isinstance(result, list)
```

Run live tests explicitly:

```bash
pytest -m eval tests/integration/
```

## conftest.py

```python
# tests/conftest.py
import pytest

@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"
```
