"""Integration tests for the lmcp CLI using typer.testing.CliRunner."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

typer = pytest.importorskip("typer", reason="requires lauren-mcp[cli]")

from typer.testing import CliRunner  # noqa: E402

from lauren_mcp.cli import app  # noqa: E402

runner = CliRunner()

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
            patch("lauren_mcp.cli._commands._write_mcp_config") as mock_write,
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
        mock_write.assert_called_once_with(str(cfg), "custom", "server.py")

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
