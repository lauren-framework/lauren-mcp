# Multiple MCP Servers

A single Lauren AI application can connect to several MCP servers simultaneously.
Tool names are **namespaced** with an alias so names from different servers
never collide.

---

## 1. Configure multiple servers

Pass a list of `McpServerConfig` objects when building the agent module:

```python
from lauren import Lauren
from lauren_mcp import McpServer, McpServerConfig

mcp_servers = [
    McpServerConfig(
        alias="fs",
        client=McpServer.stdio(
            ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        ),
    ),
    McpServerConfig(
        alias="shop",
        client=McpServer.ws("ws://shop-service.internal/mcp/ws"),
    ),
]
```

---

## 2. Tool namespacing

Each tool is registered as `{alias}__{tool_name}`.  If the filesystem server
exposes `read_file` and `list_directory`, and the shop server exposes `search`
and `get_product`, the combined tool catalogue looks like:

```
fs__read_file
fs__list_directory
fs__write_file
shop__search
shop__get_product
```

This means two servers can both expose a tool called `search` without conflict:
the first becomes `fs__search` and the second `shop__search`.

---

## 3. Call a namespaced tool

From a client that connects to a bridge or agent, use the full namespaced name:

```python
from lauren_mcp import McpServer, McpToolBridge, McpServerConfig

async def main():
    # McpToolBridge manages lifecycle for a set of McpServerConfig entries
    from lauren_mcp._bridge import McpToolBridge, McpServerConfig

    client_a = McpServer.stdio(["python", "server_a.py"])
    client_b = McpServer.stdio(["python", "server_b.py"])

    bridge = McpToolBridge([
        McpServerConfig(alias="alpha", client=client_a),
        McpServerConfig(alias="beta", client=client_b),
    ])

    # Manually connect to inspect namespaced tools
    await client_a.connect()
    await client_b.connect()

    tools_a = await client_a.list_tools()
    tools_b = await client_b.list_tools()

    print("alpha tools:", [f"alpha__{t.name}" for t in tools_a])
    print("beta tools:",  [f"beta__{t.name}"  for t in tools_b])

    # Call a tool on server_b via client_b
    result = await client_b.call_tool("echo", {"text": "hello beta"})
    print(result["content"][0]["text"])

    await client_a.close()
    await client_b.close()
```

---

## 4. Handling a broken server

`McpToolBridge.connect_all()` catches exceptions per server and logs them at
ERROR level.  A server that fails to connect does not prevent other servers
from loading:

```python
from lauren_mcp import McpServer, McpToolBridge, McpServerConfig

bridge = McpToolBridge([
    McpServerConfig(alias="broken", client=McpServer.stdio(["false"])),  # will fail
    McpServerConfig(alias="working", client=McpServer.stdio(["python", "server.py"])),
])

# broken server fails silently; working server loads successfully
await bridge.connect_all()
```

Configure your registry to handle the partial load gracefully — only the tools
from successfully connected servers will be available.

---

## 5. Graceful shutdown

Call `disconnect_all()` (or `McpToolBridge.disconnect_all()`) to cleanly close
all connections:

```python
await bridge.disconnect_all()
```

Each client receives a close call; exceptions during individual closes are
suppressed so every client gets a close attempt.

---

## 6. Example: two independent echo servers

This end-to-end example connects two separate echo servers and calls a tool
on each:

```python
import asyncio
from lauren_mcp import McpServer

ECHO_SCRIPT = '''
import sys, json

for line in sys.stdin:
    msg = json.loads(line.strip())
    method = msg.get("method")
    id_ = msg.get("id")
    if method == "initialize":
        print(json.dumps({"jsonrpc":"2.0","id":id_,"result":{
            "protocolVersion":"2025-03-26",
            "capabilities":{"tools":{}},
            "serverInfo":{"name":"echo","version":"1.0.0"}
        }}), flush=True)
    elif method == "tools/list":
        print(json.dumps({"jsonrpc":"2.0","id":id_,"result":{"tools":[{
            "name":"echo","description":"Echo text.",
            "inputSchema":{"type":"object",
                "properties":{"text":{"type":"string"}},"required":["text"]}
        }]}}), flush=True)
    elif method == "tools/call":
        args = (msg.get("params") or {}).get("arguments", {})
        print(json.dumps({"jsonrpc":"2.0","id":id_,"result":{
            "content":[{"type":"text","text":args.get("text","")}],
            "isError":False
        }}), flush=True)
    elif method == "ping":
        print(json.dumps({"jsonrpc":"2.0","id":id_,"result":{}}), flush=True)
'''

async def main():
    import sys, os, tempfile

    # Write echo script to a temp file
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(ECHO_SCRIPT)
        script = f.name

    try:
        client_a = McpServer.stdio([sys.executable, script])
        client_b = McpServer.stdio([sys.executable, script])
        await client_a.connect()
        await client_b.connect()

        result_a = await client_a.call_tool("echo", {"text": "from server A"})
        result_b = await client_b.call_tool("echo", {"text": "from server B"})

        print(result_a["content"][0]["text"])  # "from server A"
        print(result_b["content"][0]["text"])  # "from server B"

        await client_a.close()
        await client_b.close()
    finally:
        os.unlink(script)

asyncio.run(main())
```

---

## Next steps

- **[Testing](testing.md)** — test multi-server setups with mock clients
- **[Error handling](error-handling.md)** — retry, timeout, and failure patterns
