# PRD — Publishing to the official MCP Registry

**Status:** Draft
**Date:** 2026-11-26
**Scope:** `src/lauren_mcp/cli/` (`__init__.py`, new `_registry.py`), `src/lauren_mcp/server/` (new `_manifest.py`), `pyproject.toml`
**Priority:** P2
**Issue:** [#77](https://github.com/lauren-framework/lauren-mcp/issues/77)

---

## 1. Problem Statement

The MCP Registry is no longer a preview curiosity. At build `2026-11-23T13:54:44Z` the service is at
**1.8.16** (E-120), its listing endpoint reports **≥ 20,000 server records** (E-121), and reads are
**unauthenticated and read-only** for consumers (E-122), so anything published is immediately
discoverable by every scanning client. Third-party directories are the same order of magnitude —
Glama 131,130 entries, mcp.so 20,915, Smithery folded into Arcade (E-129) — and they all consume the
same `server.json` shape.

Publishing is *possible* for a `lauren-mcp` server today, but only by hand — `grep -rn
"server.json" src/ pyproject.toml` matches nothing, so nothing here knows what a `server.json` is.
Meanwhile the thing the registry wants described in JSON is already fully described in Python. A
`@mcp_server("/mcp", transport="streamable")` class (`src/lauren_mcp/server/_decorators.py:736`,
`:743`) is collected by `McpServerModule.for_root(...)` (`src/lauren_mcp/server/_module.py:58`, `:62`)
into concrete metadata — `tools`, `resources`, `prompts`, `completions`, `lifespan_meta`
(`src/lauren_mcp/server/_module.py:160-164`) — and each tool already carries `name`, `description`
and `title` from the decorator (`src/lauren_mcp/server/_decorators.py:758-763`) into `McpToolMeta`
(`src/lauren_mcp/server/_meta.py:45-50`). The registry manifest is therefore a *serialisation*
problem, not an authorship problem, and today we ask the user to solve it by hand.

### 1.1 Failure scenario — a correct server registered as a broken record

A team ships `acme-weather-mcp`, writes `server.json` by hand, and gets four things wrong that no
local test catches because only the registry ever reads the file:

1. **Name shape.** They write `"name": "acme-weather"`. Schema revision `2025-12-11` requires a
   reverse-DNS `name` with **exactly one slash** (E-123), so the publish is rejected after the
   release is already tagged.
2. **Version drift.** `pyproject.toml` declares `dynamic = ["version"]` (`pyproject.toml:7`) and the
   real version comes from VCS at build time. Their hand-typed `"1.0.0"` is stale on the next tag —
   and registry versions are **immutable**, with `isLatest` marking the current one (E-127). A stale
   version is not a typo you can edit away; it is a permanent orphan record.
3. **Wrong transport class.** The server is remote-only, served by `uvicorn` behind the
   `@mcp_server` path (`src/lauren_mcp/cli/_commands.py:240-241`), but they copied a `packages[]`
   example. The registry accepts `remotes[]` with no package for remote-only servers (E-124) and
   *also* accepts `packages[]`, so the record publishes while pointing clients at a stdio package
   that does not exist on PyPI. Nothing fails loudly; clients simply cannot connect.
4. **Secrets leaked into public metadata.** The server needs `ACME_API_KEY`; they write
   `{"name": "ACME_API_KEY", "value": "sk-live-…"}`. `isSecret` exists so the value is not rendered
   (E-123). Unset, the key is now part of a public, immutable record.

Each is a derivation the framework could have done: the path is in the decorator, the transport in
`for_root`, the version in package metadata, the env contract in the code.

### 1.2 Secondary problem — ownership claims fail silently until publish time

A record is only useful if it is *yours*. Ownership is proven through `mcp-publisher` using `dns`,
`http`, `github`, `github-oidc`, `github-at` or `anonymous` (E-125), and package ownership is claimed
separately through metadata keys: `mcpName` in `package.json` for npm, an `mcp-name:` line in the
PyPI README for Python (E-126). The Python marker lives in `README.md`, usually written long before
anyone thinks about the registry. A user who publishes a valid `server.json`, then discovers the
package cannot be claimed, must add the marker, cut a release and publish a *new immutable version*
(E-127) to attach it. `lmcp registry validate` should check the marker locally — offline, cheap,
turning a failed publish into a failing pre-commit hook.

### 1.3 What already exists that we must not duplicate

`lmcp` is a Typer app with five commands registered by direct `app.command(...)` calls
(`src/lauren_mcp/cli/__init__.py:10`, `:18-22`), implementations in
`src/lauren_mcp/cli/_commands.py` (`run` `:24`, `dev` `:49`, `inspect_cmd` `:71`, `call` `:119`,
`install` `:185`), and one shared file-spec resolver `resolve_server_class(spec)`
(`src/lauren_mcp/cli/_resolve.py:19`, documented `:3-5`). It ships behind the existing `cli` extra
(`pyproject.toml:32`, `:38-42`).

Hence the single most important constraint of this PRD: **the registry commands are two more
`app.command(...)` registrations in that app, reusing `resolve_server_class`. No second console
script, no `python -m` entry point, no shell wrapper** (E-224).

## 2. Goals

1. `lmcp registry-init app.py:WeatherServer --name com.acme/weather --out server.json` writes a
   `server.json` conforming to schema revision `2025-12-11` (E-123), derived from the imported server
   class rather than user-typed JSON.
2. Derived, not authored: description from the server class docstring, per-tool titles from
   `@mcp_tool(title=...)` (`src/lauren_mcp/server/_decorators.py:762`), version from installed
   package metadata (`pyproject.toml:7`).
3. Emits `remotes[]` for Streamable HTTP and `packages[]` for stdio, never both by accident, and
   refuses the combination that would advertise a non-existent package (E-124).
4. Env config declared via repeatable `--env KEY` / `--env-secret KEY` lands in the manifest with
   `isSecret: true` for secrets, so a secret value can never be inlined (E-123).
5. `lmcp registry-validate server.json` exits `0`/`1` with per-field diagnostics; `--check-pypi`
   additionally verifies the `mcp-name:` marker (E-126) before publish, not after.
6. `--dry-run` on both commands prints the manifest and the corresponding `mcp-publisher` command and
   writes nothing, so it is safe in CI.
7. A reverse-DNS name is *derived* when `--name` is omitted — from `[project.urls]`
   (`pyproject.toml:50-51`) for GitHub-hosted projects, yielding `io.github.<owner>/<repo>` — and
   ambiguous cases fail loudly instead of guessing.
8. Zero new runtime dependencies: `json`, `dataclasses`, `importlib.metadata` only; the `cli` extra
   (`pyproject.toml:38-42`) is unchanged, so the two-dependency posture holds (E-222).
9. Docs in `llms-full.txt`/`README.md` covering the six ownership methods (E-125) and the
   immutable-version rule (E-127).

## 3. Non-Goals

- **No publishing, no ownership verification.** Library code never calls
  `registry.modelcontextprotocol.io` (publishing stays with `mcp-publisher`, so no credentials live in
  a framework module, E-222), and there are no DNS TXT lookups, OIDC device flows or token stores
  (E-125): we validate the *inputs* and print the command.
- **No third-party directory sync.** Glama/mcp.so/Smithery ingestion (E-129) is out of scope.
- **No vendored schema.** No `server.schema.json` in the wheel; validation is structural in code, and
  the authoritative check is the network-gated test against the `2025-12-11` schema URL (§8.2).
- **No registry reads.** `isLatest` bookkeeping is server-side (E-127); the CLI never calls the
  consumer API (E-122).
- **No `README.md` rewriting.** `validate` reports a missing marker and prints the exact line.
- **No package types we cannot inspect** beyond passing `npm`/`pypi` `registryType` through verbatim.

## lauren-mcp Advantages

This is a small capability here because the manifest is **already in memory**. Inventory §6.1
(`prds/2026-11-landscape/_research/lauren-mcp-inventory.md:221`) records the decorator surface, and
that surface fully describes a server: `mcp_tool` takes `name`, `description`, `title` and
`annotations` (`src/lauren_mcp/server/_decorators.py:758-763`) and materialises them into
`McpToolMeta` with `name`/`description` fields (`src/lauren_mcp/server/_meta.py:45-50`); `for_root`
then walks the class and collects `tools`, `resources`, `prompts`, `completions` and `lifespan_meta`
(`src/lauren_mcp/server/_module.py:160-164`).

So a `lauren-mcp` author maintains **one** source of truth: no second place to forget, and no drift
between what the registry advertises and what the server serves, because both come from the same
decorated class. Where the manifest is a separate JSON file, entry and code diverge the first time a
tool is renamed; here `init` re-derives the file and `validate` proves in CI that the checked-in
`server.json` still matches the code.

Three supporting assets make it cheap:

- **Shared resolution exists.** `resolve_server_class` (`src/lauren_mcp/cli/_resolve.py:19`) imports a
  module by path and returns the `@mcp_server` class, with a `_die` helper (`:80`) for uniform
  errors, so `app.py:WeatherServer` means the same thing to `lmcp run`, `lmcp inspect` and
  `lmcp registry-init`.
- **Transport intent is declarative.** `@mcp_server(path=..., transport=...)`
  (`src/lauren_mcp/server/_decorators.py:736`) and `for_root(transport=...)`
  (`src/lauren_mcp/server/_module.py:62`, `:65`; `_TRANSPORTS` at `:55` includes `"streamable"`)
  already encode the `remotes[]`-versus-`packages[]` decision (E-124) that hand-written manifests get
  wrong.
- **The dependency posture survives.** Two runtime dependencies — `lauren`, `anyio` (E-222) — and a
  CLI extra already installed for anyone using `lmcp` (`pyproject.toml:38-42`): we add files, not deps.

A naive "just use the official SDK's schema types" approach would pull a validator tree into runtime
and still not know the transport, the tool inventory or the version — the three fields that actually
break publishes (§1.1).

## 4. Design

### 4.1 Two commands on the existing app

`src/lauren_mcp/cli/__init__.py:18-22` registers commands as `app.command("name")(fn)`; the registry
commands follow that shape, in a new module so `_commands.py` does not grow past its current 341
lines:

```python
# src/lauren_mcp/cli/__init__.py  (append after line 22)
from ._registry import init as registry_init, validate as registry_validate

app.command("registry-init")(registry_init)
app.command("registry-validate")(registry_validate)
```

A Typer sub-app (`add_typer(..., name="registry")`) is deliberately **not** used: the five existing
commands are flat, and flat keeps shell completion, `--help` text and error formatting identical to
`lmcp install`. Whether the spelling becomes `lmcp registry init` is Open Question 1.

### 4.2 What is derived from what

The generator is a pure function of the imported class plus explicit flags:

| `server.json` field | Source in this repo | Verified at |
|---|---|---|
| `name` | `--name`, else derived from `[project.urls]` Homepage | `pyproject.toml:50-51` |
| `description` | server class docstring, first paragraph, one line | `src/lauren_mcp/server/_decorators.py:736` |
| `version` | `importlib.metadata.version(...)` (VCS-derived project version) | `pyproject.toml:7` |
| `remotes[0].url` | `--url` + decorator mount path | `src/lauren_mcp/server/_decorators.py:743` |
| `remotes[0].type` | `--transport` (`streamable`, `sse`) | `src/lauren_mcp/server/_module.py:55` |
| `packages[0]` | `--package-identifier` (default: project name, `pyproject.toml:6`), transport `"stdio"` under `--stdio` (`src/lauren_mcp/server/_module.py:65`) | `pyproject.toml:6` |
| `env[]` entries | repeatable `--env` / `--env-secret` | new |

### 4.3 Reverse-DNS naming — exactly one slash

The schema requires reverse-DNS with **exactly one slash** (E-123). The generator enforces it before
writing anything, and derives a candidate when `--name` is absent:

```python
# src/lauren_mcp/server/_manifest.py
import re
from urllib.parse import urlparse

_NAME_RE = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?/[a-zA-Z0-9._-]+$")
_GITHUB_HOSTS = {"github.com", "www.github.com"}

#: `remotes[].type` values accepted by schema revision 2025-12-11 (E-123).
_REMOTE_TYPES = {"streamable": "streamable-http", "sse": "sse"}


class ManifestError(ValueError):
    """Raised when derived or supplied metadata cannot form a valid record."""


def check_name(name: str) -> str:
    """Validate a reverse-DNS server name; never silently repairs it."""
    if name.count("/") != 1:
        raise ManifestError(
            f"server name {name!r} must contain exactly one '/' "
            f"(namespace + '/' + server), e.g. 'io.github.acme/weather'"
        )
    if not _NAME_RE.match(name):
        raise ManifestError(f"server name {name!r} contains invalid characters")
    return name


def derive_name(homepage: str | None, namespace: str | None = None) -> str:
    """Derive ``io.github.<owner>/<repo>``; a wrong name is an immutable artefact (E-127)."""
    if homepage is None:
        raise ManifestError("cannot derive a name without a project URL; pass --name")
    parsed = urlparse(homepage)
    parts = [p for p in parsed.path.split("/") if p]
    if parsed.netloc in _GITHUB_HOSTS and len(parts) >= 2:
        return check_name(f"io.github.{parts[0]}/{parts[1].removesuffix('.git')}")
    if namespace:  # caller-supplied namespace, verifiable by dns/http (E-125)
        return check_name(f"{namespace}/{parts[-1].removesuffix('.git') if parts else 'server'}")
    raise ManifestError(
        f"cannot derive a reverse-DNS name from {homepage!r}; pass --name "
        f"<namespace>/<server> with a namespace you control (E-125)"
    )
```

For this repository that resolves to `io.github.lauren-framework/lauren-mcp`, since
`pyproject.toml:51` declares `Homepage = "https://github.com/lauren-framework/lauren-mcp"` — a
namespace claimable through the `github` method (E-125) with no DNS work. The rule bites when a team
wants `com.acme/weather`: that namespace needs the `dns` method and a TXT record on `acme.com`, so
`derive_name` refuses to invent it.

### 4.4 `remotes[]` for Streamable HTTP, `packages[]` for stdio

The two arrays describe different distribution stories, and the registry supports either — including
remote-only servers with no package (E-124). The choice is a total function:

```python
def _remotes(url, transport, mount_path):
    if url is None:
        return []
    remote_type = _REMOTE_TYPES.get(transport)     # {"streamable": "streamable-http", "sse": "sse"}
    if remote_type is None:
        raise ManifestError(f"{transport!r} is not a remote transport; pass --stdio instead")
    if not url.rstrip("/").endswith(mount_path):
        url = url.rstrip("/") + mount_path          # decorator mount path, _decorators.py:743
    return [{"type": remote_type, "url": url}]


def _packages(stdio, package_type, identifier, version):
    if not stdio:
        return []
    return [{"registryType": package_type, "identifier": identifier,
             "version": version, "transport": {"type": "stdio"}}]
```

Rules the CLI adds: `--stdio` with `--url` is rejected unless `--both`, because a record advertising
both must be deliberate (publishing `packages[]` for a package that does not exist is the silent
failure of §1.1(3)); `--package-identifier` defaults to the distribution name of the project being
generated, so `name = "lauren-mcp"` (`pyproject.toml:6`) is never hard-coded into a user's manifest.

### 4.5 `isSecret` for env-var-driven config

Env files already have a path in this repo: `lmcp dev`/`lmcp run` load `.env` through `_load_env`
(`src/lauren_mcp/cli/_commands.py:203`). Registry metadata is the one place where those names become
public, so every entry is *declared*, never discovered:

```bash
lmcp registry-init app.py:WeatherServer --url https://weather.acme.com/mcp \
  --env ACME_LOG_LEVEL --env-secret ACME_API_KEY --out server.json
```

```json
{
  "env": [
    {"name": "ACME_LOG_LEVEL", "isRequired": false},
    {"name": "ACME_API_KEY", "isRequired": true, "isSecret": true}
  ]
}
```

`isSecret: true` tells the registry not to render the value (E-123). Two guards: `--env-secret` never
accepts a value (`KEY=value` is rejected with a pointer to `.env`), and validation errors on any
`isSecret` entry that carries `value`. A key matching `(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)` with
`isSecret` unset is a *warning*, promoted to an error under `--strict`, because the name heuristic is
not authoritative.

### 4.6 `validate` and the dry-run path

`lmcp registry-validate server.json` is offline and structural — no dependency, no network:
`validate` checks, in order: JSON parses to an object; `name`, `description`, `version` present
(E-123); `check_name` passes (§4.3); `remotes[]`/`packages[]` contain at least one non-empty array,
`remotes[].type` ∈ `{"streamable-http", "sse"}`, `packages[].transport.type == "stdio"`, and the two
are never mixed; `env[]` names are unique and match `^[A-Z][A-Z0-9_]*$`, with no `value` on an
`isSecret` entry; `version` equals the installed distribution version when validating a checkout
(warning by default, error under `--strict`, catching §1.1(2) drift); and, under `--check-pypi`,
`README.md` matches `^mcp-name:\s*<name>$` for the manifest name (E-126), else exit 1 with the exact
line to add.

Exit codes are the CI contract: `0` clean (warnings allowed), `1` any error. `--dry-run` applies to
both commands and prints (a) the manifest, (b) the `mcp-publisher` invocation it corresponds to — and
nothing else on stderr, so it can be diffed in tests without touching the filesystem.

## 5. Server-side Changes

Two new modules, one new user-facing file, zero edits to existing logic.

### 5.1 `src/lauren_mcp/server/_manifest.py` (new, ~230 lines)

Owns derivation and validation and knows nothing about Typer:

```python
def build_manifest(server_cls: type, *, opts: ManifestOptions) -> dict[str, Any]:
    """Build a schema-2025-12-11 server.json body from a decorated class."""
```

It reads what the runtime already uses — `MCP_SERVER_META` (imported at
`src/lauren_mcp/server/_module.py:44`) for mount path and transport, plus the per-tool metadata
`for_root` collects (`:160-164`) — but never builds an app, never touches `lauren`'s DI container and
never binds a socket. The description's tool summary is the tool count plus the first three
`McpToolMeta.title` values (`src/lauren_mcp/server/_meta.py:45-50`).

### 5.2 `src/lauren_mcp/cli/_registry.py` (new, ~140 lines)

A thin Typer layer mirroring the existing command shape (`run` at `src/lauren_mcp/cli/_commands.py:24`,
`install` at `:185`):

Both commands are plain `def` functions with `typer.Argument`/`typer.Option` parameters:
`init(file_spec, --name, --url, --transport, --stdio, --both, --env, --env-secret, --out, --dry-run)`
and `validate(path, --strict, --check-pypi, --dry-run)`.

`init` calls `resolve_server_class(file_spec)` (`src/lauren_mcp/cli/_resolve.py:19`) — identical
semantics and, via `_die` (`:80`), identical failure messages — then `build_manifest`, then writes
`--out` unless `--dry-run`. `validate` never imports user code.

### 5.3 `src/lauren_mcp/cli/__init__.py` — two registrations

Append the two `app.command(...)` calls after the existing registrations
(`src/lauren_mcp/cli/__init__.py:18-22`). The app object (`:10`) and docstring (`:1-4`) are untouched.

### 5.4 `pyproject.toml` — no dependency change

The only edit is a comment above `[project.optional-dependencies]` (`pyproject.toml:32`) noting that
both commands ship with the `cli` extra (`:38-42`) and need nothing new. Real JSON-Schema validation
at runtime, if ever wanted, goes in a new `registry` extra following the existing pattern
(`pyproject.toml:33-37`) — explicitly not in this PRD.

## 6. Exact Lines to Change

| # | Path:line | Change |
|---|---|---|
| 1 | `src/lauren_mcp/cli/__init__.py:22` | After `app.command("install")(install)`, import `_registry` and register `registry-init` / `registry-validate` (§4.1). |
| 2 | `src/lauren_mcp/cli/_registry.py` (new) | Typer commands `init`/`validate`, reusing `resolve_server_class` and `_die`. |
| 3 | `src/lauren_mcp/server/_manifest.py` (new) | `ManifestOptions`, `ManifestError`, `check_name`, `derive_name`, `_remotes`, `_packages`, `build_manifest`, `validate_manifest`. |
| 4 | `src/lauren_mcp/server/__init__.py` | Export `build_manifest` and `ManifestOptions` next to the existing public names. |
| 5 | `pyproject.toml:32` | Comment only: no new extra, runtime deps stay at two (E-222). |
| 6 | `pyproject.toml:60-62` | Unchanged: `packages = ["src/lauren_mcp"]` already ships both new modules. |
| 7 | `tests/unit/test_registry_manifest.py` (new) | Derivation/validation unit tests (§8.1). |
| 8 | `tests/unit/test_registry_cli.py` (new) | CLI surface: flags, exit codes, `--dry-run` writes nothing. |
| 9 | `tests/integration/test_registry_schema_integration.py` (new) | Golden file plus network-gated schema check (§8.2). |
| 10 | `tests/fixtures/registry/*` (new) | Fixture servers and `server.golden.json`. |
| 11 | `README.md` | Add `mcp-name: io.github.lauren-framework/lauren-mcp` so this project itself can be claimed (E-126). |
| 12 | `src/lauren_mcp/llms-full.txt` | Document both commands and the publish flow. |

Deliberately untouched: `src/lauren_mcp/server/_decorators.py:736-763`,
`src/lauren_mcp/server/_module.py:58-164`, all five commands in
`src/lauren_mcp/cli/_commands.py`, and the two runtime dependencies (E-222).

## 7. Backward Compatibility / Migration

**Migration: none required.** The change is additive in everything a user can observe:

- `lmcp --help` grows two commands; the five existing ones (`src/lauren_mcp/cli/__init__.py:18-22`)
  keep names, flags and exit codes because their implementations in `src/lauren_mcp/cli/_commands.py`
  (`:24`, `:49`, `:71`, `:119`, `:185`) are not edited.
- `resolve_server_class` (`src/lauren_mcp/cli/_resolve.py:19`) gains a caller, no new behaviour; the
  file-spec syntax (`:3-5`) is unchanged.
- No new runtime dependency, so `pip install lauren-mcp` still installs `lauren` and `anyio` only
  (E-222); the console script is unchanged (`pyproject.toml:47-48`).
- `server.json` is optional and never read at import or request time.

Versions are immutable and `isLatest` is server-side (E-127), so a bad publish cannot be fixed in
place — hence `validate`, not `init`, carries the strict exit-code contract — and the schema revision
lives in one constant (`SCHEMA_REVISION = "2025-12-11"`, E-123).

## 8. Test Plan

### 8.1 Unit tests — `tests/unit/test_registry_manifest.py`, `tests/unit/test_registry_cli.py`

Fixtures: `tests/fixtures/registry/remote_server.py` (a `@mcp_server("/mcp", transport="streamable")`
class with two `@mcp_tool` methods carrying `title=`/`description=`) and `stdio_server.py`.

| Test | Asserts |
|---|---|
| `test_build_manifest_remote_only` | `remotes == [{"type": "streamable-http", "url": "https://x/mcp"}]`, `packages == []` (E-124). |
| `test_build_manifest_stdio` | `packages[0]["transport"]["type"] == "stdio"`, `registryType == "pypi"`. |
| `test_stdio_and_url_requires_both` | `ManifestError` unless `--both`. |
| `test_description_derived` | Collapsed class docstring; tool count and first three `McpToolMeta.title` values (`src/lauren_mcp/server/_meta.py:45-50`). |
| `test_name_requires_single_slash` | `"acme-weather"`, `"a/b/c"`, `"/x"` raise with actionable messages (§4.3). |
| `test_derive_name_from_github_homepage` | `pyproject.toml:51` homepage → `io.github.lauren-framework/lauren-mcp`. |
| `test_env_secret_sets_is_secret` | `--env-secret ACME_API_KEY` → `isSecret: true` (E-123); `KEY=value` rejected. |
| `test_validate_version_drift` | Manifest version ≠ installed version warns; `--strict` errors (§1.1(2)). |
| `test_validate_check_pypi_marker` | Missing `mcp-name:` line exits 1 and prints the line to add (E-126). |

### 8.2 Integration tests — `tests/integration/test_registry_schema_integration.py`

1. **Golden manifest (offline).** Generate from the fixture with fixed options and compare
   byte-for-byte with `server.golden.json`, so a field rename shows up as a reviewable diff.
2. **Network-gated schema validation** against the authoritative `2025-12-11` schema (E-123), using
   `jsonschema` as a dev/test dependency only — never a runtime one:

```python
import json
import os
import pytest

SCHEMA_URL = "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"

pytestmark = pytest.mark.skipif(
    os.environ.get("LMCP_NETWORK_TESTS") != "1",
    reason="network-gated: set LMCP_NETWORK_TESTS=1 to fetch the 2025-12-11 schema (E-123)",
)


@pytest.mark.anyio
async def test_generated_manifest_matches_published_schema(generated_manifest):
    import httpx
    import jsonschema

    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(SCHEMA_URL)
        resp.raise_for_status()
        schema = resp.json()

    jsonschema.validate(instance=json.loads(generated_manifest), schema=schema)

    # Guard the hard requirements, so a relaxed schema cannot silently weaken our validator.
    assert {"name", "description", "version"} <= set(schema["required"])
```

3. **Smoke + posture.** A `--help`-only invocation of both commands fails CI on any import error
   without the network, and a test asserts `httpx` is imported in `tests/` only, so no publish path
   exists (E-222).

## Acceptance Criteria

- [ ] `lmcp registry-init tests/fixtures/registry/remote_server.py:RemoteServer --url https://weather.acme.com --env-secret ACME_API_KEY --dry-run` prints JSON with `remotes[0].url == "https://weather.acme.com/mcp"`, `remotes[0].type == "streamable-http"`, no `packages` key, and an `env` entry with `isSecret: true`.
- [ ] Without `--dry-run` it writes `server.json` and nothing else (`git status --short` shows only `?? server.json`).
- [ ] `--name acme-weather` fails with exit 1 and "must contain exactly one '/'".
- [ ] `--stdio --url https://x/mcp` fails unless `--both` is passed.
- [ ] `lmcp registry-validate server.json` exits 0 on the generated file and 1 on a version-drifted copy (`--strict` differing only in severity for non-schema findings).
- [ ] `lmcp registry-validate --check-pypi server.json` exits 1 printing `mcp-name: io.github.lauren-framework/lauren-mcp` when `README.md` lacks it, and 0 once added (E-126).
- [ ] `pytest -q tests/unit/test_registry_manifest.py tests/unit/test_registry_cli.py` passes.
- [ ] `tests/integration/test_registry_schema_integration.py::test_generated_manifest_matches_published_schema` validates the generated manifest against `https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json` with `LMCP_NETWORK_TESTS=1`, and skips cleanly otherwise.
- [ ] `python -c "import lauren_mcp.cli"` works with only `lauren` + `anyio` installed, and `pytest -q` shows no new failures (E-222).
- [ ] `pip install .` then `lmcp --help` lists both commands; `pyproject.toml:47-48` still declares exactly one console script (E-224).
- [ ] `README.md` / `src/lauren_mcp/llms-full.txt` document the publish flow, the six ownership methods (E-125) and the immutable-version rule (E-127).

## 9. Open Questions

1. **Flat commands or a `registry` sub-app?** This PRD ships `registry-init`/`registry-validate` to
   match the flat registrations at `src/lauren_mcp/cli/__init__.py:18-22`; if a sibling PRD introduces
   sub-apps, both names move to `lmcp registry init`. Needed before docs, not before code.
2. **Canonical schema URL.** §8.2 pins the `static.modelcontextprotocol.io` host for revision
   `2025-12-11` (revision confirmed by E-123); verify on the first `LMCP_NETWORK_TESTS=1` run. Only
   the constant changes.
4. **Env discovery.** Explicit flags only for now; scanning `.env` (already loaded by `_load_env`,
   `src/lauren_mcp/cli/_commands.py:203`) and proposing candidates is a follow-up, because discovery
   would guess.

## 10. References

- **E-120** — Registry live and versioned: **1.8.16**, git `a21a32b`, build
  `2026-11-23T13:54:44Z`; `https://registry.modelcontextprotocol.io/v0/version`.
- **E-121** — Scale: ≥ 20,000 records; `/v0.1/servers?limit=100`.
- **E-122** — Consumer API read-only and unauthenticated.
- **E-123** — `server.json` schema revision **`2025-12-11`**; required `name`/`description`/`version`;
  reverse-DNS `name` with exactly one slash; `packages[]`, `remotes[]`, `isSecret`.
- **E-124** — Remote-only servers publishable with no package.
- **E-125** — Ownership verification: `dns`, `http`, `github`, `github-oidc`, `github-at`,
  `anonymous`, via `mcp-publisher`.
- **E-126** — Package ownership via `mcpName` in `package.json` or `mcp-name:` in a PyPI README.
- **E-127** — Versions immutable, carrying `isLatest`.
- **E-128** — Registry repo traction: 7,500★, latest release `v1.8.16`.
- **E-129** — Third-party scale: Glama 131,130; mcp.so 20,915; Smithery → Arcade.
- **E-222** — Exactly two runtime dependencies: `lauren>=1.7.0`, `anyio>=4.0`.
- **E-224** — Console script `lmcp` in `pyproject.toml` `[project.scripts]`.
- Inventory §6.1 — `prds/2026-11-landscape/_research/lauren-mcp-inventory.md:221`.
- Repo citations: `pyproject.toml:6`, `:7`, `:32`, `:33-37`, `:38-42`, `:47-48`, `:50-51`, `:60-62`;
  `src/lauren_mcp/cli/__init__.py:1-4`, `:10`, `:18-22`; `src/lauren_mcp/cli/_commands.py:24-241`;
  `src/lauren_mcp/cli/_resolve.py:3-5`, `:19`, `:80`; `src/lauren_mcp/server/_module.py:44`, `:55`,
  `:58`, `:62`, `:65`, `:160-164`; `src/lauren_mcp/server/_decorators.py:736`, `:743`, `:758-763`;
  `src/lauren_mcp/server/_meta.py:45-50`.
