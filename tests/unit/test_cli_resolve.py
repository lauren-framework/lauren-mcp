"""Unit tests for lauren_mcp.cli._resolve."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

typer = pytest.importorskip("typer", reason="requires lauren-mcp[cli]")

from lauren_mcp.cli._commands import _get_config_path, _write_mcp_config  # noqa: E402
from lauren_mcp.cli._resolve import resolve_server_class  # noqa: E402
from lauren_mcp.server._meta import MCP_SERVER_META  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers to write temporary server files
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

_MULTI_SERVER = """\
from lauren_mcp.server._decorators import mcp_server

@mcp_server('/a')
class ServerA:
    pass

@mcp_server('/b')
class ServerB:
    pass
"""

_NO_SERVER = """\
class NotAServer:
    pass
"""

_PLAIN_CLASS = """\
from lauren_mcp.server._decorators import mcp_server

@mcp_server('/x')
class RealServer:
    pass

class NotAServer:
    pass
"""


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content)
    return p


# ---------------------------------------------------------------------------
# resolve_server_class
# ---------------------------------------------------------------------------


class TestResolveServerClass:
    def test_finds_single_mcp_server_class(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "server.py", _SINGLE_SERVER)
        cls = resolve_server_class(str(p))
        assert cls.__name__ == "MyServer"
        assert hasattr(cls, MCP_SERVER_META)

    def test_finds_named_class_with_colon_spec(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "server.py", _SINGLE_SERVER)
        cls = resolve_server_class(f"{p}:MyServer")
        assert cls.__name__ == "MyServer"

    def test_raises_on_multiple_classes_without_name(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "multi.py", _MULTI_SERVER)
        with pytest.raises(typer.BadParameter, match="Multiple @mcp_server"):
            resolve_server_class(str(p))

    def test_raises_on_no_mcp_server_class(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "empty.py", _NO_SERVER)
        with pytest.raises(typer.BadParameter, match="No @mcp_server"):
            resolve_server_class(str(p))

    def test_raises_on_missing_file(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.py"
        with pytest.raises(typer.BadParameter, match="File not found"):
            resolve_server_class(str(missing))

    def test_raises_on_nonexistent_named_class(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "server.py", _SINGLE_SERVER)
        with pytest.raises(typer.BadParameter, match="No attribute"):
            resolve_server_class(f"{p}:DoesNotExist")

    def test_raises_when_named_class_lacks_decorator(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "server.py", _PLAIN_CLASS)
        with pytest.raises(typer.BadParameter, match="not decorated with @mcp_server"):
            resolve_server_class(f"{p}:NotAServer")

    def test_multiple_classes_error_lists_names(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "multi.py", _MULTI_SERVER)
        with pytest.raises(typer.BadParameter) as exc_info:
            resolve_server_class(str(p))
        msg = str(exc_info.value)
        assert "ServerA" in msg or "ServerB" in msg

    def test_parent_dir_added_to_sys_path(self, tmp_path: Path) -> None:
        p = _write(tmp_path, "server.py", _SINGLE_SERVER)
        parent = str(tmp_path)
        # Remove parent from sys.path if present so we can verify it gets added.
        was_present = parent in sys.path
        if was_present:
            sys.path.remove(parent)
        try:
            resolve_server_class(str(p))
            assert parent in sys.path
        finally:
            if not was_present and parent in sys.path:
                sys.path.remove(parent)


# ---------------------------------------------------------------------------
# _get_config_path
# ---------------------------------------------------------------------------


class TestGetConfigPath:
    def test_claude_macos_path(self) -> None:
        with patch("platform.system", return_value="Darwin"):
            path = _get_config_path("claude")
        assert "Library/Application Support/Claude" in path
        assert path.endswith("claude_desktop_config.json")

    def test_claude_linux_path(self) -> None:
        with patch("platform.system", return_value="Linux"):
            path = _get_config_path("claude")
        assert ".config/claude" in path
        assert path.endswith("claude_desktop_config.json")

    def test_cursor_macos_path(self) -> None:
        with patch("platform.system", return_value="Darwin"):
            path = _get_config_path("cursor")
        assert "Cursor" in path
        assert path.endswith("mcp.json")

    def test_cursor_linux_path(self) -> None:
        with patch("platform.system", return_value="Linux"):
            path = _get_config_path("cursor")
        assert "Cursor" in path
        assert path.endswith("mcp.json")

    def test_unknown_client_raises_exit(self) -> None:
        with pytest.raises(typer.Exit):
            _get_config_path("unknown_client")


# ---------------------------------------------------------------------------
# _write_mcp_config
# ---------------------------------------------------------------------------


class TestWriteMcpConfig:
    def test_creates_file_if_absent(self, tmp_path: Path) -> None:
        import json

        config_file = tmp_path / "config.json"
        _write_mcp_config(str(config_file), "my_server", "server.py")
        assert config_file.exists()
        data = json.loads(config_file.read_text())
        assert "mcpServers" in data
        assert "my_server" in data["mcpServers"]

    def test_merges_into_existing_mcp_servers(self, tmp_path: Path) -> None:
        import json

        config_file = tmp_path / "config.json"
        existing = {"mcpServers": {"other_server": {"command": "python", "args": []}}}
        config_file.write_text(json.dumps(existing))
        _write_mcp_config(str(config_file), "my_server", "server.py")
        data = json.loads(config_file.read_text())
        assert "other_server" in data["mcpServers"]
        assert "my_server" in data["mcpServers"]

    def test_does_not_overwrite_other_top_level_keys(self, tmp_path: Path) -> None:
        import json

        config_file = tmp_path / "config.json"
        existing = {"globalShortcut": "Cmd+M", "mcpServers": {}}
        config_file.write_text(json.dumps(existing))
        _write_mcp_config(str(config_file), "my_server", "server.py")
        data = json.loads(config_file.read_text())
        assert data["globalShortcut"] == "Cmd+M"

    def test_overwrites_existing_entry_for_same_name(self, tmp_path: Path) -> None:
        import json

        config_file = tmp_path / "config.json"
        existing = {"mcpServers": {"my_server": {"command": "old_python", "args": ["old.py"]}}}
        config_file.write_text(json.dumps(existing))
        _write_mcp_config(str(config_file), "my_server", "new_server.py")
        data = json.loads(config_file.read_text())
        assert "new_server.py" in data["mcpServers"]["my_server"]["args"]

    def test_entry_uses_sys_executable(self, tmp_path: Path) -> None:
        import json

        config_file = tmp_path / "config.json"
        _write_mcp_config(str(config_file), "srv", "my_server.py")
        data = json.loads(config_file.read_text())
        assert data["mcpServers"]["srv"]["command"] == sys.executable

    def test_creates_parent_directory_if_needed(self, tmp_path: Path) -> None:

        config_file = tmp_path / "nested" / "dir" / "config.json"
        _write_mcp_config(str(config_file), "srv", "server.py")
        assert config_file.exists()
