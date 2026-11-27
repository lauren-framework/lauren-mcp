**PRD:** [`prd-registry-publishing.md`](https://github.com/lauren-framework/lauren-mcp/blob/docs/mcp-landscape-2026-11/prds/2026-11-landscape/prd-registry-publishing.md)
**Priority:** P2 — The registry is live at 1.8.16 and everything consumes one `server.json` shape; we publish none
**Theme:** Ecosystem
**Key evidence:** E-120, E-121, E-122 — see `EVIDENCE.md` in the same directory.

## Problem

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

## Goals

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

## Acceptance criteria

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

---

Drafted from the 2026-11 MCP landscape review (evidence retrieved 2026-11-26). Full PRD, evidence register (`EVIDENCE.md`) and `VERSIONS-MATRIX.md` live in `prds/2026-11-landscape/` on branch `docs/mcp-landscape-2026-11`.
