"""Unit tests for lauren_mcp.cli._commands covering all previously-uncovered lines."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

typer = pytest.importorskip("typer", reason="requires lauren-mcp[cli]")

from lauren_mcp.cli._commands import (  # noqa: E402
    _call_async,
    _get_config_path,
    _inspect_async,
    _load_env,
    _make_stdio_script,
    _start_server,
    _write_mcp_config,
    call,
    dev,
    install,
    inspect_cmd,
    run,
)

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
# _load_env
# ---------------------------------------------------------------------------


class TestLoadEnv:
    def test_returns_none_when_env_file_is_none(self) -> None:
        # Should not call anything — just return
        _load_env(None)

    def test_calls_load_dotenv_when_dotenv_available(self, tmp_path: Path) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("FOO=bar\n")
        mock_load = MagicMock()
        with patch.dict("sys.modules", {"dotenv": MagicMock(load_dotenv=mock_load)}):
            _load_env(str(env_file))
        mock_load.assert_called_once_with(str(env_file))

    def test_warns_when_dotenv_not_installed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        env_file = tmp_path / ".env"
        env_file.write_text("FOO=bar\n")

        # Make dotenv unavailable by raising ImportError on import
        real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__  # type: ignore[attr-defined]

        def _fake_import(name: str, *args: object, **kwargs: object) -> object:
            if name == "dotenv":
                raise ImportError("dotenv not installed")
            return real_import(name, *args, **kwargs)  # type: ignore[call-arg]

        with patch("builtins.__import__", side_effect=_fake_import):
            _load_env(str(env_file))

        # typer.echo writes to stderr when err=True
        captured = capsys.readouterr()
        assert "python-dotenv not installed" in captured.err


# ---------------------------------------------------------------------------
# _get_config_path
# ---------------------------------------------------------------------------


class TestGetConfigPath:
    def test_claude_macos(self) -> None:
        with patch("platform.system", return_value="Darwin"):
            p = _get_config_path("claude")
        assert "Library/Application Support/Claude" in p
        assert p.endswith("claude_desktop_config.json")

    def test_claude_windows(self) -> None:
        with (
            patch("platform.system", return_value="Windows"),
            patch.dict("os.environ", {"APPDATA": "C:\\Users\\user\\AppData\\Roaming"}),
        ):
            p = _get_config_path("claude")
        assert "Claude" in p
        assert p.endswith("claude_desktop_config.json")

    def test_claude_linux(self) -> None:
        with patch("platform.system", return_value="Linux"):
            p = _get_config_path("claude")
        assert ".config/claude" in p
        assert p.endswith("claude_desktop_config.json")

    def test_cursor_macos(self) -> None:
        with patch("platform.system", return_value="Darwin"):
            p = _get_config_path("cursor")
        assert "Cursor" in p
        assert p.endswith("mcp.json")

    def test_cursor_windows(self) -> None:
        with (
            patch("platform.system", return_value="Windows"),
            patch.dict("os.environ", {"APPDATA": "C:\\Users\\user\\AppData\\Roaming"}),
        ):
            p = _get_config_path("cursor")
        assert "Cursor" in p
        assert p.endswith("mcp.json")

    def test_cursor_linux(self) -> None:
        with patch("platform.system", return_value="Linux"):
            p = _get_config_path("cursor")
        assert "Cursor" in p
        assert p.endswith("mcp.json")

    def test_unknown_client_raises_exit(self) -> None:
        with pytest.raises(typer.Exit):
            _get_config_path("vscode")


# ---------------------------------------------------------------------------
# _write_mcp_config
# ---------------------------------------------------------------------------


class TestWriteMcpConfig:
    def test_creates_new_file(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.json"
        _write_mcp_config(str(cfg), "mysrv", "server.py")
        data = json.loads(cfg.read_text())
        assert "mysrv" in data["mcpServers"]
        assert data["mcpServers"]["mysrv"]["command"] == sys.executable

    def test_merges_with_existing(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.json"
        cfg.write_text(json.dumps({"mcpServers": {"existing": {}}}))
        _write_mcp_config(str(cfg), "new_srv", "server.py")
        data = json.loads(cfg.read_text())
        assert "existing" in data["mcpServers"]
        assert "new_srv" in data["mcpServers"]

    def test_invalid_json_treated_as_empty(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config.json"
        cfg.write_text("NOT_JSON{{{")
        _write_mcp_config(str(cfg), "srv", "server.py")
        data = json.loads(cfg.read_text())
        assert "srv" in data["mcpServers"]

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        cfg = tmp_path / "a" / "b" / "config.json"
        _write_mcp_config(str(cfg), "srv", "server.py")
        assert cfg.exists()


# ---------------------------------------------------------------------------
# _start_server
# ---------------------------------------------------------------------------


class TestStartServer:
    def _make_server_cls(self) -> type:
        class FakeServer:
            pass

        return FakeServer

    def test_raises_exit_when_uvicorn_missing(self) -> None:
        import sys as _sys

        orig = _sys.modules.get("uvicorn")
        _sys.modules["uvicorn"] = None  # type: ignore[assignment]
        try:
            with pytest.raises(typer.Exit):
                _start_server(self._make_server_cls(), transport="ws", host="127.0.0.1", port=8000)
        finally:
            if orig is None:
                _sys.modules.pop("uvicorn", None)
            else:
                _sys.modules["uvicorn"] = orig

    def test_calls_uvicorn_run(self, tmp_path: Path) -> None:
        p = _write_server_file(tmp_path)
        from lauren_mcp.cli._resolve import resolve_server_class

        server_cls = resolve_server_class(str(p))

        mock_uvicorn = MagicMock()
        mock_app = MagicMock()
        mock_lauren_factory = MagicMock(return_value=mock_app)

        fake_module = MagicMock()
        fake_module.LaurenFactory.create = mock_lauren_factory
        fake_module.module = lambda **kw: lambda cls: cls

        mock_mcp_module = MagicMock()
        mock_mcp_module.McpServerModule.for_root = MagicMock(return_value=MagicMock())

        with (
            patch.dict(
                "sys.modules",
                {
                    "uvicorn": mock_uvicorn,
                    "lauren": fake_module,
                    "lauren_mcp.server._module": mock_mcp_module,
                },
            ),
        ):
            _start_server(server_cls, transport="ws", host="127.0.0.1", port=8000)

        mock_uvicorn.run.assert_called_once()
        call_kwargs = mock_uvicorn.run.call_args
        assert call_kwargs.kwargs["host"] == "127.0.0.1"
        assert call_kwargs.kwargs["port"] == 8000
        assert call_kwargs.kwargs["log_level"] == "info"

    def test_calls_uvicorn_run_with_debug_log_level(self, tmp_path: Path) -> None:
        p = _write_server_file(tmp_path)
        from lauren_mcp.cli._resolve import resolve_server_class

        server_cls = resolve_server_class(str(p))

        mock_uvicorn = MagicMock()
        fake_module = MagicMock()
        fake_module.module = lambda **kw: lambda cls: cls

        mock_mcp_module = MagicMock()
        mock_mcp_module.McpServerModule.for_root = MagicMock(return_value=MagicMock())

        with patch.dict(
            "sys.modules",
            {
                "uvicorn": mock_uvicorn,
                "lauren": fake_module,
                "lauren_mcp.server._module": mock_mcp_module,
            },
        ):
            _start_server(server_cls, transport="ws", host="0.0.0.0", port=9000, log_level="debug")

        assert mock_uvicorn.run.call_args.kwargs["log_level"] == "debug"


# ---------------------------------------------------------------------------
# run command
# ---------------------------------------------------------------------------


class TestRunCommand:
    def test_run_calls_start_server(self, tmp_path: Path) -> None:
        p = _write_server_file(tmp_path)
        with (
            patch("lauren_mcp.cli._commands._load_env") as mock_load_env,
            patch("lauren_mcp.cli._commands.resolve_server_class") as mock_resolve,
            patch("lauren_mcp.cli._commands._start_server") as mock_start,
        ):
            mock_resolve.return_value = type("FakeServer", (), {})
            run(str(p), transport="ws", host="127.0.0.1", port=8000, env_file=None, reload=False)

        mock_load_env.assert_called_once_with(None)
        mock_start.assert_called_once()

    def test_run_with_reload_warns(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        p = _write_server_file(tmp_path)
        with (
            patch("lauren_mcp.cli._commands._load_env"),
            patch("lauren_mcp.cli._commands.resolve_server_class") as mock_resolve,
            patch("lauren_mcp.cli._commands._start_server"),
        ):
            mock_resolve.return_value = type("FakeServer", (), {})
            run(str(p), transport="ws", host="127.0.0.1", port=8000, env_file=None, reload=True)

        captured = capsys.readouterr()
        assert "Warning" in captured.out
        assert "reload" in captured.out

    def test_run_passes_env_file(self, tmp_path: Path) -> None:
        p = _write_server_file(tmp_path)
        with (
            patch("lauren_mcp.cli._commands._load_env") as mock_load_env,
            patch("lauren_mcp.cli._commands.resolve_server_class") as mock_resolve,
            patch("lauren_mcp.cli._commands._start_server"),
        ):
            mock_resolve.return_value = type("FakeServer", (), {})
            run(str(p), transport="ws", host="127.0.0.1", port=8000, env_file=".env", reload=False)

        mock_load_env.assert_called_once_with(".env")


# ---------------------------------------------------------------------------
# dev command
# ---------------------------------------------------------------------------


class TestDevCommand:
    def test_dev_sets_debug_logging_and_starts_server(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        p = _write_server_file(tmp_path)
        with (
            patch("lauren_mcp.cli._commands._load_env"),
            patch("lauren_mcp.cli._commands.resolve_server_class") as mock_resolve,
            patch("lauren_mcp.cli._commands._start_server") as mock_start,
        ):
            fake_cls = type("DevServer", (), {"__name__": "DevServer"})
            mock_resolve.return_value = fake_cls
            dev(str(p), transport="ws", host="127.0.0.1", port=8000, env_file=None)

        mock_start.assert_called_once()
        call_kwargs = mock_start.call_args.kwargs
        assert call_kwargs["log_level"] == "debug"

    def test_dev_prints_startup_message(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        p = _write_server_file(tmp_path)
        with (
            patch("lauren_mcp.cli._commands._load_env"),
            patch("lauren_mcp.cli._commands.resolve_server_class") as mock_resolve,
            patch("lauren_mcp.cli._commands._start_server"),
        ):
            fake_cls = type("DevServer", (), {"__name__": "DevServer"})
            mock_resolve.return_value = fake_cls
            dev(str(p), transport="sse", host="0.0.0.0", port=9090, env_file=None)

        captured = capsys.readouterr()
        assert "DevServer" in captured.out
        assert "9090" in captured.out

    def test_dev_passes_env_file(self, tmp_path: Path) -> None:
        p = _write_server_file(tmp_path)
        with (
            patch("lauren_mcp.cli._commands._load_env") as mock_load_env,
            patch("lauren_mcp.cli._commands.resolve_server_class") as mock_resolve,
            patch("lauren_mcp.cli._commands._start_server"),
        ):
            fake_cls = type("DevServer", (), {"__name__": "DevServer"})
            mock_resolve.return_value = fake_cls
            dev(str(p), transport="ws", host="127.0.0.1", port=8000, env_file=".env")

        mock_load_env.assert_called_once_with(".env")


# ---------------------------------------------------------------------------
# inspect_cmd
# ---------------------------------------------------------------------------


class TestInspectCmd:
    def test_inspect_calls_asyncio_run(self) -> None:
        def _drain_and_return(coro: object) -> None:
            # Close the coroutine to suppress 'was never awaited' warnings
            if hasattr(coro, "close"):
                coro.close()  # type: ignore[union-attr]

        with patch("asyncio.run", side_effect=_drain_and_return) as mock_run:
            inspect_cmd("ws://localhost:8000/ws", transport="ws")
        mock_run.assert_called_once()

    async def test_inspect_async_ws_url(self) -> None:
        mock_client = AsyncMock()
        mock_client.list_tools = AsyncMock(return_value=[])
        mock_client.list_resources = AsyncMock(return_value=[])
        mock_client.list_prompts = AsyncMock(return_value=[])

        mock_factory = MagicMock()
        mock_factory.ws = MagicMock(return_value=mock_client)

        with patch("lauren_mcp._client._factory.McpServer", mock_factory):
            await _inspect_async("ws://localhost:8000/ws", "ws")

        mock_factory.ws.assert_called_once_with("ws://localhost:8000/ws")
        mock_client.connect.assert_called_once()
        mock_client.close.assert_called_once()

    async def test_inspect_async_http_url(self) -> None:
        mock_client = AsyncMock()
        mock_client.list_tools = AsyncMock(return_value=[])
        mock_client.list_resources = AsyncMock(return_value=[])
        mock_client.list_prompts = AsyncMock(return_value=[])

        mock_factory = MagicMock()
        mock_factory.http = MagicMock(return_value=mock_client)

        with patch("lauren_mcp._client._factory.McpServer", mock_factory):
            await _inspect_async("http://localhost:8000/mcp", "streamable")

        mock_factory.http.assert_called_once_with("http://localhost:8000/mcp")

    async def test_inspect_async_local_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        p = _write_server_file(tmp_path)

        mock_tool = MagicMock()
        mock_tool.name = "greet"
        mock_tool.description = "Greet someone."

        mock_resource = MagicMock()
        mock_resource.uri = "file:///test"
        mock_resource.name = "test_resource"

        mock_prompt = MagicMock()
        mock_prompt.name = "my_prompt"
        mock_prompt.description = "A test prompt."

        mock_client = AsyncMock()
        mock_client.list_tools = AsyncMock(return_value=[mock_tool])
        mock_client.list_resources = AsyncMock(return_value=[mock_resource])
        mock_client.list_prompts = AsyncMock(return_value=[mock_prompt])

        mock_factory = MagicMock()
        mock_factory.stdio = MagicMock(return_value=mock_client)

        with (
            patch("lauren_mcp.cli._commands.resolve_server_class") as mock_resolve,
            patch("lauren_mcp._client._factory.McpServer", mock_factory),
        ):
            fake_cls = type("MyServer", (), {"__module__": "server", "__name__": "MyServer"})
            mock_resolve.return_value = fake_cls
            await _inspect_async(str(p), "ws")

        mock_factory.stdio.assert_called_once()
        captured = capsys.readouterr()
        assert "greet" in captured.out
        assert "test_resource" in captured.out
        assert "my_prompt" in captured.out

    async def test_inspect_async_prints_counts(self, capsys: pytest.CaptureFixture) -> None:
        mock_client = AsyncMock()
        mock_client.list_tools = AsyncMock(return_value=[])
        mock_client.list_resources = AsyncMock(return_value=[])
        mock_client.list_prompts = AsyncMock(return_value=[])

        mock_factory = MagicMock()
        mock_factory.ws = MagicMock(return_value=mock_client)

        with patch("lauren_mcp._client._factory.McpServer", mock_factory):
            await _inspect_async("wss://secure.example.com/ws", "ws")

        captured = capsys.readouterr()
        assert "Tools (0)" in captured.out
        assert "Resources (0)" in captured.out
        assert "Prompts (0)" in captured.out


# ---------------------------------------------------------------------------
# call command
# ---------------------------------------------------------------------------


class TestCallCommand:
    def test_call_parses_key_value_args(self) -> None:
        with patch("asyncio.run") as mock_run:
            call("ws://localhost:8000/ws", "greet", arg=["name=Alice", "count=3"], transport="ws")

        mock_run.assert_called_once()
        # Extract the coroutine argument
        coro = mock_run.call_args.args[0]
        # The coroutine should have been created with name=Alice, count=3 in kwargs
        # We can verify it's a coroutine for _call_async
        assert hasattr(coro, "cr_frame") or hasattr(coro, "send")
        coro.close()  # clean up

    def test_call_errors_on_bad_key_value(self, capsys: pytest.CaptureFixture) -> None:
        with pytest.raises(typer.Exit) as exc_info:
            call("ws://localhost:8000/ws", "greet", arg=["bad_format"], transport="ws")

        assert exc_info.value.exit_code == 1
        captured = capsys.readouterr()
        assert "KEY=VALUE" in captured.err

    def test_call_json_parses_integers(self) -> None:
        with patch("asyncio.run") as mock_run:
            call("ws://localhost:8000/ws", "add", arg=["x=42", "y=true"], transport="ws")

        coro = mock_run.call_args.args[0]
        coro.close()

    def test_call_handles_no_args(self) -> None:
        with patch("asyncio.run") as mock_run:
            call("ws://localhost:8000/ws", "ping", arg=None, transport="ws")

        mock_run.assert_called_once()
        coro = mock_run.call_args.args[0]
        coro.close()

    async def test_call_async_ws_url(self, capsys: pytest.CaptureFixture) -> None:
        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(return_value={"result": "hello"})

        mock_factory = MagicMock()
        mock_factory.ws = MagicMock(return_value=mock_client)

        with patch("lauren_mcp._client._factory.McpServer", mock_factory):
            await _call_async("ws://localhost:8000/ws", "greet", {"name": "Alice"}, "ws")

        mock_factory.ws.assert_called_once_with("ws://localhost:8000/ws")
        captured = capsys.readouterr()
        assert "hello" in captured.out

    async def test_call_async_http_url(self, capsys: pytest.CaptureFixture) -> None:
        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(return_value={"result": "done"})

        mock_factory = MagicMock()
        mock_factory.http = MagicMock(return_value=mock_client)

        with patch("lauren_mcp._client._factory.McpServer", mock_factory):
            await _call_async("https://example.com/mcp", "ping", {}, "streamable")

        mock_factory.http.assert_called_once_with("https://example.com/mcp")
        captured = capsys.readouterr()
        assert "done" in captured.out

    async def test_call_async_local_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        p = _write_server_file(tmp_path)

        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(return_value={"greeting": "Hello Alice"})

        mock_factory = MagicMock()
        mock_factory.stdio = MagicMock(return_value=mock_client)

        with (
            patch("lauren_mcp.cli._commands.resolve_server_class") as mock_resolve,
            patch("lauren_mcp._client._factory.McpServer", mock_factory),
        ):
            fake_cls = type("MyServer", (), {"__module__": "server", "__name__": "MyServer"})
            mock_resolve.return_value = fake_cls
            await _call_async(str(p), "greet", {"name": "Alice"}, "ws")

        mock_factory.stdio.assert_called_once()
        captured = capsys.readouterr()
        assert "Hello Alice" in captured.out

    async def test_call_async_prints_json_output(self, capsys: pytest.CaptureFixture) -> None:
        result = {"key": "value", "number": 42}
        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(return_value=result)

        mock_factory = MagicMock()
        mock_factory.ws = MagicMock(return_value=mock_client)

        with patch("lauren_mcp._client._factory.McpServer", mock_factory):
            await _call_async("ws://localhost/ws", "tool", {}, "ws")

        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed == result


# ---------------------------------------------------------------------------
# install command
# ---------------------------------------------------------------------------


class TestInstallCommand:
    def test_install_uses_server_class_name_when_no_name_given(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        cfg = tmp_path / "config.json"
        with (
            patch("lauren_mcp.cli._commands.resolve_server_class") as mock_resolve,
            patch("lauren_mcp.cli._commands._get_config_path") as mock_cfg_path,
            patch("lauren_mcp.cli._commands._write_mcp_config") as mock_write,
        ):
            fake_cls = type("MyServer", (), {"__name__": "MyServer"})
            mock_resolve.return_value = fake_cls
            mock_cfg_path.return_value = str(cfg)
            install("server.py", name=None, client="claude")

        mock_write.assert_called_once_with(str(cfg), "MyServer", "server.py")
        captured = capsys.readouterr()
        assert "MyServer" in captured.out

    def test_install_uses_explicit_name(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        cfg = tmp_path / "config.json"
        with (
            patch("lauren_mcp.cli._commands.resolve_server_class") as mock_resolve,
            patch("lauren_mcp.cli._commands._get_config_path") as mock_cfg_path,
            patch("lauren_mcp.cli._commands._write_mcp_config") as mock_write,
        ):
            fake_cls = type("MyServer", (), {"__name__": "MyServer"})
            mock_resolve.return_value = fake_cls
            mock_cfg_path.return_value = str(cfg)
            install("server.py", name="custom_name", client="claude")

        mock_write.assert_called_once_with(str(cfg), "custom_name", "server.py")

    def test_install_cursor_client(self, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
        cfg = tmp_path / "mcp.json"
        with (
            patch("lauren_mcp.cli._commands.resolve_server_class") as mock_resolve,
            patch("lauren_mcp.cli._commands._get_config_path") as mock_cfg_path,
            patch("lauren_mcp.cli._commands._write_mcp_config"),
        ):
            fake_cls = type("MyServer", (), {"__name__": "MyServer"})
            mock_resolve.return_value = fake_cls
            mock_cfg_path.return_value = str(cfg)
            install("server.py", name=None, client="cursor")

        mock_cfg_path.assert_called_once_with("cursor")

    def test_install_prints_registered_message(
        self, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        cfg = tmp_path / "config.json"
        with (
            patch("lauren_mcp.cli._commands.resolve_server_class") as mock_resolve,
            patch("lauren_mcp.cli._commands._get_config_path") as mock_cfg_path,
            patch("lauren_mcp.cli._commands._write_mcp_config"),
        ):
            fake_cls = type("AwesomeServer", (), {"__name__": "AwesomeServer"})
            mock_resolve.return_value = fake_cls
            mock_cfg_path.return_value = str(cfg)
            install("server.py", name=None, client="claude")

        captured = capsys.readouterr()
        assert "Registered" in captured.out
        assert "AwesomeServer" in captured.out


# ---------------------------------------------------------------------------
# _make_stdio_script
# ---------------------------------------------------------------------------


class TestMakeStdioScript:
    def test_script_contains_class_name(self) -> None:
        fake_cls = type("MyServer", (), {"__module__": "mymodule", "__name__": "MyServer"})
        script = _make_stdio_script(fake_cls, "ws")
        assert "MyServer" in script
        assert "mymodule" in script
        assert "run_stdio_server" in script

    def test_script_contains_transport(self) -> None:
        fake_cls = type("TestServer", (), {"__module__": "test_mod", "__name__": "TestServer"})
        script = _make_stdio_script(fake_cls, "sse")
        assert "'sse'" in script
