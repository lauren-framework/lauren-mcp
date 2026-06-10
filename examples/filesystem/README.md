# Filesystem MCP Server

A production-quality example MCP server that exposes a sandboxed filesystem as
a set of CRUD tools, a file resource, and an edit prompt.

## Installation

```bash
pip install "lauren-mcp[all]"
```

## Running

### HTTP / WebSocket (for Claude desktop or MCP inspector)

```bash
MCP_FS_ROOT=/tmp/sandbox python examples/filesystem/server.py
```

The server listens on `http://127.0.0.1:8765`.

### Via the lauren-mcp CLI

```bash
MCP_FS_ROOT=/tmp/sandbox lmcp run examples/filesystem/server.py --transport streamable
```

### stdio (for agent use)

```bash
MCP_FS_ROOT=/tmp/sandbox python examples/filesystem/server.py
```

## Connecting with Claude Desktop

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "python",
      "args": ["examples/filesystem/server.py"],
      "env": {
        "MCP_FS_ROOT": "/tmp/sandbox"
      }
    }
  }
}
```

## Environment Variables

| Variable      | Default         | Description                                      |
|---------------|-----------------|--------------------------------------------------|
| `MCP_FS_ROOT` | `.` (cwd)       | Root sandbox directory. **Always set this.**     |

## Security

- **Always set `MCP_FS_ROOT`** to a dedicated, sandboxed directory. The default
  of `.` (current working directory) is only suitable for quick local testing.
- Every path argument is validated against the sandbox root before use. Any
  attempt to escape via `../` or absolute paths outside the sandbox raises an
  error and is logged.
- The `McpFilesystemGuard` is included as an extension point for authentication
  policies (API key checks, IP allowlists, etc.).

## Available Tools

| Tool                 | Description                                      | Hints              |
|----------------------|--------------------------------------------------|--------------------|
| `list_files`         | List files/dirs at a path                        | readOnly           |
| `read_file`          | Read a file as UTF-8 text (max 1 MB)             | readOnly           |
| `write_file`         | Create or overwrite a file                       | destructive        |
| `create_directory`   | Create a directory (and parents)                 |                    |
| `delete_file`        | Delete a single file                             | destructive        |
| `delete_directory`   | Delete a directory (optionally recursive)        | destructive        |
| `move_file`          | Move or rename a file                            | destructive        |
| `file_info`          | Return metadata about a file or directory        | readOnly           |

## Resource

`file://{path}` — exposes any file in the sandbox as a readable MCP resource
with MIME type `text/plain`.

## Prompt

`edit_file_prompt(path, instruction)` — generates a prompt instructing an
agent to edit a file according to a natural-language description.

## Transport Options

The server supports all three MCP transports (`transport="all"`):

| Transport        | Endpoint                   | Protocol version   |
|------------------|----------------------------|--------------------|
| WebSocket        | `ws://host/filesystem/ws`  | Any                |
| HTTP+SSE         | `http://host/filesystem/`  | 2024-11-05         |
| Streamable HTTP  | `http://host/filesystem/`  | 2025-03-26         |

## Running Tests

```bash
# Unit tests only (fast, no network)
uv run --no-sync pytest examples/filesystem/tests/test_filesystem_unit.py -q

# Integration tests (in-process Lauren app)
uv run --no-sync pytest examples/filesystem/tests/test_filesystem_integration.py -q

# End-to-end tests (real subprocess)
uv run --no-sync pytest examples/filesystem/tests/test_filesystem_e2e.py -q

# All filesystem tests
uv run --no-sync pytest examples/filesystem/tests/ -q
```
