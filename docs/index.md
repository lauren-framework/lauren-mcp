# Lauren MCP

> Model Context Protocol server and client for the Lauren web framework.

`lauren-mcp` adds two capabilities to any Lauren application:

**Server** — expose any Lauren service as an MCP server that AI clients can discover and call:

```python
from lauren_mcp import mcp_server, mcp_tool, McpServerModule

@mcp_server("/mcp")
class SearchServer:
    @mcp_tool()
    async def search(self, query: str) -> list[dict]:
        """Search the catalogue.  Args: query: Search terms."""
        ...
```

**Client** — consume any remote MCP server and wire its tools into a Lauren AI agent:

```python
from lauren_mcp import McpServer, McpServerConfig

mcp_servers=[
    McpServerConfig(alias="fs", client=McpServer.stdio(["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"])),
]
```

## Installation

| Command | What you get |
|---|---|
| `pip install lauren-mcp` | Core: JSON-RPC types + server decorators |
| `pip install "lauren-mcp[ws]"` | + WebSocket client |
| `pip install "lauren-mcp[http]"` | + HTTP+SSE client |
| `pip install "lauren-mcp[all]"` | All transports |

## Quick links

- [Getting Started](getting-started/index.md)
- [MCP Server guide](guides/mcp-server.md)
- [MCP Client guide](guides/mcp-client.md)
- [API Reference](reference/index.md)
