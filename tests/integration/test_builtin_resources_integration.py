"""Integration tests for built-in resource types (FileResource, DirectoryResource).

These tests mount a real Lauren app via McpServerModule and exercise the full
resources/list + resources/read path via WsTestClient.

HttpResource is not tested here to avoid network dependencies; it is covered
by the unit-level mock tests.
"""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

import pytest
from lauren import LaurenFactory, module, post_construct
from lauren.testing import TestClient, WsTestClient

from lauren_mcp import McpServerModule, mcp_server, mcp_tool
from lauren_mcp._server._catalog import McpCatalogManager
from lauren_mcp.server._builtin_resources import (
    DirectoryResource,
    FileResource,
    register_directory_resource,
    register_file_resource,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _handshake(conn) -> None:  # type: ignore[no-untyped-def]
    await conn.send_json(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1.0"},
            },
        }
    )
    await asyncio.wait_for(conn.receive_json(), timeout=5.0)
    await conn.send_json({"jsonrpc": "2.0", "method": "notifications/initialized"})


# ---------------------------------------------------------------------------
# FileResource integration — text file
# ---------------------------------------------------------------------------


class TestFileResourceIntegration:
    @pytest.fixture(scope="class")
    def tmp_text_file(self, tmp_path_factory: pytest.TempPathFactory) -> Path:
        d = tmp_path_factory.mktemp("file_res")
        p = d / "hello.txt"
        p.write_text("hello from file resource")
        return p

    @pytest.fixture(scope="class")
    def lauren_app_file(self, tmp_text_file: Path):  # type: ignore[no-untyped-def]
        file_path = tmp_text_file

        @mcp_server("/mcp")
        class FileServer:
            def __init__(self, catalog: McpCatalogManager) -> None:
                self._catalog = catalog
                self._file_path = file_path

            @post_construct
            async def _setup(self) -> None:
                register_file_resource(
                    self._catalog,
                    FileResource(
                        self._file_path,
                        "file:///hello.txt",
                        name="hello",
                        description="A greeting file",
                    ),
                )

            @mcp_tool()
            async def ping(self) -> str:
                "Ping."
                return "pong"

        @module(imports=[McpServerModule.for_root(FileServer)])
        class AppModule:
            pass

        app = LaurenFactory.create(AppModule)
        TestClient(app)
        return app

    @pytest.fixture
    def ws(self, lauren_app_file):  # type: ignore[no-untyped-def]
        return WsTestClient(lauren_app_file)

    async def test_resources_list_contains_file_uri(self, ws) -> None:  # type: ignore[no-untyped-def]
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json({"jsonrpc": "2.0", "id": 10, "method": "resources/list"})
            resp = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
            uris = [r["uri"] for r in resp["result"]["resources"]]
            assert "file:///hello.txt" in uris

    async def test_resources_list_name_matches(self, ws) -> None:  # type: ignore[no-untyped-def]
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json({"jsonrpc": "2.0", "id": 11, "method": "resources/list"})
            resp = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
            resource = resp["result"]["resources"][0]
            assert resource["name"] == "hello"

    async def test_read_resource_returns_file_content(self, ws) -> None:  # type: ignore[no-untyped-def]
        async with ws.connect("/mcp/ws") as conn:
            await _handshake(conn)
            await conn.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 12,
                    "method": "resources/read",
                    "params": {"uri": "file:///hello.txt"},
                }
            )
            resp = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
            text = resp["result"]["contents"][0]["text"]
            assert text == "hello from file resource"


# ---------------------------------------------------------------------------
# FileResource integration — binary file
# ---------------------------------------------------------------------------


class TestBinaryFileResourceIntegration:
    @pytest.fixture(scope="class")
    def tmp_png_file(self, tmp_path_factory: pytest.TempPathFactory) -> Path:
        d = tmp_path_factory.mktemp("bin_res")
        p = d / "pixel.png"
        # Minimal valid PNG header (1x1 transparent PNG)
        p.write_bytes(
            bytes.fromhex(
                "89504e470d0a1a0a0000000d494844520000000100000001"
                "0806000000 1f15c4890000000a49444154789c6260000000020001"
                "e221bc330000000049454e44ae426082".replace(" ", "")
            )
        )
        return p

    @pytest.fixture(scope="class")
    def lauren_app_binary(self, tmp_png_file: Path):  # type: ignore[no-untyped-def]
        file_path = tmp_png_file

        @mcp_server("/mcp_bin")
        class BinaryServer:
            def __init__(self, catalog: McpCatalogManager) -> None:
                self._catalog = catalog
                self._file_path = file_path

            @post_construct
            async def _setup(self) -> None:
                register_file_resource(
                    self._catalog,
                    FileResource(self._file_path, "file:///pixel.png", name="pixel"),
                )

            @mcp_tool()
            async def ping(self) -> str:
                "Ping."
                return "pong"

        @module(imports=[McpServerModule.for_root(BinaryServer)])
        class AppModule:
            pass

        app = LaurenFactory.create(AppModule)
        TestClient(app)
        return app

    @pytest.fixture
    def ws(self, lauren_app_binary):  # type: ignore[no-untyped-def]
        return WsTestClient(lauren_app_binary)

    async def test_binary_resource_returns_blob_field(self, ws) -> None:  # type: ignore[no-untyped-def]
        async with ws.connect("/mcp_bin/ws") as conn:
            await _handshake(conn)
            await conn.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 20,
                    "method": "resources/read",
                    "params": {"uri": "file:///pixel.png"},
                }
            )
            resp = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
            content = resp["result"]["contents"][0]
            # Binary resources come back with "blob" not "text"
            assert "blob" in content
            assert "text" not in content

    async def test_binary_resource_blob_is_base64(self, ws, tmp_png_file: Path) -> None:  # type: ignore[no-untyped-def]
        async with ws.connect("/mcp_bin/ws") as conn:
            await _handshake(conn)
            await conn.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 21,
                    "method": "resources/read",
                    "params": {"uri": "file:///pixel.png"},
                }
            )
            resp = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
            blob_b64 = resp["result"]["contents"][0]["blob"]
            decoded = base64.b64decode(blob_b64)
            assert decoded == tmp_png_file.read_bytes()


# ---------------------------------------------------------------------------
# DirectoryResource integration
# ---------------------------------------------------------------------------


class TestDirectoryResourceIntegration:
    @pytest.fixture(scope="class")
    def tmp_dir(self, tmp_path_factory: pytest.TempPathFactory) -> Path:
        d = tmp_path_factory.mktemp("dir_res")
        (d / "alpha.txt").write_text("a")
        (d / "beta.txt").write_text("b")
        (d / ".hidden").write_text("h")
        return d

    @pytest.fixture(scope="class")
    def lauren_app_dir(self, tmp_dir: Path):  # type: ignore[no-untyped-def]
        dir_path = tmp_dir

        @mcp_server("/mcp_dir")
        class DirServer:
            def __init__(self, catalog: McpCatalogManager) -> None:
                self._catalog = catalog
                self._dir_path = dir_path

            @post_construct
            async def _setup(self) -> None:
                register_directory_resource(
                    self._catalog,
                    DirectoryResource(
                        self._dir_path, "dir:///mydir", name="mydir", pattern="*.txt"
                    ),
                )

            @mcp_tool()
            async def ping(self) -> str:
                "Ping."
                return "pong"

        @module(imports=[McpServerModule.for_root(DirServer)])
        class AppModule:
            pass

        app = LaurenFactory.create(AppModule)
        TestClient(app)
        return app

    @pytest.fixture
    def ws(self, lauren_app_dir):  # type: ignore[no-untyped-def]
        return WsTestClient(lauren_app_dir)

    async def test_directory_resource_in_list(self, ws) -> None:  # type: ignore[no-untyped-def]
        async with ws.connect("/mcp_dir/ws") as conn:
            await _handshake(conn)
            await conn.send_json({"jsonrpc": "2.0", "id": 30, "method": "resources/list"})
            resp = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
            uris = [r["uri"] for r in resp["result"]["resources"]]
            assert "dir:///mydir" in uris

    async def test_directory_resource_read_returns_json(self, ws) -> None:  # type: ignore[no-untyped-def]
        async with ws.connect("/mcp_dir/ws") as conn:
            await _handshake(conn)
            await conn.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 31,
                    "method": "resources/read",
                    "params": {"uri": "dir:///mydir"},
                }
            )
            resp = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
            content = resp["result"]["contents"][0]
            files = json.loads(content["text"])
            assert "alpha.txt" in files
            assert "beta.txt" in files

    async def test_directory_resource_excludes_hidden(self, ws) -> None:  # type: ignore[no-untyped-def]
        async with ws.connect("/mcp_dir/ws") as conn:
            await _handshake(conn)
            await conn.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": 32,
                    "method": "resources/read",
                    "params": {"uri": "dir:///mydir"},
                }
            )
            resp = await asyncio.wait_for(conn.receive_json(), timeout=5.0)
            content = resp["result"]["contents"][0]
            files = json.loads(content["text"])
            assert ".hidden" not in files
