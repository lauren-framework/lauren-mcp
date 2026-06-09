#!/usr/bin/env python3
"""Generate docs/generated-reference/ pages from lauren_mcp public API."""
from __future__ import annotations
import pathlib

PAGES = {
    "docs/generated-reference/server.md": """# Server API Reference

::: lauren_mcp.server
    options:
      members:
        - mcp_server
        - mcp_tool
        - mcp_resource
        - mcp_prompt
        - McpServerModule
""",
    "docs/generated-reference/client.md": """# Client API Reference

::: lauren_mcp
    options:
      members:
        - McpServer
        - McpClientProtocol
        - McpServerConfig
        - McpToolBridge
""",
    "docs/generated-reference/types.md": """# Wire Types Reference

::: lauren_mcp
    options:
      members:
        - JsonRpcRequest
        - JsonRpcNotification
        - JsonRpcResponse
        - JsonRpcErrorResponse
        - McpErrorCode
        - parse_message
        - build_error_response
        - ToolSchema
        - ResourceSchema
        - PromptSchema
        - TextContent
        - ImageContent
        - EmbeddedResource
        - PromptArgument
        - PromptMessage
        - InitializeParams
        - InitializeResult
        - ClientCapabilities
        - ServerCapabilities
        - Implementation
        - ToolCallParams
        - ToolResult
        - ReadResourceParams
        - ReadResourceResult
        - GetPromptParams
        - GetPromptResult
""",
}


def main() -> None:
    root = pathlib.Path(__file__).parent.parent
    for rel_path, content in PAGES.items():
        p = root / rel_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        print(f"Written: {rel_path}")


if __name__ == "__main__":
    main()
