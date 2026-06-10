"""Unit tests for the Filesystem MCP Server helper functions and server class.

These tests do not require a running Lauren application or any network I/O.
They exercise:
  - _resolve_safe_path: valid paths, traversal attempts, absolute outside root
  - FilesystemServer tool methods via a fake McpToolContext
  - Correct return structures for every tool
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from examples.filesystem.server import FilesystemServer, _resolve_safe_path

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fake context helpers
# ---------------------------------------------------------------------------


def _make_ctx(root: Path) -> Any:
    """Return a minimal McpToolContext-like object backed by *root*."""

    @dataclass
    class _FakeCtx:
        lifespan_context: dict[str, Any] = field(
            default_factory=lambda: {"root": root, "allowed_root": root}
        )
        tool_name: str = "test"
        tool_use_id: str | None = None

        async def info(self, message: str, data: Any = None) -> None:
            pass  # discard in unit tests

        async def report_progress(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def log(self, level: str, message: str, data: Any = None) -> None:
            pass

    return _FakeCtx()


# ---------------------------------------------------------------------------
# Tests: _resolve_safe_path
# ---------------------------------------------------------------------------


class TestResolveSafePath:
    def test_simple_relative_path_resolves_under_root(self, tmp_path):
        result = _resolve_safe_path("subdir/file.txt", tmp_path)
        assert result == tmp_path / "subdir" / "file.txt"

    def test_dot_resolves_to_root_itself(self, tmp_path):
        result = _resolve_safe_path(".", tmp_path)
        assert result == tmp_path

    def test_nested_relative_path(self, tmp_path):
        result = _resolve_safe_path("a/b/c/d.py", tmp_path)
        assert result == tmp_path / "a" / "b" / "c" / "d.py"

    def test_path_with_trailing_slash_handled(self, tmp_path):
        result = _resolve_safe_path("subdir/", tmp_path)
        assert result == tmp_path / "subdir"

    def test_traversal_double_dot_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="traversal"):
            _resolve_safe_path("../outside.txt", tmp_path)

    def test_traversal_through_subdir_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="traversal"):
            _resolve_safe_path("subdir/../../outside.txt", tmp_path)

    def test_absolute_path_inside_root_treated_as_relative(self, tmp_path):
        # Absolute paths have the leading slash stripped and are joined under root.
        # So "/file.txt" becomes root/"file.txt".
        result = _resolve_safe_path("/file.txt", tmp_path)
        assert result == tmp_path / "file.txt"

    def test_absolute_path_etc_passwd_sandboxed(self, tmp_path):
        # "/etc/passwd" is stripped to "etc/passwd" and joined under root,
        # resulting in root/etc/passwd (sandboxed, no traversal).
        result = _resolve_safe_path("/etc/passwd", tmp_path)
        assert result == tmp_path / "etc" / "passwd"

    def test_traversal_to_parent_of_root_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="traversal"):
            _resolve_safe_path("..", tmp_path)


# ---------------------------------------------------------------------------
# Tests: list_files
# ---------------------------------------------------------------------------


class TestListFiles:
    @pytest.fixture
    def setup(self, tmp_path):
        (tmp_path / "a.txt").write_text("hello")
        (tmp_path / "b.txt").write_text("world")
        (tmp_path / "subdir").mkdir()
        (tmp_path / "subdir" / "c.txt").write_text("nested")
        return FilesystemServer(), _make_ctx(tmp_path)

    async def test_list_root_returns_direct_children(self, setup):
        srv, ctx = setup
        result = await srv.list_files(ctx)
        assert "a.txt" in result
        assert "b.txt" in result
        assert "subdir" in result

    async def test_list_recursive_includes_nested(self, setup):
        srv, ctx = setup
        result = await srv.list_files(ctx, recursive=True)
        assert any("c.txt" in r for r in result)

    async def test_list_non_recursive_excludes_nested(self, setup):
        srv, ctx = setup
        result = await srv.list_files(ctx, recursive=False)
        assert not any("c.txt" in r for r in result)

    async def test_list_subdir(self, setup, tmp_path):
        srv, ctx = setup
        result = await srv.list_files(ctx, path="subdir")
        assert any("c.txt" in r for r in result)

    async def test_list_nonexistent_raises(self, setup):
        srv, ctx = setup
        with pytest.raises(ValueError, match="does not exist"):
            await srv.list_files(ctx, path="nonexistent")

    async def test_list_file_as_dir_raises(self, setup):
        srv, ctx = setup
        with pytest.raises(ValueError, match="not a directory"):
            await srv.list_files(ctx, path="a.txt")

    async def test_traversal_in_list_raises(self, setup):
        srv, ctx = setup
        with pytest.raises(ValueError, match="traversal"):
            await srv.list_files(ctx, path="../")


# ---------------------------------------------------------------------------
# Tests: read_file
# ---------------------------------------------------------------------------


class TestReadFile:
    @pytest.fixture
    def setup(self, tmp_path):
        (tmp_path / "hello.txt").write_text("Hello, world!")
        return FilesystemServer(), _make_ctx(tmp_path), tmp_path

    async def test_read_existing_file(self, setup):
        srv, ctx, _ = setup
        content = await srv.read_file(ctx, path="hello.txt")
        assert content == "Hello, world!"

    async def test_read_nonexistent_raises(self, setup):
        srv, ctx, _ = setup
        with pytest.raises(ValueError, match="does not exist"):
            await srv.read_file(ctx, path="missing.txt")

    async def test_read_directory_raises(self, setup, tmp_path):
        srv, ctx, root = setup
        (root / "adir").mkdir()
        with pytest.raises(ValueError, match="not a file"):
            await srv.read_file(ctx, path="adir")

    async def test_read_large_file_raises(self, setup, tmp_path):
        srv, ctx, root = setup
        big_file = root / "big.bin"
        big_file.write_bytes(b"x" * (1_048_576 + 1))
        with pytest.raises(ValueError, match="larger than 1 MB"):
            await srv.read_file(ctx, path="big.bin")

    async def test_read_binary_file_raises_unicode_error(self, setup, tmp_path):
        srv, ctx, root = setup
        (root / "data.bin").write_bytes(bytes(range(256)))
        with pytest.raises(ValueError, match="not valid UTF-8"):
            await srv.read_file(ctx, path="data.bin")

    async def test_traversal_in_read_raises(self, setup):
        srv, ctx, _ = setup
        with pytest.raises(ValueError, match="traversal"):
            await srv.read_file(ctx, path="../secret")


# ---------------------------------------------------------------------------
# Tests: write_file
# ---------------------------------------------------------------------------


class TestWriteFile:
    @pytest.fixture
    def setup(self, tmp_path):
        return FilesystemServer(), _make_ctx(tmp_path), tmp_path

    async def test_write_creates_new_file(self, setup, tmp_path):
        srv, ctx, _ = setup
        result = await srv.write_file(ctx, path="new.txt", content="data")
        assert (tmp_path / "new.txt").read_text() == "data"
        assert result["created"] is True

    async def test_write_overwrites_existing_file(self, setup, tmp_path):
        srv, ctx, root = setup
        (root / "existing.txt").write_text("old")
        result = await srv.write_file(ctx, path="existing.txt", content="new")
        assert (root / "existing.txt").read_text() == "new"
        assert result["created"] is False

    async def test_write_returns_bytes_written(self, setup):
        srv, ctx, _ = setup
        content = "hello"
        result = await srv.write_file(ctx, path="f.txt", content=content)
        assert result["bytes_written"] == len(content.encode("utf-8"))

    async def test_write_returns_relative_path(self, setup):
        srv, ctx, _ = setup
        result = await srv.write_file(ctx, path="f.txt", content="x")
        assert result["path"] == "f.txt"

    async def test_write_missing_parent_raises_without_create_dirs(self, setup):
        srv, ctx, _ = setup
        with pytest.raises(ValueError, match="does not exist"):
            await srv.write_file(ctx, path="missing/parent/file.txt", content="x")

    async def test_write_creates_parent_dirs_when_flag_set(self, setup, tmp_path):
        srv, ctx, _ = setup
        await srv.write_file(ctx, path="new/subdir/file.txt", content="hi", create_dirs=True)
        assert (tmp_path / "new" / "subdir" / "file.txt").read_text() == "hi"

    async def test_traversal_in_write_raises(self, setup):
        srv, ctx, _ = setup
        with pytest.raises(ValueError, match="traversal"):
            await srv.write_file(ctx, path="../outside.txt", content="x")


# ---------------------------------------------------------------------------
# Tests: create_directory
# ---------------------------------------------------------------------------


class TestCreateDirectory:
    @pytest.fixture
    def setup(self, tmp_path):
        return FilesystemServer(), _make_ctx(tmp_path), tmp_path

    async def test_create_new_directory(self, setup, tmp_path):
        srv, ctx, _ = setup
        result = await srv.create_directory(ctx, path="newdir")
        assert (tmp_path / "newdir").is_dir()
        assert result["created"] is True

    async def test_create_nested_directories(self, setup, tmp_path):
        srv, ctx, _ = setup
        await srv.create_directory(ctx, path="a/b/c")
        assert (tmp_path / "a" / "b" / "c").is_dir()

    async def test_create_existing_directory_returns_created_false(self, setup, tmp_path):
        srv, ctx, _ = setup
        (tmp_path / "exists").mkdir()
        result = await srv.create_directory(ctx, path="exists")
        assert result["created"] is False

    async def test_traversal_in_create_dir_raises(self, setup):
        srv, ctx, _ = setup
        with pytest.raises(ValueError, match="traversal"):
            await srv.create_directory(ctx, path="../escape")


# ---------------------------------------------------------------------------
# Tests: delete_file
# ---------------------------------------------------------------------------


class TestDeleteFile:
    @pytest.fixture
    def setup(self, tmp_path):
        f = tmp_path / "to_delete.txt"
        f.write_text("bye")
        return FilesystemServer(), _make_ctx(tmp_path), tmp_path

    async def test_delete_existing_file(self, setup, tmp_path):
        srv, ctx, _ = setup
        result = await srv.delete_file(ctx, path="to_delete.txt")
        assert not (tmp_path / "to_delete.txt").exists()
        assert result["deleted"] is True

    async def test_delete_nonexistent_raises(self, setup):
        srv, ctx, _ = setup
        with pytest.raises(ValueError, match="does not exist"):
            await srv.delete_file(ctx, path="missing.txt")

    async def test_delete_directory_raises(self, setup, tmp_path):
        srv, ctx, _ = setup
        (tmp_path / "adir").mkdir()
        with pytest.raises(ValueError, match="directory"):
            await srv.delete_file(ctx, path="adir")

    async def test_traversal_in_delete_raises(self, setup):
        srv, ctx, _ = setup
        with pytest.raises(ValueError, match="traversal"):
            await srv.delete_file(ctx, path="../sneaky.txt")


# ---------------------------------------------------------------------------
# Tests: delete_directory
# ---------------------------------------------------------------------------


class TestDeleteDirectory:
    @pytest.fixture
    def setup(self, tmp_path):
        (tmp_path / "emptydir").mkdir()
        nested = tmp_path / "nonempty"
        nested.mkdir()
        (nested / "file.txt").write_text("contents")
        return FilesystemServer(), _make_ctx(tmp_path), tmp_path

    async def test_delete_empty_directory(self, setup, tmp_path):
        srv, ctx, _ = setup
        result = await srv.delete_directory(ctx, path="emptydir")
        assert not (tmp_path / "emptydir").exists()
        assert result["deleted"] is True

    async def test_delete_nonempty_without_recursive_raises(self, setup):
        srv, ctx, _ = setup
        with pytest.raises(ValueError, match="not empty"):
            await srv.delete_directory(ctx, path="nonempty")

    async def test_delete_nonempty_with_recursive(self, setup, tmp_path):
        srv, ctx, _ = setup
        await srv.delete_directory(ctx, path="nonempty", recursive=True)
        assert not (tmp_path / "nonempty").exists()

    async def test_delete_nonexistent_raises(self, setup):
        srv, ctx, _ = setup
        with pytest.raises(ValueError, match="does not exist"):
            await srv.delete_directory(ctx, path="ghost")

    async def test_delete_file_as_dir_raises(self, setup, tmp_path):
        srv, ctx, _ = setup
        (tmp_path / "afile.txt").write_text("x")
        with pytest.raises(ValueError, match="not a directory"):
            await srv.delete_directory(ctx, path="afile.txt")

    async def test_traversal_in_delete_dir_raises(self, setup):
        srv, ctx, _ = setup
        with pytest.raises(ValueError, match="traversal"):
            await srv.delete_directory(ctx, path="../")


# ---------------------------------------------------------------------------
# Tests: move_file
# ---------------------------------------------------------------------------


class TestMoveFile:
    @pytest.fixture
    def setup(self, tmp_path):
        (tmp_path / "src.txt").write_text("move me")
        return FilesystemServer(), _make_ctx(tmp_path), tmp_path

    async def test_move_renames_file(self, setup, tmp_path):
        srv, ctx, _ = setup
        result = await srv.move_file(ctx, source="src.txt", destination="dst.txt")
        assert not (tmp_path / "src.txt").exists()
        assert (tmp_path / "dst.txt").read_text() == "move me"
        assert result["moved"] is True

    async def test_move_returns_correct_paths(self, setup):
        srv, ctx, _ = setup
        result = await srv.move_file(ctx, source="src.txt", destination="dst.txt")
        assert result["source"] == "src.txt"
        assert result["destination"] == "dst.txt"

    async def test_move_raises_if_dest_exists_without_overwrite(self, setup, tmp_path):
        srv, ctx, _ = setup
        (tmp_path / "dst.txt").write_text("existing")
        with pytest.raises(ValueError, match="already exists"):
            await srv.move_file(ctx, source="src.txt", destination="dst.txt")

    async def test_move_overwrites_when_flag_set(self, setup, tmp_path):
        srv, ctx, _ = setup
        (tmp_path / "dst.txt").write_text("old")
        await srv.move_file(ctx, source="src.txt", destination="dst.txt", overwrite=True)
        assert (tmp_path / "dst.txt").read_text() == "move me"

    async def test_move_nonexistent_source_raises(self, setup):
        srv, ctx, _ = setup
        with pytest.raises(ValueError, match="does not exist"):
            await srv.move_file(ctx, source="ghost.txt", destination="dst.txt")

    async def test_traversal_in_source_raises(self, setup):
        srv, ctx, _ = setup
        with pytest.raises(ValueError, match="traversal"):
            await srv.move_file(ctx, source="../outside.txt", destination="dst.txt")

    async def test_traversal_in_destination_raises(self, setup):
        srv, ctx, _ = setup
        with pytest.raises(ValueError, match="traversal"):
            await srv.move_file(ctx, source="src.txt", destination="../outside.txt")


# ---------------------------------------------------------------------------
# Tests: file_info
# ---------------------------------------------------------------------------


class TestFileInfo:
    @pytest.fixture
    def setup(self, tmp_path):
        (tmp_path / "info.txt").write_text("abc")
        (tmp_path / "subdir").mkdir()
        return FilesystemServer(), _make_ctx(tmp_path), tmp_path

    async def test_info_for_file_has_correct_keys(self, setup):
        srv, ctx, _ = setup
        info = await srv.file_info(ctx, path="info.txt")
        for key in ("name", "path", "size", "is_file", "is_dir", "modified_at", "extension"):
            assert key in info, f"Missing key: {key!r}"

    async def test_info_is_file_true(self, setup):
        srv, ctx, _ = setup
        info = await srv.file_info(ctx, path="info.txt")
        assert info["is_file"] is True
        assert info["is_dir"] is False

    async def test_info_is_dir_true(self, setup):
        srv, ctx, _ = setup
        info = await srv.file_info(ctx, path="subdir")
        assert info["is_dir"] is True
        assert info["is_file"] is False

    async def test_info_name_is_basename(self, setup):
        srv, ctx, _ = setup
        info = await srv.file_info(ctx, path="info.txt")
        assert info["name"] == "info.txt"

    async def test_info_size_correct(self, setup):
        srv, ctx, _ = setup
        info = await srv.file_info(ctx, path="info.txt")
        assert info["size"] == 3  # "abc"

    async def test_info_extension_correct(self, setup):
        srv, ctx, _ = setup
        info = await srv.file_info(ctx, path="info.txt")
        assert info["extension"] == ".txt"

    async def test_info_modified_at_is_iso8601(self, setup):
        srv, ctx, _ = setup
        from datetime import datetime

        info = await srv.file_info(ctx, path="info.txt")
        # Should parse without exception
        dt = datetime.fromisoformat(info["modified_at"])
        assert dt.tzinfo is not None  # UTC timezone present

    async def test_info_nonexistent_raises(self, setup):
        srv, ctx, _ = setup
        with pytest.raises(ValueError, match="does not exist"):
            await srv.file_info(ctx, path="ghost.txt")

    async def test_traversal_in_file_info_raises(self, setup):
        srv, ctx, _ = setup
        with pytest.raises(ValueError, match="traversal"):
            await srv.file_info(ctx, path="../../etc/passwd")
