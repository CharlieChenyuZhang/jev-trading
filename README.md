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

## Safety

Dry-run only. No live orders.
