# PRD — Per-host MCP compatibility profiles

**Status:** Draft
**Date:** 2026-11-26
**Scope:** `lauren-mcp` CLI (`cli/_commands.py`, `cli/__init__.py`), new `src/lauren_mcp/_hosts.py` registry, `docs/guides/host-profiles.md`, `mkdocs.yml`
**Priority:** **P2** — this is tooling and documentation. It changes **no wire behaviour**: no MCP method, no capability default, no transport byte. A server already running behaves identically whether or not this ships. It is P2 rather than P1 because a wrong profile makes a host fail to *launch* the server (loud, one config file, diagnosable), whereas a wrong wire assumption — the P1 class in this set — fails *silently mid-session*. It is not P3 because all ten verified hosts differ structurally in filename, top-level key or transport, and those differences cannot be fixed by prose alone.
**Issue:** (filled in later by the index script)

---

## 1. Problem Statement

### 1.1 `lmcp install` writes one shape; the hosts have ten

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

That is the entire host model: two names, one key, one transport, one body shape.

| Host | What it actually wants | Emitted today |
|---|---|---|
| Claude Desktop | `claude_desktop_config.json`, `mcpServers` | ✅ |
| Cursor | `~/.cursor/mcp.json` \| `.cursor/mcp.json`, `mcpServers` | ✅ |
| Claude Code | `.mcp.json`, `mcpServers` | ❌ unknown client |
| VS Code (Copilot) | `.vscode/mcp.json`, **`servers`**, `"type"` | ❌ unknown client |
| Zed | `settings.json`, **`context_servers`** | ❌ unknown client |
| Devin | `.devin/mcp_config.json`, `mcpServers`, `url` | ❌ unknown client |
| Cline | `cline_mcp_settings.json`, `mcpServers` | ❌ unknown client |
| Continue | `config.yaml` (YAML), `mcpServers` | ❌ unknown client |
| Gemini CLI | `settings.json`, `mcpServers`, **`httpUrl`** | ❌ unknown client |
| ChatGPT | no local file; **Streamable HTTP required, stdio forbidden** | ❌ unknown client |

Filenames, keys and transports are `VERSIONS-MATRIX.md` §6 / `EVIDENCE.md` E-190…E-199. Three
cells are not stylistic corrections but silent failures: VS Code's key is `servers` (E-193), so our
documented block registers **nothing** there; Zed's is `context_servers` (E-195); Gemini CLI spells
the remote URL `httpUrl`, not `url` (E-199). ChatGPT has no file to write at all (E-198).

The docs carry the same bias — one shape, once: `docs/reference/cli.md:70` reads "`install` writes or
merges an `mcpServers` entry for Claude Desktop or Cursor", and `examples/filesystem/README.md:126`
says "Add to your `claude_desktop_config.json`" above a single `mcpServers` block (`:129`).

### 1.2 The server cannot ask what the host cannot do

```python
# src/lauren_mcp/server/_module.py  line 232
        if capabilities is None:
            resolved_caps = ServerCapabilities(
                tools={"listChanged": True} if tools else None,                       # line 234
                resources={"listChanged": True, "subscribe": True} if resources else None,
                prompts={"listChanged": True} if prompts else None,
            )
```

Capabilities follow *registration*, never *who is connected*. A `@resource`-decorated server
advertises `resources/listChanged` and `resources/subscribe` to Zed, which supports Tools and Prompts
only and marks Resources `✗` — the single `✗` in the matrix (E-195). The tool then returns a
`file:///…` pointer the host can never open. On the other axis, an author targeting ChatGPT cannot learn
here that stdio is forbidden (E-198), and one targeting Claude Code cannot learn that tool definitions
are deferred by default (E-191a), instructions are capped at 4,096 chars and deferred descriptions at
16,384 (E-191b), or that output warns at 10,000 tokens and caps at 25,000 (E-191c).

### 1.3 Authors have no degradation contract

With no profile to consult there is no answer to "what do I do instead?": authors either hard-depend
on `@resource` (Zed-dead) or hand-roll an untestable per-host branch inside a tool body. `E-153` adds
pressure — the MCP Apps extension ships a UI payload any proxy must pass through, and a host that
cannot render it needs a fallback nobody has written down.

---

## 2. Goals

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

---

## 3. Non-Goals

- **No host detection.** Nothing sniffs `clientInfo` to guess a profile; the operator always declares
  it. `clientInfo` is self-reported and generic in practice.
- **No capability inflation.** Profiles only ever *remove*; the default stays "advertise what is
  registered" (`_module.py:232-237`).
- **No MCP Apps renderer.** `E-153` motivates only the text-fallback rule in §4.5.
- **No protocol-version negotiation** (that is the P1 sibling PRD) and no fix for the behavioural
  consequences of deferred tool loading — we *report* the limits, we do not re-shape tools.
- **No JetBrains profile.** §4.6.

---

## 4. Design

### 4.1 The registry — `src/lauren_mcp/_hosts.py` (new)

One frozen dataclass, one table, no I/O, no `typer` import, so `server/_module.py` can use it.

```python
# src/lauren_mcp/_hosts.py  (new file)
from __future__ import annotations
from dataclasses import dataclass
from typing import Literal

Transport = Literal["stdio", "streamable-http", "http-sse", "websocket"]


@dataclass(frozen=True, slots=True)
class HostProfile:
    """One agent host, as evidenced by VERSIONS-MATRIX.md §6."""

    id: str                              # "claude-code"
    display_name: str                    # "Claude Code"
    evidence: tuple[str, ...]            # ("E-191",)  — never empty
    config_format: Literal["json", "yaml", "sheet"]
    top_level_key: str | None            # "mcpServers" / "servers" / "context_servers" / None
    config_paths: tuple[str, ...]        # "{project}" / "{home}" / "{appdata}" templates
    transports: frozenset[Transport]
    resources: bool                      # resources/* incl. subscribe
    prompts: bool
    resources_subscribe: bool = False
    ui_payload: Literal["yes", "no", "unknown"] = "unknown"   # E-153 ext-apps
    deferred_tools: bool = False         # E-191a
    instructions_limit: int | None = None
    description_limit: int | None = None
    output_warn_tokens: int | None = None
    output_cap_tokens: int | None = None
    provisional: tuple[str, ...] = ()    # body shapes beyond the evidence matrix (§4.6)
    notes: str = ""


HOST_PROFILES: dict[str, HostProfile] = {
    "claude-code": HostProfile(
        id="claude-code", display_name="Claude Code",
        evidence=("E-191", "E-191a", "E-191b", "E-191c", "E-191d"),
        config_format="json", top_level_key="mcpServers",
        config_paths=("{project}/.mcp.json", "{home}/.claude.json"),
        transports=frozenset({"stdio", "streamable-http", "websocket"}),
        resources=True, prompts=True, resources_subscribe=True, deferred_tools=True,
        instructions_limit=4096, description_limit=16384,          # E-191b
        output_warn_tokens=10000, output_cap_tokens=25000,         # E-191c
        provisional=("remote-block",),                             # §9 Q2
    ),
    # The other nine are the same record with different cells — see the table below.
}
```

The other six, reduced to the fields that differ (all `resources=True, prompts=True`):

| `id` | `top_level_key` | `config_paths` | `transports` | Quirk the emitter honours | Evidence |
|---|---|---|---|---|---|
| `cursor` | `mcpServers` | `{home}/.cursor/mcp.json`, `{project}/.cursor/mcp.json` | stdio, streamable-http, ws | two valid locations; project wins | E-192 |
| `vscode` | **`servers`** | `{project}/.vscode/mcp.json` | stdio, streamable-http | `"type": "stdio"` / `"type": "http"` | E-193 |
| `devin` | `mcpServers` | `{project}/.devin/mcp_config.json`, `…/mcp_config.local.json` | stdio, streamable-http | remote key is `url`; Resources/Prompts **not documented** → degrade | E-194 |
| `cline` | `mcpServers` | `{home}/.cline/data/settings/cline_mcp_settings.json` | stdio, streamable-http | optional `autoApprove` list | E-196 |
| `continue` | `mcpServers` | `{home}/.continue/config.yaml` | stdio, streamable-http | YAML, not JSON | E-197 |
| `gemini-cli` | `mcpServers` | `{home}/.gemini/settings.json` | stdio, streamable-http | remote key is **`httpUrl`** | E-199 |

`devin` is the one asymmetry worth spelling out: the matrix says `not doc'd`, not `✗`. The registry
encodes `resources=False, prompts=False` with `notes="unspecified upstream: treat as unsupported"`.
Degrading something a host might have costs a user a nicer object; advertising something it lacks
strands them with a dead URI. We take the first error.

`evidence` is carried on the record so `lmcp hosts --json` doubles as an evidence map and any row
added without an `E-…` ID fails `tests/unit/test_hosts_registry.py`.

### 4.2 The capability matrix the server can consult

**(a) CLI** — `lmcp hosts` renders the matrix, `--json` dumps `HOST_PROFILES`.

**(b) Server boot flag** — `lmcp run … --host-profile zed` threads a profile id into
`McpServerModule.for_root(..., host_profile="zed")` and applies the only subtractive rule that exists:

```python
# src/lauren_mcp/server/_module.py  line 232 — new
        if capabilities is None:
            p = _resolve_profile(host_profile)          # None when not supplied
            want_res   = resources and (p is None or p.resources)
            want_prom  = prompts   and (p is None or p.prompts)
            want_sub   = p is None or p.resources_subscribe
            resolved_caps = ServerCapabilities(
                tools={"listChanged": True} if tools else None,
                resources=({**{"listChanged": True}, **({"subscribe": True} if want_sub else {})}
                           if want_res else None),
                prompts={"listChanged": True} if want_prom else None,
            )
```

`host_profile=None` — the default every existing caller passes — reproduces today's expression
exactly. That is the whole compatibility argument for the server half.

**(c) Python API** for authors branching at import time: `hosts.get("zed")` (raises `KeyError`,
never guesses), `hosts.ids()`, `hosts.matrix()`.

### 4.3 Per-host emitters — exact files and keys

One emitter, `render(profile, spec, transport) -> Emitted(path, top_level_key, document, fmt)`.
Bodies below are the emitter's output, verbatim.

**`claude-desktop`, `cursor`, `claude-code`, `cline`, `gemini-cli` — `mcpServers` + stdio** (different
filename only):

```json
{
  "mcpServers": {
    "filesystem": {
      "command": "/usr/bin/python3",
      "args": ["-m", "lauren_mcp.cli", "run", "/abs/path/examples/filesystem/server.py", "--stdio"],
      "env": {"MCP_FS_ROOT": "/tmp/sandbox"}
    }
  }
}
```

`cline` additionally accepts, only under `--auto-approve`, `"autoApprove": ["read_file"]` (§9 Q6).

**`vscode` — `servers`:**

```json
{"servers": {"filesystem": {"type": "stdio",
  "command": "/usr/bin/python3",
  "args": ["-m", "lauren_mcp.cli", "run", "/abs/path/server.py", "--stdio"]}}}
```

**`zed` — `context_servers`** (merge into the existing settings document; refuse to write if it
exists and does not parse; `--force` is the only override and appears in no happy path):

```json
{"context_servers": {"filesystem": {"source": "custom",
  "command": "/usr/bin/python3",
  "args": ["-m", "lauren_mcp.cli", "run", "/abs/path/server.py", "--stdio"],
  "env": {}}}}
```

**Remote blocks differ by host — this is the whole point of the registry:**

| Host | Transport flag | Emitted body |
|---|---|---|
| `gemini-cli` | `--transport http` | `{"mcpServers": {"filesystem": {"httpUrl": "http://127.0.0.1:8000/mcp"}}}` (E-199) |
| `devin` | `--transport http` | `{"mcpServers": {"filesystem": {"url": "http://127.0.0.1:8000/mcp"}}}` (E-194) |
| `vscode` | `--transport http` | `{"servers": {"filesystem": {"type": "http", "url": …}}}` (E-193) |
| `claude-code` | `--transport http` | `mcpServers` + `type`/`url` — **provisional** (§9 Q2) |

**`continue` — `config.yaml`, YAML not JSON:** `mcpServers:` as a list of `{name, command, args,
env}` entries. The key is evidenced (E-197); the list body shape is not, hence
`provisional=("body",)`.

**`chatgpt` — a sheet, not a file** (`config_format="sheet"`, `top_level_key=None`): the emitter
prints the three evidenced facts a user must act on — deploy over **Streamable HTTP** because stdio is
forbidden (E-198), present `/mcp` for host-side connector registration, expect OAuth (our
`.well-known/oauth-authorization-server` is already served) — and states that Resources and Prompts
are unavailable (E-198), so tools must not depend on them. There is no local file to write.

`--out` refuses to write a `sheet`; that is why `--all-hosts` yields nine files for ten profiles.

### 4.4 CLI surface

```
lmcp hosts [--json] [--include-unverified]
lmcp init FILE_SPEC [--host PROFILE | --all-hosts]
                      [--transport stdio|http] [--name NAME]
                      [--print] [--out DIR] [--allow-unverified] [--force]
lmcp install FILE_SPEC [--client claude|cursor]      # unchanged, now a thin alias
```

- `lmcp hosts` — id, display name, config file, key, transports, R/P, evidence; one footnote:
  `jetbrains — no profile: evidence marked [U] (E-199b)`.
- `lmcp init --host claude-code` — writes/merges the file, prints the path, then one line per
  suppressed capability (`note: claude-code defers tool definitions by default (E-191a)`).
- `lmcp init --all-hosts --out DIR` — per-profile trees (`DIR/vscode/.vscode/mcp.json`,
  `DIR/zed/.zed/settings.json`, …) copyable over a repo root, plus `DIR/chatgpt.md`.
- `lmcp install` keeps its signature (`--client claude` → `--host claude-desktop`, `--client cursor`
  → `--host cursor`) and writes byte-identical files, so
  `tests/integration/test_cli_commands_integration.py:322` keeps passing.

The `--host` collision is documented, not hidden: `lmcp run --host` is a **bind address**
(`_commands.py:27`), `lmcp init --host` is a **profile id** — different verbs, disjoint value spaces.
§9 Q1 records the alternative.

### 4.5 Degradation guidance for tool authors

| Feature the host lacks | Symptom if depended on | Required fallback |
|---|---|---|
| `resources/*` (Zed, ChatGPT, Devin-as-unspecified) | host never lists or reads the URI; a tool returning `{"uri": …}` hands over a dead pointer | return the bytes **inline**; add a twin `@tool read_<resource>` wrapping `resources/read` |
| `resources/subscribe` | no `notifications/resources/updated`; the model waits forever | return a snapshot per call; a re-invoke is the only portable poll |
| `prompts/*` (ChatGPT) | prompt never appears in the host UI | mirror every `@prompt` as a zero-arg `@tool` with the same name and template |
| server-driven UI (`E-153`) | host renders nothing, call looks empty | always put a text rendering in the same result; never make the UI payload the only content |
| deferred tool definitions (Claude Code, E-191a) | tool discoverable but never chosen | self-sufficient first ~200 chars, ≤16,384 total (E-191b); server instructions ≤4,096 (E-191b) |
| 25,000-token output cap (E-191c) | result truncated near the cap | paginate at the tool boundary: handle + `next` argument, not one payload |
| `stdio` (ChatGPT, E-198) | connection never establishes | nothing to degrade in-process; the operator deploys Streamable HTTP — §4.3's sheet is the artefact |

New page `docs/guides/host-profiles.md` (nav at `mkdocs.yml:99`) carries this table and the host
sheets; `examples/filesystem/README.md:126` loses its single-host framing and links here.

### 4.6 Why `jetbrains` is excluded, and what `provisional` is for

`E-199b` is marked `[U]`: no filename, no key, no transport, no capability column — only a link to
JetBrains' own page. Emitting a profile would mean inventing the three fields this PRD exists to get
right, and a wrong guess is *worse* than none because `lmcp init --host jetbrains` looks
authoritative. So: no entry in `HOST_PROFILES`, no row in `lmcp hosts` (one footnote), and a test
that greps the string out of `_hosts.py`. Adding it later is five lines plus flipping `[U]` → `[P]`
in `EVIDENCE.md`.

`provisional` is the same discipline at smaller scale: `continue` (body shape), `zed` (body shape) and
`claude-code` (remote keys) are evidenced for *key* and *capability*, not for *body*, so the emitter
prints the block, flags the unwarranted part, and writes nothing without `--allow-unverified`.

---

## 5. CLI-side Changes

New `src/lauren_mcp/_hosts.py` (registry, `render()`, `merge()`, `sheets()` — no `typer`); new
`src/lauren_mcp/cli/_hosts_commands.py` (`hosts()`, `init_cmd()`, same `Annotated[... typer.Option]`
style as `cli/_commands.py`); both registered in `cli/__init__.py`; `_get_config_path` /
`_write_mcp_config` delegated so exactly one place knows a host's key; `host_profile: str | None =
None` added to `for_root` with `--host-profile` on `run`/`dev`; docs updated (§6 rows 12-14). No change
under `src/lauren_mcp/_server/`, asserted in §2.

---

## 6. Exact Lines to Change

| # | File:line | Change |
|---|---|---|
| 1 | `src/lauren_mcp/cli/_commands.py:283` | delegate to `_hosts.path_for(profile, scope)`; keep as legacy shim | |
| 2 | `src/lauren_mcp/cli/_commands.py:288` | map to profile `claude-desktop` | |
| 3 | `src/lauren_mcp/cli/_commands.py:298` | map to profile `cursor` | |
| 4 | `src/lauren_mcp/cli/_commands.py:307` | error text generated from the registry | |
| 5 | `src/lauren_mcp/cli/_commands.py:311` | `def _write_mcp_config(path, profile, document)`, merge logic unchanged | |
| 6 | `src/lauren_mcp/cli/_commands.py:326` | `setdefault(profile.top_level_key, {})` | |
| 7 | `src/lauren_mcp/cli/_commands.py:329-331` | `_hosts.stdio_block(spec)` so Zed/VS Code variants share one source | |
| 8 | `src/lauren_mcp/cli/_commands.py:26` | unchanged; add sibling `--host-profile` | |
| 9 | `src/lauren_mcp/cli/__init__.py:22` | add `app.command("hosts")(hosts)` and `app.command("init")(init_cmd)` after it | |
| 10 | `src/lauren_mcp/server/_module.py:232-237` | apply `p.resources` / `p.prompts` / `p.resources_subscribe` when a profile is supplied | |
| 11 | `src/lauren_mcp/server/_module.py:65` | unchanged; `host_profile` added as a sibling kwarg | |
| 12 | `docs/reference/cli.md:70` | ten-host matrix pointer + legacy aliases | |
| 13 | `examples/filesystem/README.md:126` | `lmcp init examples/filesystem/server.py --host <host>` + link | |
| 14 | `mkdocs.yml:98` | insert `    - Agent Host Profiles: guides/host-profiles.md` before line 99 (`  - API Reference:`) | |

---

## 7. Backward Compatibility

**`lmcp install` users.** Byte-identical output: same filename, `mcpServers` key, `command`/`args`,
merge-not-overwrite, 2-space `json.dumps`, so home-directory diffs stay empty. Only the
unknown-`--client` message grows the ten profile ids.

**Servers.** `for_root` gains a keyword-only parameter defaulting to `None`; with `None` the
capability expression at `_module.py:232-237` is textually the same as today, so no `initialize`
response changes, including the advertised `resources/subscribe`. **Clients** untouched.

**Migration notes.** Nothing to migrate; new verbs are additive and `install` remains.
`--host-profile` is a per-deployment choice, not per-client negotiation — one process serves one
profile, so a multi-host deployment starts two processes (§10). Users who hand-copied
`examples/filesystem/README.md:129` into VS Code or Zed now get a working command.

---

## 8. Test Plan

**Unit — `tests/unit/test_hosts_registry.py`.** Ten ids in stable order; every `evidence` matches
`^E-\d+[a-d]?$`; every `json` profile has a `top_level_key` and every `sheet` profile empty
`config_paths`; `"jetbrains"` absent from both `HOST_PROFILES` and the module source; one assertion
per cell this PRD fixes (`zed.resources is False`, `zed.top_level_key == "context_servers"`,
`vscode.top_level_key == "servers"`, `chatgpt.transports == {"streamable-http"}`, `claude-code` limits
`4096/16384/10000/25000`); `claude-desktop` templates reproduce `_commands.py:288-297` for
Darwin/Linux/Windows.

**Unit — `tests/unit/test_hosts_emitters.py`.** `render(vscode, …)` has `servers` and no
`mcpServers`; `render(zed, …)` has `context_servers` and a pre-existing `{"theme": "One Dark"}`
survives the merge; `render(gemini-cli, …, "http")` body keys `== {"httpUrl"}` while
`render(devin, …, "http")` has `url`; `render(chatgpt, …)` returns `sheet` and `write()` raises
`UnsupportedHost`; provisional profiles raise without `--allow-unverified` and warn with it;
`render(continue, …)` YAML `safe_load`s (skipped if PyYAML absent); `stdio_block()` bytes equal
today's `_commands.py:329-331` output for `claude-desktop` and `cursor`.

**Unit — `tests/unit/test_cli_hosts_commands.py`.** `CliRunner`: `hosts` prints ten rows; `--json`
round-trips; `--print` writes nothing; `--all-hosts --out` creates nine files plus `chatgpt.md`;
`init --host nope` exits 1 listing valid ids.

**Unit — `tests/unit/test_hosts_docs.py`.** Every fenced block in `docs/guides/host-profiles.md` parses.

**Integration — `tests/integration/test_cli_hosts_integration.py`.** `init --host vscode` into a temp
root, then `json.load` asserting `servers["filesystem"]["type"] == "stdio"`; start `run … --stdio
--host-profile zed`, send `initialize`, assert the result has **no** `resources` key, then repeat
without the flag and assert `resources["subscribe"] is True` — the only wire-touching test, and it
asserts absence, never a new shape; `install --client claude` still satisfies
`test_cli_commands_integration.py:322`.

---

## 9. Open Questions

- **Q1 — flag name.** `init --host` collides conceptually with `run --host` (bind address,
  `_commands.py:27`); `--profile` on both verbs is the alternative.
- **Q2 — `claude-code` remote keys.** Streamable HTTP support is verified (`✓ (+ ws)`) but the JSON
  keys are not, so that block stays provisional until checked against `code.claude.com/docs/en/mcp`.
- **Q3 — Zed body shape.** Key and no-Resources rule are evidenced (E-195); `source: "custom"` is not
  — check `zed.dev/docs/ai/mcp.md` before dropping `provisional`.
- **Q4 — YAML without a dependency.** `continue` needs YAML; `lauren-mcp-inventory.md` §1 keeps
  runtime deps minimal, so a hand-rendered ~12-line emitter, PyYAML test-only.
- **Q5 — non-Desktop OS paths.** Only `claude-desktop` has platform-verified paths
  (`_commands.py:288-297`); the rest are `$HOME`-relative everywhere — confirm before documenting.
- **Q6 — pre-populate host filters?** Gemini's `toolFilter` (E-199) and Cline's `autoApprove` (E-196)
  *can* be filled by us; default **no** — we do not grant approvals for a user.
- **Q7 — does `--host-profile` belong in P2?** It is subtractive and cheap, but adds a
  per-deployment switch; registry + emitters + docs could ship alone.

---

## 10. lauren-mcp Advantages

**One binary, one server class, every host profile.** `lauren-mcp` speaks stdio
(`lmcp run --stdio`), WebSocket (default), legacy HTTP+SSE and Streamable HTTP from one
dependency-free Python package — `_research/lauren-mcp-inventory.md:105-107`, against
`_TRANSPORTS = ("ws", "sse", "streamable", "both", "all")` at `src/lauren_mcp/server/_module.py:55`:

> **This is a genuine strength:** the repo is one of very few MCP implementations
> with native WebSocket, and it can mount three transports from a single class.

That is why this PRD is small: the transports already exist, so a profile is only a filename, a key
and a block. Eight of the ten verified hosts reach one process started as

```bash
lmcp run server.py --transport all --port 8000      # ws + streamable-http
```

and the stdio-only spawn cases (Claude Desktop, Continue, Cline, Zed, VS Code stdio, Gemini local)
are the same binary spawning itself (`python -m lauren_mcp.cli run server.py --stdio`). No Node shim,
no second server implementation, no per-host fork.

**Honest caveat, because it shapes `--all-hosts`:** `"all"` is WebSocket + Streamable HTTP, not
everything — the docstring at `src/lauren_mcp/server/_module.py:88-90` says legacy HTTP+SSE and
Streamable HTTP "share the `POST /` route, so the [...] cannot be mounted together on one path". So
one *bind* serves ws + Streamable HTTP; the `2024-11-05` HTTP+SSE era needs `--transport both` in a
second process. No profile in the current ten requires HTTP+SSE, so this costs nothing today — but
`lmcp hosts` will say so rather than pretend one process covers all four eras.

**Behind, stated once:** there is no per-host metadata today (this PRD), and the `E-153` ext-apps
payload is passed through but never rendered, so UI experiences degrade to text — §4.5 makes that
fallback mandatory instead of accidental.

---

## 11. References

**Evidence rows** — `prds/2026-11-landscape/EVIDENCE.md`; each row there carries its source URL. The
four load-bearing ones are `code.claude.com/docs/en/mcp` (E-191…d), `zed.dev/docs/ai/mcp.md`
(E-195), `developers.openai.com/plugins/build/mcp-server.md` (E-198) and the Gemini CLI
tools/mcp-server doc (E-199).

| ID | Subject | Line |
|---|---|---|
| E-153 | MCP Apps SDK; UI payload any proxy must pass through | 263 |
| E-190 | Claude Desktop — `claude_desktop_config.json`, `mcpServers` | 346 |
| E-191…d | Claude Code — `.mcp.json`, deferred tools, 4,096/16,384 chars, 10,000/25,000 tokens | 347, 367-370 |
| E-192 | Cursor — `~/.cursor/mcp.json`, `mcpServers` | 349 |
| E-193 | VS Code — `.vscode/mcp.json`, **`servers`**, `"type": "http"` | 350 |
| E-194 | Devin — `.devin/mcp_config.json`, `command`/`url`, R/P undocumented | 351 |
| E-195 | Zed — `settings.json`, **`context_servers`**, Resources ✗ | 352 |
| E-196 | Cline — `cline_mcp_settings.json`, `autoApprove` | 353 |
| E-197 | Continue — `config.yaml`, `mcpServers` | 354 |
| E-198 | ChatGPT — stdio ✗, Streamable HTTP required, OAuth, Resources ✗, Prompts ✗ | 355 |
| E-199 | Gemini CLI — `settings.json`, `mcpServers`, `httpUrl` | 356 |
| E-199b | JetBrains — **[U]**, excluded (§4.6) | 357 |

**Research and repo anchors:** `VERSIONS-MATRIX.md` §6 (163-177) and §6.1 (179-193);
`_research/lauren-mcp-inventory.md` §3 (76-110) and §1; `_research/PRD-BRIEF.md`;
`src/lauren_mcp/cli/_commands.py:26-30, 185-196, 283-341`; `src/lauren_mcp/cli/__init__.py:18-22`;
`src/lauren_mcp/server/_module.py:55, 65, 84-90, 232-237`; `docs/reference/cli.md:68-82`;
`examples/filesystem/README.md:121-133`; `mkdocs.yml:85-99`;
`tests/integration/test_cli_commands_integration.py:322-323`.
