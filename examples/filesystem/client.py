"""Interactive Poolside CLI client for the Filesystem MCP Server.

Connects to a running Filesystem MCP server over Streamable HTTP, fetches the
tool catalogue, and runs an agentic loop powered by the Poolside inference API
(OpenAI-compatible).  Every tool call is executed against the real MCP server;
results are pretty-printed with Rich.

Usage:
    # 1. Start the server in one terminal
    MCP_FS_ROOT=/tmp/sandbox python examples/filesystem/server.py

    # 2. Run the client in another terminal
    POOLSIDE_API_KEY=<key> python examples/filesystem/client.py

    # Or point at a custom MCP server URL
    POOLSIDE_API_KEY=<key> python examples/filesystem/client.py http://localhost:8765/filesystem

Environment variables (see .env.example):
    OPENAI_API_KEY      Required. Your API key.
    OPENAI_MODEL        Model to use (default: poolside/laguna-xs.2).
    OPENAI_API_BASE_URL Inference base URL (default: https://inference.poolside.ai/v1).
    MCP_SERVER_URL      Streamable-HTTP base URL of the MCP server
                        (default: http://127.0.0.1:8765/filesystem).
    MCP_FS_ROOT         Shown in the header so you know which directory is
                        active (default: ./sandbox).
    SYSTEM_PROMPT       Override the default system prompt.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
from pathlib import Path

# Optional convenience: load a .env file if python-dotenv is installed
with contextlib.suppress(ImportError):
    from dotenv import load_dotenv  # type: ignore[import-not-found]

    load_dotenv()

# ---------------------------------------------------------------------------
# Dependency guard — clear error before anything else fails
# ---------------------------------------------------------------------------
try:
    import openai
    from openai import AsyncOpenAI
    from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolParam
    from rich.console import Console
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.prompt import Prompt
    from rich.spinner import Spinner
    from rich.table import Table
    from rich.text import Text
    from rich.theme import Theme
except ImportError as _dep_err:
    _pkg = "openai" if "openai" in str(_dep_err) else "rich"
    print(
        f"Missing dependency: {_pkg}\nInstall with:  pip install openai rich",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_API_BASE_URL = os.environ.get("OPENAI_API_BASE_URL", "https://inference.poolside.ai/v1")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "poolside/laguna-xs.2")
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://127.0.0.1:8765/filesystem")
MCP_FS_ROOT = os.environ.get("MCP_FS_ROOT", str(Path("./sandbox").resolve()))

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful file-management assistant with access to a sandboxed filesystem. "
    "Use the provided tools to read, write, list, move, copy, and delete files. "
    "Always confirm destructive operations with the user before proceeding. "
    "Provide clear, concise summaries after completing each task."
)
SYSTEM_PROMPT = os.environ.get("SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT)

# ---------------------------------------------------------------------------
# Rich theme
# ---------------------------------------------------------------------------

THEME = Theme(
    {
        "user": "bold cyan",
        "assistant": "bold green",
        "tool.name": "bold yellow",
        "tool.input": "dim white",
        "tool.result": "dim green",
        "tool.error": "bold red",
        "info": "dim white",
        "header": "bold white on blue",
        "separator": "dim white",
    }
)

console = Console(theme=THEME, highlight=False)

# ---------------------------------------------------------------------------
# MCP client helpers
# ---------------------------------------------------------------------------


async def _connect_mcp() -> tuple[list[dict], object]:
    """Connect to the MCP server and return (tools_openai_schema, client)."""
    try:
        from lauren_mcp import McpServer  # noqa: PLC0415
    except ImportError as exc:
        console.print(
            "[tool.error]lauren-mcp not installed.[/] pip install lauren-mcp",
            style="bold red",
        )
        raise SystemExit(1) from exc

    client = McpServer.streamable_http(MCP_SERVER_URL)
    await client.connect()
    tools = await client.list_tools()
    return tools, client


def _mcp_tools_to_openai(mcp_tools: list) -> list[ChatCompletionToolParam]:
    """Convert MCP ToolSchema objects to OpenAI function-tool dicts."""
    result: list[ChatCompletionToolParam] = []
    for t in mcp_tools:
        schema = t.inputSchema if hasattr(t, "inputSchema") else {}
        # Remove $schema key if present — OpenAI rejects it
        schema = {k: v for k, v in schema.items() if k != "$schema"}
        result.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": (t.description or "").strip(),
                    "parameters": schema,
                },
            }
        )
    return result


# ---------------------------------------------------------------------------
# Rich display helpers
# ---------------------------------------------------------------------------

TOOL_EMOJIS: dict[str, str] = {
    "list_files": "📂",
    "read_file": "📖",
    "write_file": "✏️ ",
    "create_directory": "📁",
    "delete_file": "🗑️ ",
    "delete_directory": "🗑️ ",
    "move_file": "📦",
    "file_info": "ℹ️ ",
    "bulk_write_files": "📝",
    "bulk_delete_files": "🗑️ ",
    "bulk_copy_files": "📋",
    "sync_directory": "🔄",
}


def _print_welcome(tool_schemas: list) -> None:
    """Print the welcome panel with server info and available tools."""
    header = Table.grid(padding=(0, 1))
    header.add_row(
        Text("Filesystem MCP Client", style="bold white"),
        Text("—", style="dim"),
        Text(f"model: {OPENAI_MODEL}", style="dim cyan"),
    )
    header.add_row(
        Text("Server:", style="dim"),
        Text(MCP_SERVER_URL, style="cyan"),
    )
    header.add_row(
        Text("Sandbox:", style="dim"),
        Text(MCP_FS_ROOT, style="cyan"),
    )

    tools_table = Table(
        show_header=True,
        header_style="bold",
        show_edge=False,
        pad_edge=False,
        box=None,
    )
    tools_table.add_column("Tool", style="tool.name", no_wrap=True)
    tools_table.add_column("Description", style="dim white")

    for t in tool_schemas:
        name = t.name if hasattr(t, "name") else t.get("name", "")
        desc = (t.description if hasattr(t, "description") else t.get("description", "")) or ""
        emoji = TOOL_EMOJIS.get(name, "🔧")
        tools_table.add_row(f"{emoji}  {name}", desc[:72])

    console.print()
    console.print(Panel(header, border_style="blue", padding=(0, 1)))
    console.print()
    console.print(Panel(tools_table, title="[bold]Available tools[/]", border_style="dim white"))
    console.print()
    console.print(
        "[dim]Type a message and press Enter.  "
        "[bold]exit[/] or [bold]quit[/] to leave.  "
        "[bold]/tools[/] to list tools.  "
        "[bold]/clear[/] to reset history.[/dim]"
    )
    console.print()


def _print_tool_call(name: str, arguments: dict) -> None:
    """Render a tool call as a Rich panel."""
    emoji = TOOL_EMOJIS.get(name, "🔧")
    args_text = json.dumps(arguments, indent=2, ensure_ascii=False)
    # Truncate very large payloads (e.g. bulk_write with many files)
    if len(args_text) > 800:
        args_text = args_text[:800] + "\n  … (truncated)"
    console.print(
        Panel(
            f"[tool.input]{args_text}[/]",
            title=f"[tool.name]{emoji}  {name}[/]",
            border_style="yellow",
            padding=(0, 1),
        )
    )


def _print_tool_result(name: str, result: str, is_error: bool = False) -> None:
    """Render a tool result."""
    style = "tool.error" if is_error else "tool.result"
    border = "red" if is_error else "green"
    label = "error" if is_error else "result"
    # Pretty-print if JSON
    display = result
    try:
        parsed = json.loads(result)
        display = json.dumps(parsed, indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, ValueError):
        pass
    if len(display) > 1200:
        display = display[:1200] + "\n… (truncated)"
    console.print(
        Panel(
            f"[{style}]{display}[/]",
            title=f"[dim]{name} {label}[/]",
            border_style=border,
            padding=(0, 1),
        )
    )


# ---------------------------------------------------------------------------
# Agentic loop
# ---------------------------------------------------------------------------


async def _run_turn(
    client_openai: AsyncOpenAI,
    client_mcp: object,
    messages: list[ChatCompletionMessageParam],
    openai_tools: list[ChatCompletionToolParam],
) -> None:
    """Run one turn: call OpenAI → execute any tool calls → repeat until done."""
    while True:
        # ── Call OpenAI with streaming ──────────────────────────────────────
        streamed_content: list[str] = []
        tool_calls_raw: dict[int, dict] = {}  # index → {id, name, args}

        with Live(
            Spinner("dots", text="[dim]Thinking…[/]"),
            console=console,
            refresh_per_second=10,
            transient=True,
        ):
            stream = await client_openai.chat.completions.create(
                model=OPENAI_MODEL,
                messages=messages,
                tools=openai_tools if openai_tools else openai.NOT_GIVEN,  # type: ignore[attr-defined]
                stream=True,
            )

            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta is None:
                    continue

                # Accumulate text content
                if delta.content:
                    streamed_content.append(delta.content)

                # Accumulate tool calls
                for tc in delta.tool_calls or []:
                    idx = tc.index
                    if idx not in tool_calls_raw:
                        tool_calls_raw[idx] = {
                            "id": tc.id or "",
                            "name": tc.function.name if tc.function else "",
                            "args": "",
                        }
                    if tc.id:
                        tool_calls_raw[idx]["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            tool_calls_raw[idx]["name"] = tc.function.name
                        if tc.function.arguments:
                            tool_calls_raw[idx]["args"] += tc.function.arguments

        # ── Print assistant text ────────────────────────────────────────────
        if streamed_content:
            full_text = "".join(streamed_content)
            console.print("\n[assistant]Assistant[/]  ", end="")
            console.print(Markdown(full_text))
            console.print()

        # ── No tool calls → turn is done ───────────────────────────────────
        if not tool_calls_raw:
            # Append the assistant message to history
            messages.append({"role": "assistant", "content": "".join(streamed_content)})
            break

        # ── Build the assistant message with tool calls ─────────────────────
        tool_calls_list = []
        ordered_tcs = [tool_calls_raw[k] for k in sorted(tool_calls_raw)]
        for tc in ordered_tcs:
            tool_calls_list.append(
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["args"]},
                }
            )

        messages.append(
            {
                "role": "assistant",
                "content": "".join(streamed_content) or None,
                "tool_calls": tool_calls_list,  # type: ignore[typeddict-item]
            }
        )

        # ── Execute each tool call ──────────────────────────────────────────
        for tc in tool_calls_list:
            name: str = tc["function"]["name"]
            args_str: str = tc["function"]["arguments"]
            call_id: str = tc["id"]

            try:
                arguments: dict = json.loads(args_str) if args_str.strip() else {}
            except json.JSONDecodeError:
                arguments = {}

            _print_tool_call(name, arguments)

            # Execute against MCP
            is_error = False
            result_text = ""
            with Live(
                Spinner("dots2", text=f"[dim]{name}…[/]"),
                console=console,
                refresh_per_second=10,
                transient=True,
            ):
                try:
                    raw_result = await client_mcp.call_tool(name, arguments)  # type: ignore[attr-defined]
                    # Unwrap MCP content list to text
                    if isinstance(raw_result, list):
                        parts = []
                        for item in raw_result:
                            if isinstance(item, dict):
                                parts.append(item.get("text") or json.dumps(item))
                            else:
                                text = getattr(item, "text", None)
                                parts.append(text if text is not None else str(item))
                        result_text = "\n".join(parts)
                    else:
                        result_text = str(raw_result)
                except Exception as exc:  # noqa: BLE001
                    result_text = f"Tool error: {exc}"
                    is_error = True

            _print_tool_result(name, result_text, is_error=is_error)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": result_text,
                }
            )

        # Loop back to get the next model response


# ---------------------------------------------------------------------------
# Main REPL
# ---------------------------------------------------------------------------


async def main() -> None:
    if not OPENAI_API_KEY:
        console.print(
            Panel(
                "[bold red]OPENAI_API_KEY is not set.[/]\n\n"
                "Export it or add it to a [bold].env[/] file:\n"
                "  [cyan]export OPENAI_API_KEY=<your-key>[/]\n\n"
                "See [bold].env.example[/] for all options.",
                title="[bold red]Configuration error[/]",
                border_style="red",
            )
        )
        raise SystemExit(1) from None

    # ── Connect to MCP server ───────────────────────────────────────────────
    console.print(f"\n[dim]Connecting to [cyan]{MCP_SERVER_URL}[/cyan]…[/dim]")
    try:
        mcp_tools, client_mcp = await _connect_mcp()
    except Exception as exc:  # noqa: BLE001
        console.print(
            Panel(
                f"[bold red]Could not connect to MCP server.[/]\n\n"
                f"[dim]{exc}[/dim]\n\n"
                f"Make sure the server is running:\n"
                "  [cyan]MCP_FS_ROOT=/tmp/sandbox python examples/filesystem/server.py[/]",
                title="[bold red]Connection error[/]",
                border_style="red",
            )
        )
        raise SystemExit(1) from exc

    openai_tools = _mcp_tools_to_openai(mcp_tools)
    client_openai = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_API_BASE_URL)

    _print_welcome(mcp_tools)

    # Conversation history
    messages: list[ChatCompletionMessageParam] = [{"role": "system", "content": SYSTEM_PROMPT}]

    # ── REPL ────────────────────────────────────────────────────────────────
    while True:
        try:
            user_input = Prompt.ask("[user]You[/]")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/dim]")
            break

        user_input = user_input.strip()
        if not user_input:
            continue

        # ── Built-in commands ───────────────────────────────────────────────
        if user_input.lower() in {"exit", "quit", "bye"}:
            console.print("[dim]Goodbye![/dim]")
            break

        if user_input.lower() == "/clear":
            messages = [{"role": "system", "content": SYSTEM_PROMPT}]
            console.clear()
            _print_welcome(mcp_tools)
            continue

        if user_input.lower() == "/tools":
            _print_welcome(mcp_tools)
            continue

        if user_input.lower() == "/history":
            for i, m in enumerate(messages[1:], 1):  # skip system
                role = str(m.get("role", "?"))
                content = str(m.get("content", ""))[:120]
                console.print(f"[dim]{i:3}  [{role}] {content}[/dim]")
            console.print()
            continue

        # ── Append and run ──────────────────────────────────────────────────
        messages.append({"role": "user", "content": user_input})

        try:
            await _run_turn(client_openai, client_mcp, messages, openai_tools)
        except openai.APIError as exc:
            console.print(
                Panel(
                    f"[bold red]OpenAI API error:[/] {exc}",
                    border_style="red",
                )
            )
        except Exception as exc:  # noqa: BLE001
            console.print(
                Panel(
                    f"[bold red]Unexpected error:[/] {exc}",
                    border_style="red",
                )
            )

    # ── Cleanup ─────────────────────────────────────────────────────────────
    with contextlib.suppress(Exception):
        await client_mcp.close()  # type: ignore[attr-defined]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Filesystem MCP CLI client (Poolside)")
    parser.add_argument(
        "url",
        nargs="?",
        default=None,
        help="MCP server URL (overrides MCP_SERVER_URL, default: http://127.0.0.1:8765/filesystem)",
    )
    parser.add_argument(
        "--model",
        "-m",
        default=None,
        help="Model to use (overrides POOLSIDE_MODEL, default: poolside/laguna-xs.2)",
    )
    cli_args = parser.parse_args()

    if cli_args.url:
        MCP_SERVER_URL = cli_args.url
    if cli_args.model:
        OPENAI_MODEL = cli_args.model

    asyncio.run(main())
