"""Sub-command implementations for the ``lmcp`` CLI.

Each public function (``run``, ``dev``, ``inspect_cmd``, ``call``, ``install``) is
registered on the Typer app in ``cli/__init__.py``.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Annotated

import typer

from lauren_mcp.cli._resolve import resolve_server_class

# ---------------------------------------------------------------------------
# lmcp run
# ---------------------------------------------------------------------------


def run(
    file_spec: Annotated[str, typer.Argument(help="file.py or file.py:ClassName")],
    transport: Annotated[str, typer.Option(help="ws | sse | streamable | all")] = "ws",
    host: Annotated[str, typer.Option(help="Bind host")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Bind port")] = 8000,
    env_file: Annotated[str | None, typer.Option(help=".env file path")] = None,
    reload: Annotated[bool, typer.Option(help="Hot-reload (not yet implemented)")] = False,
) -> None:
    """Start an MCP server from a Python source file."""
    _load_env(env_file)
    if reload:
        typer.echo("Warning: --reload is not yet implemented; running without reload.")
    server_cls = resolve_server_class(file_spec)
    _start_server(server_cls, transport=transport, host=host, port=port)


# ---------------------------------------------------------------------------
# lmcp dev
# ---------------------------------------------------------------------------


def dev(
    file_spec: Annotated[str, typer.Argument(help="file.py or file.py:ClassName")],
    transport: Annotated[str, typer.Option()] = "ws",
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option()] = 8000,
    env_file: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Start an MCP server in development mode (debug logging + verbose output)."""
    import logging  # noqa: PLC0415

    logging.basicConfig(level=logging.DEBUG)
    _load_env(env_file)
    server_cls = resolve_server_class(file_spec)
    typer.echo(f"[lmcp dev] Starting {server_cls.__name__} on {host}:{port} ({transport})")
    _start_server(server_cls, transport=transport, host=host, port=port, log_level="debug")


# ---------------------------------------------------------------------------
# lmcp inspect
# ---------------------------------------------------------------------------


def inspect_cmd(
    file_spec_or_url: Annotated[
        str,
        typer.Argument(help="file.py, file.py:ClassName, or ws://host:port/path/ws"),
    ],
    transport: Annotated[str, typer.Option()] = "ws",
) -> None:
    """Connect to an MCP server and list its tools, resources, and prompts."""
    asyncio.run(_inspect_async(file_spec_or_url, transport))


async def _inspect_async(file_spec_or_url: str, transport: str) -> None:
    from lauren_mcp._client._factory import McpServer  # noqa: PLC0415

    if file_spec_or_url.startswith(("ws://", "wss://")):
        client = McpServer.ws(file_spec_or_url)
    elif file_spec_or_url.startswith(("http://", "https://")):
        client = McpServer.http(file_spec_or_url)
    else:
        # Local file spec: run server in subprocess and connect via stdio.
        server_cls = resolve_server_class(file_spec_or_url)
        script = _make_stdio_script(server_cls, transport)
        client = McpServer.stdio(["python", "-c", script], max_retries=0)
    await client.connect()

    tools = await client.list_tools()
    resources = await client.list_resources()
    prompts = await client.list_prompts()

    typer.echo(f"\nTools ({len(tools)}):")
    for t in tools:
        typer.echo(f"  {t.name}: {t.description}")

    typer.echo(f"\nResources ({len(resources)}):")
    for r in resources:
        typer.echo(f"  {r.uri}: {r.name}")

    typer.echo(f"\nPrompts ({len(prompts)}):")
    for p in prompts:
        typer.echo(f"  {p.name}: {p.description}")

    await client.close()


# ---------------------------------------------------------------------------
# lmcp call
# ---------------------------------------------------------------------------


def call(
    file_spec_or_url: Annotated[
        str,
        typer.Argument(help="file.py, file.py:ClassName, or ws://host:port/path/ws"),
    ],
    tool_name: Annotated[str, typer.Argument(help="Tool name to invoke")],
    arg: Annotated[
        list[str] | None,
        typer.Option(help="KEY=VALUE arguments (repeatable)"),
    ] = None,
    transport: Annotated[str, typer.Option()] = "ws",
) -> None:
    """Call a tool by name and print the result as JSON."""
    kwargs: dict[str, object] = {}
    for kv in arg or []:
        if "=" not in kv:
            typer.echo(f"Error: argument {kv!r} must be KEY=VALUE", err=True)
            raise typer.Exit(code=1)
        k, v = kv.split("=", 1)
        # Try JSON-parsing the value so users can pass integers/booleans.
        try:
            parsed: object = json.loads(v)
        except (json.JSONDecodeError, ValueError):
            parsed = v
        kwargs[k] = parsed
    asyncio.run(_call_async(file_spec_or_url, tool_name, kwargs, transport))


async def _call_async(
    file_spec_or_url: str,
    tool_name: str,
    arguments: dict[str, object],
    transport: str,
) -> None:
    from lauren_mcp._client._factory import McpServer  # noqa: PLC0415

    if file_spec_or_url.startswith(("ws://", "wss://")):
        client = McpServer.ws(file_spec_or_url)
    elif file_spec_or_url.startswith(("http://", "https://")):
        client = McpServer.http(file_spec_or_url)
    else:
        server_cls = resolve_server_class(file_spec_or_url)
        script = _make_stdio_script(server_cls, transport)
        client = McpServer.stdio(["python", "-c", script], max_retries=0)
    await client.connect()

    result = await client.call_tool(tool_name, arguments)
    typer.echo(json.dumps(result, indent=2, default=str))
    await client.close()


# ---------------------------------------------------------------------------
# lmcp install
# ---------------------------------------------------------------------------


def install(
    file_spec: Annotated[str, typer.Argument(help="file.py or file.py:ClassName")],
    name: Annotated[str | None, typer.Option(help="Server name in config")] = None,
    client: Annotated[str, typer.Option(help="claude | cursor")] = "claude",
) -> None:
    """Register this server in Claude Desktop's or Cursor's MCP config."""
    server_cls = resolve_server_class(file_spec)
    server_name = name or server_cls.__name__
    config_path = _get_config_path(client)
    _write_mcp_config(config_path, server_name, file_spec)
    typer.echo(f"Registered {server_name!r} in {config_path}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _load_env(env_file: str | None) -> None:
    if env_file is None:
        return
    try:
        from dotenv import load_dotenv  # noqa: PLC0415

        load_dotenv(env_file)
    except ImportError:
        typer.echo(
            "Warning: python-dotenv not installed; --env-file ignored.\n"
            "Install with: pip install 'lauren-mcp[cli]'",
            err=True,
        )


def _start_server(
    server_cls: type,  # type: ignore[type-arg]
    *,
    transport: str,
    host: str,
    port: int,
    log_level: str = "info",
) -> None:
    try:
        import uvicorn  # noqa: PLC0415
    except ImportError:
        typer.echo("uvicorn is required; install with: pip install 'lauren-mcp[cli]'", err=True)
        raise typer.Exit(code=1)  # noqa: B904

    from lauren import LaurenFactory, module  # noqa: PLC0415

    from lauren_mcp.server._module import McpServerModule  # noqa: PLC0415

    @module(imports=[McpServerModule.for_root(server_cls, transport=transport)])
    class _AppModule:
        pass

    app = LaurenFactory.create(_AppModule)
    uvicorn.run(app, host=host, port=port, log_level=log_level)


def _make_stdio_script(server_cls: type, transport: str) -> str:  # type: ignore[type-arg]
    """Build a ``python -c`` script string that runs *server_cls* over stdio."""
    module_name = server_cls.__module__
    class_name = server_cls.__name__
    return (
        f"import sys; sys.path.insert(0, '.')\n"
        f"import {module_name} as _m\n"
        f"from lauren import LaurenFactory, module\n"
        f"from lauren_mcp.server._module import McpServerModule\n"
        f"@module(imports=[McpServerModule.for_root(_m.{class_name}, transport='{transport}')])\n"
        f"class _App: pass\n"
        f"import asyncio\n"
        f"from lauren_mcp._server._stdio import run_stdio_server\n"
        f"asyncio.run(run_stdio_server(LaurenFactory.create(_App)))\n"
    )


def _get_config_path(client_name: str) -> str:
    import os  # noqa: PLC0415
    import platform  # noqa: PLC0415

    system = platform.system()
    if client_name == "claude":
        if system == "Darwin":
            base = os.path.expanduser("~/Library/Application Support/Claude")
        elif system == "Windows":
            base = os.environ.get("APPDATA", os.path.expanduser("~"))
            base = os.path.join(base, "Claude")
        else:
            # Linux / WSL
            base = os.path.expanduser("~/.config/claude")
        return os.path.join(base, "claude_desktop_config.json")
    elif client_name == "cursor":
        if system == "Darwin":
            base = os.path.expanduser("~/Library/Application Support/Cursor")
        elif system == "Windows":
            base = os.environ.get("APPDATA", "")
            base = os.path.join(base, "Cursor")
        else:
            base = os.path.expanduser("~/.config/Cursor")
        return os.path.join(base, "mcp.json")
    else:
        typer.echo(f"Unknown client {client_name!r}; expected 'claude' or 'cursor'", err=True)
        raise typer.Exit(code=1)


def _write_mcp_config(config_path: str, server_name: str, file_spec: str) -> None:
    import json as _json  # noqa: PLC0415
    from pathlib import Path as _Path  # noqa: PLC0415

    path = _Path(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, object] = {}
    if path.exists():
        try:  # noqa: SIM105
            existing = _json.loads(path.read_text())
        except Exception:
            pass

    servers = existing.setdefault("mcpServers", {})
    assert isinstance(servers, dict)
    servers[server_name] = {
        "command": sys.executable,
        "args": ["-m", "lauren_mcp.cli", "run", file_spec],
    }
    path.write_text(_json.dumps(existing, indent=2))
