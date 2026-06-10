"""Unit tests for lauren_mcp.server._builtin_resources."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lauren_mcp._types import BlobResource
from lauren_mcp.server._builtin_resources import (
    DirectoryResource,
    FileResource,
    HttpResource,
    _detect_mime,
    register_directory_resource,
    register_file_resource,
    register_http_resource,
)
from lauren_mcp.server._meta import McpResourceMeta

# ---------------------------------------------------------------------------
# _detect_mime
# ---------------------------------------------------------------------------


class TestDetectMime:
    def test_text_file(self, tmp_path: Path) -> None:
        f = tmp_path / "readme.txt"
        f.touch()
        assert _detect_mime(f).startswith("text/")

    def test_html_file(self, tmp_path: Path) -> None:
        f = tmp_path / "index.html"
        f.touch()
        assert _detect_mime(f) == "text/html"

    def test_json_file(self, tmp_path: Path) -> None:
        f = tmp_path / "data.json"
        f.touch()
        assert _detect_mime(f) == "application/json"

    def test_png_file(self, tmp_path: Path) -> None:
        f = tmp_path / "image.png"
        f.touch()
        assert _detect_mime(f) == "image/png"

    def test_unknown_extension(self, tmp_path: Path) -> None:
        f = tmp_path / "data.bin"
        f.touch()
        assert _detect_mime(f) == "application/octet-stream"

    def test_no_extension(self, tmp_path: Path) -> None:
        f = tmp_path / "makefile"
        f.touch()
        assert _detect_mime(f) == "application/octet-stream"


# ---------------------------------------------------------------------------
# FileResource
# ---------------------------------------------------------------------------


class TestFileResource:
    def test_name_defaults_to_basename(self, tmp_path: Path) -> None:
        f = tmp_path / "report.txt"
        f.write_text("hello")
        fr = FileResource(f, "file:///report.txt")
        assert fr._name == "report.txt"

    def test_explicit_name_overrides_basename(self, tmp_path: Path) -> None:
        f = tmp_path / "report.txt"
        f.write_text("hello")
        fr = FileResource(f, "file:///report.txt", name="Monthly Report")
        assert fr._name == "Monthly Report"

    def test_explicit_mime_type_overrides_auto_detection(self, tmp_path: Path) -> None:
        f = tmp_path / "data.bin"
        f.write_bytes(b"\x00\x01")
        fr = FileResource(f, "file:///data.bin", mime_type="image/png")
        assert fr._mime_type == "image/png"

    def test_is_text_for_text_plain(self, tmp_path: Path) -> None:
        f = tmp_path / "notes.txt"
        f.write_text("hi")
        fr = FileResource(f, "file:///notes.txt")
        assert fr._is_text() is True

    def test_is_text_for_text_html(self, tmp_path: Path) -> None:
        f = tmp_path / "index.html"
        f.write_text("<h1>Hi</h1>")
        fr = FileResource(f, "file:///index.html")
        assert fr._is_text() is True

    def test_is_text_for_application_json(self, tmp_path: Path) -> None:
        f = tmp_path / "config.json"
        f.write_text("{}")
        fr = FileResource(f, "file:///config.json")
        assert fr._is_text() is True

    def test_is_text_for_application_xml(self, tmp_path: Path) -> None:
        f = tmp_path / "data.xml"
        f.write_text("<root/>")
        fr = FileResource(f, "file:///data.xml", mime_type="application/xml")
        assert fr._is_text() is True

    def test_is_not_text_for_image_png(self, tmp_path: Path) -> None:
        f = tmp_path / "logo.png"
        f.write_bytes(b"\x89PNG")
        fr = FileResource(f, "file:///logo.png")
        assert fr._is_text() is False

    async def test_read_text_file_returns_str(self, tmp_path: Path) -> None:
        f = tmp_path / "hello.txt"
        f.write_text("hello world")
        fr = FileResource(f, "file:///hello.txt")
        result = await fr.read()
        assert isinstance(result, str)
        assert result == "hello world"

    async def test_read_binary_file_returns_blob_resource(self, tmp_path: Path) -> None:
        raw = b"\x89PNG\r\n\x1a\n"
        f = tmp_path / "image.png"
        f.write_bytes(raw)
        fr = FileResource(f, "file:///image.png")
        result = await fr.read()
        assert isinstance(result, BlobResource)
        assert result.data == raw
        assert result.mime_type == "image/png"

    async def test_read_html_returns_str(self, tmp_path: Path) -> None:
        f = tmp_path / "page.html"
        f.write_text("<p>test</p>", encoding="utf-8")
        fr = FileResource(f, "file:///page.html")
        result = await fr.read()
        assert isinstance(result, str)
        assert "<p>test</p>" in result

    def test_as_mcp_resource_meta_correct_uri(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("x")
        fr = FileResource(f, "file:///data/file.txt")
        meta = fr.as_mcp_resource_meta()
        assert meta.uri_template == "file:///data/file.txt"

    def test_as_mcp_resource_meta_method_name_is_read(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("x")
        fr = FileResource(f, "file:///file.txt")
        meta = fr.as_mcp_resource_meta()
        assert meta.method_name == "read"

    def test_as_mcp_resource_meta_has_bound_instance(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("x")
        fr = FileResource(f, "file:///file.txt")
        meta = fr.as_mcp_resource_meta()
        assert getattr(meta, "_bound_instance", None) is fr

    def test_as_mcp_resource_meta_mime_type(self, tmp_path: Path) -> None:
        f = tmp_path / "data.json"
        f.write_text("{}")
        fr = FileResource(f, "file:///data.json")
        meta = fr.as_mcp_resource_meta()
        assert meta.mime_type == "application/json"

    def test_as_mcp_resource_meta_name(self, tmp_path: Path) -> None:
        f = tmp_path / "myfile.txt"
        f.write_text("x")
        fr = FileResource(f, "file:///myfile.txt", name="Custom Name")
        meta = fr.as_mcp_resource_meta()
        assert meta.name == "Custom Name"

    def test_as_mcp_resource_meta_description(self, tmp_path: Path) -> None:
        f = tmp_path / "file.txt"
        f.write_text("x")
        fr = FileResource(f, "file:///file.txt", description="A description")
        meta = fr.as_mcp_resource_meta()
        assert meta.description == "A description"


# ---------------------------------------------------------------------------
# HttpResource
# ---------------------------------------------------------------------------


class TestHttpResource:
    def test_name_defaults_to_url(self) -> None:
        hr = HttpResource("https://example.com/api", "mcp://api")
        assert hr._name == "https://example.com/api"

    def test_explicit_name(self) -> None:
        hr = HttpResource("https://example.com/api", "mcp://api", name="API Resource")
        assert hr._name == "API Resource"

    def test_as_mcp_resource_meta_uri(self) -> None:
        hr = HttpResource("https://example.com", "mcp://example")
        meta = hr.as_mcp_resource_meta()
        assert meta.uri_template == "mcp://example"

    def test_as_mcp_resource_meta_method_name(self) -> None:
        hr = HttpResource("https://example.com", "mcp://example")
        meta = hr.as_mcp_resource_meta()
        assert meta.method_name == "read"

    def test_as_mcp_resource_meta_bound_instance(self) -> None:
        hr = HttpResource("https://example.com", "mcp://example")
        meta = hr.as_mcp_resource_meta()
        assert getattr(meta, "_bound_instance", None) is hr

    def _make_mock_httpx(
        self, content_type: str, text: str = "", content: bytes = b""
    ) -> tuple[MagicMock, AsyncMock]:
        """Return (mock_httpx_module, mock_client) for patching."""
        mock_response = MagicMock()
        mock_response.headers = {"content-type": content_type}
        mock_response.text = text
        mock_response.content = content
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient = MagicMock(return_value=mock_client)
        return mock_httpx, mock_client

    async def test_read_text_response_returns_str(self) -> None:
        mock_httpx, _ = self._make_mock_httpx("text/html; charset=utf-8", text="<html>hello</html>")
        hr = HttpResource("https://example.com", "mcp://example")
        with patch.dict("sys.modules", {"httpx": mock_httpx}):
            result = await hr.read()

        assert isinstance(result, str)
        assert result == "<html>hello</html>"

    async def test_read_binary_response_returns_blob(self) -> None:
        raw = b"\x89PNG\r\n"
        mock_httpx, _ = self._make_mock_httpx("image/png", content=raw)
        hr = HttpResource("https://example.com/img.png", "mcp://img")
        with patch.dict("sys.modules", {"httpx": mock_httpx}):
            result = await hr.read()

        assert isinstance(result, BlobResource)
        assert result.data == raw
        assert result.mime_type == "image/png"

    async def test_read_json_response_returns_str(self) -> None:
        mock_httpx, _ = self._make_mock_httpx("application/json", text='{"key": "value"}')
        hr = HttpResource("https://example.com/api.json", "mcp://api")
        with patch.dict("sys.modules", {"httpx": mock_httpx}):
            result = await hr.read()

        assert isinstance(result, str)

    async def test_read_raises_import_error_when_httpx_missing(self) -> None:
        hr = HttpResource("https://example.com", "mcp://example")
        # Remove httpx from sys.modules to simulate it not being installed.
        with patch.dict("sys.modules", {"httpx": None}):  # type: ignore[dict-item]  # noqa: SIM117
            with pytest.raises(ImportError, match="lauren-mcp\\[http\\]"):
                await hr.read()

    def test_explicit_mime_type_overrides_response_header(self) -> None:
        hr = HttpResource("https://example.com", "mcp://example", mime_type="text/plain")
        assert hr._mime_type == "text/plain"


# ---------------------------------------------------------------------------
# DirectoryResource
# ---------------------------------------------------------------------------


class TestDirectoryResource:
    def test_name_defaults_to_dir_basename(self, tmp_path: Path) -> None:
        dr = DirectoryResource(tmp_path, "dir:///tmp")
        assert dr._name == tmp_path.name

    async def test_read_returns_json_list(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        dr = DirectoryResource(tmp_path, "dir:///tmp")
        result = await dr.read()
        files = json.loads(result)
        assert "a.txt" in files
        assert "b.txt" in files

    async def test_read_excludes_hidden_by_default(self, tmp_path: Path) -> None:
        (tmp_path / "visible.txt").write_text("v")
        (tmp_path / ".hidden").write_text("h")
        dr = DirectoryResource(tmp_path, "dir:///tmp")
        result = await dr.read()
        files = json.loads(result)
        assert "visible.txt" in files
        assert ".hidden" not in files

    async def test_read_includes_hidden_when_flag_set(self, tmp_path: Path) -> None:
        (tmp_path / "visible.txt").write_text("v")
        (tmp_path / ".hidden").write_text("h")
        dr = DirectoryResource(tmp_path, "dir:///tmp", include_hidden=True)
        result = await dr.read()
        files = json.loads(result)
        assert ".hidden" in files

    async def test_read_non_recursive_does_not_descend(self, tmp_path: Path) -> None:
        subdir = tmp_path / "sub"
        subdir.mkdir()
        (tmp_path / "top.txt").write_text("t")
        (subdir / "nested.txt").write_text("n")
        dr = DirectoryResource(tmp_path, "dir:///tmp", recursive=False)
        result = await dr.read()
        files = json.loads(result)
        assert "top.txt" in files
        # nested.txt is under sub/, not directly in tmp
        assert not any("nested.txt" in f for f in files) or any("sub" in f for f in files)

    async def test_read_recursive_descends_into_subdirs(self, tmp_path: Path) -> None:
        subdir = tmp_path / "sub"
        subdir.mkdir()
        (tmp_path / "top.txt").write_text("t")
        (subdir / "nested.txt").write_text("n")
        dr = DirectoryResource(tmp_path, "dir:///tmp", recursive=True)
        result = await dr.read()
        files = json.loads(result)
        assert any("nested.txt" in f for f in files)

    async def test_read_pattern_filters_files(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.py").write_text("b")
        dr = DirectoryResource(tmp_path, "dir:///tmp", pattern="*.txt")
        result = await dr.read()
        files = json.loads(result)
        assert "a.txt" in files
        assert "b.py" not in files

    def test_as_mcp_resource_meta_mime_type_is_json(self, tmp_path: Path) -> None:
        dr = DirectoryResource(tmp_path, "dir:///tmp")
        meta = dr.as_mcp_resource_meta()
        assert meta.mime_type == "application/json"

    def test_as_mcp_resource_meta_bound_instance(self, tmp_path: Path) -> None:
        dr = DirectoryResource(tmp_path, "dir:///tmp")
        meta = dr.as_mcp_resource_meta()
        assert getattr(meta, "_bound_instance", None) is dr

    async def test_read_returns_sorted_list(self, tmp_path: Path) -> None:
        (tmp_path / "c.txt").write_text("c")
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        dr = DirectoryResource(tmp_path, "dir:///tmp")
        result = await dr.read()
        files = json.loads(result)
        assert files == sorted(files)


# ---------------------------------------------------------------------------
# Register helper functions
# ---------------------------------------------------------------------------


class TestRegisterHelpers:
    def test_register_file_resource_calls_catalog(self, tmp_path: Path) -> None:
        f = tmp_path / "f.txt"
        f.write_text("x")
        fr = FileResource(f, "file:///f.txt")
        catalog = MagicMock()
        register_file_resource(catalog, fr)
        catalog.register_resource.assert_called_once()
        meta_arg = catalog.register_resource.call_args[0][0]
        assert isinstance(meta_arg, McpResourceMeta)
        assert meta_arg.uri_template == "file:///f.txt"

    def test_register_http_resource_calls_catalog(self) -> None:
        hr = HttpResource("https://example.com", "mcp://example")
        catalog = MagicMock()
        register_http_resource(catalog, hr)
        catalog.register_resource.assert_called_once()

    def test_register_directory_resource_calls_catalog(self, tmp_path: Path) -> None:
        dr = DirectoryResource(tmp_path, "dir:///tmp")
        catalog = MagicMock()
        register_directory_resource(catalog, dr)
        catalog.register_resource.assert_called_once()
