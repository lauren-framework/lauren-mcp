**PRD:** [`prd-conformance-ci.md`](https://github.com/lauren-framework/lauren-mcp/blob/docs/mcp-landscape-2026-11/prds/2026-11-landscape/prd-conformance-ci.md)
**Priority:** P2 — No conformance measurement of any kind: every claim about our own protocol behaviour is an assertion with no number attached
**Theme:** Tooling and conformance
**Key evidence:** E-75, E-76, E-55 — see `EVIDENCE.md` in the same directory.

## Problem

`lauren-mcp` 1.0.0 has no conformance measurement of any kind. Every statement this
repo makes about its own protocol behaviour is an assertion with no number behind it
and no command a reviewer can run.

That is no longer acceptable: the ecosystem publishes a number for everyone else. The official suite exists and is exactly what the official Tier 1/2/3
ratings are computed from: `npx @modelcontextprotocol/conformance client --command …
--scenario …`, version **0.1.16**, repo pushed 2026-11-23 (E-75). The tier rules are
verbatim — **pass rate 100 % / 80 % / none for Tiers 1 / 2 / 3** (E-76) — and the
tiering system is SEP-1730, first shipped in `2025-11-25` (E-55).

## Goals

1. A repo-local scenario suite, `tests/conformance/`, pinning **legacy behaviour for
   all four advertised versions**, hermetic (no network, no Node).
2. A thin adapter, `tests/conformance/harness.py`, starting a real `lauren-mcp` server
   on **stdio** and on **Streamable HTTP** (ephemeral port) and returning a
   ready-to-run command for the official suite.
3. A checked-in baseline, `tests/conformance/baseline.json`, plus a comparator that
   **fails the build when a passing scenario fails or disappears**.
4. CI separating hermetic from network-gated scenarios via `LMCP_NETWORK_TESTS`,
   mirroring the existing marker machinery (`pyproject.toml:125-129`).
5. `lmcp conformance`, running the same subset locally.
6. A written statement of **what the official suite cannot measure**, with a
   local scenario as a *supplement*, never a replacement.
7. No new runtime dependency: `lauren` + `anyio` stay the whole set
   (`pyproject.toml:27-30`), and Node is a subprocess, never an import.

**Why P2.** Real SDKs ship this and the ratings are public (E-80 … E-90), but its
absence costs credibility and regression safety, not interop: no host refuses us for lack of a harness. That is P2, not P1.

### Acceptance checklist

- [ ] `ls tests/conformance/{harness.py,scenarios.toml,baseline.json}` — all three exist
- [ ] `unshare -rn python -m pytest tests/conformance -q -m 'not network'` passes with no network at all
- [ ] `grep -c 'era = "legacy"' tests/conformance/scenarios.toml` returns ≥ 8
- [ ] `grep -o '20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]' tests/conformance/scenarios.toml | sort -u | wc -l` returns ≥ 4 (all of `src/lauren_mcp/_mcp_version.py:7`)
- [ ] `python -m pytest tests/conformance -q -k harness` starts a target on stdio **and** on a bound port; afterwards `pgrep -f 'tests.conformance._serve' | wc -l` returns 0
- [ ] `python tools/check_conformance_baseline.py --report tests/conformance/report.json --baseline tests/conformance/baseline.json` exits 0 on an unchanged tree
- [ ] Breaking a scenario on purpose (`sed -i 's/"echo"/"echoo"/' tests/conformance/_fixture_server.py`) makes that command exit **1** — the gate is proven, not assumed
- [ ] `python -m pytest tests/unit/test_conformance_baseline.py -q` passes, including the pass→fail case
- [ ] `lmcp conformance --era legacy --transport stdio` exits 0, and 1 when a scenario fails
- [ ] `LMCP_NETWORK_TESTS=1 lmcp conformance --official` runs, or exits **2** naming the missing prerequisite — never 0 by silent skip
- [ ] `grep -rn npx tests/conformance/ | grep -v _official.py` returns nothing
- [ ] `wc -c tests/conformance/baseline.json` returns < 4096

## Acceptance criteria

- [ ] `ls tests/conformance/{harness.py,scenarios.toml,baseline.json}` — all three exist
- [ ] `unshare -rn python -m pytest tests/conformance -q -m 'not network'` passes with no network at all
- [ ] `grep -c 'era = "legacy"' tests/conformance/scenarios.toml` returns ≥ 8
- [ ] `grep -o '20[0-9][0-9]-[0-9][0-9]-[0-9][0-9]' tests/conformance/scenarios.toml | sort -u | wc -l` returns ≥ 4 (all of `src/lauren_mcp/_mcp_version.py:7`)
- [ ] `python -m pytest tests/conformance -q -k harness` starts a target on stdio **and** on a bound port; afterwards `pgrep -f 'tests.conformance._serve' | wc -l` returns 0
- [ ] `python tools/check_conformance_baseline.py --report tests/conformance/report.json --baseline tests/conformance/baseline.json` exits 0 on an unchanged tree
- [ ] Breaking a scenario on purpose (`sed -i 's/"echo"/"echoo"/' tests/conformance/_fixture_server.py`) makes that command exit **1** — the gate is proven, not assumed
- [ ] `python -m pytest tests/unit/test_conformance_baseline.py -q` passes, including the pass→fail case
- [ ] `lmcp conformance --era legacy --transport stdio` exits 0, and 1 when a scenario fails
- [ ] `LMCP_NETWORK_TESTS=1 lmcp conformance --official` runs, or exits **2** naming the missing prerequisite — never 0 by silent skip
- [ ] `grep -rn npx tests/conformance/ | grep -v _official.py` returns nothing
- [ ] `wc -c tests/conformance/baseline.json` returns < 4096

---

Drafted from the 2026-11 MCP landscape review (evidence retrieved 2026-11-26). Full PRD, evidence register (`EVIDENCE.md`) and `VERSIONS-MATRIX.md` live in `prds/2026-11-landscape/` on branch `docs/mcp-landscape-2026-11`.
