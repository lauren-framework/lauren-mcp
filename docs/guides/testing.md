# Testing Guide

This guide shows how to write reliable tests for MCP servers and clients.

---

## Testing MCP servers with a real subprocess

The most realistic way to test an MCP server is to run it as a subprocess and connect
with `McpServer.stdio`. This exercises the full stack including serialisation,
transport, and business logic.

### Echo server pattern

Create a minimal "echo" MCP server script for use in tests:

```python
# tests/fixtures/echo_server.py
"""Minimal MCP server that echoes tool arguments back as JSON."""
from __future__ import annotations
import json
import sys

from lauren import Lauren
from lauren_mcp import mcp_server, mcp_tool, McpServerModule


@mcp_server("/mcp")
class EchoServer:
    @mcp_tool()
    async def echo(self, message: str) -> str:
        """Echo the message back.

        Args:
            message: The message to echo.
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


app = Lauren()
app.include(McpServerModule.for_root(transports=["stdio"]))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, transport="stdio")
```

### Test using the echo server

```python
# tests/integration/test_echo_server.py
from __future__ import annotations
import sys
import pytest
from lauren_mcp import McpServer


@pytest.fixture
async def echo_client():
    client = McpServer.stdio([sys.executable, "tests/fixtures/echo_server.py"])
    async with client:
        yield client


async def test_echo_tool(echo_client):
    result = await echo_client.call_tool("echo", {"message": "hello"})
    assert len(result) == 1
    assert result[0].text == "hello"


async def test_add_tool(echo_client):
    result = await echo_client.call_tool("add", {"a": 3.0, "b": 4.0})
    assert len(result) == 1
    assert float(result[0].text) == 7.0


async def test_list_tools(echo_client):
    tools = await echo_client.list_tools()
    names = [t.name for t in tools]
    assert "echo" in names
    assert "add" in names
```

---

## Mocking `McpClientProtocol`

For unit tests that should not spawn subprocesses, mock the protocol directly:

```python
# tests/unit/test_agent_tools.py
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock
import pytest

from lauren_mcp import McpServerConfig, McpToolBridge
from lauren_mcp._types import ToolSchema, TextContent


@pytest.fixture
def mock_client():
    client = AsyncMock()
    client.list_tools = AsyncMock(
        return_value=[
            ToolSchema(
                name="search",
                description="Search the catalogue.",
                inputSchema={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            )
        ]
    )
    client.call_tool = AsyncMock(
        return_value=[TextContent(type="text", text='[{"id": 1, "name": "Widget A"}]')]
    )
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


async def test_bridge_registers_tools(mock_client):
    config = McpServerConfig(alias="cat", client=mock_client)
    bridge = McpToolBridge(config)
    async with bridge:
        tools = bridge.get_tool_names()
        assert "cat__search" in tools


async def test_bridge_calls_tool(mock_client):
    config = McpServerConfig(alias="cat", client=mock_client)
    bridge = McpToolBridge(config)
    async with bridge:
        result = await bridge.call("cat__search", {"query": "widget"})
        assert "Widget A" in result[0].text
```

---

## `pytest.mark.eval` for live tests

Tests that require a running external MCP server (e.g. the official filesystem server
from npm) should be marked `eval` so they are excluded from the default test run:

```python
# tests/integration/test_filesystem_server.py
import sys
import pytest
from lauren_mcp import McpServer


@pytest.mark.eval
async def test_filesystem_list_directory():
    """Live test: requires npx and @modelcontextprotocol/server-filesystem."""
    client = McpServer.stdio(
        ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    )
    async with client:
        result = await client.call_tool("list_directory", {"path": "/tmp"})
        assert len(result) >= 0  # /tmp may be empty
```

Run eval tests explicitly:

```bash
pytest -m eval tests/integration/
```

The `pyproject.toml` default options exclude them:

```toml
[tool.pytest.ini_options]
addopts = "-m 'not benchmark and not eval'"
```

---

## Coverage setup

The `pyproject.toml` coverage configuration:

```toml
[tool.coverage.run]
source = ["src/lauren_mcp"]
omit   = ["tests/*"]

[tool.coverage.report]
fail_under   = 80
show_missing = true
```

Run coverage:

```bash
nox -s coverage
# or
pytest --cov=src/lauren_mcp --cov-report=term-missing
```

Open the HTML report:

```bash
open htmlcov/index.html
```

---

## conftest.py recommendation

```python
# tests/conftest.py
from __future__ import annotations
import pytest


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"
```

With `asyncio_mode = "auto"` in `pyproject.toml` all `async def test_*` functions are
automatically treated as asyncio coroutines without needing the `@pytest.mark.asyncio`
decorator.
