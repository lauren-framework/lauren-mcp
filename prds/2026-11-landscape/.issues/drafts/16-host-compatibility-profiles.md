**PRD:** [`prd-host-compatibility-profiles.md`](https://github.com/lauren-framework/lauren-mcp/blob/docs/mcp-landscape-2026-11/prds/2026-11-landscape/prd-host-compatibility-profiles.md)
**Priority:** P2 — `lmcp install` writes one config shape for ten hosts, and the server cannot ask what a host cannot do
**Theme:** Ecosystem
**Key evidence:** E-191, E-195, E-198 — see `EVIDENCE.md` in the same directory.

## Problem

```python
# src/lauren_mcp/cli/_commands.py  line 283
def _get_config_path(client_name: str) -> str:
    system = platform.system()
    if client_name == "claude":                       # line 288
        ...
    elif client_name == "cursor":                     # line 298
        ...
    else:                                             # line 307
        typer.echo(f"Unknown client {client_name!r}; expected 'claude' or 'cursor'", err=True)
        raise typer.Exit(code=1)
```

```python
# src/lauren_mcp/cli/_commands.py  line 326
    servers = existing.setdefault("mcpServers", {})   # line 326
    servers[server_name] = {
        "command": sys.executable,                    # line 329
        "args": ["-m", "lauren_mcp.cli", "run", file_spec, "--stdio"],
    }
```

## Goals

1. Ship a declarative in-tree registry — `src/lauren_mcp/_hosts.py` — with one `HostProfile` per
   verified host: filename, top-level key, transports, capability flags, harness limits, evidence IDs.
2. Ship `lmcp hosts` and `lmcp hosts --json` listing exactly ten profiles, with `jetbrains` absent and
   the reason printed.
3. Ship `lmcp init --host <profile>` emitting that host's correct file, key and transport block, plus
   `--transport stdio|http`.
4. Ship `lmcp init --all-hosts` writing every host's artefact in one invocation.
5. Expose the registry to server code so `--host-profile <profile>` degrades *before* advertising.
6. Document, per missing feature, the exact fallback a tool author must implement (§4.5).
7. Keep `lmcp install --client claude|cursor` byte-identical on disk.
8. Change no wire behaviour: no new method, no changed response shape, no changed capability unless a
   profile is explicitly supplied.

### Acceptance checklist

- [ ] `python -m lauren_mcp.cli hosts` prints ten rows and no `jetbrains` row.
- [ ] `python -m lauren_mcp.cli hosts --json | python -c 'import json,sys; print(len(json.load(sys.stdin)))'` prints `10`.
- [ ] `python -m lauren_mcp.cli init examples/filesystem/server.py --host vscode --print | grep -c '"servers"'` prints `1`, and `… | grep -c mcpServers` prints `0`.
- [ ] `python -m lauren_mcp.cli init examples/filesystem/server.py --host zed --print | grep -c context_servers` prints `1`.
- [ ] `python -m lauren_mcp.cli init examples/filesystem/server.py --host gemini-cli --transport http --print | grep -c httpUrl` prints `1`.
- [ ] `python -m lauren_mcp.cli init examples/filesystem/server.py --host chatgpt --print | grep -c 'Streamable HTTP'` prints `1`, and the output is **not** JSON.
- [ ] `python -m lauren_mcp.cli init examples/filesystem/server.py --all-hosts --out /tmp/hosts-out && ls /tmp/hosts-out | wc -l` prints `9`.
- [ ] `grep -c mcpServers src/lauren_mcp/cli/_commands.py` prints `0`; `grep -c jetbrains src/lauren_mcp/_hosts.py` prints `0`.
- [ ] `python -m lauren_mcp.cli run examples/filesystem/server.py --stdio --host-profile zed` advertises no `resources` in `initialize`; without the flag the response is unchanged.
- [ ] `python -m pytest tests/unit/test_hosts_registry.py tests/unit/test_hosts_emitters.py tests/unit/test_cli_hosts_commands.py tests/unit/test_hosts_docs.py tests/integration/test_cli_hosts_integration.py -q` passes, and `tests/integration/test_cli_commands_integration.py -q` still passes.
- [ ] `git diff --stat src/lauren_mcp/_server/ | wc -l` prints `0`.

## Acceptance criteria

- [ ] `python -m lauren_mcp.cli hosts` prints ten rows and no `jetbrains` row.
- [ ] `python -m lauren_mcp.cli hosts --json | python -c 'import json,sys; print(len(json.load(sys.stdin)))'` prints `10`.
- [ ] `python -m lauren_mcp.cli init examples/filesystem/server.py --host vscode --print | grep -c '"servers"'` prints `1`, and `… | grep -c mcpServers` prints `0`.
- [ ] `python -m lauren_mcp.cli init examples/filesystem/server.py --host zed --print | grep -c context_servers` prints `1`.
- [ ] `python -m lauren_mcp.cli init examples/filesystem/server.py --host gemini-cli --transport http --print | grep -c httpUrl` prints `1`.
- [ ] `python -m lauren_mcp.cli init examples/filesystem/server.py --host chatgpt --print | grep -c 'Streamable HTTP'` prints `1`, and the output is **not** JSON.
- [ ] `python -m lauren_mcp.cli init examples/filesystem/server.py --all-hosts --out /tmp/hosts-out && ls /tmp/hosts-out | wc -l` prints `9`.
- [ ] `grep -c mcpServers src/lauren_mcp/cli/_commands.py` prints `0`; `grep -c jetbrains src/lauren_mcp/_hosts.py` prints `0`.
- [ ] `python -m lauren_mcp.cli run examples/filesystem/server.py --stdio --host-profile zed` advertises no `resources` in `initialize`; without the flag the response is unchanged.
- [ ] `python -m pytest tests/unit/test_hosts_registry.py tests/unit/test_hosts_emitters.py tests/unit/test_cli_hosts_commands.py tests/unit/test_hosts_docs.py tests/integration/test_cli_hosts_integration.py -q` passes, and `tests/integration/test_cli_commands_integration.py -q` still passes.
- [ ] `git diff --stat src/lauren_mcp/_server/ | wc -l` prints `0`.

---

Drafted from the 2026-11 MCP landscape review (evidence retrieved 2026-11-26). Full PRD, evidence register (`EVIDENCE.md`) and `VERSIONS-MATRIX.md` live in `prds/2026-11-landscape/` on branch `docs/mcp-landscape-2026-11`.
