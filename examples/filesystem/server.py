"""Filesystem MCP Server — CRUD operations on a sandboxed directory.

This server exposes a sandboxed filesystem as a set of MCP tools, allowing
agents to read, write, list, create, and delete files within a safe boundary.

Usage (HTTP / WebSocket):
    MCP_FS_ROOT=/tmp/sandbox python examples/filesystem/server.py

Usage (stdio for agent use):
    MCP_FS_ROOT=/tmp/sandbox python examples/filesystem/server.py --stdio

Environment variables:
    MCP_FS_ROOT   Base directory for all operations (default: current dir).
                  Always set this to a sandboxed directory in production.
"""

from __future__ import annotations

import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lauren import (
    BackgroundTasks,
    LaurenFactory,
    Scope,
    injectable,
    module,
    set_metadata,
    use_guards,
)

from lauren_mcp import (
    McpServerModule,
    McpToolContext,
    ToolAnnotations,
    mcp_prompt,
    mcp_resource,
    mcp_server,
    mcp_tool,
)
from lauren_mcp.server import mcp_lifespan

# ---------------------------------------------------------------------------
# Sandbox path helper
# ---------------------------------------------------------------------------


def _resolve_safe_path(path: str, root: Path) -> Path:
    """Resolve *path* relative to *root* and verify it stays inside *root*.

    Args:
        path: A relative or absolute path string supplied by the caller.
        root: The sandbox root (must already be resolved).

    Returns:
        The resolved absolute :class:`Path`.

    Raises:
        ValueError: When the resolved path escapes *root* (directory traversal
            attempt) or when an absolute path outside *root* is supplied.
    """
    # Treat absolute paths as relative to root (strip leading slash).
    if os.path.isabs(path):
        # Strip the leading separator so Path(root) / path works safely.
        path = path.lstrip("/\\")

    candidate = (root / path).resolve()

    # candidate must be equal to root or a descendant of root.
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"Path traversal detected: {path!r} resolves to {candidate} "
            f"which is outside the sandbox {root}"
        ) from exc
    return candidate


# ---------------------------------------------------------------------------
# Guard: rejects requests when the server environment is not ready.
# ---------------------------------------------------------------------------


@injectable(scope=Scope.SINGLETON)
class McpFilesystemGuard:
    """Guard that allows all requests to pass through.

    The actual sandbox enforcement is performed inside each tool method via
    ``_resolve_safe_path``.  This guard exists as a hook point for future
    authentication / IP-allowlist policies.
    """

    async def can_activate(self, ctx: Any) -> bool:
        return True


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------


@set_metadata("allowed_root", os.environ.get("MCP_FS_ROOT", "."))
@use_guards(McpFilesystemGuard)
@mcp_server("/filesystem")
class FilesystemServer:
    """MCP server exposing CRUD filesystem operations on a sandboxed directory."""

    # ------------------------------------------------------------------
    # Lifespan: validate / create the sandbox root on startup.
    # ------------------------------------------------------------------

    @mcp_lifespan
    async def lifespan(self) -> Any:
        """Validate sandbox directory exists on startup; yield context dict."""
        root = Path(os.environ.get("MCP_FS_ROOT", "."))
        root.mkdir(parents=True, exist_ok=True)
        resolved = root.resolve()
        yield {"root": resolved, "allowed_root": resolved}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _root(self, ctx: McpToolContext) -> Path:
        return ctx.lifespan_context["root"]

    def _safe(self, path: str, ctx: McpToolContext) -> Path:
        return _resolve_safe_path(path, self._root(ctx))

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    @mcp_tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def list_files(
        self,
        ctx: McpToolContext,
        path: str = ".",
        recursive: bool = False,
    ) -> list[str]:
        """List files and directories at *path* inside the sandbox.

        Args:
            path: Relative path inside the sandbox (default: sandbox root).
            recursive: When True, list all descendants recursively.

        Returns:
            Sorted list of paths relative to the sandbox root.
        """
        target = self._safe(path, ctx)
        if not target.exists():
            raise ValueError(f"Path does not exist: {path!r}")
        if not target.is_dir():
            raise ValueError(f"Path is not a directory: {path!r}")

        root = self._root(ctx)
        if recursive:
            entries = sorted(str(p.relative_to(root)) for p in target.rglob("*"))
        else:
            entries = sorted(str(p.relative_to(root)) for p in target.iterdir())

        await ctx.info(f"Listed {len(entries)} entries at {path!r}")
        return entries

    @mcp_tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def read_file(self, ctx: McpToolContext, path: str) -> str:
        """Read a file and return its content as a UTF-8 string.

        Files larger than 1 MB are rejected to prevent memory exhaustion.
        Progress notifications are sent for files over 64 KB.

        Args:
            path: Relative path to the file inside the sandbox.

        Returns:
            File content as a string.
        """
        target = self._safe(path, ctx)
        if not target.exists():
            raise ValueError(f"File does not exist: {path!r}")
        if not target.is_file():
            raise ValueError(f"Path is not a file: {path!r}")

        size = target.stat().st_size
        if size > 1_048_576:  # 1 MB
            raise ValueError(
                f"File {path!r} is {size} bytes; files larger than 1 MB are not supported"
            )

        if size > 65_536:  # 64 KB — emit progress
            await ctx.report_progress(0, size, f"Reading {path!r}")

        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"File {path!r} is not valid UTF-8 text: {exc}") from exc

        if size > 65_536:
            await ctx.report_progress(size, size, f"Done reading {path!r}")

        await ctx.info(f"Read {size} bytes from {path!r}")
        return content

    @mcp_tool(
        annotations=ToolAnnotations(destructiveHint=True),
        timeout=30.0,
    )
    async def write_file(
        self,
        ctx: McpToolContext,
        path: str,
        content: str,
        create_dirs: bool = False,
    ) -> dict[str, Any]:
        """Create or overwrite a file with *content*.

        Args:
            path: Relative path to the file inside the sandbox.
            content: UTF-8 content to write.
            create_dirs: When True, create missing parent directories.

        Returns:
            Dict with keys ``path``, ``bytes_written``, and ``created``
            (True if the file was newly created, False if overwritten).
        """
        target = self._safe(path, ctx)
        created = not target.exists()

        if create_dirs:
            target.parent.mkdir(parents=True, exist_ok=True)
        elif not target.parent.exists():
            raise ValueError(
                f"Parent directory {str(target.parent.relative_to(self._root(ctx)))!r} "
                "does not exist; pass create_dirs=True to create it"
            )

        encoded = content.encode("utf-8")
        target.write_bytes(encoded)

        await ctx.info(f"{'Created' if created else 'Overwrote'} {path!r} ({len(encoded)} bytes)")
        return {
            "path": str(target.relative_to(self._root(ctx))),
            "bytes_written": len(encoded),
            "created": created,
        }

    @mcp_tool()
    async def create_directory(
        self,
        ctx: McpToolContext,
        path: str,
    ) -> dict[str, Any]:
        """Create a directory (and any missing parents).

        Args:
            path: Relative path of the new directory inside the sandbox.

        Returns:
            Dict with keys ``path`` and ``created`` (True if newly created).
        """
        target = self._safe(path, ctx)
        created = not target.exists()
        target.mkdir(parents=True, exist_ok=True)
        await ctx.info(f"{'Created' if created else 'Already exists'} directory {path!r}")
        return {
            "path": str(target.relative_to(self._root(ctx))),
            "created": created,
        }

    @mcp_tool(annotations=ToolAnnotations(destructiveHint=True))
    async def delete_file(self, ctx: McpToolContext, path: str) -> dict[str, Any]:
        """Delete a file inside the sandbox.

        Directories are not accepted; use ``delete_directory`` instead.

        Args:
            path: Relative path to the file inside the sandbox.

        Returns:
            Dict with keys ``path`` and ``deleted`` (always True on success).
        """
        target = self._safe(path, ctx)
        if not target.exists():
            raise ValueError(f"File does not exist: {path!r}")
        if target.is_dir():
            raise ValueError(
                f"Path {path!r} is a directory; use delete_directory to remove directories"
            )
        target.unlink()
        await ctx.info(f"Deleted file {path!r}")
        return {
            "path": str(target.relative_to(self._root(ctx))),
            "deleted": True,
        }

    @mcp_tool(annotations=ToolAnnotations(destructiveHint=True))
    async def delete_directory(
        self,
        ctx: McpToolContext,
        path: str,
        recursive: bool = False,
    ) -> dict[str, Any]:
        """Delete a directory inside the sandbox.

        Args:
            path: Relative path to the directory inside the sandbox.
            recursive: When False (default), the directory must be empty.
                When True, the entire tree is removed.

        Returns:
            Dict with keys ``path`` and ``deleted`` (always True on success).
        """
        target = self._safe(path, ctx)
        if not target.exists():
            raise ValueError(f"Directory does not exist: {path!r}")
        if not target.is_dir():
            raise ValueError(f"Path {path!r} is not a directory; use delete_file to remove files")

        if not recursive:
            children = list(target.iterdir())
            if children:
                raise ValueError(
                    f"Directory {path!r} is not empty ({len(children)} items). "
                    "Pass recursive=True to remove it and all its contents."
                )
            target.rmdir()
        else:
            shutil.rmtree(target)

        await ctx.info(f"Deleted directory {path!r} (recursive={recursive})")
        return {
            "path": str(target.relative_to(self._root(ctx))),
            "deleted": True,
        }

    @mcp_tool(annotations=ToolAnnotations(destructiveHint=True))
    async def move_file(
        self,
        ctx: McpToolContext,
        source: str,
        destination: str,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Move or rename a file inside the sandbox.

        Args:
            source: Relative path of the existing file.
            destination: Relative path of the target location.
            overwrite: When False (default), raises if the destination exists.

        Returns:
            Dict with keys ``source``, ``destination``, and ``moved``.
        """
        src = self._safe(source, ctx)
        dst = self._safe(destination, ctx)

        if not src.exists():
            raise ValueError(f"Source does not exist: {source!r}")

        if dst.exists() and not overwrite:
            raise ValueError(
                f"Destination {destination!r} already exists; pass overwrite=True to replace it"
            )

        dst.parent.mkdir(parents=True, exist_ok=True)
        src.rename(dst)
        root = self._root(ctx)
        await ctx.info(f"Moved {source!r} -> {destination!r}")
        return {
            "source": str(src.relative_to(root)),
            "destination": str(dst.relative_to(root)),
            "moved": True,
        }

    @mcp_tool(annotations=ToolAnnotations(readOnlyHint=True))
    async def file_info(self, ctx: McpToolContext, path: str) -> dict[str, Any]:
        """Return metadata about a file or directory.

        Args:
            path: Relative path inside the sandbox.

        Returns:
            Dict with keys ``name``, ``path``, ``size``, ``is_file``,
            ``is_dir``, ``modified_at`` (ISO-8601 UTC), and ``extension``.
        """
        target = self._safe(path, ctx)
        if not target.exists():
            raise ValueError(f"Path does not exist: {path!r}")

        st = target.stat()
        mtime = datetime.fromtimestamp(st.st_mtime, tz=UTC).isoformat()
        root = self._root(ctx)

        await ctx.info(f"Queried info for {path!r}")
        return {
            "name": target.name,
            "path": str(target.relative_to(root)),
            "size": st.st_size,
            "is_file": target.is_file(),
            "is_dir": target.is_dir(),
            "modified_at": mtime,
            "extension": target.suffix,
        }

    # ------------------------------------------------------------------
    # Multi-CRUD tools with BackgroundTasks
    # ------------------------------------------------------------------

    @mcp_tool(
        annotations=ToolAnnotations(destructiveHint=True),
        timeout=60.0,
    )
    async def bulk_write_files(
        self,
        files: list[dict],
        bg: BackgroundTasks,
        ctx: McpToolContext,
        create_dirs: bool = False,
    ) -> dict:
        """Write multiple files in one call.

        Each item in *files* must have ``path`` (str) and ``content`` (str) keys.
        An optional ``audit_log`` entry is written in the background after all
        files are persisted.

        Args:
            files: List of ``{"path": str, "content": str}`` dicts.
            create_dirs: Create missing parent directories automatically.

        Returns:
            Dict with ``written`` (list of paths), ``failed`` (list of
            ``{"path", "error"}`` dicts), and ``total`` counts.
        """
        written: list[str] = []
        failed: list[dict] = []
        root = self._root(ctx)

        for entry in files:
            p = entry.get("path", "")
            c = entry.get("content", "")
            try:
                target = _resolve_safe_path(p, root)
                if create_dirs:
                    target.parent.mkdir(parents=True, exist_ok=True)
                elif not target.parent.exists():
                    raise ValueError(f"Parent of {p!r} does not exist")
                target.write_text(c, encoding="utf-8")
                written.append(p)
            except Exception as exc:
                failed.append({"path": p, "error": str(exc)})

        await ctx.info(f"bulk_write_files: {len(written)} written, {len(failed)} failed")

        # Background: append to audit log (runs after response is sent)
        audit_path = root / ".audit.log"
        audit_lines = [f"[bulk_write] {p}\n" for p in written] + [
            f"[bulk_write:fail] {e['path']}: {e['error']}\n" for e in failed
        ]

        async def _append_audit(path: Path, lines: list[str]) -> None:
            with path.open("a", encoding="utf-8") as fh:
                fh.writelines(lines)

        bg.add_task(_append_audit, audit_path, audit_lines)

        return {
            "written": written,
            "failed": failed,
            "total": len(files),
        }

    @mcp_tool(
        annotations=ToolAnnotations(destructiveHint=True),
        timeout=60.0,
    )
    async def bulk_delete_files(
        self,
        paths: list[str],
        bg: BackgroundTasks,
        ctx: McpToolContext,
    ) -> dict:
        """Delete multiple files in one call.

        Directories are skipped (use ``delete_directory`` individually).
        Deletions are logged to ``.audit.log`` in the background.

        Args:
            paths: List of relative file paths to delete.

        Returns:
            Dict with ``deleted``, ``failed``, and ``skipped`` lists.
        """
        deleted: list[str] = []
        failed: list[dict] = []
        skipped: list[str] = []
        root = self._root(ctx)

        for p in paths:
            try:
                target = _resolve_safe_path(p, root)
                if not target.exists():
                    skipped.append(p)
                    continue
                if target.is_dir():
                    skipped.append(p)
                    await ctx.warning(f"Skipping directory {p!r}; use delete_directory")
                    continue
                target.unlink()
                deleted.append(p)
            except Exception as exc:
                failed.append({"path": p, "error": str(exc)})

        await ctx.info(
            f"bulk_delete_files: {len(deleted)} deleted, "
            f"{len(skipped)} skipped, {len(failed)} failed"
        )

        audit_path = root / ".audit.log"
        audit_lines = (
            [f"[bulk_delete] {p}\n" for p in deleted]
            + [f"[bulk_delete:skip] {p}\n" for p in skipped]
            + [f"[bulk_delete:fail] {e['path']}: {e['error']}\n" for e in failed]
        )

        async def _append_audit(path: Path, lines: list[str]) -> None:
            with path.open("a", encoding="utf-8") as fh:
                fh.writelines(lines)

        bg.add_task(_append_audit, audit_path, audit_lines)

        return {"deleted": deleted, "skipped": skipped, "failed": failed}

    @mcp_tool(
        annotations=ToolAnnotations(destructiveHint=False, idempotentHint=False),
        timeout=60.0,
    )
    async def bulk_copy_files(
        self,
        copies: list[dict],
        bg: BackgroundTasks,
        ctx: McpToolContext,
        overwrite: bool = False,
    ) -> dict:
        """Copy multiple files in one call.

        Each item in *copies* must have ``source`` (str) and ``destination``
        (str) keys.  A ``.manifest`` file in the sandbox root is updated in the
        background with a record of every copy.

        Args:
            copies: List of ``{"source": str, "destination": str}`` dicts.
            overwrite: Allow overwriting existing destination files.

        Returns:
            Dict with ``copied`` and ``failed`` lists.
        """
        import shutil as _shutil  # noqa: PLC0415

        copied: list[dict] = []
        failed: list[dict] = []
        root = self._root(ctx)

        for entry in copies:
            src_str = entry.get("source", "")
            dst_str = entry.get("destination", "")
            try:
                src = _resolve_safe_path(src_str, root)
                dst = _resolve_safe_path(dst_str, root)
                if not src.exists():
                    raise ValueError(f"Source does not exist: {src_str!r}")
                if dst.exists() and not overwrite:
                    raise ValueError(
                        f"Destination {dst_str!r} exists; pass overwrite=True to replace"
                    )
                dst.parent.mkdir(parents=True, exist_ok=True)
                _shutil.copy2(src, dst)
                copied.append({"source": src_str, "destination": dst_str})
            except Exception as exc:
                failed.append({"source": src_str, "destination": dst_str, "error": str(exc)})

        await ctx.info(f"bulk_copy_files: {len(copied)} copied, {len(failed)} failed")

        # Background: update manifest
        manifest_path = root / ".manifest"
        manifest_entries = [f"{e['source']} -> {e['destination']}\n" for e in copied]

        async def _update_manifest(path: Path, lines: list[str]) -> None:
            with path.open("a", encoding="utf-8") as fh:
                fh.writelines(lines)

        bg.add_task(_update_manifest, manifest_path, manifest_entries)

        return {"copied": copied, "failed": failed}

    @mcp_tool(
        annotations=ToolAnnotations(destructiveHint=False),
        timeout=120.0,
    )
    async def sync_directory(
        self,
        source: str,
        destination: str,
        bg: BackgroundTasks,
        ctx: McpToolContext,
        overwrite: bool = False,
    ) -> dict:
        """Recursively copy all files from *source* directory to *destination*.

        This is a one-way sync: files in *destination* that are not in *source*
        are left untouched.  A sync log is written to ``.sync.log`` in the
        background after all files are copied.

        Args:
            source: Relative path to the source directory.
            destination: Relative path to the destination directory.
            overwrite: Allow overwriting existing files in destination.

        Returns:
            Dict with ``synced`` count, ``skipped`` count, ``failed`` list,
            and ``destination`` path.
        """
        import shutil as _shutil  # noqa: PLC0415

        root = self._root(ctx)
        src_dir = _resolve_safe_path(source, root)
        dst_dir = _resolve_safe_path(destination, root)

        if not src_dir.exists() or not src_dir.is_dir():
            raise ValueError(f"Source is not a directory: {source!r}")

        dst_dir.mkdir(parents=True, exist_ok=True)

        synced = 0
        skipped = 0
        failed: list[dict] = []

        for src_file in src_dir.rglob("*"):
            if not src_file.is_file():
                continue
            rel = src_file.relative_to(src_dir)
            dst_file = dst_dir / rel
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            if dst_file.exists() and not overwrite:
                skipped += 1
                continue
            try:
                _shutil.copy2(src_file, dst_file)
                synced += 1
            except Exception as exc:
                failed.append({"file": str(rel), "error": str(exc)})

        await ctx.info(
            f"sync_directory {source!r} -> {destination!r}: "
            f"{synced} synced, {skipped} skipped, {len(failed)} failed"
        )

        # Background: write sync log
        sync_log = root / ".sync.log"
        log_lines = [
            f"[sync] {source} -> {destination}: "
            f"{synced} synced, {skipped} skipped, {len(failed)} failed\n"
        ]

        async def _write_sync_log(path: Path, lines: list[str]) -> None:
            with path.open("a", encoding="utf-8") as fh:
                fh.writelines(lines)

        bg.add_task(_write_sync_log, sync_log, log_lines)

        return {
            "synced": synced,
            "skipped": skipped,
            "failed": failed,
            "destination": str(dst_dir.relative_to(root)),
        }

    # ------------------------------------------------------------------
    # Resource
    # ------------------------------------------------------------------

    @mcp_resource("file://{path}", mime_type="text/plain")
    async def file_content(self, path: str) -> str:
        """Read a file as an MCP resource.

        Args:
            path: Relative path inside the sandbox.
        """
        root = Path(os.environ.get("MCP_FS_ROOT", ".")).resolve()
        target = _resolve_safe_path(path, root)
        if not target.exists() or not target.is_file():
            return f"(file not found: {path!r})"
        try:
            return target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return f"(binary file: {path!r})"

    # ------------------------------------------------------------------
    # Prompt
    # ------------------------------------------------------------------

    @mcp_prompt()
    async def edit_file_prompt(self, path: str, instruction: str) -> str:
        """Generate a prompt that instructs an agent to edit a file.

        Args:
            path: Path to the file to edit.
            instruction: Natural-language description of the desired change.
        """
        root = Path(os.environ.get("MCP_FS_ROOT", ".")).resolve()
        target = _resolve_safe_path(path, root)

        try:
            current_content = target.read_text(encoding="utf-8") if target.is_file() else ""
        except Exception:
            current_content = ""

        preview = current_content[:500] + ("..." if len(current_content) > 500 else "")
        return (
            f"Please edit the file at path {path!r}.\n\n"
            f"Instruction: {instruction}\n\n"
            f"Current content (first 500 chars):\n```\n{preview}\n```\n\n"
            "Use the write_file tool to save your changes."
        )


# ---------------------------------------------------------------------------
# Lauren module + app
# ---------------------------------------------------------------------------


@module(
    imports=[
        McpServerModule.for_root(
            FilesystemServer,
            transport="all",
            log_level="info",
            providers=[McpFilesystemGuard],
        )
    ]
)
class FilesystemModule:
    """Root Lauren module for the Filesystem MCP server."""


app = LaurenFactory.create(FilesystemModule)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8765)
