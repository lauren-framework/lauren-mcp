"""Edge case and error handling tests for the Filesystem MCP Server.

These tests cover additional scenarios not fully tested in other test files:
- Empty and special filename handling
- Large file handling
- Special character paths
- Concurrent operations edge cases
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
            pass

        async def report_progress(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def log(self, level: str, message: str, data: Any = None) -> None:
            pass

    return _FakeCtx()


# ---------------------------------------------------------------------------
# Tests: Empty and special files
# ---------------------------------------------------------------------------


class TestEmptyAndSpecialFiles:
    @pytest.fixture
    def setup(self, tmp_path):
        return FilesystemServer(), _make_ctx(tmp_path), tmp_path

    async def test_read_empty_file(self, setup):
        """Reading an empty file should return empty string."""
        srv, ctx, root = setup
        (root / "empty.txt").write_text("")
        content = await srv.read_file(ctx, path="empty.txt")
        assert content == ""

    async def test_write_empty_file(self, setup):
        """Writing an empty file should succeed."""
        srv, ctx, root = setup
        result = await srv.write_file(ctx, path="empty.txt", content="")
        assert (root / "empty.txt").read_text() == ""
        assert result["bytes_written"] == 0

    async def test_file_with_spaces_in_name(self, setup, tmp_path):
        """Files with spaces should work correctly."""
        srv, ctx, root = setup
        result = await srv.write_file(ctx, path="file with spaces.txt", content="space")
        assert (root / "file with spaces.txt").read_text() == "space"

    async def test_filename_with_special_chars(self, setup, tmp_path):
        """Files with special characters should work."""
        srv, ctx, root = setup
        # Test with dash and underscore
        result = await srv.write_file(ctx, path="file-name_test.txt", content="special")
        assert (root / "file-name_test.txt").read_text() == "special"

    async def test_file_with_unicode_name(self, setup):
        """Files with unicode characters in name should work."""
        srv, ctx, root = setup
        result = await srv.write_file(ctx, path="文件测试.txt", content="unicode")
        assert (root / "文件测试.txt").read_text() == "unicode"

    async def test_read_file_with_unicode_content(self, setup):
        """Reading files with unicode content should work."""
        srv, ctx, root = setup
        (root / "unicode.txt").write_text("中文测试 🌍")
        content = await srv.read_file(ctx, path="unicode.txt")
        assert content == "中文测试 🌍"


# ---------------------------------------------------------------------------
# Tests: Large file handling
# ---------------------------------------------------------------------------


class TestLargeFileHandling:
    @pytest.fixture
    def setup(self, tmp_path):
        return FilesystemServer(), _make_ctx(tmp_path), tmp_path

    async def test_read_too_large_file_raises(self, setup, tmp_path):
        """Files larger than 1MB should raise an error."""
        srv, ctx, root = setup
        big_file = root / "large.bin"
        # Create a file slightly larger than 1MB
        big_file.write_bytes(b"x" * (1_048_576 + 1))
        with pytest.raises(ValueError, match="larger than 1 MB"):
            await srv.read_file(ctx, path="large.bin")

    async def test_write_large_file_allowed(self, setup, tmp_path):
        """Writing files larger than 1MB should be allowed."""
        srv, ctx, root = setup
        # 2MB content
        large_content = "x" * (2 * 1024 * 1024)
        result = await srv.write_file(ctx, path="large.txt", content=large_content)
        assert result["bytes_written"] == len(large_content)


# ---------------------------------------------------------------------------
# Tests: Path resolution edge cases
# ---------------------------------------------------------------------------


class TestPathResolutionEdgeCases:
    def test_multiple_slashes_handled(self, tmp_path):
        """Paths with multiple consecutive slashes should be handled."""
        result = _resolve_safe_path("a//b///c.txt", tmp_path)
        assert result == tmp_path / "a" / "b" / "c.txt"

    def test_current_dir_with_file(self, tmp_path):
        """Path starting with ./ should work."""
        result = _resolve_safe_path("./file.txt", tmp_path)
        assert result == tmp_path / "file.txt"

    def test_single_dot_slash(self, tmp_path):
        """Path just being ./should resolve to root."""
        result = _resolve_safe_path("./", tmp_path)
        assert result == tmp_path

    def test_path_with_dot_segments_in_middle(self, tmp_path):
        """Path with . segments in the middle should be preserved."""
        result = _resolve_safe_path("a/./b.txt", tmp_path)
        # Python's Path handles . gracefully
        assert result == tmp_path / "a" / "b.txt"


# ---------------------------------------------------------------------------
# Tests: File info edge cases
# ---------------------------------------------------------------------------


class TestFileInfoEdgeCases:
    @pytest.fixture
    def setup(self, tmp_path):
        return FilesystemServer(), _make_ctx(tmp_path), tmp_path

    async def test_file_info_empty_file(self, setup, tmp_path):
        """File info for empty file should have size 0."""
        srv, ctx, root = setup
        (root / "empty.txt").write_text("")
        info = await srv.file_info(ctx, path="empty.txt")
        assert info["size"] == 0

    async def test_file_info_no_extension(self, setup, tmp_path):
        """File info for file without extension should have empty string."""
        srv, ctx, root = setup
        (root / "README").write_text("readme")
        info = await srv.file_info(ctx, path="README")
        assert info["extension"] == ""

    async def test_file_info_multiple_dots(self, setup, tmp_path):
        """File info should return last extension only."""
        srv, ctx, root = setup
        (root / "file.min.js").write_text("code")
        info = await srv.file_info(ctx, path="file.min.js")
        assert info["extension"] == ".js"

    async def test_file_info_long_filename(self, setup, tmp_path):
        """File info should handle long filenames."""
        srv, ctx, root = setup
        name = "a" * 200 + ".txt"
        (root / name).write_text("long")
        info = await srv.file_info(ctx, path=name)
        assert info["name"] == name


# ---------------------------------------------------------------------------
# Tests: Move file edge cases
# ---------------------------------------------------------------------------


class TestMoveFileEdgeCases:
    @pytest.fixture
    def setup(self, tmp_path):
        return FilesystemServer(), _make_ctx(tmp_path), tmp_path

    async def test_move_file_between_directories(self, setup, tmp_path):
        """Moving file between directories should work."""
        srv, ctx, root = setup
        (root / "src").mkdir()
        (root / "dst").mkdir()
        (root / "src" / "file.txt").write_text("content")
        result = await srv.move_file(ctx, source="src/file.txt", destination="dst/file.txt")
        assert result["moved"] is True
        assert not (root / "src" / "file.txt").exists()
        assert (root / "dst" / "file.txt").read_text() == "content"

    async def test_move_file_to_same_location(self, setup, tmp_path):
        """Moving file to same location should work or be idempotent."""
        srv, ctx, root = setup
        (root / "same.txt").write_text("content")
        # Moving to self - we expect this to work (overwrite with same content)
        result = await srv.move_file(ctx, source="same.txt", destination="same.txt")
        assert result["moved"] is True
        assert (root / "same.txt").read_text() == "content"


# ---------------------------------------------------------------------------
# Tests: List files edge cases
# ---------------------------------------------------------------------------


class TestListFilesEdgeCases:
    @pytest.fixture
    def setup(self, tmp_path):
        return FilesystemServer(), _make_ctx(tmp_path), tmp_path

    async def test_list_empty_directory(self, setup, tmp_path):
        """Listing empty directory should return empty list."""
        srv, ctx, root = setup
        result = await srv.list_files(ctx, path="empty_dir")
        assert result == []

    async def test_list_nested_directories(self, setup, tmp_path):
        """Listing nested directories should show all levels."""
        srv, ctx, root = setup
        (root / "deep").mkdir()
        (root / "deep" / "level1").mkdir()
        (root / "deep" / "level1" / "level2").mkdir()
        (root / "deep" / "level1" / "level2" / "file.txt").write_text("deep")
        result = await srv.list_files(ctx, path="deep", recursive=True)
        assert any("file.txt" in r for r in result)

    async def test_list_hidden_files(self, setup, tmp_path):
        """Hidden files (starting with .) should be listed."""
        srv, ctx, root = setup
        (root / ".hidden").write_text("secret")
        (root / ".config").mkdir()
        result = await srv.list_files(ctx, path=".")
        assert ".hidden" in result
        assert ".config" in result


# ---------------------------------------------------------------------------
# Tests: Delete directory edge cases
# ---------------------------------------------------------------------------


class TestDeleteDirectoryEdgeCases:
    @pytest.fixture
    def setup(self, tmp_path):
        return FilesystemServer(), _make_ctx(tmp_path), tmp_path

    async def test_delete_nonempty_with_many_files(self, setup, tmp_path):
        """Deleting directory with many files should work with recursive."""
        srv, ctx, root = setup
        dir_path = root / "many_files"
        dir_path.mkdir()
        for i in range(100):
            (dir_path / f"file_{i}.txt").write_text(f"content {i}")
        result = await srv.delete_directory(ctx, path="many_files", recursive=True)
        assert result["deleted"] is True
        assert not dir_path.exists()

    async def test_delete_empty_directory_is_idempotent(self, setup, tmp_path):
        """Deleting same empty directory twice should fail on second attempt."""
        srv, ctx, root = setup
        (root / "to_delete").mkdir()
        result = await srv.delete_directory(ctx, path="to_delete")
        assert result["deleted"] is True
        # Second attempt should fail
        with pytest.raises(ValueError, match="does not exist"):
            await srv.delete_directory(ctx, path="to_delete")


# ---------------------------------------------------------------------------
# Tests: Bulk operations edge cases
# ---------------------------------------------------------------------------


class TestBulkEdgeCases:
    @pytest.fixture
    def setup(self, tmp_path):
        return FilesystemServer(), _make_ctx(tmp_path), tmp_path

    async def test_bulk_write_empty_list(self, setup):
        """Bulk write with empty list should succeed with 0 files."""
        srv, ctx, _ = setup
        result = await srv.bulk_write_files(ctx, files=[])
        assert result["written"] == []
        assert result["failed"] == []
        assert result["total"] == 0

    async def test_bulk_delete_empty_list(self, setup):
        """Bulk delete with empty list should succeed with 0 files."""
        srv, ctx, _ = setup
        result = await srv.bulk_delete_files(ctx, paths=[])
        assert result["deleted"] == []
        assert result["skipped"] == []
        assert result["total"] == 0

    async def test_bulk_copy_empty_list(self, setup):
        """Bulk copy with empty list should succeed."""
        srv, ctx, _ = setup
        result = await srv.bulk_copy_files(ctx, copies=[])
        assert result["copied"] == []
        assert result["failed"] == []
        assert result["total"] == 0
