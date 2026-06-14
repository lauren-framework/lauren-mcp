# Filesystem MCP Example

A production-quality MCP server that exposes a sandboxed filesystem as CRUD
tools, a file resource, and an edit prompt — plus an interactive OpenAI CLI
client powered by [Rich](https://github.com/Textualize/rich).

```
┌─ Filesystem MCP Client ─ model: gpt-4o-mini ─────────────────────────────┐
│  Server:   http://127.0.0.1:8765/filesystem                               │
│  Sandbox:  /tmp/sandbox                                                   │
└───────────────────────────────────────────────────────────────────────────┘

┌─ Available tools ─────────────────────────────────────────────────────────┐
│  📂  list_files          List files and directories at a path             │
│  📖  read_file           Read a file as UTF-8 text (max 1 MB)            │
│  ✏️   write_file          Create or overwrite a file                       │
│  …                                                                        │
└───────────────────────────────────────────────────────────────────────────┘

You  > list all files then read README.md

╭─ 📂  list_files ─────────────────────────────────────────────────────────╮
│  {}                                                                       │
╰───────────────────────────────────────────────────────────────────────────╯
╭─ list_files result ──────────────────────────────────────────────────────╮
│  ["README.md", "notes.txt"]                                               │
╰───────────────────────────────────────────────────────────────────────────╯
```

## Installation

```bash
pip install "lauren-mcp[all]" openai rich
# Optional: load .env automatically
pip install python-dotenv
```

## Quick start

```bash
# 1. Copy and fill in environment variables
cp examples/filesystem/.env.example .env
$EDITOR .env   # set OPENAI_API_KEY at minimum

# 2. Start the MCP server
MCP_FS_ROOT=/tmp/sandbox python examples/filesystem/server.py

# 3. In a second terminal, start the client
python examples/filesystem/client.py
```

## Environment variables

Copy `.env.example` to `.env` (or export the variables directly):

| Variable | Default | Description |
|---|---|---|
| `OPENAI_API_KEY` | *(required)* | Your OpenAI API key |
| `OPENAI_MODEL` | `gpt-4o-mini` | Model for the agentic loop |
| `MCP_SERVER_URL` | `http://127.0.0.1:8765/filesystem` | Streamable-HTTP URL of the server |
| `MCP_FS_ROOT` | `./sandbox` | Displayed in the header; must match the server's `MCP_FS_ROOT` |
| `SYSTEM_PROMPT` | *(built-in)* | Override the system prompt |

## Client commands

Inside the REPL:

| Input | Action |
|---|---|
| Any text | Send message to the model |
| `/tools` | Show the available tool table |
| `/clear` | Reset conversation history |
| `/history` | Print the message history |
| `exit` / `quit` | Close the client |

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

## How the client works

```
client.py
  │
  ├─ AsyncOpenAI           Chat Completions API (streaming)
  │    └─ tool_calls  ──►  McpServer.streamable_http()
  │                             └─ call_tool(name, args)  ──►  server.py
  └─ Rich Console          Live spinners · panels · Markdown
```

1. On startup, `McpServer.streamable_http(MCP_SERVER_URL).connect()` performs
   the MCP `initialize` handshake and fetches the tool list via `tools/list`.
2. Each tool is converted to an OpenAI function-tool schema and passed in the
   `tools=` parameter of every Chat Completions request.
3. When the model emits a `tool_calls` chunk, the client prints a yellow panel
   with the call arguments, executes it against the MCP server, prints the
   result, and appends both messages to the history.
4. The loop continues until the model produces a plain text response with no
   tool calls.

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
