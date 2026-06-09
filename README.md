# lauren-mcp

> Model Context Protocol server and client for the Lauren web framework.

[![Tests](https://github.com/lauren-framework/lauren-mcp/actions/workflows/tests.yml/badge.svg)](https://github.com/lauren-framework/lauren-mcp/actions/workflows/tests.yml)
[![Lint](https://github.com/lauren-framework/lauren-mcp/actions/workflows/lint.yml/badge.svg)](https://github.com/lauren-framework/lauren-mcp/actions/workflows/lint.yml)
[![codecov](https://codecov.io/gh/lauren-framework/lauren-mcp/branch/main/graph/badge.svg)](https://codecov.io/gh/lauren-framework/lauren-mcp)
[![PyPI](https://img.shields.io/pypi/v/lauren-mcp)](https://pypi.org/project/lauren-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/lauren-mcp)](https://pypi.org/project/lauren-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/)

`lauren-mcp` extends the [Lauren](https://github.com/lauren-framework/lauren-framework)
web framework with first-class support for the
[Model Context Protocol (MCP)](https://modelcontextprotocol.io/). It lets you:

- **Expose** any Lauren service as an MCP server so AI clients can discover and call
  its tools over WebSocket or HTTP+SSE.
- **Consume** any remote MCP server (stdio, WebSocket, or HTTP+SSE) and wire its tools
  into a Lauren AI agent with automatic namespacing.

## Features

- `@mcp_server`, `@mcp_tool`, `@mcp_resource`, `@mcp_prompt` decorators with
  automatic JSON Schema generation from Python type annotations
- Three client transports: stdio subprocess, WebSocket, HTTP+SSE
- `McpServerConfig` + `AgentModule.for_root(mcp_servers=[...])` for zero-boilerplate
  agent tool integration
- Tool namespacing (`alias__tool_name`) prevents collisions across multiple MCP servers
- Automatic system prompt injection listing all available MCP tools
- Exponential backoff reconnect for the WebSocket client
- DI-aware tool dispatch — DI parameters are excluded from the generated JSON Schema
- 100% typed (mypy strict), 80%+ test coverage

## Installation

| Command | What you get |
|---|---|
| `pip install lauren-mcp` | Core: JSON-RPC types + server decorators + stdio client |
| `pip install "lauren-mcp[ws]"` | + WebSocket client (`websockets`) |
| `pip install "lauren-mcp[http]"` | + HTTP+SSE client (`httpx`, `httpx-sse`) |
| `pip install "lauren-mcp[all]"` | All transports |

## Quick start — Server

```python
from lauren import Lauren
from lauren_mcp import mcp_server, mcp_tool, McpServerModule

CATALOGUE = [{"id": 1, "name": "Widget A"}, {"id": 2, "name": "Widget B"}]

@mcp_server("/mcp")
class CatalogueServer:
    @mcp_tool()
    async def search(self, query: str) -> list[dict]:
        """Search the catalogue by name.

        Args:
            query: Search terms.
        """
        return [i for i in CATALOGUE if query.lower() in i["name"].lower()]

    @mcp_tool()
    async def get_item(self, item_id: int) -> dict | None:
        """Get a single item by ID.

        Args:
            item_id: The numeric item ID.
        """
        return next((i for i in CATALOGUE if i["id"] == item_id), None)

app = Lauren()
app.include(McpServerModule.for_root())
```

## Quick start — Client

```python
from lauren_mcp import McpServer, McpServerConfig
from lauren.contrib.ai import AgentModule

mcp_servers = [
    McpServerConfig(
        alias="fs",
        client=McpServer.stdio(
            ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        ),
    ),
]

# tools available to agent: fs__read_file, fs__write_file, fs__list_directory, ...
app.include(AgentModule.for_root(model="claude-opus-4-5", mcp_servers=mcp_servers))
```

## Documentation

- [Getting Started](https://mcp.lauren-py.dev/getting-started/)
- [MCP Server guide](https://mcp.lauren-py.dev/guides/mcp-server/)
- [MCP Client guide](https://mcp.lauren-py.dev/guides/mcp-client/)
- [Agent Tools guide](https://mcp.lauren-py.dev/guides/mcp-agent-tools/)
- [Testing guide](https://mcp.lauren-py.dev/guides/testing/)
- [API Reference](https://mcp.lauren-py.dev/reference/)
