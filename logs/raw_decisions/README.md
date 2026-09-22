# Raw investment decision logs

Append-only JSONL. One line = one Jev decision tick.

- `crypto.jsonl` / `stock.jsonl` — durable archive across runs
- Also mirrored per run at `out/{market}/decisions.jsonl`

Each line includes: timestamp, market, experiment/strategy id + gates,
candidates, **jev_raw_answers** (model primitive outputs), parsed fields,
and execution (fill / shadow fills / equity).

Do not rewrite; only append.
