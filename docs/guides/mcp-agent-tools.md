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

## McpServerConfig

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
| `client` | `McpClientProtocol` | yes | A client created by `McpServer.stdio/ws/http/streamable_http` |

---

## Choosing a transport

`McpServer` provides four factory methods for creating clients:

| Factory | Transport | When to use |
|---|---|---|
| `McpServer.stdio(command)` | subprocess via stdin/stdout | local tools, CLI servers |
| `McpServer.ws(url)` | WebSocket | low-latency remote servers |
| `McpServer.streamable_http(url)` | Streamable HTTP (2025-03-26) | preferred for HTTP; supports progress and server-push |
| `McpServer.http(url)` | Legacy HTTP+SSE (2024-11-05) | older servers only |

`McpServer.streamable_http` is the recommended choice for any HTTP-based MCP
server.  It supports progress notifications, log streaming, and server-push
out of the box.

---

## AgentModule.for_root(mcp_servers=[...])

```python
from lauren import LaurenFactory, module
from lauren_ai import AgentModule
from lauren_mcp import McpServer, McpServerConfig

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
                    alias="analytics",
                    client=McpServer.streamable_http(
                        "http://analytics.internal/mcp",
                    ),
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
INFO lauren_ai.mcp._bridge: MCP bridge: loaded 2 tools from 'analytics'
INFO lauren_ai.mcp._bridge: MCP bridge:   analytics__daily_report
INFO lauren_ai.mcp._bridge: MCP bridge:   analytics__top_pages
```

---

## Tool namespacing

Every tool from a remote MCP server is prefixed with `{alias}__`:

| MCP server alias | Remote tool name | Namespaced name seen by agent |
|---|---|---|
| `fs` | `read_file` | `fs__read_file` |
| `fs` | `write_file` | `fs__write_file` |
| `analytics` | `daily_report` | `analytics__daily_report` |
| `analytics` | `top_pages` | `analytics__top_pages` |

This prevents collisions between tools from different servers and between MCP
tools and native agent tools.

---

## Monitoring tool execution

### Progress notifications

Register a progress handler to receive `notifications/progress` events while a
tool is running.  This is useful for surfacing status in an agent loop UI or
logging pipeline.

```python
import logging

_log = logging.getLogger(__name__)

def log_progress(params: dict) -> None:
    progress = params.get("progress", 0)
    total    = params.get("total")
    if total:
        _log.info("Tool progress: %.0f / %.0f", progress, total)
    else:
        _log.info("Tool progress: %.0f", progress)


client = McpServer.streamable_http(
    "http://analytics.internal/mcp",
    progress_handler=log_progress,
)
```

You can also register handlers after construction:

```python
client = McpServer.streamable_http("http://analytics.internal/mcp")

unsubscribe = client.on_progress(log_progress)
# later:
unsubscribe()   # removes the handler
```

### Log notifications

Servers can emit structured log messages via `ctx.log()` / `ctx.info()` etc.
(see [Using with Lauren](using-with-lauren.md)).  Register a log handler to
receive them on the client side:

```python
def handle_log(params: dict) -> None:
    level   = params.get("level", "info")
    logger  = params.get("logger", "mcp")
    data    = params.get("data") or {}
    message = data.get("message", "")
    _log.log(
        {"debug": logging.DEBUG, "info": logging.INFO,
         "warning": logging.WARNING, "error": logging.ERROR}.get(level, logging.INFO),
        "[%s] %s", logger, message,
    )


client = McpServer.streamable_http(
    "http://analytics.internal/mcp",
    log_handler=handle_log,
)
```

Or after construction:

```python
unsubscribe = client.on_log(handle_log)
```

### List-changed notifications

React when a server's tool/resource/prompt catalogue changes at runtime:

```python
async def refresh_catalogue(kind: str) -> None:
    # kind is "tools", "resources", or "prompts"
    print(f"Server catalogue changed: {kind}")
    new_tools = await client.list_tools()
    update_agent_tool_map(new_tools)

client.on_list_changed(refresh_catalogue)
```

---

## Sampling: server calls back to run an LLM

Some MCP servers use MCP sampling to delegate an LLM sub-call back to the
client (the agent) rather than calling an LLM directly.  Register a
`sampling_handler` to handle these requests:

```python
import anthropic

_anthropic = anthropic.Anthropic()

async def sampling_handler(params: dict) -> dict:
    """Handle a sampling/createMessage request from the server."""
    messages = [
        {"role": m["role"], "content": m["content"]["text"]}
        for m in params.get("messages", [])
    ]
    response = _anthropic.messages.create(
        model="claude-opus-4-5",
        max_tokens=params.get("maxTokens", 1024),
        messages=messages,
    )
    return {
        "role": "assistant",
        "content": {"type": "text", "text": response.content[0].text},
        "model": response.model,
        "stopReason": response.stop_reason,
    }


client = McpServer.streamable_http(
    "http://analytics.internal/mcp",
    sampling_handler=sampling_handler,
)
```

The client advertises the `sampling` capability during the handshake.  If the
server tries to sample but the client did not register a handler, the server
raises `McpSamplingNotAvailable`.

> **Note**: `sampling_handler` is supported by WebSocket and Streamable HTTP
> transports.  Legacy HTTP+SSE does not support server-to-client requests.

---

## Roots: file-system-aware tools

Provide a `roots` list to advertise the file-system paths the agent is allowed
to access.  Servers that respect the `roots` capability will scope their
operations accordingly.

```python
from lauren_mcp import McpServer, Root

client = McpServer.stdio(
    ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/workspace"],
    roots=[Root(uri="file:///workspace", name="Workspace")],
)
```

Pass a callable to provide dynamic roots:

```python
def get_current_roots() -> list[Root]:
    return [Root(uri=f"file://{current_project_path()}", name="Project")]

client = McpServer.stdio(
    ["python", "server.py"],
    roots=get_current_roots,           # called each time the server asks
)

# Notify the server when roots change:
await client.notify_roots_changed()
```

---

## Full example: McpToolBridge in an agent loop

`McpToolBridge` manages lifecycle for a set of `McpServerConfig` entries.
Use it when building an agent outside of a Lauren app (e.g. a standalone
script):

```python
import asyncio, logging
from lauren_mcp import McpServer, McpToolBridge, McpServerConfig, Root

logging.basicConfig(level=logging.INFO)

def log_progress(params: dict) -> None:
    logging.info("progress: %s/%s", params.get("progress"), params.get("total"))

def log_msg(params: dict) -> None:
    data = params.get("data") or {}
    logging.info("[server log] %s", data.get("message", ""))

mcp_servers = [
    McpServerConfig(
        alias="fs",
        client=McpServer.stdio(
            ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
            roots=[Root(uri="file:///tmp", name="Temp")],
        ),
    ),
    McpServerConfig(
        alias="analytics",
        client=McpServer.streamable_http(
            "http://analytics.internal/mcp",
            progress_handler=log_progress,
            log_handler=log_msg,
        ),
    ),
]

bridge = McpToolBridge(mcp_servers)

async def run_agent():
    await bridge.connect_all()

    # List all available tools (namespaced)
    for config in mcp_servers:
        tools = await config.client.list_tools()
        for t in tools:
            print(f"{config.alias}__{t.name}: {t.description}")

    # Call a tool directly via its client
    result = await mcp_servers[0].client.call_tool(
        "read_file", {"path": "/tmp/notes.txt"}
    )
    print(result["content"][0]["text"])

    await bridge.disconnect_all()

asyncio.run(run_agent())
```

### Partial failures

`connect_all()` catches exceptions per server and logs them at `ERROR` level.
A server that fails to connect does not prevent other servers from loading:

```
ERROR lauren_mcp._bridge: MCP bridge: failed to connect 'broken': ConnectionRefusedError
INFO  lauren_mcp._bridge: MCP bridge: loaded 2 tools from 'analytics'
```

The application starts even if some MCP servers are unavailable.  Their tools
are simply absent from the tool catalogue.

---

## Mixing native and MCP tools

Native tools (`@use_tools(...)` on the agent class) and MCP tools coexist:

```python
from lauren_ai import agent, use_tools, AgentModule
from lauren_mcp import McpServer, McpServerConfig

@agent(model="claude-opus-4-5", system="You are a helpful assistant.")
@use_tools(GetCartTool, CheckoutTool)
class ShopAgent:
    pass

AgentModule.for_root(
    agents=[ShopAgent],
    mcp_servers=[
        McpServerConfig(
            alias="fs",
            client=McpServer.stdio(["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]),
        ),
    ],
)
# Agent tool list: get_cart, checkout (native) + fs__read_file, ... (MCP)
```

---

## Startup log

At `INFO` level each registered tool name is logged.  Reference these names in
your agent's system prompt so the LLM knows to use them:

```
Available MCP tools:
- fs__read_file: Read a file from the filesystem.
- fs__list_directory: List files in a directory.
- analytics__daily_report: Generate a daily analytics report.
```

---

## Next steps

- **[Multiple servers](multiple-servers.md)** — `mounts=`, `proxies=`, OpenAPI import
- **[Using with Lauren](using-with-lauren.md)** — `@mcp_lifespan`, `McpToolContext`, progress from the server side
- **[Error handling](error-handling.md)** — `McpCallError`, retry patterns
