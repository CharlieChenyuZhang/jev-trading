# jev-trading

Paper-trading (dry-run) smokes that feed a **symbol universe** into [Jev](https://openrouter.ai/~typesafe/jev-latest) via **OpenRouter**. Each tick Jev **picks one symbol** (or `none`), then decides direction.

Crypto and stock stay **separate** processes / strategies.

## Design principles (autoresearch / RSI-style)

We treat paper trading like a small **auto-research** lab (Karpathy-style loop), not a single hard-coded strategy.

1. **Parallel strategy wars.** Each tick, the same Jev answers feed many compare ledgers at once (today A–H; the set can grow). Think model wars / factorial waves: try different hypotheses in parallel instead of hill-climbing one book.
2. **Fixed, comparable campaigns.** A campaign has a clear `ends_ts` / duration, fresh paper books (e.g. $10k), and shared logs so variants are judged under the same wall-clock window.
3. **Hourly reflect → keep or change.** On a schedule, an agent reviews fills, marks, and decisions: which calls looked right, which looked wrong, and why. Lessons go into `docs/strategy-iteration-log.md` (Observed / Lessons / Decision `CHANGE` | `KEEP` | `OBSERVE`).
4. **CHANGE restarts a new wave.** Editing strategy rules mid-book contaminates the experiment. On `CHANGE`, archive the old books, start a **new** campaign (new primary/shadows as needed, new `ends_ts`), and keep `logs/raw_decisions/*.jsonl` **append-only** for audit — never truncate history.
5. **Objective keep/discard.** Promote or discard variants using paper metrics (PnL, fill churn, drawdown, gate pass rates)—our analogue of autoresearch’s fixed metric + time budget. No clear lesson → `KEEP` / `OBSERVE`; clear lesson → `CHANGE` and relaunch.
6. **Human writes the research org; agents edit the experiment.** Standing instructions (this README, iteration-log format, routines) are the human-owned “program.” Agents may change experiment config / execution overlays and re-run; they do not invent live trading or wipe the decision history.
7. **Paper only.** Dry-run. No live orders.

Inspiration: [karpathy/autoresearch](https://github.com/karpathy/autoresearch) — propose → run under a fixed budget → evaluate → keep/discard → repeat; scale by running many candidates in parallel.

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
