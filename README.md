# jev-trading

Paper-trading (dry-run) smokes that feed a **symbol universe** into [Jev](https://openrouter.ai/~typesafe/jev-latest) via **OpenRouter**. Each tick Jev **picks one symbol** (or `none`), then decides direction.

Crypto and stock stay **separate** processes / strategies.

## Universes

| Market | Venue | Universe |
| --- | --- | --- |
| Crypto | Coinbase public | BTC-USD, ETH-USD, SOL-USD, XRP-USD, DOGE-USD, LINK-USD, AVAX-USD |
| Stock | Yahoo public chart | AAPL, MSFT, NVDA, GOOGL, AMZN, META, TSLA |

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
export OPENROUTER_API_KEY=...
python smoke_crypto.py
python smoke_stock.py
# or:
python -m jev_trading.smoke crypto --duration 3600
python -m jev_trading.smoke stock --duration 3600
```

## Parameter comparison (shadow books)

Same Jev signals; parallel paper ledgers:

| Book | noul | confidence |
| --- | --- | --- |
| primary | ≥ 0.60 | ≥ 0.55 |
| shadow_035_025 | ≥ 0.35 | ≥ 0.25 |
| shadow_040_030 | ≥ 0.40 | ≥ 0.30 |
| shadow_030_020 | ≥ 0.30 | ≥ 0.20 |

See `out/<market>/live.json` (`pick_dist`, `book`, `shadows`).

## Live dashboard

```bash
python dashboard/server.py
# http://127.0.0.1:8787
```

## Safety

Dry-run only. No live orders.
