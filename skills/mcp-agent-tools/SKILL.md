---
skill: mcp-agent-tools
version: 3.0.0
tags: [mcp, agent, tools, AgentModule, McpServerConfig, McpToolBridge, lauren-ai, streamable-http, lauren-mcp]
summary: Wire MCP server tools into a lauren_ai AgentModule with tool namespacing, progress monitoring, and sampling.
---

# Skill: MCP Agent Tools

## When to use this skill

Use this skill when you need to:
- Make a `lauren_ai` AI agent able to call tools from remote MCP servers
- Understand how tool names are namespaced to avoid collisions
- Mix native agent tools with remote MCP tools
- Monitor progress, log, and catalog-change notifications from MCP servers
- Handle server-initiated sampling or elicitation requests in an agent
- Use `proxies=` composition as an alternative to the bridge for tighter integration

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

# MCP server configurations
mcp_servers = [
    # stdio: local subprocess
    McpServerConfig(
        alias="fs",
        client=McpServer.stdio(
            ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        ),
    ),
    # Streamable HTTP: recommended for remote services
    McpServerConfig(
        alias="search",
        client=McpServer.streamable_http("https://search-service.internal/mcp"),
    ),
    # WebSocket: still supported
    McpServerConfig(
        alias="analytics",
        client=McpServer.ws("ws://analytics:8080/mcp/ws"),
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

## `McpServerConfig` fields

```python
from lauren_mcp import McpServerConfig, McpServer

McpServerConfig(
    alias="my_server",      # prefix for namespaced tool names
    client=McpServer.streamable_http("https://api.example.com/mcp"),
)
```

Only two fields: `alias` and `client`. There is **no** `description` or
`tool_filter` field.

## Monitoring with notification handlers

Pass notification callbacks to the client factory when configuring
`McpServerConfig`. These are fired for each incoming notification:

```python
def on_progress(params: dict) -> None:
    pct = params.get("progress", 0) / (params.get("total") or 1) * 100
    print(f"Progress: {pct:.0f}% — {params.get('message', '')}")

def on_log(params: dict) -> None:
    print(f"[{params.get('level', 'info').upper()}] {params['data']['message']}")

def on_catalog_changed(kind: str) -> None:
    print(f"Server catalog changed: {kind}")

mcp_servers = [
    McpServerConfig(
        alias="search",
        client=McpServer.streamable_http(
            "https://search.internal/mcp",
            progress_handler=on_progress,
            log_handler=on_log,
            list_changed_handler=on_catalog_changed,
        ),
    ),
]
```

## Live resource updates

Subscribe to resource changes after the client is connected:

```python
client = McpServer.streamable_http(
    "https://api.internal/mcp",
    resource_updated_handler=lambda uri: reload_cache(uri),
)
cfg = McpServerConfig(alias="data", client=client)
```

The `resource_updated_handler` fires whenever the server pushes
`notifications/resources/updated` for a URI that the client has subscribed
to via `client.subscribe_resource(uri)`.

## Sampling handler — server asks the agent's LLM

When a tool on the remote MCP server calls `ctx.sample()`, the server sends
a `sampling/createMessage` request to the client. Provide a `sampling_handler`
so the agent's LLM can respond:

```python
async def handle_sampling(params: dict) -> dict:
    # params: {messages, maxTokens, systemPrompt, ...}
    # Use your LLM client here
    response = await my_llm_client.chat(
        messages=params.get("messages", []),
        max_tokens=params.get("maxTokens", 1024),
        system=params.get("systemPrompt"),
    )
    return {
        "role": "assistant",
        "content": {"type": "text", "text": response.text},
        "model": response.model,
        "stopReason": response.stop_reason,
    }

cfg = McpServerConfig(
    alias="tools",
    client=McpServer.streamable_http(
        url,
        sampling_handler=handle_sampling,
        sampling_tools=True,   # also advertise tool-enabled sampling support
    ),
)
```

## Elicitation handler — server asks for user input

```python
async def handle_elicitation(params: dict) -> dict:
    print(f"Server requests input: {params.get('message')}")
    # Show params["requestedSchema"] as a form to the user
    user_answer = input("> ")
    return {"action": "accept", "content": {"value": user_answer}}

cfg = McpServerConfig(
    alias="tools",
    client=McpServer.streamable_http(url, elicitation_handler=handle_elicitation),
)
```

## `McpToolBridge` — standalone usage without AgentModule

`McpToolBridge` can be used standalone when `lauren-ai` is not available, or
when you need programmatic control:

```python
from lauren_mcp import McpServerConfig, McpToolBridge, McpServer

bridge = McpToolBridge([
    McpServerConfig(alias="fs", client=McpServer.stdio(["npx", "...", "/tmp"])),
    McpServerConfig(alias="search", client=McpServer.streamable_http(url)),
])
# Optionally attach a tool registry (any object with register_mcp_server)
bridge.set_registry(my_registry)

await bridge.connect_all()
# ... use tools from the registry ...
await bridge.disconnect_all()
```

`connect_all()` iterates each config, calls `client.connect()`, fetches
`list_tools()`, and registers via `registry.register_mcp_server(alias, tools, client)`.
Individual connection failures are logged at ERROR and skipped.

## Server composition alternative — `proxies=` in `McpServerModule`

For tighter in-process integration, use `proxies=` on `McpServerModule.for_root()`
instead of the bridge. This registers remote tools in the local MCP catalog
under a prefix, making them directly accessible to clients of your server:

```python
from lauren_mcp import McpServer, McpServerModule, mcp_server, mcp_tool

@mcp_server("/mcp")
class GatewayServer:
    @mcp_tool()
    async def local_tool(self) -> str:
        return "from gateway"

@module(imports=[
    McpServerModule.for_root(
        GatewayServer,
        transport="streamable",
        proxies=[
            (McpServer.streamable_http("https://backend/mcp"), "backend_"),
        ],
    )
])
class AppModule: pass
```

Clients connecting to `GatewayServer` see both `local_tool` and
`backend_<tool>` for every tool on the remote server.

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
declared in two modules inside the same app. If you want multiple MCP servers,
pass them all to a single `AgentModule.for_root(mcp_servers=[...])` call.
