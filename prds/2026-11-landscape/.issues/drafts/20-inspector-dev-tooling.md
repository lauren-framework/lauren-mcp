**PRD:** [`prd-inspector-dev-tooling.md`](https://github.com/lauren-framework/lauren-mcp/blob/docs/mcp-landscape-2026-11/prds/2026-11-landscape/prd-inspector-dev-tooling.md)
**Priority:** P3 — `lmcp inspect` is a thin positional command; Inspector is at 2.16.0 with capabilities we neither drive nor test
**Theme:** Tooling and conformance
**Key evidence:** E-165, E-166, E-222 — see `EVIDENCE.md` in the same directory.

## Problem

| Claim | Value | Anchor |
|---|---|---|
| Inspector current version | **2.16.0** (`latest` dist-tag) | `E-165` |
| Inspector has known advisories | **2 OSV advisories** | `E-166` |
| Inspector's functional surface at 2.16.0 | **not enumerated** | `U-01` |

```
prds/2026-11-landscape/EVIDENCE.md  line 516
| U-01 | Inspector's full functional surface at 2.16.0 | an "Inspector parity" PRD needs a
  checklist, not a version | read the Inspector README/source at implementation time |
```

## Goals

1. **Expose every client method** — all 13 in `_protocol.py` reachable from `inspect` (`AC-02`).
2. **Print schemas, not names** — `inputSchema`, resource `uri`/`mimeType`, prompt `arguments` (`AC-03`).
3. **Show the raw envelope** — unknown keys preserved, `resultType` when present, `isError` always (`AC-04`).
4. **A versioned JSON document** (`--json`, logs to stderr) and a **scenario engine** (`--script` with
   assertions and a stable exit-code contract) (`AC-05`…`AC-10`).
5. **Record and replay** — `--record` writes a bundle; `--diff` re-runs and compares (`AC-11`); and
   `--transcript` shows raw frames with direction and relative time, redacted by default (`AC-12`).
6. **Interactive server-initiated requests** — elicitation, sampling, MRTR answers via the factory kwargs at
7. **Fail closed on execution** — nothing spawns without `--allow-exec` (`AC-09`, `AC-10`).

**Priority — P3, and why.** `PRD-BRIEF.md` §4 defines P3 as ergonomics, packaging, and developer tooling.
Nothing here breaks a deployment, no spec MUST is violated by its absence, and the command already connects
over all four transports — incremental surface, not a rescue.

## Acceptance criteria

- [ ] **AC-01** — all flags documented: `lmcp inspect --help | grep -c -- '--json\|--script\|--record\|--diff\|--transcript\|--interactive\|--allow-exec'` → `7`
- [ ] **AC-02** — no orphaned client method: all 13 `_protocol.py` names appear in `cli/_inspect/_scenario.py` or `_repl.py` (AC-02 test)
- [ ] **AC-03** — schemas printed: `lmcp inspect examples/demo_server.py | grep -q inputSchema` → exit 0
- [ ] **AC-04** — raw envelope: `lmcp inspect … --call add --args '{"a":1,"b":2}' --raw | jq -e '.content[0].text == "3"'`; a server-sent `resultType` appears unchanged
- [ ] **AC-05** — versioned document: `… --json 2>/dev/null | jq -e '.schemaVersion == 1'` → exit 0
- [ ] **AC-06** — stdout is pure JSON: `… --json 2>/dev/null | python -c 'import json,sys; json.load(sys.stdin)'` → exit 0
- [ ] **AC-07** — passing scenario: `… --script scenarios/add.json; echo $?` → `0`
- [ ] **AC-08** — failing assertion: `… --script scenarios/add-bad.json 2>&1 | grep -q 'adds'` → exit 0, command exit `1`
- [ ] **AC-09** — command-bearing scenario refused: `… --script scenarios/evil.json; echo $?` → `2`, no process spawned
- [ ] **AC-10** — `file` target needs opt-in: `… --script scenarios/other-file.json; echo $?` → `3`; with `--allow-exec` → `0`
- [ ] **AC-11** — record then diff is clean: `… --record /tmp/s.lmcp.json --script scenarios/add.json && … --diff /tmp/s.lmcp.json` → `0`
- [ ] **AC-12** — both directions, redacted: `… --transcript 2>/dev/null | grep -c '"dir": "out"'` ≥ 2 and `… | grep -c '<redacted>'` ≥ 1
- [ ] **AC-13** — interactive answers reach the server: `printf ':call ask_name {}\n{"name":"Ada"}\n:quit\n' | lmcp inspect … --interactive --json | jq -e '.steps != null'`
- [ ] **AC-14** — `U-01` settled: `_research/inspector-surface.md` exists, one row per capability with a source line for Inspector 2.16.0; until then no document here asserts Inspector behaviour
- [ ] **AC-15** — no new dependency: `git diff --stat pyproject.toml` empty; `python -c "import lauren_mcp.cli._inspect"` works with only `[cli]`

---

Drafted from the 2026-11 MCP landscape review (evidence retrieved 2026-11-26). Full PRD, evidence register (`EVIDENCE.md`) and `VERSIONS-MATRIX.md` live in `prds/2026-11-landscape/` on branch `docs/mcp-landscape-2026-11`.
