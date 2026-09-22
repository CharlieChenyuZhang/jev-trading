#!/usr/bin/env bash
# Append-only: stage accumulating logs/docs and push. Never delete/truncate JSONL.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export GIT_AUTHOR_NAME="${GIT_AUTHOR_NAME:-CharlieChenyuZhang}"
export GIT_AUTHOR_EMAIL="${GIT_AUTHOR_EMAIL:-charliechenyuzhang@users.noreply.github.com}"
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME"
export GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"

# Optional point-in-time snapshots (new files each run — never overwrite prior snapshots)
TS="$(TZ=America/Los_Angeles date +%Y%m%d_%H%M%S)"
mkdir -p logs/snapshots/crypto logs/snapshots/stock
for m in crypto stock; do
  if [[ -f "out/$m/live.json" ]]; then
    cp "out/$m/live.json" "logs/snapshots/$m/live_${TS}.json"
  fi
  # Keep decisions.jsonl mirrored (append-only source of truth under logs/)
  if [[ -f "out/$m/decisions.jsonl" ]]; then
    mkdir -p logs/raw_decisions
    # Prefer logs file as canonical; if out is ahead, append only missing tail by recopying whole file
    # (JSONL lines are unique by tick+ts; safe to replace logs copy with out copy when out is longer)
    out_lines=$(wc -l < "out/$m/decisions.jsonl" | tr -d ' ')
    logf="logs/raw_decisions/$m.jsonl"
    if [[ ! -f "$logf" ]]; then
      cp "out/$m/decisions.jsonl" "$logf"
    else
      log_lines=$(wc -l < "$logf" | tr -d ' ')
      if (( out_lines > log_lines )); then
        cp "out/$m/decisions.jsonl" "$logf"
      fi
    fi
  fi
done

# Strategy iteration log must remain append-only in working tree (already)
git add -A docs/strategy-iteration-log.md logs/raw_decisions/*.jsonl logs/raw_decisions/README.md logs/snapshots || true

# Refuse destructive staging of deleted jsonl if any
if git diff --cached --name-status | grep -E '^D\s+.*\.jsonl$' >/dev/null; then
  echo "Refusing commit: would delete jsonl" >&2
  git reset HEAD
  exit 1
fi

if git diff --cached --quiet; then
  echo "nothing to push"
  exit 0
fi

git -c user.name="$GIT_AUTHOR_NAME" -c user.email="$GIT_AUTHOR_EMAIL" commit -m "data: accumulate decisions/snapshots ${TS} PT"

gh auth setup-git >/dev/null 2>&1 || true
git push origin HEAD
echo "pushed ${TS}"
