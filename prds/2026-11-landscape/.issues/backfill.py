#!/usr/bin/env python3
"""Backfill issue URLs into the PRD headers and the README index.

    ./backfill.py --dry-run   # show the edits, write nothing
    ./backfill.py             # apply them

Reads `.issues/issues.json` (written by create-issues.sh) as
{"<row>": {"number": 12, "title": "...", "url": "https://..."}} and:

  1. in each PRD, replaces `**Issue:** _pending_` with `**Issue:** [#12](url)`;
  2. in README.md, adds the issue link to that PRD's summary-table row.

Idempotent: a second run finds nothing to change. Any PRD whose row is
missing from issues.json is left untouched and reported.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent  # prds/2026-11-landscape
DRY = "--dry-run" in sys.argv


def main() -> int:
    mapping_path = HERE / "issues.json"
    if not mapping_path.exists():
        print(f"no {mapping_path.name}; run create-issues.sh first", file=sys.stderr)
        return 1
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    manifest = json.loads((HERE / "manifest.json").read_text(encoding="utf-8"))

    edits = 0
    missing = []
    for entry in manifest:
        row, prd = str(entry["n"]), entry["prd"]
        info = mapping.get(row)
        if not info:
            missing.append((row, prd))
            continue
        link = f"[#{info['number']}]({info['url']})"

        path = ROOT / prd
        text = path.read_text(encoding="utf-8")
        new = text.replace("**Issue:** _pending_", f"**Issue:** {link}", 1)
        if new != text:
            edits += 1
            if DRY:
                print(f"would set {prd}: **Issue:** {link}")
            else:
                path.write_text(new, encoding="utf-8")
                print(f"set {prd}: **Issue:** {link}")
        elif f"**Issue:** {link}" not in text:
            print(f"warn {prd}: no **Issue:** line found", file=sys.stderr)

    readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8")
    changed_rows = 0
    for entry in manifest:
        info = mapping.get(str(entry["n"]))
        if not info:
            continue
        link = f"[#{info['number']}]({info['url']})"
        # Append the issue link to the row's Key-evidence cell, once.
        pattern = re.compile(
            r"(?m)^(\|\s*"
            + str(entry["n"])
            + r"\s*\|\s*P[123]\s*\|\s*\[`"
            + re.escape(entry["prd"])
            + r"`\]\([^)]+\)\s*\|[^\n]*)$"
        )
        m = pattern.search(text)
        if not m:
            print(f"warn README: no row for {entry['prd']}", file=sys.stderr)
            continue
        row_text = m.group(1)
        if link in row_text:
            continue
        new_row = row_text.rstrip("|").rstrip() + f" · {link} |"
        text = text.replace(row_text, new_row, 1)
        changed_rows += 1

    if changed_rows:
        if DRY:
            print(f"would update {changed_rows} README rows")
        else:
            readme.write_text(text, encoding="utf-8")
            print(f"updated {changed_rows} README rows")

    if missing:
        print(f"\nwithout an issue yet: {len(missing)}")
        for row, prd in missing:
            print(f"  {row:>2} {prd}")
    print(f"\nPRD edits: {edits}, README rows: {changed_rows}, dry-run={DRY}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
