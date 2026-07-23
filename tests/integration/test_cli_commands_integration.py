"""Integration tests for the lmcp CLI using typer.testing.CliRunner."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

typer = pytest.importorskip("typer", reason="requires lauren-mcp[cli]")

from typer.testing import CliRunner  # noqa: E402

from lauren_mcp.cli import app  # noqa: E402

runner = CliRunner()
REPO_ROOT = Path(__file__).resolve().parents[2]
FILESYSTEM_SERVER = REPO_ROOT / "examples" / "filesystem" / "server.py"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SINGLE_SERVER = """\
from lauren_mcp.server._decorators import mcp_server, mcp_tool

@mcp_server('/test')
class MyServer:
    @mcp_tool()
    async def greet(self, name: str) -> str:
        'Greet someone.'
        return f'Hello {name}'
"""


def _write_server_file(tmp_path: Path, name: str = "server.py") -> Path:
    p = tmp_path / name
    p.write_text(_SINGLE_SERVER)
    return p


# ---------------------------------------------------------------------------
# lmcp run
# ---------------------------------------------------------------------------


class TestRunCli:
    def test_run_invokes_start_server(self, tmp_path: Path) -> None:
        p = _write_server_file(tmp_path)
        with (
            patch("lauren_mcp.cli._commands._load_env"),
            patch("lauren_mcp.cli._commands.resolve_server_class") as mock_resolve,
            patch("lauren_mcp.cli._commands._start_server") as mock_start,
        ):
            mock_resolve.return_value = type("FakeServer", (), {})
            result = runner.invoke(app, ["run", str(p)])

        assert result.exit_code == 0
        mock_start.assert_called_once()

    def test_run_with_transport_option(self, tmp_path: Path) -> None:
        p = _write_server_file(tmp_path)
        with (
            patch("lauren_mcp.cli._commands._load_env"),
            patch("lauren_mcp.cli._commands.resolve_server_class") as mock_resolve,
            patch("lauren_mcp.cli._commands._start_server") as mock_start,
        ):
            mock_resolve.return_value = type("FakeServer", (), {})
            result = runner.invoke(app, ["run", str(p), "--transport", "sse"])

        assert result.exit_code == 0
        call_kwargs = mock_start.call_args.kwargs
        assert call_kwargs["transport"] == "sse"

    def test_run_with_reload_flag(self, tmp_path: Path) -> None:
        p = _write_server_file(tmp_path)
        with (
            patch("lauren_mcp.cli._commands._load_env"),
            patch("lauren_mcp.cli._commands.resolve_server_class") as mock_resolve,
            patch("lauren_mcp.cli._commands._start_server"),
        ):
            mock_resolve.return_value = type("FakeServer", (), {})
            result = runner.invoke(app, ["run", str(p), "--reload"])

        assert result.exit_code == 0
        assert "reload" in result.output.lower()

    def test_run_with_port_and_host(self, tmp_path: Path) -> None:
        p = _write_server_file(tmp_path)
        with (
            patch("lauren_mcp.cli._commands._load_env"),
            patch("lauren_mcp.cli._commands.resolve_server_class") as mock_resolve,
            patch("lauren_mcp.cli._commands._start_server") as mock_start,
        ):
            mock_resolve.return_value = type("FakeServer", (), {})
            result = runner.invoke(app, ["run", str(p), "--host", "0.0.0.0", "--port", "9000"])

        assert result.exit_code == 0
        call_kwargs = mock_start.call_args.kwargs
        assert call_kwargs["host"] == "0.0.0.0"
        assert call_kwargs["port"] == 9000

    def test_run_with_stdio_flag(self, tmp_path: Path) -> None:
        p = _write_server_file(tmp_path)
        with (
            patch("lauren_mcp.cli._commands._load_env"),
            patch("lauren_mcp.cli._commands.resolve_server_class") as mock_resolve,
            patch("lauren_mcp.cli._commands._start_stdio_server") as mock_start,
        ):
            mock_resolve.return_value = type("FakeServer", (), {})
            result = runner.invoke(app, ["run", str(p), "--stdio"])

        assert result.exit_code == 0
        mock_start.assert_called_once_with(mock_resolve.return_value, transport="ws")


# ---------------------------------------------------------------------------
# lmcp dev
# ---------------------------------------------------------------------------


class TestDevCli:
    def test_dev_invokes_start_server_with_debug(self, tmp_path: Path) -> None:
        p = _write_server_file(tmp_path)
        with (
            patch("lauren_mcp.cli._commands._load_env"),
            patch("lauren_mcp.cli._commands.resolve_server_class") as mock_resolve,
            patch("lauren_mcp.cli._commands._start_server") as mock_start,
        ):
            fake_cls = type("DevServer", (), {"__name__": "DevServer"})
            mock_resolve.return_value = fake_cls
            result = runner.invoke(app, ["dev", str(p)])

        assert result.exit_code == 0
        call_kwargs = mock_start.call_args.kwargs
        assert call_kwargs["log_level"] == "debug"

    def test_dev_prints_startup_info(self, tmp_path: Path) -> None:
        p = _write_server_file(tmp_path)
        with (
            patch("lauren_mcp.cli._commands._load_env"),
            patch("lauren_mcp.cli._commands.resolve_server_class") as mock_resolve,
            patch("lauren_mcp.cli._commands._start_server"),
        ):
            fake_cls = type("DevServer", (), {"__name__": "DevServer"})
            mock_resolve.return_value = fake_cls
            result = runner.invoke(app, ["dev", str(p), "--port", "8080"])

        assert result.exit_code == 0
        assert "DevServer" in result.output


# ---------------------------------------------------------------------------
# lmcp inspect
# ---------------------------------------------------------------------------


class TestInspectCli:
    def test_inspect_ws_url(self) -> None:
        mock_client = AsyncMock()
        mock_client.list_tools = AsyncMock(return_value=[])
        mock_client.list_resources = AsyncMock(return_value=[])
        mock_client.list_prompts = AsyncMock(return_value=[])

        mock_factory = MagicMock()
        mock_factory.ws = MagicMock(return_value=mock_client)

        with patch("lauren_mcp._client._factory.McpServer", mock_factory):
            result = runner.invoke(app, ["inspect", "ws://localhost:8000/ws"])

        assert result.exit_code == 0
        assert "Tools (0)" in result.output
        assert "Resources (0)" in result.output
        assert "Prompts (0)" in result.output

    def test_inspect_with_tools_listed(self) -> None:
        mock_tool = MagicMock()
        mock_tool.name = "my_tool"
        mock_tool.description = "Does something"

        mock_client = AsyncMock()
        mock_client.list_tools = AsyncMock(return_value=[mock_tool])
        mock_client.list_resources = AsyncMock(return_value=[])
        mock_client.list_prompts = AsyncMock(return_value=[])

        mock_factory = MagicMock()
        mock_factory.ws = MagicMock(return_value=mock_client)

        with patch("lauren_mcp._client._factory.McpServer", mock_factory):
            result = runner.invoke(app, ["inspect", "ws://localhost:8000/ws"])

        assert result.exit_code == 0
        assert "my_tool" in result.output
        assert "Does something" in result.output


# ---------------------------------------------------------------------------
# lmcp call
# ---------------------------------------------------------------------------


class TestCallCli:
    def test_call_with_ws_url(self) -> None:
        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(return_value={"greeting": "Hello!"})

        mock_factory = MagicMock()
        mock_factory.ws = MagicMock(return_value=mock_client)

        with patch("lauren_mcp._client._factory.McpServer", mock_factory):
            result = runner.invoke(
                app, ["call", "ws://localhost:8000/ws", "greet", "--arg", "name=Alice"]
            )

        assert result.exit_code == 0
        assert "Hello!" in result.output

    def test_call_with_bad_arg_format(self) -> None:
        result = runner.invoke(
            app, ["call", "ws://localhost:8000/ws", "greet", "--arg", "bad_format"]
        )
        assert result.exit_code != 0

    def test_call_json_value_parsing(self) -> None:
        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(return_value={"result": 84})

        mock_factory = MagicMock()
        mock_factory.ws = MagicMock(return_value=mock_client)

        with patch("lauren_mcp._client._factory.McpServer", mock_factory):
            result = runner.invoke(app, ["call", "ws://localhost:8000/ws", "add", "--arg", "x=42"])

        assert result.exit_code == 0
        # Verify integer was parsed (x=42 should become int 42 in kwargs)
        call_args = mock_client.call_tool.call_args
        assert call_args.args[1]["x"] == 42  # JSON parsed to int

    def test_call_no_args(self) -> None:
        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(return_value={"pong": True})

        mock_factory = MagicMock()
        mock_factory.ws = MagicMock(return_value=mock_client)

        with patch("lauren_mcp._client._factory.McpServer", mock_factory):
            result = runner.invoke(app, ["call", "ws://localhost:8000/ws", "ping"])

        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# lmcp install
# ---------------------------------------------------------------------------


class TestInstallCli:
    def test_install_claude_client(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.json"
        with (
            patch("lauren_mcp.cli._commands.resolve_server_class") as mock_resolve,
            patch("lauren_mcp.cli._commands._get_config_path") as mock_cfg_path,
            patch("lauren_mcp.cli._commands._write_mcp_config"),
        ):
            fake_cls = type("MyServer", (), {"__name__": "MyServer"})
            mock_resolve.return_value = fake_cls
            mock_cfg_path.return_value = str(cfg)
            result = runner.invoke(app, ["install", "server.py"])

        assert result.exit_code == 0
        assert "MyServer" in result.output
        mock_cfg_path.assert_called_once_with("claude")

    def test_install_with_explicit_name(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.json"
        with (
            patch("lauren_mcp.cli._commands.resolve_server_class") as mock_resolve,
            patch("lauren_mcp.cli._commands._get_config_path") as mock_cfg_path,
            patch("lauren_mcp.cli._commands._write_mcp_config") as mock_write,
        ):
            fake_cls = type("MyServer", (), {"__name__": "MyServer"})
            mock_resolve.return_value = fake_cls
            mock_cfg_path.return_value = str(cfg)
            result = runner.invoke(app, ["install", "server.py", "--name", "custom"])

        assert result.exit_code == 0
        mock_write.assert_called_once_with(str(cfg), "custom", str(Path("server.py").resolve()))

    def test_install_cursor_client(self, tmp_path: Path) -> None:
        cfg = tmp_path / "mcp.json"
        with (
            patch("lauren_mcp.cli._commands.resolve_server_class") as mock_resolve,
            patch("lauren_mcp.cli._commands._get_config_path") as mock_cfg_path,
            patch("lauren_mcp.cli._commands._write_mcp_config"),
        ):
            fake_cls = type("MyServer", (), {"__name__": "MyServer"})
            mock_resolve.return_value = fake_cls
            mock_cfg_path.return_value = str(cfg)
            result = runner.invoke(app, ["install", "server.py", "--client", "cursor"])

        assert result.exit_code == 0
        mock_cfg_path.assert_called_once_with("cursor")

    def test_install_actually_writes_config(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.json"
        with (
            patch("lauren_mcp.cli._commands.resolve_server_class") as mock_resolve,
            patch("lauren_mcp.cli._commands._get_config_path", return_value=str(cfg)),
        ):
            fake_cls = type("TestSrv", (), {"__name__": "TestSrv"})
            mock_resolve.return_value = fake_cls
            result = runner.invoke(app, ["install", "server.py"])

        assert result.exit_code == 0
        data = json.loads(cfg.read_text())
        assert "TestSrv" in data["mcpServers"]
        assert data["mcpServers"]["TestSrv"]["command"] == sys.executable


# ---------------------------------------------------------------------------
# Real CLI smoke tests against examples/filesystem/server.py
# ---------------------------------------------------------------------------


def _run_lmcp(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run the installed CLI entry point with the test interpreter."""

    command_env = os.environ.copy()
    if env:
        command_env.update(env)
    result = subprocess.run(
        [sys.executable, "-m", "lauren_mcp.cli", *args],
        cwd=REPO_ROOT,
        env=command_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"lmcp failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    return result


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(port: int) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise AssertionError(f"CLI server did not listen on port {port}")


def _start_lmcp_server(command: str, port: int, sandbox: Path) -> subprocess.Popen[str]:
    process_env = os.environ.copy()
    process_env["MCP_FS_ROOT"] = str(sandbox)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "lauren_mcp.cli",
            command,
            str(FILESYSTEM_SERVER),
            "--transport",
            "streamable",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=REPO_ROOT,
        env=process_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_port(port)
    except Exception:
        stdout, stderr = process.communicate(timeout=5)
        raise AssertionError(f"{command} failed:\nstdout={stdout}\nstderr={stderr}") from None
    return process


def _stop_lmcp_server(process: subprocess.Popen[str]) -> None:
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


class TestFilesystemExampleCli:
    def test_local_inspect_and_call(self, tmp_path: Path) -> None:
        sandbox = tmp_path / "sandbox"
        env = {"MCP_FS_ROOT": str(sandbox)}

        inspect_result = _run_lmcp("inspect", str(FILESYSTEM_SERVER), env=env)
        assert "list_files" in inspect_result.stdout
        assert "file://{path}" in inspect_result.stdout
        assert "edit_file_prompt" in inspect_result.stdout

        write_result = _run_lmcp(
            "call",
            str(FILESYSTEM_SERVER),
            "write_file",
            "--arg",
            "path=cli.txt",
            "--arg",
            "content=created by lmcp",
            env=env,
        )
        assert '"isError": false' in write_result.stdout

        read_result = _run_lmcp(
            "call",
            str(FILESYSTEM_SERVER),
            "read_file",
            "--arg",
            "path=cli.txt",
            env=env,
        )
        assert "created by lmcp" in read_result.stdout

    @pytest.mark.parametrize("command", ["run", "dev"])
    def test_server_commands_against_filesystem_example(self, tmp_path: Path, command: str) -> None:
        pytest.importorskip("httpx")
        pytest.importorskip("httpx_sse")
        port = _free_port()
        process = _start_lmcp_server(command, port, tmp_path / "sandbox")
        try:
            url = f"http://127.0.0.1:{port}/filesystem"
            inspect_result = _run_lmcp(
                "inspect", url, "--transport", "streamable", env={"MCP_FS_ROOT": str(tmp_path)}
            )
            assert "Tools (12)" in inspect_result.stdout
        finally:
            _stop_lmcp_server(process)

    def test_install_creates_runnable_config(self, tmp_path: Path) -> None:
        config_home = tmp_path / "home"
        install_env = os.environ.copy()
        install_env["HOME"] = str(config_home)
        _run_lmcp(
            "install",
            str(FILESYSTEM_SERVER),
            "--client",
            "cursor",
            "--name",
            "filesystem",
            env=install_env,
        )

        config_path = config_home / ".config" / "Cursor" / "mcp.json"
        data = json.loads(config_path.read_text())
        entry = data["mcpServers"]["filesystem"]
        assert entry["command"] == sys.executable
        assert entry["args"][:3] == ["-m", "lauren_mcp.cli", "run"]
        assert entry["args"][3:] == [str(FILESYSTEM_SERVER), "--stdio"]

        process = subprocess.Popen(
            [entry["command"], *entry["args"]],
            cwd=REPO_ROOT,
            env={**install_env, "MCP_FS_ROOT": str(tmp_path / "sandbox")},
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            output, error = process.communicate(
                input=(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": 1,
                            "method": "initialize",
                            "params": {
                                "protocolVersion": "2025-03-26",
                                "capabilities": {},
                                "clientInfo": {"name": "test", "version": "1"},
                            },
                        }
                    )
                    + "\n"
                    + '{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
                    + '{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n'
                ),
                timeout=30,
            )
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
        assert process.returncode == 0, error
        responses = [json.loads(line) for line in output.splitlines() if line]
        assert responses[0]["id"] == 1
        assert len(responses[1]["result"]["tools"]) == 12
