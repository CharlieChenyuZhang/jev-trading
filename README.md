# jev-trading

Paper-trading (dry-run) smokes that feed live public market state into [Jev](https://openrouter.ai/~typesafe/jev-latest) via **OpenRouter** and simulate fills.

**Crypto and stock are separate** — different strategies, thresholds, and processes. Do not combine them in one decision loop for real work.

## Markets

| Smoke | Symbol | Data | Entry |
| --- | --- | --- | --- |
| Crypto | BTC-USD | Coinbase public REST | `python smoke_crypto.py` |
| Stock | AAPL | Yahoo public chart | `python smoke_stock.py` |

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
export OPENROUTER_API_KEY=...   # from openrouter.ai
python smoke_crypto.py          # ~45s paper loop
python smoke_stock.py
# or:
python -m jev_trading.smoke crypto --duration 60
python -m jev_trading.smoke stock --duration 60
```

Also accepts `TYPESAFE_API_KEY` as a fallback env name for the same Bearer token.

Calls `POST https://openrouter.ai/api/v1/systemone` with model `~typesafe/jev-latest`.

## Outputs

Each smoke writes under `out/<market>/`:

- `results.json` — ticks, latency, simulated book
- `SUMMARY.md` — short report

These paths are gitignored.

## Parameter comparison (shadow books)

Crypto runs a **primary** book (strict gates) plus parallel **shadow** books on the same Jev signals:

| Book | noul | confidence |
| --- | --- | --- |
| primary | ≥ 0.60 | ≥ 0.55 |
| shadow_035_025 | ≥ 0.35 | ≥ 0.25 |
| shadow_040_030 | ≥ 0.40 | ≥ 0.30 |
| shadow_030_020 | ≥ 0.30 | ≥ 0.20 |

Live comparison is in `out/crypto/live.json` under `book` + `shadows`.

## Live dashboard

```bash
python dashboard/server.py
# open http://127.0.0.1:8787
```

Reads `out/*/live.json` every 2s (primary + shadow books).

## Safety

Dry-run only. No live orders.
