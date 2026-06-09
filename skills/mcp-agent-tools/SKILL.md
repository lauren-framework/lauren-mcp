---
skill: mcp-agent-tools
version: 2.0.0
tags: [mcp, agent, tools, AgentModule, McpServerConfig, lauren-ai, lauren-mcp]
summary: Wire MCP server tools into a lauren_ai AgentModule with tool namespacing.
---

# Skill: MCP Agent Tools

## When to use this skill

Use this skill when you need to:
- Make a `lauren_ai` AI agent able to call tools from remote MCP servers
- Understand how tool names are namespaced to avoid collisions
- Mix native agent tools with remote MCP tools

## Complete example

```python
# app.py
from __future__ import annotations

from lauren import LaurenFactory, module
from lauren_ai import AgentModule, agent, use_tools
from lauren_mcp import McpServer, McpServerConfig

# Native tools are defined via @use_tools on the agent class
@agent(model="claude-opus-4-8", system="You are a helpful shop assistant.")
@use_tools(GetCartTool, CheckoutTool)
class ShopAgent:
    pass

# MCP server configurations — only alias and client
mcp_servers = [
    # stdio: local subprocess
    McpServerConfig(
        alias="fs",
        client=McpServer.stdio(
            ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        ),
    ),
    # WebSocket: remote search service
    McpServerConfig(
        alias="search",
        client=McpServer.ws("ws://search-service:8080/mcp/ws"),
    ),
]

@module(
    imports=[
        AgentModule.for_root(
            agents=[ShopAgent],
            mcp_servers=mcp_servers,
        )
    ]
)
class AppModule:
    pass

app = LaurenFactory.create(AppModule)
```

## Tool namespace reference

After startup the agent sees these tools (example):

| Source | Original name | Namespaced name |
|---|---|---|
| Native | `get_cart` | `get_cart` |
| Native | `checkout` | `checkout` |
| `fs` (MCP) | `read_file` | `fs__read_file` |
| `fs` (MCP) | `list_directory` | `fs__list_directory` |
| `search` (MCP) | `search` | `search__search` |
| `search` (MCP) | `get_item` | `search__get_item` |

Double underscore (`__`) separates alias from tool name.

## McpServerConfig fields

```python
from lauren_mcp import McpServerConfig, McpServer

# Only two fields — alias and client
McpServerConfig(
    alias="fs",
    client=McpServer.stdio(["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]),
)
```

There is **no** `description` or `tool_filter` field.

## Startup log output

```
INFO lauren_ai.mcp._bridge: MCP bridge: loaded 3 tool(s) from 'fs'
INFO lauren_ai.mcp._bridge: MCP bridge:   fs__read_file
INFO lauren_ai.mcp._bridge: MCP bridge:   fs__write_file
INFO lauren_ai.mcp._bridge: MCP bridge:   fs__list_directory
INFO lauren_ai.mcp._bridge: MCP bridge: loaded 2 tool(s) from 'search'
INFO lauren_ai.mcp._bridge: MCP bridge:   search__search
INFO lauren_ai.mcp._bridge: MCP bridge:   search__get_item
```

## Connection errors

If a server fails to connect at startup, the error is logged at ERROR level and
the remaining servers continue loading:

```
ERROR lauren_ai.mcp._bridge: MCP bridge: failed to connect 'broken': ConnectionRefusedError
INFO  lauren_ai.mcp._bridge: MCP bridge: loaded 2 tool(s) from 'search'
```

## Important: separate Lauren apps per server

Lauren's module system does not allow the same `McpDispatcher` provider to be
declared in two modules inside the same app.  If you want multiple MCP servers,
pass them all to a single `AgentModule.for_root(mcp_servers=[...])` call.
