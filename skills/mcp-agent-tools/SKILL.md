---
skill: mcp-agent-tools
version: 1.0.0
tags: [mcp, agent, tools, AgentModule, McpServerConfig, lauren-mcp]
summary: Wire MCP server tools into a Lauren AgentModule with tool namespacing and system prompt guidance.
---

# Skill: MCP Agent Tools

## When to use this skill

Use this skill when you need to:
- Make a Lauren AI agent able to call tools from one or more external MCP servers
- Understand how tool names are namespaced to avoid collisions
- Customise the agent system prompt to describe available MCP tools
- Mix native agent tools with remote MCP tools

## Complete example

```python
# agent_app.py
from __future__ import annotations

from lauren import Lauren
from lauren_mcp import McpServer, McpServerConfig
from lauren.contrib.ai import AgentModule, agent, tool


# Native tools defined on the agent class
@agent
class ShopAgent:
    @tool
    async def get_cart(self, user_id: str) -> dict:
        """Return the current shopping cart for a user.

        Args:
            user_id: The user's unique identifier.
        """
        # ... implementation
        return {"user_id": user_id, "items": []}

    @tool
    async def checkout(self, user_id: str) -> str:
        """Checkout the cart for a user and return an order ID.

        Args:
            user_id: The user's unique identifier.
        """
        # ... implementation
        return "order-12345"


# MCP server configurations
mcp_servers = [
    # stdio: local subprocess
    McpServerConfig(
        alias="fs",
        client=McpServer.stdio(
            ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        ),
        description="Local filesystem access for temporary files",
        tool_filter=["read_file", "list_directory"],  # only expose read tools
    ),
    # WebSocket: remote search service
    McpServerConfig(
        alias="search",
        client=McpServer.ws("ws://search-service:8080/mcp/ws"),
        description="Product catalogue search service",
    ),
    # HTTP+SSE: analytics service
    McpServerConfig(
        alias="analytics",
        client=McpServer.http("http://analytics:9000/mcp/sse"),
        description="Order analytics and reporting",
    ),
]


app = Lauren()
app.include(
    AgentModule.for_root(
        agent=ShopAgent,
        model="claude-opus-4-5",
        system_prompt=(
            "You are a helpful shop assistant. "
            "Use your tools to help customers manage their carts and find products."
        ),
        mcp_servers=mcp_servers,
    )
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

## Tool namespace reference

After startup the agent sees these tools:

| Source | Original name | Namespaced name |
|---|---|---|
| Native | `get_cart` | `get_cart` |
| Native | `checkout` | `checkout` |
| `fs` (MCP) | `read_file` | `fs__read_file` |
| `fs` (MCP) | `list_directory` | `fs__list_directory` |
| `search` (MCP) | `search` | `search__search` |
| `search` (MCP) | `get_item` | `search__get_item` |
| `analytics` (MCP) | `daily_summary` | `analytics__daily_summary` |

## System prompt guidance

The framework auto-appends a tool catalogue to the system prompt. For best results,
your own system prompt should:

1. Explain the agent's purpose before the tool list.
2. Mention which alias corresponds to which service, if it is not obvious from the
   `description` field on `McpServerConfig`.
3. Give the agent permission to use the MCP tools freely:

```python
system_prompt=(
    "You are a shop assistant. "
    "You have access to: "
    "  - native cart and checkout tools, "
    "  - 'fs' tools for temporary file storage, "
    "  - 'search' tools to find products, "
    "  - 'analytics' tools for reporting. "
    "Use whichever tools are most appropriate to fulfil the user's request."
)
```

## Startup log output

```
INFO  [lauren-mcp] Connected to MCP server 'fs' via stdio
INFO  [lauren-mcp] Registered tools from 'fs': fs__read_file, fs__list_directory
INFO  [lauren-mcp] Connected to MCP server 'search' via WebSocket
INFO  [lauren-mcp] Registered tools from 'search': search__search, search__get_item
INFO  [lauren-mcp] Connected to MCP server 'analytics' via HTTP+SSE
INFO  [lauren-mcp] Registered tools from 'analytics': analytics__daily_summary
```
