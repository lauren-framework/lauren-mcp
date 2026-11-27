# Issue-creation kit (goal 7)

**Status: run on 2026-11-26.** The twenty issues exist as
`lauren-framework/lauren-mcp` #61-#80, each labelled `prd` plus its priority.
`issues.json` holds the number/title/URL map, and every PRD header and README
row now carries its link.

## What is in here

| File | Purpose |
|---|---|
| `manifest.json` | 20 entries: row number, priority, PRD filename, issue title (`[P1] …`, matching the repo's existing convention), draft body path, labels (`prd` + `p1`/`p2`/`p3`), byte size |
| `drafts/NN-slug.md` | One issue body per PRD: PRD link, priority with its one-line justification, theme, key `E-xxx` IDs, the problem statement (first paragraphs), the full Goals list, the acceptance checklist |
| `create-issues.sh` | Creates the `prd`/`p1`/`p2`/`p3` labels, creates the issues, writes `issues.json`. Idempotent: a title that already exists is skipped, so a partial run can be resumed |
| `backfill.py` | Reads `issues.json`, replaces `**Issue:** _pending_` in each PRD header and appends the link to that PRD's row in `README.md`. `--dry-run` shows the edits |
| `issues.json` | The result: row number → issue number, title and URL |

## How it was run

```bash
cd prds/2026-11-landscape/.issues
./create-issues.sh --dry-run    # 20 "would create" lines, no API writes
./create-issues.sh              # create labels + 20 issues, write issues.json
./backfill.py --dry-run         # confirm the header and README edits
./backfill.py                   # apply them
```

Requires `gh` authenticated with `repo` scope (`gh auth status`) and `jq`.

Both scripts are safe to re-run. `create-issues.sh` matches on exact title, so a
second run reports 20 skips and writes nothing; `backfill.py` finds no
`**Issue:** _pending_` left and leaves the files alone.

## What was checked before creating

- `gh auth status` → logged in to github.com with `repo`.
- Dry run reported 20 creates and 0 title collisions against the 55 issues that
  already existed (#1-#55).
- Labels `prd`, `p1`, `p2`, `p3` did not exist; `create-issues.sh` created them
  with `--force`, which updates in place if someone adds them first.
- The repo already uses `[P1] …` / `[P2] …` titles (issues #46-#55), so the
  titles here follow the same convention rather than plain PRD titles.
- All 20 PRDs carried `**Issue:** _pending_` immediately after `**Priority:**`,
  so the backfill was a single mechanical substitution per file.

## Deliberate scope limits

- Bodies are condensed, not the full 28-30 KB PRD, so the issue stays readable;
  the PRD link on `docs/mcp-landscape-2026-11` is the authority.
- No `enhancement` label is added: `prd` plus the priority is enough, and mixing
  the two vocabularies would make the existing label filter useless.
- Nothing is assigned, milestoned or linked as a sub-issue: those are planning
  decisions, not part of this pass.
