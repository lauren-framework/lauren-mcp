"""
Deploy the Filesystem MCP server on Modal with a persistent Volume.

The server exposes full CRUD filesystem operations over the MCP protocol.
All files are stored in a Modal Volume — shared persistent storage that
survives container restarts and scales across replicas.

Quick start
-----------
    pip install modal
    modal setup                      # authenticate once

    # Serve locally (hot-reload, no deploy)
    modal serve examples/filesystem/modal_deploy.py

    # Deploy to production
    modal deploy examples/filesystem/modal_deploy.py

    # Connect from Python
    from lauren_mcp import McpServer
    client = McpServer.streamable_http("https://<your-app>.modal.run/mcp/")
    await client.connect()
    await client.call_tool("write_file", {"path": "hello.txt", "content": "hi"})

    # Or use the lmcp CLI
    lmcp inspect --url https://<your-app>.modal.run/mcp/

Volume durability
-----------------
Modal Volumes use a network filesystem.  Writes are immediately visible
within the same container instance.  To guarantee visibility across freshly
started containers (e.g. after a cold start), call ``commit_volume()``:

    modal run examples/filesystem/modal_deploy.py::commit_volume

Authentication
--------------
By default the endpoint is public.  To restrict access, add an auth guard
to the server class or set the MCP_REQUIRE_TOKEN env var below and attach
a Modal Secret containing your bearer token.

    modal secret create mcp-auth MCP_REQUIRE_TOKEN=my-secret-token
    # then uncomment secrets=[modal.Secret.from_name("mcp-auth")] below
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import modal

# ---------------------------------------------------------------------------
# Configuration — tweak these as needed
# ---------------------------------------------------------------------------

APP_NAME = "lauren-mcp-filesystem"  # Modal app name (appears in your dashboard)
VOLUME_NAME = "mcp-filesystem-data"  # persistent volume name
VOLUME_MOUNT = "/mnt/mcp-fs"  # mount point inside each container

# ---------------------------------------------------------------------------
# Modal resources
# ---------------------------------------------------------------------------

app = modal.App(APP_NAME)

# Persistent Volume — created on first deploy, shared by all replicas.
# modal.Volume.from_name() references or creates the volume by name.
volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)

# Container image: Python 3.12 + lauren-mcp + server module.
# add_local_file copies server.py into the image at build time so it is
# available in every container without a network round-trip.
_server_src = Path(__file__).parent / "server.py"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "lauren-mcp[all]",  # core + all transport extras
    )
    .add_local_file(str(_server_src), "/app/server.py")
)

# ---------------------------------------------------------------------------
# ASGI endpoint — serves Streamable HTTP (MCP 2025-03-26) + WebSocket
# ---------------------------------------------------------------------------


@app.function(
    image=image,
    volumes={VOLUME_MOUNT: volume},
    # Allow many concurrent MCP connections per container.
    allow_concurrent_inputs=100,
    # Keep one warm instance to avoid cold-start latency for interactive use.
    keep_warm=1,
    # Uncomment to add auth:
    # secrets=[modal.Secret.from_name("mcp-auth")],
)
@modal.asgi_app()
def serve() -> Any:
    """Return the Lauren ASGI app for Modal to serve.

    The function body runs once when the container initialises.
    Setting MCP_FS_ROOT before importing server.py ensures the
    lifespan hook creates/validates the correct sandbox directory.
    """
    # Make the bundled server module importable.
    sys.path.insert(0, "/app")

    # Set before importing — server.py reads MCP_FS_ROOT at import time.
    os.environ["MCP_FS_ROOT"] = VOLUME_MOUNT

    # Optionally reject connections without a bearer token.
    token = os.environ.get("MCP_REQUIRE_TOKEN")
    if token:
        os.environ.setdefault("MCP_AUTH_TOKEN", token)

    from server import app as lauren_app  # noqa: PLC0415

    return lauren_app


# ---------------------------------------------------------------------------
# Volume management helpers (run with `modal run modal_deploy.py::fn`)
# ---------------------------------------------------------------------------


@app.function(image=image, volumes={VOLUME_MOUNT: volume})
def commit_volume() -> str:
    """Flush all pending writes to Modal's durable storage layer.

    Run after bulk write operations or before scaling down:

        modal run examples/filesystem/modal_deploy.py::commit_volume
    """
    volume.commit()
    return f"✓ Volume '{VOLUME_NAME}' committed."


@app.function(image=image, volumes={VOLUME_MOUNT: volume})
def list_volume(path: str = ".") -> list[str]:
    """List the contents of *path* inside the volume.

    modal run examples/filesystem/modal_deploy.py::list_volume
    modal run examples/filesystem/modal_deploy.py::list_volume --path docs
    """
    import os as _os  # noqa: PLC0415

    safe_path = VOLUME_MOUNT + "/" + path.strip("/")
    resolved = _os.path.normpath(safe_path)
    if not resolved.startswith(VOLUME_MOUNT):
        return ["error: path traversal detected"]
    try:
        entries = sorted(
            ("📁 " if _os.path.isdir(_os.path.join(resolved, e)) else "📄 ") + e
            for e in _os.listdir(resolved)
        )
        return entries or ["(empty)"]
    except FileNotFoundError:
        return [f"error: {path!r} not found in volume"]


@app.function(image=image, volumes={VOLUME_MOUNT: volume})
def wipe_volume(confirm: str = "") -> str:
    """Delete **all** files from the volume.  Pass confirm='yes' to proceed.

    modal run examples/filesystem/modal_deploy.py::wipe_volume --confirm yes
    """
    if confirm.lower() != "yes":
        return "Aborted — pass --confirm yes to wipe the volume."
    import shutil as _shutil  # noqa: PLC0415

    root = Path(VOLUME_MOUNT)
    for child in root.iterdir():
        if child.is_dir():
            _shutil.rmtree(child)
        else:
            child.unlink()
    volume.commit()
    return f"✓ Volume '{VOLUME_NAME}' wiped and committed."


# ---------------------------------------------------------------------------
# Local entrypoint — shown when you run `modal run modal_deploy.py`
# ---------------------------------------------------------------------------


@app.local_entrypoint()
def main() -> None:
    """Print usage instructions."""
    name = Path(__file__).name
    print()
    print("  Lauren MCP Filesystem — Modal deployment")
    print()
    print(f"  Serve locally:   modal serve {name}")
    print(f"  Deploy:          modal deploy {name}")
    print()
    print(f"  List files:      modal run {name}::list_volume")
    print(f"  List subdir:     modal run {name}::list_volume --path my/subdir")
    print(f"  Commit writes:   modal run {name}::commit_volume")
    print(f"  Wipe volume:     modal run {name}::wipe_volume --confirm yes")
    print()
    print("  Python client:")
    print("    from lauren_mcp import McpServer")
    print('    client = McpServer.streamable_http("https://<app>.modal.run/mcp/")')
    print("    await client.connect()")
    print("    tools = await client.list_tools()")
