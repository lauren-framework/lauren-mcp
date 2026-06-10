"""Integration tests for the Filesystem MCP Server.

Uses LaurenFactory.create(FilesystemModule) + TestClient(app) + WsTestClient
with a real temporary directory set via MCP_FS_ROOT.

Test classes:
  TestToolListing           — tools/list returns all 8 tools with correct annotations
  TestWriteReadRoundTrip    — write_file then read_file round-trip
  TestDirectoryOperations   — create_directory, list_files
  TestDeleteOperations      — delete_file, delete_directory
  TestMoveFile              — move_file semantics
  TestFileInfo              — file_info metadata
  TestPathTraversal         — all tools reject ../  traversal attempts
  TestFileResource          — file://{path} resource returns file content
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import pytest
from lauren import LaurenFactory, module
from lauren.testing import TestClient, WsTestClient

from lauren_mcp import McpServerModule

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# App fixture — one app per test class, real temp directory
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def sandbox(tmp_path_factory):
    """A real temporary directory used as the MCP_FS_ROOT sandbox."""
    return tmp_path_factory.mktemp("fs_sandbox")


@pytest.fixture(scope="module")
def fs_app(sandbox):
    """Create the filesystem Lauren app with the sandbox as MCP_FS_ROOT."""
    old_root = os.environ.get("MCP_FS_ROOT")
    os.environ["MCP_FS_ROOT"] = str(sandbox)
    try:
        # Import server after setting env var so FilesystemModule picks up the path.
        from examples.filesystem.server import FilesystemServer

        @module(imports=[McpServerModule.for_root(FilesystemServer, transport="ws")])
        class _App:
            pass

        application = LaurenFactory.create(_App)
        TestClient(application)  # triggers @post_construct / lifespan
        yield application
    finally:
        if old_root is None:
            os.environ.pop("MCP_FS_ROOT", None)
        else:
            os.environ["MCP_FS_ROOT"] = old_root


# ---------------------------------------------------------------------------
# WS helpers
# ---------------------------------------------------------------------------


async def _handshake(conn: Any) -> dict:
    await conn.send_json(
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
    resp = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
    await conn.send_json({"jsonrpc": "2.0", "method": "notifications/initialized"})
    return resp


async def _call(conn: Any, name: str, args: dict, req_id: int = 2) -> dict:
    await conn.send_json(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
        }
    )
    # Drain notifications until we get a response with our id.
    while True:
        msg = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
        if msg.get("id") == req_id:
            return msg


async def _list_tools(conn: Any, req_id: int = 3) -> list[dict]:
    await conn.send_json({"jsonrpc": "2.0", "id": req_id, "method": "tools/list", "params": {}})
    resp = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
    return resp["result"]["tools"]


async def _read_resource(conn: Any, uri: str, req_id: int = 4) -> dict:
    await conn.send_json(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "resources/read",
            "params": {"uri": uri},
        }
    )
    return await asyncio.wait_for(conn.receive_json(), timeout=5.0)


def _text(result: dict) -> str:
    """Extract the first text content from a tools/call result dict."""
    content = result.get("result", {}).get("content", [])
    for item in content:
        if item.get("type") == "text":
            return item["text"]
    return ""


def _json_result(result: dict) -> Any:
    return json.loads(_text(result))


# ---------------------------------------------------------------------------
# 1. Tool listing
# ---------------------------------------------------------------------------


class TestToolListing:
    _EXPECTED_TOOLS = {
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

    async def test_tools_list_returns_all_twelve_tools(self, fs_app):
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            tools = await _list_tools(conn)
            names = {t["name"] for t in tools}
            assert names == self._EXPECTED_TOOLS

    async def test_read_only_tools_have_readOnlyHint(self, fs_app):
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            tools = await _list_tools(conn)
            by_name = {t["name"]: t for t in tools}
            for read_tool in ("list_files", "read_file", "file_info"):
                annotations = by_name[read_tool].get("annotations", {})
                assert annotations.get("readOnlyHint") is True, (
                    f"{read_tool!r} missing readOnlyHint"
                )

    async def test_destructive_tools_have_destructiveHint(self, fs_app):
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            tools = await _list_tools(conn)
            by_name = {t["name"]: t for t in tools}
            for dt in ("write_file", "delete_file", "delete_directory", "move_file"):
                annotations = by_name[dt].get("annotations", {})
                assert annotations.get("destructiveHint") is True, f"{dt!r} missing destructiveHint"

    async def test_all_tools_have_descriptions(self, fs_app):
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            tools = await _list_tools(conn)
            for t in tools:
                assert t.get("description"), f"Tool {t['name']!r} has no description"

    async def test_list_files_has_path_and_recursive_params(self, fs_app):
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            tools = await _list_tools(conn)
            lf = next(t for t in tools if t["name"] == "list_files")
            props = lf["inputSchema"]["properties"]
            assert "path" in props
            assert "recursive" in props

    async def test_write_file_has_create_dirs_param(self, fs_app):
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            tools = await _list_tools(conn)
            wf = next(t for t in tools if t["name"] == "write_file")
            props = wf["inputSchema"]["properties"]
            assert "create_dirs" in props


# ---------------------------------------------------------------------------
# 2. Write / read round-trip
# ---------------------------------------------------------------------------


class TestWriteReadRoundTrip:
    async def test_write_then_read_returns_same_content(self, fs_app):
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            content = "Hello from integration test!"
            write_resp = await _call(
                conn, "write_file", {"path": "roundtrip.txt", "content": content}
            )
            assert write_resp.get("error") is None
            read_resp = await _call(conn, "read_file", {"path": "roundtrip.txt"}, req_id=3)
            assert _text(read_resp) == content

    async def test_write_returns_created_true_for_new_file(self, fs_app):
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            resp = await _call(conn, "write_file", {"path": "brand_new.txt", "content": "new"})
            data = _json_result(resp)
            assert data["created"] is True

    async def test_write_returns_created_false_for_existing_file(self, fs_app, sandbox):
        (sandbox / "existing.txt").write_text("was here")
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            resp = await _call(conn, "write_file", {"path": "existing.txt", "content": "updated"})
            data = _json_result(resp)
            assert data["created"] is False

    async def test_write_returns_bytes_written(self, fs_app):
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            content = "precise byte count"
            resp = await _call(conn, "write_file", {"path": "bytes_test.txt", "content": content})
            data = _json_result(resp)
            assert data["bytes_written"] == len(content.encode())

    async def test_write_unicode_content_round_trips(self, fs_app):
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            content = "Unicode: 中文测试 \U0001f600"
            await _call(conn, "write_file", {"path": "unicode.txt", "content": content})
            resp = await _call(conn, "read_file", {"path": "unicode.txt"}, req_id=3)
            assert _text(resp) == content

    async def test_overwrite_changes_content(self, fs_app):
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            await _call(conn, "write_file", {"path": "overwrite_me.txt", "content": "first"})
            await _call(
                conn, "write_file", {"path": "overwrite_me.txt", "content": "second"}, req_id=3
            )
            resp = await _call(conn, "read_file", {"path": "overwrite_me.txt"}, req_id=4)
            assert _text(resp) == "second"


# ---------------------------------------------------------------------------
# 3. Directory operations
# ---------------------------------------------------------------------------


class TestDirectoryOperations:
    async def test_create_directory_then_list_shows_new_dir(self, fs_app):
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            await _call(conn, "create_directory", {"path": "new_dir_integration"})
            resp = await _call(conn, "list_files", {"path": "."}, req_id=3)
            entries = _json_result(resp)
            assert any("new_dir_integration" in e for e in entries)

    async def test_create_directory_returns_created_true(self, fs_app):
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            resp = await _call(conn, "create_directory", {"path": "fresh_dir"})
            data = _json_result(resp)
            assert data["created"] is True

    async def test_create_directory_idempotent(self, fs_app):
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            await _call(conn, "create_directory", {"path": "idem_dir"})
            resp = await _call(conn, "create_directory", {"path": "idem_dir"}, req_id=3)
            data = _json_result(resp)
            assert data["created"] is False

    async def test_list_files_recursive(self, fs_app, sandbox):
        (sandbox / "recdir").mkdir(exist_ok=True)
        (sandbox / "recdir" / "deep.txt").write_text("deep")
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            resp = await _call(conn, "list_files", {"path": ".", "recursive": True})
            entries = _json_result(resp)
            assert any("deep.txt" in e for e in entries)

    async def test_write_with_create_dirs(self, fs_app):
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            resp = await _call(
                conn,
                "write_file",
                {"path": "auto/parents/file.txt", "content": "auto-created", "create_dirs": True},
            )
            assert resp.get("error") is None


# ---------------------------------------------------------------------------
# 4. Delete operations
# ---------------------------------------------------------------------------


class TestDeleteOperations:
    async def test_delete_file_removes_it(self, fs_app, sandbox):
        (sandbox / "to_delete.txt").write_text("gone")
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            resp = await _call(conn, "delete_file", {"path": "to_delete.txt"})
            data = _json_result(resp)
            assert data["deleted"] is True
            assert not (sandbox / "to_delete.txt").exists()

    async def test_delete_nonexistent_file_returns_error(self, fs_app):
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            resp = await _call(conn, "delete_file", {"path": "ghost.txt"})
            assert resp.get("error") is not None or (resp.get("result", {}).get("isError") is True)

    async def test_delete_directory_empty(self, fs_app, sandbox):
        (sandbox / "empty_to_delete").mkdir(exist_ok=True)
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            resp = await _call(conn, "delete_directory", {"path": "empty_to_delete"})
            data = _json_result(resp)
            assert data["deleted"] is True

    async def test_delete_nonempty_without_recursive_is_error(self, fs_app, sandbox):
        d = sandbox / "nonempty_dir"
        d.mkdir(exist_ok=True)
        (d / "file.txt").write_text("x")
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            resp = await _call(conn, "delete_directory", {"path": "nonempty_dir"})
            # Should be an error result
            assert resp.get("error") is not None or (resp.get("result", {}).get("isError") is True)

    async def test_delete_directory_recursive(self, fs_app, sandbox):
        d = sandbox / "big_tree"
        d.mkdir(exist_ok=True)
        (d / "a.txt").write_text("a")
        (d / "sub").mkdir()
        (d / "sub" / "b.txt").write_text("b")
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            resp = await _call(conn, "delete_directory", {"path": "big_tree", "recursive": True})
            data = _json_result(resp)
            assert data["deleted"] is True
            assert not (sandbox / "big_tree").exists()


# ---------------------------------------------------------------------------
# 5. Move file
# ---------------------------------------------------------------------------


class TestMoveFile:
    async def test_move_file_source_gone_dest_exists(self, fs_app, sandbox):
        (sandbox / "movable.txt").write_text("move me")
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            resp = await _call(
                conn, "move_file", {"source": "movable.txt", "destination": "moved.txt"}
            )
            data = _json_result(resp)
            assert data["moved"] is True
            assert not (sandbox / "movable.txt").exists()
            assert (sandbox / "moved.txt").read_text() == "move me"

    async def test_move_to_existing_without_overwrite_is_error(self, fs_app, sandbox):
        (sandbox / "src_no_ow.txt").write_text("src")
        (sandbox / "dst_no_ow.txt").write_text("dst")
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            resp = await _call(
                conn, "move_file", {"source": "src_no_ow.txt", "destination": "dst_no_ow.txt"}
            )
            assert resp.get("error") is not None or (resp.get("result", {}).get("isError") is True)

    async def test_move_with_overwrite(self, fs_app, sandbox):
        (sandbox / "src_ow.txt").write_text("winner")
        (sandbox / "dst_ow.txt").write_text("loser")
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            resp = await _call(
                conn,
                "move_file",
                {"source": "src_ow.txt", "destination": "dst_ow.txt", "overwrite": True},
            )
            data = _json_result(resp)
            assert data["moved"] is True
            assert (sandbox / "dst_ow.txt").read_text() == "winner"


# ---------------------------------------------------------------------------
# 6. file_info
# ---------------------------------------------------------------------------


class TestFileInfo:
    async def test_file_info_returns_correct_metadata(self, fs_app, sandbox):
        (sandbox / "info_test.py").write_text("# test")
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            resp = await _call(conn, "file_info", {"path": "info_test.py"})
            data = _json_result(resp)
            assert data["name"] == "info_test.py"
            assert data["is_file"] is True
            assert data["is_dir"] is False
            assert data["extension"] == ".py"
            assert data["size"] >= 0

    async def test_file_info_for_directory(self, fs_app, sandbox):
        (sandbox / "infodir").mkdir(exist_ok=True)
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            resp = await _call(conn, "file_info", {"path": "infodir"})
            data = _json_result(resp)
            assert data["is_dir"] is True
            assert data["is_file"] is False

    async def test_file_info_modified_at_format(self, fs_app, sandbox):
        (sandbox / "dated.txt").write_text("dated")
        from datetime import datetime

        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            resp = await _call(conn, "file_info", {"path": "dated.txt"})
            data = _json_result(resp)
            dt = datetime.fromisoformat(data["modified_at"])
            assert dt.tzinfo is not None


# ---------------------------------------------------------------------------
# 7. Path traversal rejection (all tools)
# ---------------------------------------------------------------------------


class TestPathTraversal:
    @pytest.mark.parametrize(
        "tool, args",
        [
            ("list_files", {"path": "../"}),
            ("read_file", {"path": "../../etc/passwd"}),
            ("write_file", {"path": "../evil.txt", "content": "x"}),
            ("create_directory", {"path": "../escapedir"}),
            ("delete_file", {"path": "../outside.txt"}),
            ("delete_directory", {"path": "../outside"}),
            ("move_file", {"source": "../src.txt", "destination": "dst.txt"}),
            ("move_file", {"source": "src.txt", "destination": "../dst.txt"}),
            ("file_info", {"path": "../../etc/hosts"}),
        ],
    )
    async def test_traversal_rejected(self, fs_app, tool, args):
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            resp = await _call(conn, tool, args)
            # Either JSON-RPC error or isError=True in result
            is_error = resp.get("error") is not None or (
                resp.get("result", {}).get("isError") is True
            )
            assert is_error, (
                f"Tool {tool!r} with args {args!r} should have returned an error but got: {resp}"
            )


# ---------------------------------------------------------------------------
# 8. File resource
# ---------------------------------------------------------------------------


class TestFileResource:
    async def test_resource_returns_file_content(self, fs_app, sandbox):
        (sandbox / "resource_test.txt").write_text("resource content here")
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            resp = await _read_resource(conn, "file://resource_test.txt")
            contents = resp.get("result", {}).get("contents", [])
            texts = [c.get("text", "") for c in contents]
            assert any("resource content here" in t for t in texts)

    async def test_resource_missing_file_returns_not_found_message(self, fs_app):
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            resp = await _read_resource(conn, "file://does_not_exist.txt")
            contents = resp.get("result", {}).get("contents", [])
            texts = [c.get("text", "") for c in contents]
            combined = " ".join(texts)
            assert "not found" in combined.lower() or "file not found" in combined.lower()


# ---------------------------------------------------------------------------
# 9. Multi-CRUD with BackgroundTasks
# ---------------------------------------------------------------------------


class TestBulkWriteFiles:
    async def test_writes_multiple_files(self, fs_app, sandbox):
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            resp = await _call(
                conn,
                "bulk_write_files",
                {
                    "files": [
                        {"path": "bulk/a.txt", "content": "alpha"},
                        {"path": "bulk/b.txt", "content": "beta"},
                        {"path": "bulk/c.txt", "content": "gamma"},
                    ],
                    "create_dirs": True,
                },
            )
            result = json.loads(_text(resp))
            assert sorted(result["written"]) == ["bulk/a.txt", "bulk/b.txt", "bulk/c.txt"]
            assert result["failed"] == []
            assert result["total"] == 3
            # Verify files exist on disk
            assert (sandbox / "bulk" / "a.txt").read_text() == "alpha"
            assert (sandbox / "bulk" / "b.txt").read_text() == "beta"

    async def test_background_audit_log_written(self, fs_app, sandbox):
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            await _call(
                conn,
                "bulk_write_files",
                {
                    "files": [{"path": "audit_check.txt", "content": "hi"}],
                    "create_dirs": False,
                },
            )
        # Give the background task time to run
        await asyncio.sleep(0.05)
        audit = sandbox / ".audit.log"
        assert audit.exists(), "Background task should have created .audit.log"
        content = audit.read_text()
        assert "audit_check.txt" in content

    async def test_partial_failure_reports_failed(self, fs_app, sandbox):
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            resp = await _call(
                conn,
                "bulk_write_files",
                {
                    "files": [
                        {"path": "ok_file.txt", "content": "good"},
                        # Missing parent dir without create_dirs=True → failure
                        {"path": "no_parent_dir/file.txt", "content": "bad"},
                    ],
                    "create_dirs": False,
                },
            )
            result = json.loads(_text(resp))
            assert "ok_file.txt" in result["written"]
            assert len(result["failed"]) == 1
            assert result["failed"][0]["path"] == "no_parent_dir/file.txt"

    async def test_tools_list_includes_bulk_write(self, fs_app):
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            tools = await _list_tools(conn)
            names = {t["name"] for t in tools}
            assert "bulk_write_files" in names
            # bg param excluded from schema
            bwf = next(t for t in tools if t["name"] == "bulk_write_files")
            props = bwf["inputSchema"]["properties"]
            assert "bg" not in props
            assert "files" in props


class TestBulkDeleteFiles:
    async def test_deletes_multiple_files(self, fs_app, sandbox):
        # Pre-create files
        for name in ("del1.txt", "del2.txt", "del3.txt"):
            (sandbox / name).write_text("x")
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            resp = await _call(
                conn,
                "bulk_delete_files",
                {
                    "paths": ["del1.txt", "del2.txt", "del3.txt"],
                },
            )
            result = json.loads(_text(resp))
            assert sorted(result["deleted"]) == ["del1.txt", "del2.txt", "del3.txt"]
            assert result["failed"] == []
        assert not (sandbox / "del1.txt").exists()
        assert not (sandbox / "del2.txt").exists()

    async def test_skips_nonexistent_files(self, fs_app):
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            resp = await _call(
                conn,
                "bulk_delete_files",
                {
                    "paths": ["ghost_file.txt"],
                },
            )
            result = json.loads(_text(resp))
            assert "ghost_file.txt" in result["skipped"]
            assert result["deleted"] == []

    async def test_skips_directories(self, fs_app, sandbox):
        (sandbox / "a_dir").mkdir(exist_ok=True)
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            resp = await _call(conn, "bulk_delete_files", {"paths": ["a_dir"]})
            result = json.loads(_text(resp))
            assert "a_dir" in result["skipped"]


class TestBulkCopyFiles:
    async def test_copies_multiple_files(self, fs_app, sandbox):
        (sandbox / "src1.txt").write_text("source one")
        (sandbox / "src2.txt").write_text("source two")
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            resp = await _call(
                conn,
                "bulk_copy_files",
                {
                    "copies": [
                        {"source": "src1.txt", "destination": "copies/dst1.txt"},
                        {"source": "src2.txt", "destination": "copies/dst2.txt"},
                    ],
                    "overwrite": False,
                },
            )
            result = json.loads(_text(resp))
            assert len(result["copied"]) == 2
            assert result["failed"] == []
        assert (sandbox / "copies" / "dst1.txt").read_text() == "source one"
        assert (sandbox / "copies" / "dst2.txt").read_text() == "source two"

    async def test_background_manifest_updated(self, fs_app, sandbox):
        (sandbox / "manifest_src.txt").write_text("data")
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            await _call(
                conn,
                "bulk_copy_files",
                {
                    "copies": [{"source": "manifest_src.txt", "destination": "manifest_dst.txt"}],
                    "overwrite": True,
                },
            )
        await asyncio.sleep(0.05)
        manifest = sandbox / ".manifest"
        assert manifest.exists(), "Background task should have created .manifest"
        assert "manifest_src.txt" in manifest.read_text()

    async def test_no_overwrite_raises_for_existing(self, fs_app, sandbox):
        (sandbox / "existing_dst.txt").write_text("already here")
        (sandbox / "copy_src.txt").write_text("new content")
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            resp = await _call(
                conn,
                "bulk_copy_files",
                {
                    "copies": [{"source": "copy_src.txt", "destination": "existing_dst.txt"}],
                    "overwrite": False,
                },
            )
            result = json.loads(_text(resp))
            assert len(result["failed"]) == 1
            assert "overwrite" in result["failed"][0]["error"].lower()


class TestSyncDirectory:
    async def test_syncs_all_files(self, fs_app, sandbox):
        sync_src = sandbox / "sync_source"
        sync_src.mkdir(exist_ok=True)
        (sync_src / "file1.txt").write_text("one")
        (sync_src / "file2.txt").write_text("two")
        sub = sync_src / "subdir"
        sub.mkdir(exist_ok=True)
        (sub / "deep.txt").write_text("deep")

        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            resp = await _call(
                conn,
                "sync_directory",
                {
                    "source": "sync_source",
                    "destination": "sync_dest",
                    "overwrite": False,
                },
            )
            result = json.loads(_text(resp))
            assert result["synced"] == 3
            assert result["failed"] == []

        assert (sandbox / "sync_dest" / "file1.txt").read_text() == "one"
        assert (sandbox / "sync_dest" / "subdir" / "deep.txt").read_text() == "deep"

    async def test_background_sync_log_written(self, fs_app, sandbox):
        log_src = sandbox / "log_sync_src"
        log_src.mkdir(exist_ok=True)
        (log_src / "x.txt").write_text("x")
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            await _call(
                conn,
                "sync_directory",
                {
                    "source": "log_sync_src",
                    "destination": "log_sync_dst",
                    "overwrite": True,
                },
            )
        await asyncio.sleep(0.05)
        sync_log = sandbox / ".sync.log"
        assert sync_log.exists(), "Background task should have created .sync.log"
        assert "log_sync_src" in sync_log.read_text()

    async def test_skips_existing_files_without_overwrite(self, fs_app, sandbox):
        skip_src = sandbox / "skip_sync_src"
        skip_src.mkdir(exist_ok=True)
        (skip_src / "a.txt").write_text("new")
        skip_dst = sandbox / "skip_sync_dst"
        skip_dst.mkdir(exist_ok=True)
        (skip_dst / "a.txt").write_text("original")  # already exists

        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            resp = await _call(
                conn,
                "sync_directory",
                {
                    "source": "skip_sync_src",
                    "destination": "skip_sync_dst",
                    "overwrite": False,
                },
            )
            result = json.loads(_text(resp))
            assert result["synced"] == 0
            assert result["skipped"] == 1
        # Destination file should be unchanged
        assert (skip_dst / "a.txt").read_text() == "original"

    async def test_source_not_found_raises(self, fs_app):
        async with WsTestClient(fs_app).connect("/filesystem/ws") as conn:
            await _handshake(conn)
            resp = await _call(
                conn,
                "sync_directory",
                {
                    "source": "no_such_dir",
                    "destination": "anywhere",
                    "overwrite": False,
                },
            )
            assert resp.get("result", {}).get("isError") or "error" in resp
