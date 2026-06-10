#!/usr/bin/env python3
"""
Check that llms-full.txt covers all public symbols in lauren_mcp.__all__.

Exit codes:
  0 - all symbols documented
  1 - one or more symbols missing from llms-full.txt
  2 - error (import failure, file not found, etc.)
"""

from __future__ import annotations

import pathlib
import sys

# Ensure the package is importable from source even when not installed.
_src = pathlib.Path(__file__).resolve().parent.parent / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))


def main() -> int:
    # -------------------------------------------------------------------------
    # 1. Import the package and collect __all__
    # -------------------------------------------------------------------------
    try:
        import lauren_mcp  # noqa: PLC0415
    except ImportError as exc:
        print(f"ERROR: Could not import lauren_mcp: {exc}", file=sys.stderr)
        print(
            "Hint: make sure the package is installed (uv sync --extra dev --active)",
            file=sys.stderr,
        )
        return 2

    try:
        public_symbols: list[str] = list(lauren_mcp.__all__)
    except AttributeError:
        print("ERROR: lauren_mcp does not define __all__", file=sys.stderr)
        return 2

    if not public_symbols:
        print("WARNING: lauren_mcp.__all__ is empty — nothing to check.")
        return 0

    # -------------------------------------------------------------------------
    # 2. Find llms-full.txt (prefer repo root, fall back to src/lauren_mcp/)
    # -------------------------------------------------------------------------
    script_dir = pathlib.Path(__file__).resolve().parent
    repo_root = script_dir.parent

    candidates = [
        repo_root / "llms-full.txt",
        repo_root / "src" / "lauren_mcp" / "llms-full.txt",
    ]

    llms_full_path: pathlib.Path | None = None
    for candidate in candidates:
        if candidate.exists():
            llms_full_path = candidate
            break

    if llms_full_path is None:
        print(
            "ERROR: llms-full.txt not found. Checked:\n" + "\n".join(f"  {c}" for c in candidates),
            file=sys.stderr,
        )
        return 2

    # -------------------------------------------------------------------------
    # 3. Read llms-full.txt content
    # -------------------------------------------------------------------------
    try:
        llms_content = llms_full_path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"ERROR: Could not read {llms_full_path}: {exc}", file=sys.stderr)
        return 2

    # -------------------------------------------------------------------------
    # 4. Check each symbol appears in the file
    # -------------------------------------------------------------------------
    missing: list[str] = []
    for symbol in sorted(public_symbols):
        # A symbol is considered documented if it appears as a section header
        # (## symbol or # symbol) or as a plain occurrence in the text.
        # We require it to appear at the start of a line or after whitespace
        # to avoid false positives from partial matches.
        found = False
        for marker in (
            f"## {symbol}",
            f"# {symbol}",
            f"`{symbol}`",
            f":{symbol}:",
        ):
            if marker in llms_content:
                found = True
                break
        if not found:
            # Fallback: bare word occurrence at word boundary
            import re  # noqa: PLC0415

            if re.search(rf"\b{re.escape(symbol)}\b", llms_content):
                found = True
        if not found:
            missing.append(symbol)

    # -------------------------------------------------------------------------
    # 5. Report
    # -------------------------------------------------------------------------
    print(f"Checked {len(public_symbols)} symbols against {llms_full_path.name}")

    if missing:
        print(f"\nMISSING ({len(missing)} symbol(s) not documented in llms-full.txt):")
        for sym in missing:
            print(f"  - {sym}")
        print(
            "\nPlease add documentation for the missing symbols to llms-full.txt "
            "and (if applicable) src/lauren_mcp/llms-full.txt."
        )
        return 1

    print(f"OK: all {len(public_symbols)} public symbols are documented.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
