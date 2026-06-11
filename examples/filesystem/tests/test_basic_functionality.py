"""Basic functionality tests to verify the test setup works correctly.

These tests are simple sanity checks that the test environment is properly configured.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


class TestBasicSanity:
    """These tests verify the basic test infrastructure is working."""

    def test_basic_assertion_works(self):
        """Simple assertion that test framework is running."""
        assert True

    def test_basic_calculation(self):
        """Simple calculation test."""
        assert 1 + 1 == 2

    async def test_async_test_works(self):
        """Verify async tests are supported."""
        import asyncio

        await asyncio.sleep(0)
        assert True

    def test_import_server_module(self):
        """Verify the server module can be imported."""
        from examples.filesystem.server import FilesystemServer

        assert FilesystemServer is not None

    def test_resolve_safe_path_function_exists(self):
        """Verify _resolve_safe_path can be imported."""
        from examples.filesystem.server import _resolve_safe_path

        assert callable(_resolve_safe_path)
