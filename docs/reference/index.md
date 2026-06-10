# API Reference

Complete reference for all public symbols in `lauren_mcp`.

## Server decorators

| Symbol | Import | Description |
|---|---|---|
| [`mcp_server`](server.md#mcp_server) | `from lauren_mcp import mcp_server` | Class decorator — registers an MCP server at a URL path |
| [`mcp_tool`](server.md#mcp_tool) | `from lauren_mcp import mcp_tool` | Method decorator — exposes an async method as an MCP tool |
| [`mcp_resource`](server.md#mcp_resource) | `from lauren_mcp import mcp_resource` | Method decorator — exposes a URI-addressable resource |
| [`mcp_prompt`](server.md#mcp_prompt) | `from lauren_mcp import mcp_prompt` | Method decorator — exposes a parameterised prompt template |
| [`mcp_lifespan`](server.md#mcp_lifespan) | `from lauren_mcp.server import mcp_lifespan` | Method decorator — async generator run at server startup/shutdown |
| [`McpServerModule`](server.md#mcpservermodule) | `from lauren_mcp import McpServerModule` | Lauren module factory that wires an `@mcp_server` class into the app |

## Server context and return types

| Symbol | Import | Description |
|---|---|---|
| [`McpToolContext`](server.md#mcptoolcontext) | `from lauren_mcp import McpToolContext` | Per-call context injected into `@mcp_tool` methods |
| [`ToolAnnotations`](server.md#toolannotations) | `from lauren_mcp import ToolAnnotations` | Behavioural hints for a tool (`readOnly`, `destructive`, etc.) |
| [`ToolOutput`](types.md#tooloutput) | `from lauren_mcp import ToolOutput` | Rich tool return type — separates display content from structured data |
| [`BlobResource`](types.md#blobresource) | `from lauren_mcp import BlobResource` | Binary resource return type |
| [`ResourceResult`](types.md#resourceresult) | `from lauren_mcp import ResourceResult` | Multi-item resource return type |

## Composition helpers

| Symbol | Import | Description |
|---|---|---|
| [`make_mount_binder`](server.md#make_mount_binder) | `from lauren_mcp.server import make_mount_binder` | Expose another `@mcp_server` class's tools through this server |
| [`make_proxy_binder`](server.md#make_proxy_binder) | `from lauren_mcp.server import make_proxy_binder` | Proxy a remote MCP server's tools through this server |
| [`McpToolNameCollision`](server.md#mcptoolnamecollision) | `from lauren_mcp import McpToolNameCollision` | Exception raised when two sources share the same tool name |
| [`build_openapi_server_class`](server.md#build_openapi_server_class) | `from lauren_mcp.server import build_openapi_server_class` | Generate an `@mcp_server` class from an OpenAPI 3.x spec |
| [`RouteEntry`](server.md#routeentry) | `from lauren_mcp.server import RouteEntry` | Routing rule for `build_openapi_server_class` |

## Client

| Symbol | Import | Description |
|---|---|---|
| [`McpServer`](client.md#mcpserver) | `from lauren_mcp import McpServer` | Factory with `stdio`, `ws`, `http`, and `streamable_http` class methods |
| [`McpClientProtocol`](client.md#mcpclientprotocol) | `from lauren_mcp import McpClientProtocol` | Abstract interface implemented by all transport clients |
| [`McpCallError`](client.md#mcpcallerror) | `from lauren_mcp import McpCallError` | Raised when the server returns a JSON-RPC error response |
| [`McpServerConfig`](client.md#mcpserverconfig) | `from lauren_mcp import McpServerConfig` | Pairs an alias with a client for use with `McpToolBridge` |
| [`McpToolBridge`](client.md#mcptoolbridge) | `from lauren_mcp import McpToolBridge` | Lifecycle manager for multiple MCP client connections |

## Wire types

| Symbol | Description |
|---|---|
| [`JsonRpcRequest`](types.md#jsonrpcrequest) | Outgoing/incoming JSON-RPC 2.0 request |
| [`JsonRpcNotification`](types.md#jsonrpcnotification) | JSON-RPC 2.0 notification (no `id`) |
| [`JsonRpcResponse`](types.md#jsonrpcresponse) | Successful JSON-RPC 2.0 response |
| [`JsonRpcError`](types.md#jsonrpcerror) | Error object embedded in `JsonRpcErrorResponse` |
| [`JsonRpcErrorResponse`](types.md#jsonrpcerrorresponse) | Error JSON-RPC 2.0 response |
| [`McpErrorCode`](types.md#mcperrorcode) | Enum of standard JSON-RPC and MCP error codes |
| [`parse_message`](types.md#parse_message) | Parse raw bytes/string into a typed JSON-RPC message |
| [`build_error_response`](types.md#build_error_response) | Construct a `JsonRpcErrorResponse` from code and message |
| [`ToolSchema`](types.md#toolschema) | JSON Schema descriptor for a tool (`tools/list`) |
| [`ToolCallParams`](types.md#toolcallparams) | Arguments for a `tools/call` request |
| [`ToolResult`](types.md#toolresult) | Full result envelope from a `tools/call` response |
| [`ResourceSchema`](types.md#resourceschema) | Descriptor for a resource (`resources/list`) |
| [`ResourceContent`](types.md#resourcecontent) | The contents of a read resource |
| [`ReadResourceParams`](types.md#readresourceparams) | Arguments for a `resources/read` request |
| [`ReadResourceResult`](types.md#readresourceresult) | Result envelope from a `resources/read` response |
| [`PromptArgument`](types.md#promptargument) | Single argument descriptor in a prompt schema |
| [`PromptSchema`](types.md#promptschema) | Descriptor for a prompt (`prompts/list`) |
| [`PromptMessage`](types.md#promptmessage) | A rendered message within a `GetPromptResult` |
| [`GetPromptParams`](types.md#getpromptparams) | Arguments for a `prompts/get` request |
| [`GetPromptResult`](types.md#getpromptresult) | Result envelope from a `prompts/get` response |
| [`TextContent`](types.md#textcontent) | Plain-text content block |
| [`ImageContent`](types.md#imagecontent) | Base-64 encoded image content block |
| [`EmbeddedResource`](types.md#embeddedresource) | Embedded resource content block |
| [`AnyContent`](types.md#anycontent) | Union alias: `TextContent \| ImageContent \| EmbeddedResource` |
| [`SamplingMessage`](types.md#samplingmessage) | A message in a `sampling/createMessage` request |
| [`CreateMessageParams`](types.md#createmessageparams) | Parameters for a `sampling/createMessage` request |
| [`CreateMessageResult`](types.md#createmessageresult) | Result of a `sampling/createMessage` request |
| [`ElicitResult`](types.md#elicitresult) | Result of an `elicitation/create` request |
| [`Root`](types.md#root) | A filesystem root advertised by the client |
| [`ClientCapabilities`](types.md#clientcapabilities) | Capability flags from the client during handshake |
| [`ServerCapabilities`](types.md#servercapabilities) | Capability flags from the server during handshake |
| [`Implementation`](types.md#implementation) | Name + version pair identifying a client or server |
| [`InitializeParams`](types.md#initializeparams) | Client capabilities sent during the MCP handshake |
| [`InitializeResult`](types.md#initializeresult) | Server capabilities returned during the MCP handshake |

## Exceptions

| Symbol | Description |
|---|---|
| [`McpCallError`](client.md#mcpcallerror) | JSON-RPC error response from a remote server |
| [`McpParseError`](types.md#mcpparseerror) | Invalid JSON or non-conforming JSON-RPC shape |
| [`McpSamplingNotAvailable`](types.md#mcpsamplingnotavailable) | `ctx.sample()` called but client lacks `sampling` capability |
| [`McpElicitationNotAvailable`](types.md#mcpelicitationnotavailable) | `ctx.elicit()` called but client lacks `elicitation` capability |
| [`McpToolNameCollision`](server.md#mcptoolnamecollision) | Two composition sources expose the same tool name |

## Version constants

| Symbol | Value | Description |
|---|---|---|
| `LATEST` | `"2025-03-26"` | Latest MCP protocol version supported by this library |
| `STABLE` | `"2024-11-05"` | Stable MCP protocol version recommended for production |
| `SUPPORTED` | `frozenset({...})` | All protocol version strings this library can handle |
