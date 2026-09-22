# jev-trading

Paper-trading (dry-run) loop that feeds live public market state into [Jev](https://jevapi.dev/) (`jev-latest`) and simulates fills. No real orders.

## Markets

- **Crypto:** BTC-USD via Coinbase Exchange public REST (order book + trades)
- **Stock:** AAPL via Yahoo Finance public chart endpoint

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install requests  # stdlib urllib is enough; requests optional
export TYPESAFE_API_KEY=...   # from console.typesafe.ai
python run_dry_hft.py
```

Requires `TYPESAFE_API_KEY`. The script POSTs to `https://api.typesafe.ai/v1/systemone` with model `jev-latest`.

## What it does

Every ~2.5s for ~120s:

1. Pull crypto + stock top-of-book / short-window features
2. Ask Jev (in parallel): direction (`buy`/`sell`/`hold`), `should_trade` (noul), edge score
3. If noul ≥ 0.6 and confidence ≥ 0.55, simulate a 1% notional fill at bid/ask
4. Write `results.json` and `SUMMARY.md` (gitignored)

Latency is typically 70–500ms per Jev call — short-horizon decision trading, not exchange-colocation HFT.

## Safety

Dry-run only. Do not point this at live execution without separate risk controls, keys, and explicit enablement.
