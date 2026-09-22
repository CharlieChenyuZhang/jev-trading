# Accumulating run data (git-backed)

**Rule: append / add new files only. Never truncate or overwrite historical records.**

| Path | What |
|------|------|
| `raw_decisions/*.jsonl` | Every Jev tick decision (append-only) |
| `snapshots/{market}/live_YYYYMMDD_HHMMSS.json` | Point-in-time live book copies (new file each push) |
| `../docs/strategy-iteration-log.md` | Strategy lessons (append sections only) |

`out/` is local scratch (gitignored). Decisions are mirrored here before each push.
