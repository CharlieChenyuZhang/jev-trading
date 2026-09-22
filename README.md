# jev-trading

Paper-trading (dry-run) loop that feeds live public market state into [Jev](https://openrouter.ai/~typesafe/jev-latest) via **OpenRouter** and simulates fills. No real orders.

## Markets

- **Crypto:** BTC-USD via Coinbase Exchange public REST (top-of-book + trades)
- **Stock:** AAPL via Yahoo Finance public chart endpoint

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
export OPENROUTER_API_KEY=...   # from openrouter.ai — preferred
# or: export TYPESAFE_API_KEY=...  # also accepted (same Bearer header)
python run_dry_hft.py
```

Calls `POST https://openrouter.ai/api/v1/systemone` with model `~typesafe/jev-latest` (TypeSafe System One shape).

Native TypeSafe keys use `https://api.typesafe.ai/v1/systemone` and model `jev-latest` — this repo defaults to OpenRouter because that is the common path with an OpenRouter key.

## What it does

Every ~2.5s for ~120s:

1. Pull crypto + stock top-of-book / short-window features
2. Ask Jev (in parallel): direction (`buy`/`sell`/`hold`), `should_trade` (noul), edge score
3. If noul ≥ 0.6 and confidence ≥ 0.55, simulate a 1% notional fill at bid/ask
4. Write `results.json` and `SUMMARY.md` (gitignored)

Latency is typically a few hundred ms per Jev call — short-horizon decision trading, not exchange-colocation HFT.

## Safety

Dry-run only. Do not point this at live execution without separate risk controls, keys, and explicit enablement.
