# Guides

Practical, task-oriented guides for every major feature of `lauren-mcp`.

| Guide | Description |
|---|---|
| [MCP Server](mcp-server.md) | Expose a Lauren service as an MCP server using `@mcp_server`, `@mcp_tool`, `@mcp_resource`, and `@mcp_prompt` |
| [MCP Client](mcp-client.md) | Connect to remote MCP servers over stdio, WebSocket, or HTTP+SSE using `McpServer` factory methods |
| [Agent Tools](mcp-agent-tools.md) | Wire MCP server tools into a Lauren `AgentModule` with tool namespacing and system prompt guidance |
| [Testing](testing.md) | Test MCP servers with real subprocesses, mock `McpClientProtocol`, and use `pytest.mark.eval` for live tests |
