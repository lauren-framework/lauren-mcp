# Quick Start

Two complete, runnable examples that cover the two main usage modes.

---

## Example 1 — MCP Server

Expose a catalogue search service as an MCP server. This example shows:

- `@mcp_lifespan` for startup/shutdown resource management
- `@mcp_tool` with `ToolAnnotations` and per-parameter docstring descriptions
- `McpToolContext` for progress reporting and structured logging
- `McpServerModule.for_root()` wired into a Lauren app

```python
# app.py
from __future__ import annotations

from lauren import Lauren
from lauren_mcp import (
    McpServerModule,
    McpToolContext,
    ToolAnnotations,
    mcp_lifespan,
    mcp_server,
    mcp_tool,
)

CATALOGUE = [
    {"id": 1, "name": "Widget A", "tags": ["blue", "small"]},
    {"id": 2, "name": "Widget B", "tags": ["red", "large"]},
    {"id": 3, "name": "Gadget C", "tags": ["blue", "large"]},
]


@mcp_server("/mcp", transport="streamable")
class CatalogueServer:
    """Catalogue MCP server — exposes search and lookup tools."""

    @mcp_lifespan
    async def lifespan(self):
        # Set up shared resources at startup; tear them down at shutdown.
        print("CatalogueServer starting up")
        try:
            yield {"catalogue": CATALOGUE}
        finally:
            print("CatalogueServer shutting down")

    @mcp_tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    async def search(
        self,
        query: str,
        limit: int = 10,
        ctx: McpToolContext = None,  # type: ignore[assignment]
    ) -> list[dict]:
        """Search the catalogue by name or tag.

        Args:
            query: Search terms to match against item names and tags.
            limit: Maximum number of results to return.
        """
        await ctx.report_progress(0, 1)
        await ctx.info(f"Searching for {query!r}")

        catalogue = ctx.lifespan_context["catalogue"]
        q = query.lower()
        results = [
            item for item in catalogue
            if q in item["name"].lower() or any(q in t for t in item["tags"])
        ][:limit]

        await ctx.report_progress(1, 1)
        return results

    @mcp_tool(annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False))
    async def get_item(self, item_id: int) -> dict | None:
        """Fetch a single catalogue item by its numeric ID.

        Args:
            item_id: The numeric ID of the item to retrieve.
        """
        return next((i for i in CATALOGUE if i["id"] == item_id), None)


app = Lauren()
app.include_module(McpServerModule.for_root(CatalogueServer))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

Run it:

```bash
pip install "lauren-mcp" uvicorn
python app.py
```

Connect with any MCP client that supports Streamable HTTP (MCP 2025-03-26) pointed at
`http://localhost:8000/mcp`.

!!! tip "Choosing a transport"
    The example uses `transport="streamable"` (MCP 2025-03-26). Switch to `"ws"` for
    WebSocket (the default), `"sse"` for legacy HTTP+SSE, or `"all"` to serve both
    WebSocket and Streamable HTTP simultaneously from the same path.

---

## Example 2 — MCP Client (Streamable HTTP)

Connect to the server from Example 1 and call its tools programmatically, using the
Streamable HTTP transport introduced in MCP 2025-03-26.

```python
# client.py
from __future__ import annotations

import asyncio

from lauren_mcp import McpServer


async def main() -> None:
    client = McpServer.streamable_http(
        "http://localhost:8000/mcp",
        progress_handler=lambda p: print(f"Progress: {p}"),
        log_handler=lambda m: print(f"[{m.get('level', 'info')}] {m.get('data', {}).get('message', '')}"),
    )

    await client.connect()
    print(f"Connected — protocol version: {client.protocol_version}")

    # List available tools
    tools = await client.list_tools()
    print(f"Tools: {[t.name for t in tools]}")

    # Call the search tool
    result = await client.call_tool("search", {"query": "blue", "limit": 5})
    print("Search results:", result)

    # Call the get_item tool
    item = await client.call_tool("get_item", {"item_id": 1})
    print("Item:", item)

    await client.close()


if __name__ == "__main__":
    asyncio.run(main())
```

Run it (with the server from Example 1 already running):

```bash
pip install "lauren-mcp[http]"
python client.py
```

Expected output:

```
Connected — protocol version: 2025-03-26
Tools: ['search', 'get_item']
Search results: [{'content': [...], ...}]
Item: [{'content': [...], ...}]
```

!!! note "Using other transports"
    To connect to a WebSocket server use `McpServer.ws("ws://localhost:8000/mcp/ws")`.
    For legacy HTTP+SSE servers use `McpServer.http("http://localhost:8000/mcp")`.
    For a stdio subprocess use `McpServer.stdio(["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"])`.
    All four factory methods accept the same optional keyword arguments (`progress_handler`,
    `log_handler`, `list_changed_handler`, `sampling_handler`, `elicitation_handler`, `roots`).

---

## Example 3 — MCP Client (stdio)

Connect to the official `@modelcontextprotocol/server-filesystem` stdio server and
make its tools available inside a Lauren agent module.

```python
# agent_app.py
from __future__ import annotations

from lauren import Lauren
from lauren_mcp import McpServer, McpServerConfig
from lauren.contrib.ai import AgentModule  # hypothetical agent integration

mcp_servers = [
    McpServerConfig(
        alias="fs",
        client=McpServer.stdio(
            ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        ),
    ),
]

app = Lauren()
app.include_module(
    AgentModule.for_root(
        model="claude-opus-4-5",
        mcp_servers=mcp_servers,
    )
)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
```

After startup you will see log lines like:

```
INFO  [lauren-mcp] Connected to MCP server 'fs' via stdio
INFO  [lauren-mcp] Registered tools: fs__read_file, fs__write_file, fs__list_directory
```

The agent can now call `fs__read_file`, `fs__write_file`, and `fs__list_directory`
in addition to any native tools you have defined.
