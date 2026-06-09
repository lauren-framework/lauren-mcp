# MCP Agent Tools Guide

This guide shows how to wire remote MCP server tools into a `lauren_ai`
`AgentModule` so that an AI agent can discover and call them alongside its
native tools.

---

## Overview

`AgentModule.for_root(mcp_servers=[...])` accepts a list of `McpServerConfig`
objects.  At application startup the module:

1. Connects to each MCP server using the configured transport.
2. Calls `tools/list` to fetch the server's tool manifest.
3. Registers each tool under a namespaced name: `{alias}__{tool_name}`.
4. Injects the namespaced tools into every agent's tool map.

---

## `McpServerConfig`

```python
from lauren_mcp import McpServer, McpServerConfig

McpServerConfig(
    alias="fs",
    client=McpServer.stdio(["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]),
)
```

**Fields**

| Field | Type | Required | Description |
|---|---|---|---|
| `alias` | `str` | yes | Short name used to namespace tools: `alias__tool_name` |
| `client` | `McpClientProtocol` | yes | A client created by `McpServer.stdio/ws/http` |

---

## `AgentModule.for_root(mcp_servers=[...])`

```python
from lauren import LaurenFactory, module
from lauren_ai import AgentModule
from lauren_ai._config import AgentConfig, LLMConfig
from lauren_mcp import McpServer, McpServerConfig

# Define your agents (from lauren_ai)
# @agent(model="claude-opus-4-8")
# class MyAgent: ...

@module(
    imports=[
        AgentModule.for_root(
            agents=[MyAgent],
            mcp_servers=[
                McpServerConfig(
                    alias="fs",
                    client=McpServer.stdio(
                        ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
                    ),
                ),
                McpServerConfig(
                    alias="search",
                    client=McpServer.ws("ws://search-service:8080/mcp/ws"),
                ),
            ],
        )
    ]
)
class AppModule:
    pass

app = LaurenFactory.create(AppModule)
```

At startup you will see log output like:

```
INFO lauren_ai.mcp._bridge: MCP bridge: loaded 3 tools from 'fs'
INFO lauren_ai.mcp._bridge: MCP bridge:   fs__read_file
INFO lauren_ai.mcp._bridge: MCP bridge:   fs__write_file
INFO lauren_ai.mcp._bridge: MCP bridge:   fs__list_directory
INFO lauren_ai.mcp._bridge: MCP bridge: loaded 2 tools from 'search'
INFO lauren_ai.mcp._bridge: MCP bridge:   search__search
INFO lauren_ai.mcp._bridge: MCP bridge:   search__get_item
```

---

## Tool namespacing

Every tool from a remote MCP server is prefixed with `{alias}__`:

| MCP server alias | Remote tool name | Namespaced name seen by agent |
|---|---|---|
| `fs` | `read_file` | `fs__read_file` |
| `fs` | `write_file` | `fs__write_file` |
| `search` | `search` | `search__search` |
| `search` | `get_item` | `search__get_item` |

This prevents collisions between tools from different servers and between MCP
tools and native agent tools.

---

## Mixing native and MCP tools

Native tools (`@use_tools(...)` on the agent class) and MCP tools coexist:

```python
from lauren_ai import agent, use_tools, AgentModule
from lauren_mcp import McpServer, McpServerConfig

@agent(model="claude-opus-4-8", system="You are a helpful assistant.")
@use_tools(GetCartTool, CheckoutTool)
class ShopAgent:
    pass

AgentModule.for_root(
    agents=[ShopAgent],
    mcp_servers=[
        McpServerConfig(
            alias="fs",
            client=McpServer.stdio([...]),
        ),
    ],
)
# Agent tool list: get_cart, checkout (native) + fs__read_file, ... (MCP)
```

---

## Connection errors

If a server fails to connect at startup, the error is logged at `ERROR` level
and the remaining servers continue loading:

```
ERROR lauren_ai.mcp._bridge: MCP bridge: failed to connect 'broken': ConnectionRefusedError
INFO  lauren_ai.mcp._bridge: MCP bridge: loaded 2 tools from 'ok_server'
```

The application starts even if some MCP servers are unavailable.  Their tools
are simply absent from the agent tool list.

---

## Startup log

At `INFO` level each registered tool name is logged.  Reference these names in
your agent's system prompt so the LLM knows to use them:

```
Available MCP tools:
- fs__read_file: Read a file from the filesystem.
- fs__list_directory: List files in a directory.
- search__search: Search the product catalogue.
```
