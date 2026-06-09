# API Reference

Complete reference for all public symbols in `lauren_mcp`.

## Server decorators

| Symbol | Description |
|---|---|
| [`mcp_server`](server.md#mcp_server) | Class decorator that registers an MCP server at a URL path |
| [`mcp_tool`](server.md#mcp_tool) | Method decorator that exposes an async method as an MCP tool |
| [`mcp_resource`](server.md#mcp_resource) | Method decorator that exposes a URI-addressable resource |
| [`mcp_prompt`](server.md#mcp_prompt) | Method decorator that exposes a parameterised prompt template |
| [`McpServerModule`](server.md#mcpservermodule) | Lauren module that wires all `@mcp_server` classes into the app |

## Client

| Symbol | Description |
|---|---|
| [`McpServer`](client.md#mcpserver) | Factory class with `stdio`, `ws`, and `http` class methods |
| [`McpClientProtocol`](client.md#mcpclientprotocol) | Protocol/interface implemented by all transport clients |
| [`McpServerConfig`](client.md#mcpserverconfig) | Dataclass pairing an alias with an `McpClientProtocol` instance |
| [`McpToolBridge`](client.md#mcptoolbridge) | Adapts a remote MCP server's tools for use inside a Lauren agent |

## Wire types

| Symbol | Description |
|---|---|
| [`JsonRpcRequest`](types.md#jsonrpcrequest) | Outgoing JSON-RPC 2.0 request message |
| [`JsonRpcNotification`](types.md#jsonrpcnotification) | Outgoing JSON-RPC 2.0 notification (no `id`) |
| [`JsonRpcResponse`](types.md#jsonrpcresponse) | Successful JSON-RPC 2.0 response message |
| [`JsonRpcErrorResponse`](types.md#jsonrpcerrorresponse) | Error JSON-RPC 2.0 response message |
| [`McpErrorCode`](types.md#mcperrorcode) | Enum of standard MCP/JSON-RPC error codes |
| [`parse_message`](types.md#parse_message) | Parse raw bytes/string into a JSON-RPC message object |
| [`build_error_response`](types.md#build_error_response) | Construct a `JsonRpcErrorResponse` from an error code and message |
| [`ToolSchema`](types.md#toolschema) | JSON Schema descriptor for a single MCP tool |
| [`ResourceSchema`](types.md#resourceschema) | Descriptor for a single MCP resource |
| [`PromptSchema`](types.md#promptschema) | Descriptor for a single MCP prompt |
| [`TextContent`](types.md#textcontent) | Text content block returned by tool calls |
| [`ImageContent`](types.md#imagecontent) | Base-64 encoded image content block returned by tool calls |
| [`EmbeddedResource`](types.md#embeddedresource) | Embedded resource content block |
| [`PromptArgument`](types.md#promptargument) | Single argument descriptor in a prompt schema |
| [`PromptMessage`](types.md#promptmessage) | A rendered message within a `GetPromptResult` |
| [`InitializeParams`](types.md#initializeparams) | Client capabilities sent during the MCP handshake |
| [`InitializeResult`](types.md#initializeresult) | Server capabilities returned during the MCP handshake |
| [`ClientCapabilities`](types.md#clientcapabilities) | Nested capabilities block from the client |
| [`ServerCapabilities`](types.md#servercapabilities) | Nested capabilities block from the server |
| [`Implementation`](types.md#implementation) | Name + version block identifying a client or server |
| [`ToolCallParams`](types.md#toolcallparams) | Arguments for a `tools/call` request |
| [`ToolResult`](types.md#toolresult) | Full result envelope from a `tools/call` response |
| [`ReadResourceParams`](types.md#readresourceparams) | Arguments for a `resources/read` request |
| [`ReadResourceResult`](types.md#readresourceresult) | Result envelope from a `resources/read` response |
| [`GetPromptParams`](types.md#getpromptparams) | Arguments for a `prompts/get` request |
| [`GetPromptResult`](types.md#getpromptresult) | Result envelope from a `prompts/get` response |

## Version constants

| Symbol | Description |
|---|---|
| `LATEST` | Latest MCP protocol version string supported by this library |
| `STABLE` | Stable MCP protocol version string recommended for production |
| `SUPPORTED` | List of all MCP protocol version strings this library can handle |
