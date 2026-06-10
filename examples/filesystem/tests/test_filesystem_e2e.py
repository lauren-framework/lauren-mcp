"""End-to-end tests for the Filesystem MCP Server over stdio.

Launches the server as a real subprocess with MCP_FS_ROOT pointing at a
temporary directory, then connects with McpServer.stdio(max_retries=0).

Exercises the full CRUD lifecycle:
  List → Write → Read → Move → Delete → verify gone
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest

from lauren_mcp import McpServer
from lauren_mcp._client._stdio import McpStdioClient

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Server script — spawned as a subprocess.
# Uses single-quoted docstrings throughout to avoid terminating the outer
# triple-quoted string literal.
# ---------------------------------------------------------------------------

_SERVER_SCRIPT = textwrap.dedent("""\
    import sys
    import os
    import asyncio
    import json
    from pathlib import Path

    # Allow the examples package to be imported from the repo root.
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    from examples.filesystem.server import FilesystemServer
    from lauren_mcp.server._meta import MCP_TOOL_META, MCP_RESOURCE_META, MCP_PROMPT_META
    from lauren_mcp.server._handlers import (
        make_tools_list_handler,
        make_tools_call_handler,
        make_resources_list_handler,
        make_resources_read_handler,
        make_prompts_list_handler,
        make_prompts_get_handler,
    )
    from lauren_mcp._server._dispatcher import McpDispatcher
    from lauren_mcp._server._context import LogLevelState
    from lauren_mcp._types import JsonRpcRequest


    async def main():
        root = Path(os.environ.get('MCP_FS_ROOT', '.')).resolve()
        root.mkdir(parents=True, exist_ok=True)
        lifespan_ctx = {'root': root, 'allowed_root': root}

        log_state = LogLevelState('info')

        def context_factory(tool_name, tool_use_id=None, progress_token=None,
                            send_notification=None, client_rpc=None,
                            client_capabilities=None):
            from lauren_mcp import McpToolContext
            return McpToolContext(
                tool_name=tool_name,
                tool_use_id=tool_use_id,
                lifespan_context=lifespan_ctx,
                _progress_token=progress_token,
                _send_notification=send_notification,
                _client_rpc=client_rpc,
                _client_capabilities=client_capabilities,
                _log_level_state=log_state,
            )

        server = FilesystemServer()

        tools, resources, prompts = [], [], []
        for attr_name in dir(FilesystemServer):
            try:
                attr = getattr(FilesystemServer, attr_name)
            except AttributeError:
                continue
            if hasattr(attr, MCP_TOOL_META):
                tools.append(getattr(attr, MCP_TOOL_META))
            if hasattr(attr, MCP_RESOURCE_META):
                resources.append(getattr(attr, MCP_RESOURCE_META))
            if hasattr(attr, MCP_PROMPT_META):
                prompts.append(getattr(attr, MCP_PROMPT_META))

        dispatcher = McpDispatcher()
        dispatcher._register_builtins()

        async def _init(params):
            return {
                'protocolVersion': '2025-03-26',
                'capabilities': {'tools': {}, 'resources': {}, 'prompts': {}},
                'serverInfo': {'name': 'filesystem-server', 'version': '1.0.0'},
            }
        dispatcher.register('initialize', _init)

        tl = make_tools_list_handler(tools)
        tc = make_tools_call_handler(server, tools, context_factory=context_factory)
        async def _tl(p): return await tl(JsonRpcRequest(method='tools/list', params=p))
        async def _tc(p): return await tc(JsonRpcRequest(method='tools/call', params=p))
        dispatcher.register('tools/list', _tl)
        dispatcher.register('tools/call', _tc)

        rl = make_resources_list_handler(resources)
        rr = make_resources_read_handler(server, resources)
        async def _rl(p): return await rl(JsonRpcRequest(method='resources/list', params=p))
        async def _rr(p): return await rr(JsonRpcRequest(method='resources/read', params=p))
        dispatcher.register('resources/list', _rl)
        dispatcher.register('resources/read', _rr)

        pl = make_prompts_list_handler(prompts)
        pg = make_prompts_get_handler(server, prompts)
        async def _pl(p): return await pl(JsonRpcRequest(method='prompts/list', params=p))
        async def _pg(p): return await pg(JsonRpcRequest(method='prompts/get', params=p))
        dispatcher.register('prompts/list', _pl)
        dispatcher.register('prompts/get', _pg)

        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        while True:
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=30.0)
            except asyncio.TimeoutError:
                break
            if not line:
                break
            raw = line.decode().strip()
            if not raw:
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            id_ = msg.get('id')
            if id_ is None:
                continue
            req = JsonRpcRequest(method=msg.get('method', ''), id=id_, params=msg.get('params'))
            resp = await dispatcher.dispatch(req)
            print(resp.to_json(), flush=True)

    asyncio.run(main())
""")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def fs_sandbox(tmp_path_factory):
    """Real temporary sandbox directory for e2e tests."""
    return tmp_path_factory.mktemp("e2e_fs_sandbox")


@pytest.fixture(scope="module")
def server_script(tmp_path_factory, fs_sandbox):
    """Write the server script to a temp file and return (command, sandbox)."""
    script_dir = tmp_path_factory.mktemp("scripts")
    script_path = script_dir / "fs_server.py"
    script_path.write_text(_SERVER_SCRIPT)
    return [sys.executable, str(script_path)], fs_sandbox


@pytest.fixture
async def fs_client(server_script, fs_sandbox):
    """Connected McpStdioClient backed by a real filesystem server subprocess.

    Environment variables are set on the current process before launching the
    subprocess (which inherits the parent environment).  They are restored after
    the fixture tears down.
    """
    command, sandbox = server_script

    # Patch env on the parent process so the child inherits the values.
    old_fs_root = os.environ.get("MCP_FS_ROOT")
    old_pythonpath = os.environ.get("PYTHONPATH")

    os.environ["MCP_FS_ROOT"] = str(fs_sandbox)

    # Add repo root to PYTHONPATH so the subprocess can import examples.filesystem.
    repo_root = str(Path(__file__).parent.parent.parent.parent)
    existing_pp = os.environ.get("PYTHONPATH", "")
    os.environ["PYTHONPATH"] = f"{repo_root}:{existing_pp}" if existing_pp else repo_root

    try:
        client: McpStdioClient = McpServer.stdio(command, max_retries=0)
        await asyncio.wait_for(client.connect(), timeout=15.0)
        yield client, fs_sandbox
        await client.close()
    finally:
        if old_fs_root is None:
            os.environ.pop("MCP_FS_ROOT", None)
        else:
            os.environ["MCP_FS_ROOT"] = old_fs_root
        if old_pythonpath is None:
            os.environ.pop("PYTHONPATH", None)
        else:
            os.environ["PYTHONPATH"] = old_pythonpath


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_text(result: dict) -> str:
    content = result.get("content", [])
    for c in content:
        if c.get("type") == "text":
            return c["text"]
    return ""


def _get_json(result: dict) -> Any:
    return json.loads(_get_text(result))


async def _call_tool(client, name: str, args: dict) -> dict:
    return await asyncio.wait_for(client.call_tool(name, args), timeout=10.0)


# ---------------------------------------------------------------------------
# Tests: Tool discovery
# ---------------------------------------------------------------------------


class TestE2EToolDiscovery:
    async def test_list_tools_returns_eight_tools(self, fs_client):
        client, _ = fs_client
        tools = await asyncio.wait_for(client.list_tools(), timeout=10.0)
        assert len(tools) == 12

    async def test_tool_names(self, fs_client):
        client, _ = fs_client
        tools = await asyncio.wait_for(client.list_tools(), timeout=10.0)
        names = {t.name for t in tools}
        expected = {
            "list_files",
            "read_file",
            "write_file",
            "create_directory",
            "delete_file",
            "delete_directory",
            "move_file",
            "file_info",
            "bulk_write_files",
            "bulk_delete_files",
            "bulk_copy_files",
            "sync_directory",
        }
        assert expected == names

    async def test_list_resources_includes_file_resource(self, fs_client):
        client, _ = fs_client
        resources = await asyncio.wait_for(client.list_resources(), timeout=10.0)
        uris = [r.uri for r in resources]
        assert any("file://" in u for u in uris)

    async def test_list_prompts_includes_edit_file_prompt(self, fs_client):
        client, _ = fs_client
        prompts = await asyncio.wait_for(client.list_prompts(), timeout=10.0)
        names = [p.name for p in prompts]
        assert "edit_file_prompt" in names


# ---------------------------------------------------------------------------
# Tests: Full CRUD cycle
# ---------------------------------------------------------------------------


class TestE2ECrudCycle:
    async def test_write_creates_file(self, fs_client):
        client, sandbox = fs_client
        result = await _call_tool(client, "write_file", {"path": "hello.txt", "content": "Hello!"})
        data = _get_json(result)
        assert data["created"] is True
        assert (sandbox / "hello.txt").read_text() == "Hello!"

    async def test_read_returns_content(self, fs_client):
        client, sandbox = fs_client
        (sandbox / "to_read.txt").write_text("Read me")
        result = await _call_tool(client, "read_file", {"path": "to_read.txt"})
        assert _get_text(result) == "Read me"

    async def test_list_shows_written_file(self, fs_client):
        client, sandbox = fs_client
        (sandbox / "listed.txt").write_text("listed")
        result = await _call_tool(client, "list_files", {"path": "."})
        entries = _get_json(result)
        assert any("listed.txt" in e for e in entries)

    async def test_create_directory_then_list(self, fs_client):
        client, sandbox = fs_client
        await _call_tool(client, "create_directory", {"path": "e2e_dir"})
        result = await _call_tool(client, "list_files", {"path": "."})
        entries = _get_json(result)
        assert any("e2e_dir" in e for e in entries)

    async def test_move_file(self, fs_client):
        client, sandbox = fs_client
        (sandbox / "pre_move.txt").write_text("movable")
        await _call_tool(
            client, "move_file", {"source": "pre_move.txt", "destination": "post_move.txt"}
        )
        assert not (sandbox / "pre_move.txt").exists()
        assert (sandbox / "post_move.txt").read_text() == "movable"

    async def test_delete_file(self, fs_client):
        client, sandbox = fs_client
        (sandbox / "deleteme.txt").write_text("bye")
        result = await _call_tool(client, "delete_file", {"path": "deleteme.txt"})
        data = _get_json(result)
        assert data["deleted"] is True
        assert not (sandbox / "deleteme.txt").exists()

    async def test_full_crud_sequence(self, fs_client):
        """Complete List → Write → Read → Move → Delete lifecycle."""
        client, sandbox = fs_client

        # Write
        write_res = await _call_tool(client, "write_file", {"path": "crud.txt", "content": "CRUD"})
        assert _get_json(write_res)["created"] is True

        # Read
        read_res = await _call_tool(client, "read_file", {"path": "crud.txt"})
        assert _get_text(read_res) == "CRUD"

        # List — should appear
        list_res = await _call_tool(client, "list_files", {"path": "."})
        assert any("crud.txt" in e for e in _get_json(list_res))

        # Move
        await _call_tool(
            client, "move_file", {"source": "crud.txt", "destination": "crud_moved.txt"}
        )
        assert not (sandbox / "crud.txt").exists()

        # Delete
        del_res = await _call_tool(client, "delete_file", {"path": "crud_moved.txt"})
        assert _get_json(del_res)["deleted"] is True

        # Verify gone
        list_res2 = await _call_tool(client, "list_files", {"path": "."})
        entries = _get_json(list_res2)
        assert not any("crud.txt" in e for e in entries)
        assert not any("crud_moved.txt" in e for e in entries)


# ---------------------------------------------------------------------------
# Tests: file_info
# ---------------------------------------------------------------------------


class TestE2EFileInfo:
    async def test_file_info_metadata(self, fs_client):
        client, sandbox = fs_client
        (sandbox / "info_e2e.txt").write_text("info")
        result = await _call_tool(client, "file_info", {"path": "info_e2e.txt"})
        data = _get_json(result)
        assert data["is_file"] is True
        assert data["name"] == "info_e2e.txt"
        assert data["extension"] == ".txt"


# ---------------------------------------------------------------------------
# Tests: Prompt
# ---------------------------------------------------------------------------


class TestE2EPrompt:
    async def test_edit_file_prompt_contains_instruction(self, fs_client):
        client, sandbox = fs_client
        result = await asyncio.wait_for(
            client.get_prompt(
                "edit_file_prompt", {"path": "any.txt", "instruction": "Make it better"}
            ),
            timeout=10.0,
        )
        messages = result.get("messages", [])
        text = " ".join(str(m) for m in messages)
        assert "Make it better" in text


# ---------------------------------------------------------------------------
# Tests: Error cases
# ---------------------------------------------------------------------------


class TestE2EErrors:
    async def test_read_nonexistent_raises_or_is_error(self, fs_client):
        """Reading a non-existent file raises McpCallError or returns isError=True."""
        from lauren_mcp import McpCallError

        client, _ = fs_client
        try:
            result = await _call_tool(client, "read_file", {"path": "nonexistent.txt"})
            assert result.get("isError") is True
        except McpCallError:
            pass  # Expected — stdio client raises McpCallError on JSON-RPC error

    async def test_delete_nonexistent_raises_or_is_error(self, fs_client):
        """Deleting a non-existent file raises McpCallError or returns isError=True."""
        from lauren_mcp import McpCallError

        client, _ = fs_client
        try:
            result = await _call_tool(client, "delete_file", {"path": "nonexistent_del.txt"})
            assert result.get("isError") is True
        except McpCallError:
            pass  # Expected

    async def test_traversal_raises_or_is_error(self, fs_client):
        """Path traversal raises McpCallError or returns isError=True."""
        from lauren_mcp import McpCallError

        client, _ = fs_client
        try:
            result = await _call_tool(client, "read_file", {"path": "../etc/passwd"})
            assert result.get("isError") is True
        except McpCallError as exc:
            assert "traversal" in str(exc).lower() or "outside" in str(exc).lower()

    async def test_ping_works(self, fs_client):
        client, _ = fs_client
        await asyncio.wait_for(client.ping(), timeout=5.0)
