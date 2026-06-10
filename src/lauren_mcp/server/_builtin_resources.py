"""Built-in resource types: FileResource, HttpResource, DirectoryResource.

These classes produce correctly-configured ``McpResourceMeta`` objects with
``_bound_instance`` set so ``make_resources_read_handler`` can call ``.read()``
without a server-instance fallback.  They are a thin convenience layer over
the existing handler machinery — no changes to ``_handlers.py`` or
``McpResourceMeta`` are required.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from lauren_mcp._types import BlobResource
from lauren_mcp.server._meta import McpResourceMeta

# ---------------------------------------------------------------------------
# FileResource
# ---------------------------------------------------------------------------


class FileResource:
    """Expose a local file as a static MCP resource.

    MIME type is auto-detected from the file extension when *mime_type* is
    omitted.  Files whose MIME type starts with ``"text/"`` or is one of the
    common text-like types (``application/json``, ``application/xml``) are
    served as UTF-8 strings; everything else is returned as a
    :class:`~lauren_mcp._types.BlobResource`.

    Args:
        path: Absolute or relative path to the file on disk.
        uri: The URI the resource is reachable under (e.g.
            ``"file:///data/report.pdf"``).
        name: Resource name for ``resources/list`` (defaults to the file's
            basename).
        description: Human-readable description (optional).
        mime_type: Explicit MIME type; auto-detected from extension when
            ``None``.
    """

    def __init__(
        self,
        path: str | Path,
        uri: str,
        *,
        name: str | None = None,
        description: str | None = None,
        mime_type: str | None = None,
    ) -> None:
        self._path = Path(path)
        self._uri = uri
        self._name = name or self._path.name
        self._description = description
        self._mime_type = mime_type or _detect_mime(self._path)

    # ------------------------------------------------------------------
    # Public helpers (used by tests)
    # ------------------------------------------------------------------

    def _is_text(self) -> bool:
        mt = self._mime_type or ""
        return mt.startswith("text/") or mt in ("application/json", "application/xml")

    async def read(self) -> str | BlobResource:
        """Read the file and return text or :class:`BlobResource`."""
        data = self._path.read_bytes()
        if self._is_text():
            return data.decode("utf-8", errors="replace")
        return BlobResource(data=data, mime_type=self._mime_type or "application/octet-stream")

    def as_mcp_resource_meta(self) -> McpResourceMeta:
        """Return an :class:`McpResourceMeta` whose ``method_name`` points to
        ``read``."""
        meta = McpResourceMeta(
            uri_template=self._uri,
            name=self._name,
            description=self._description,
            mime_type=self._mime_type,
            method_name="read",
            query_params=[],
            param_type_hints={},
        )
        # Bind this instance so make_resources_read_handler resolves the target.
        meta._bound_instance = self  # type: ignore[attr-defined]
        return meta


# ---------------------------------------------------------------------------
# HttpResource
# ---------------------------------------------------------------------------


class HttpResource:
    """Fetch an HTTP URL and expose the response body as an MCP resource.

    Requires the ``[http]`` extra (``httpx``).

    Args:
        url: The upstream URL to fetch on each ``resources/read``.
        uri: The URI the resource is reachable under.
        name: Resource name (defaults to *url*).
        description: Human-readable description (optional).
        mime_type: Explicit MIME type; taken from the response
            ``Content-Type`` header when ``None``.
        headers: Extra HTTP headers forwarded with every request.
        timeout: HTTP request timeout in seconds (default 30.0).
    """

    def __init__(
        self,
        url: str,
        uri: str,
        *,
        name: str | None = None,
        description: str | None = None,
        mime_type: str | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._url = url
        self._uri = uri
        self._name = name or url
        self._description = description
        self._mime_type = mime_type
        self._headers = headers or {}
        self._timeout = timeout

    async def read(self) -> str | BlobResource:
        """Fetch the upstream URL and return its body."""
        try:
            import httpx  # noqa: PLC0415
        except ImportError as exc:
            raise ImportError(
                "HttpResource requires httpx; install it with: pip install 'lauren-mcp[http]'"
            ) from exc
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(self._url, headers=self._headers)
            response.raise_for_status()
            effective_mime = (
                self._mime_type
                or response.headers.get("content-type", "application/octet-stream")
                .split(";")[0]
                .strip()
            )
            if effective_mime.startswith("text/") or effective_mime in (
                "application/json",
                "application/xml",
            ):
                return str(response.text)
            return BlobResource(data=response.content, mime_type=effective_mime)

    def as_mcp_resource_meta(self) -> McpResourceMeta:
        meta = McpResourceMeta(
            uri_template=self._uri,
            name=self._name,
            description=self._description,
            mime_type=self._mime_type,
            method_name="read",
            query_params=[],
            param_type_hints={},
        )
        meta._bound_instance = self  # type: ignore[attr-defined]
        return meta


# ---------------------------------------------------------------------------
# DirectoryResource
# ---------------------------------------------------------------------------


class DirectoryResource:
    """List files in a directory as a JSON array resource.

    Returns a JSON-serialised list of relative file paths matching *pattern*.
    The response MIME type is always ``"application/json"``.

    Args:
        path: Root directory to list.
        uri: The URI the resource is reachable under.
        name: Resource name (defaults to the directory's basename).
        description: Human-readable description (optional).
        pattern: Glob pattern relative to *path* (default ``"*"``).
        recursive: When ``True`` uses ``rglob`` instead of ``glob``.
        include_hidden: When ``False`` (default) entries whose name starts
            with ``.`` are excluded.
    """

    def __init__(
        self,
        path: str | Path,
        uri: str,
        *,
        name: str | None = None,
        description: str | None = None,
        pattern: str = "*",
        recursive: bool = False,
        include_hidden: bool = False,
    ) -> None:
        self._path = Path(path)
        self._uri = uri
        self._name = name or self._path.name
        self._description = description
        self._pattern = pattern
        self._recursive = recursive
        self._include_hidden = include_hidden

    async def read(self) -> str:
        """Return JSON array of relative paths matching the pattern."""
        import json  # noqa: PLC0415

        method = self._path.rglob if self._recursive else self._path.glob
        entries = sorted(
            str(p.relative_to(self._path))
            for p in method(self._pattern)
            if p.is_file() and (self._include_hidden or not p.name.startswith("."))
        )
        return json.dumps(entries)

    def as_mcp_resource_meta(self) -> McpResourceMeta:
        meta = McpResourceMeta(
            uri_template=self._uri,
            name=self._name,
            description=self._description,
            mime_type="application/json",
            method_name="read",
            query_params=[],
            param_type_hints={},
        )
        meta._bound_instance = self  # type: ignore[attr-defined]
        return meta


# ---------------------------------------------------------------------------
# Helper registration functions
# ---------------------------------------------------------------------------


def register_file_resource(catalog: Any, resource: FileResource) -> None:
    """Register *resource* with *catalog* (an :class:`McpCatalogManager` instance)."""
    catalog.register_resource(resource.as_mcp_resource_meta())


def register_http_resource(catalog: Any, resource: HttpResource) -> None:
    """Register *resource* with *catalog* (an :class:`McpCatalogManager` instance)."""
    catalog.register_resource(resource.as_mcp_resource_meta())


def register_directory_resource(catalog: Any, resource: DirectoryResource) -> None:
    """Register *resource* with *catalog* (an :class:`McpCatalogManager` instance)."""
    catalog.register_resource(resource.as_mcp_resource_meta())


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _detect_mime(path: Path) -> str:
    """Auto-detect MIME type from file extension; fall back to octet-stream."""
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"
