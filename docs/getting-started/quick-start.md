# Quick Start

Two complete, runnable examples that cover the two main usage modes.

---

## Example 1 — MCP Server

Expose a simple catalogue search service as an MCP server that any AI client can
discover and call over WebSocket or HTTP+SSE.

```python
# app.py
from __future__ import annotations

from lauren import Lauren
from lauren_mcp import mcp_server, mcp_tool, McpServerModule

CATALOGUE = [
    {"id": 1, "name": "Widget A", "tags": ["blue", "small"]},
    {"id": 2, "name": "Widget B", "tags": ["red", "large"]},
    {"id": 3, "name": "Gadget C", "tags": ["blue", "large"]},
]


@mcp_server("/mcp")
class CatalogueServer:
    """Catalogue MCP server — exposes search and lookup tools."""

    @mcp_tool()
    async def search(self, query: str) -> list[dict]:
        """Search the catalogue by name or tag.

        Args:
            query: Search terms to match against item names and tags.
        """
        q = query.lower()
        return [
            item for item in CATALOGUE
            if q in item["name"].lower() or any(q in t for t in item["tags"])
        ]

    @mcp_tool()
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
pip install "lauren-mcp[ws]" uvicorn
python app.py
```

Connect with any MCP client pointed at `ws://localhost:8000/mcp/ws`.

---

## Example 2 — MCP Client (stdio)

Connect to the official `@modelcontextprotocol/server-filesystem` stdio server and
make its tools available inside a Lauren agent.

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
