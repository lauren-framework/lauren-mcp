#!/usr/bin/env bash
# Create one GitHub issue per landscape PRD, then record the URLs.
#
#   ./create-issues.sh --dry-run     # print what would happen, change nothing
#   ./create-issues.sh               # create labels, create issues, write issues.json
#
# Idempotent: an issue whose title already exists is skipped, so a re-run
# after a partial failure only creates what is missing.
#
# Requires `gh` authenticated against lauren-framework/lauren-mcp with `repo`.
set -euo pipefail

REPO="lauren-framework/lauren-mcp"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"          # prds/2026-11-landscape
MANIFEST="$HERE/manifest.json"
OUT="$HERE/issues.json"
DRY_RUN=0

[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1

command -v gh >/dev/null || { echo "gh not installed" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq not installed" >&2; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "gh not authenticated" >&2; exit 1; }

if (( ! DRY_RUN )); then
  # Labels are created idempotently; --force updates an existing one in place.
  gh label create prd --repo "$REPO" --color 0e8a16 \
    --description "Design document from the 2026-11 MCP landscape review" --force
  for p in p1 p2 p3; do
    gh label create "$p" --repo "$REPO" --color "d93f0b" \
      --description "Priority ${p^^} in the 2026-11 MCP landscape review" --force
  done
fi

# Existing titles, so a re-run does not duplicate.
EXISTING="$(gh issue list --repo "$REPO" --state all --limit 500 --json number,title)"
[[ -f "$OUT" ]] || echo '{}' > "$OUT"

count=0
while IFS=$'\t' read -r n title body_file labels; do
  body="$ROOT/$body_file"
  [[ -f "$body" ]] || { echo "missing body: $body" >&2; exit 1; }

  num="$(jq -r --arg t "$title" '.[] | select(.title==$t) | .number' <<<"$EXISTING" | head -1)"
  if [[ -n "$num" ]]; then
    echo "skip  [$n] #$num already exists: $title"
    continue
  fi

  # Build the label arguments from the comma-separated manifest field
  # ("prd,p1" etc.) — the manifest already carries `prd` as the first label.
  label_args=()
  IFS=',' read -ra ls <<<"$labels"
  for l in "${ls[@]}"; do label_args+=(--label "$l"); done

  if (( DRY_RUN )); then
    echo "would create [$n] $title  (${label_args[*]})"
    echo "             body: $body ($(wc -c <"$body") bytes)"
    continue
  fi

  url="$(gh issue create --repo "$REPO" --title "$title" --body-file "$body" "${label_args[@]}")"
  num="${url##*/}"
  echo "created [$n] #$num $url"
  jq --arg n "$n" --arg t "$title" --arg u "$url" --argjson num "$num" \
     '.[$n] = {number: $num, title: $t, url: $u}' "$OUT" > "$OUT.tmp" && mv "$OUT.tmp" "$OUT"
  EXISTING="$(gh issue list --repo "$REPO" --state all --limit 500 --json number,title)"
  count=$((count + 1))
done < <(jq -r '.[] | [.n, .title, .body_file, (.labels|join(","))] | @tsv' "$MANIFEST")

echo "---"
echo "created: $count of $(jq length "$MANIFEST")  (dry-run=$DRY_RUN)"
(( DRY_RUN )) || echo "map: $OUT"
