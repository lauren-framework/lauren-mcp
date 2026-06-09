# MCP Agent Tools Guide

This guide shows how to wire remote MCP server tools into a Lauren `AgentModule` so
that an AI agent can discover and call them alongside its native tools.

---

## Overview

`AgentModule.for_root(mcp_servers=[...])` accepts a list of `McpServerConfig` objects.
At application startup the module:

1. Connects to each MCP server using the configured transport.
2. Calls `tools/list` to fetch the server's tool manifest.
3. Registers each tool under a namespaced name: `{alias}__{tool_name}`.
4. Prepends a tool catalogue section to the agent's system prompt.

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
| `description` | `str \| None` | no | Human description injected into the system prompt |
| `tool_filter` | `list[str] \| None` | no | Whitelist of tool names to expose (all if `None`) |

---

## `AgentModule.for_root(mcp_servers=[...])`

```python
from lauren import Lauren
from lauren_mcp import McpServer, McpServerConfig
from lauren.contrib.ai import AgentModule

app = Lauren()
app.include(
    AgentModule.for_root(
        model="claude-opus-4-5",
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
                description="Catalogue search service",
            ),
        ],
    )
)
```

At startup you will see log output like:

```
INFO  [lauren-mcp] Connected to MCP server 'fs' via stdio
INFO  [lauren-mcp] Registered tools from 'fs': fs__read_file, fs__write_file, fs__list_directory
INFO  [lauren-mcp] Connected to MCP server 'search' via WebSocket
INFO  [lauren-mcp] Registered tools from 'search': search__search, search__get_item
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

This prevents collisions between tools from different servers and between MCP tools and
native agent tools.

---

## Updating the system prompt

`AgentModule.for_root` automatically appends a tool catalogue to the system prompt:

```
You have access to the following MCP tools:

**fs** (Filesystem server):
- fs__read_file(path: str) → Read the contents of a file.
- fs__write_file(path: str, content: str) → Write content to a file.
- fs__list_directory(path: str) → List files in a directory.

**search** (Catalogue search service):
- search__search(query: str) → Search the catalogue by name or tag.
- search__get_item(item_id: int) → Retrieve a catalogue item by ID.
```

To customise the system prompt further, pass a `system_prompt` argument — the MCP tool
catalogue will be appended after it:

```python
AgentModule.for_root(
    model="claude-opus-4-5",
    system_prompt="You are a helpful assistant for our e-commerce platform.",
    mcp_servers=[...],
)
```

---

## Mixing native and MCP tools

Native tools (defined with `@tool` on the agent class) and MCP tools coexist without
conflict as long as their names do not collide. Native tools are registered without any
prefix; MCP tools always use the `alias__` prefix.

```python
from lauren.contrib.ai import agent, tool, AgentModule
from lauren_mcp import McpServer, McpServerConfig

@agent
class ShopAgent:
    @tool
    async def get_cart(self, user_id: str) -> dict:
        """Get the current cart for a user."""
        ...

    @tool
    async def checkout(self, user_id: str) -> str:
        """Checkout the current cart for a user."""
        ...

app = Lauren()
app.include(
    AgentModule.for_root(
        agent=ShopAgent,
        mcp_servers=[
            McpServerConfig(
                alias="fs",
                client=McpServer.stdio([...]),
            ),
        ],
    )
)
# Agent has: get_cart, checkout (native) + fs__read_file, fs__write_file, ... (MCP)
```

---

## Tool filtering

Use `tool_filter` to expose only a subset of a server's tools:

```python
McpServerConfig(
    alias="fs",
    client=McpServer.stdio([...]),
    tool_filter=["read_file", "list_directory"],  # write_file is excluded
)
```

This is useful for security (preventing write access in read-only agents) or to reduce
prompt noise when the remote server exposes many tools.

---

## Startup log output

At `DEBUG` level you will see the full tool schema for each registered tool:

```
DEBUG [lauren-mcp] Tool schema for fs__read_file:
  {"type": "object", "properties": {"path": {"type": "string", ...}}, "required": ["path"]}
```

At `INFO` level only the tool names are logged.
