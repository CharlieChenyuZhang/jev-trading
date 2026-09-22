#!/usr/bin/env python3
"""Paper-trading decision loop: public market data + Jev API. DRY RUN ONLY."""
from __future__ import annotations

import json
import os
import statistics
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

OUT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = OUT_DIR / "results.json"
SUMMARY_PATH = OUT_DIR / "SUMMARY.md"
JEV_URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
DURATION_S = 120
INTERVAL_S = 2.5
START_CASH = 10_000.0
TRADE_FRAC = 0.01
NOUL_MIN = 0.6
CONF_MIN = 0.55


def http_json(url: str, *, method: str = "GET", headers: dict | None = None, body: dict | None = None, timeout: float = 15.0) -> Any:
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("User-Agent", "jev-hft-dryrun/1.0")
    req.add_header("Accept", "application/json")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if headers:
        for k, v in headers.items():
            req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_crypto() -> dict[str, Any]:
    # Coinbase public (Binance often returns 451 from some regions)
    ticker = http_json("https://api.exchange.coinbase.com/products/BTC-USD/ticker")
    book = http_json("https://api.exchange.coinbase.com/products/BTC-USD/book?level=2")
    trades = http_json("https://api.exchange.coinbase.com/products/BTC-USD/trades?limit=20")
    bid = float(ticker["bid"])
    ask = float(ticker["ask"])
    mid = (bid + ask) / 2.0
    spread_bps = (ask - bid) / mid * 10_000 if mid else 0.0
    # Coinbase trades: side is "buy" or "sell" from taker perspective
    buy_vol = sum(float(t["size"]) for t in trades if t.get("side") == "buy")
    sell_vol = sum(float(t["size"]) for t in trades if t.get("side") == "sell")
    tot = buy_vol + sell_vol
    imbalance = (buy_vol - sell_vol) / tot if tot else 0.0
    # trades are newest-first on Coinbase
    last_px = float(trades[0]["price"]) if trades else mid
    first_px = float(trades[-1]["price"]) if trades else mid
    ret_bps = (last_px - first_px) / first_px * 10_000 if first_px else 0.0
    bids = [[float(p), float(q)] for p, q in book.get("bids", [])[:5]]
    asks = [[float(p), float(q)] for p, q in book.get("asks", [])[:5]]
    return {
        "symbol": "BTC-USD",
        "venue": "coinbase_exchange_public",
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "spread_bps": round(spread_bps, 3),
        "ret_short_bps": round(ret_bps, 3),
        "trade_imbalance": round(imbalance, 4),
        "bids": bids,
        "asks": asks,
    }


def fetch_stock() -> dict[str, Any]:
    # Yahoo chart endpoint (public)
    url = "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?interval=1m&range=1d"
    raw = http_json(url)
    result = raw["chart"]["result"][0]
    meta = result["meta"]
    quotes = result["indicators"]["quote"][0]
    closes = [c for c in (quotes.get("close") or []) if c is not None]
    last = float(meta.get("regularMarketPrice") or (closes[-1] if closes else 0))
    prev = float(closes[-6]) if len(closes) >= 6 else float(closes[0] if closes else last)
    ret_bps = (last - prev) / prev * 10_000 if prev else 0.0
    # Approximate top-of-book from last + typical spread proxy
    spread_bps = 1.0  # ~1bp proxy for liquid large-cap
    half = last * spread_bps / 10_000 / 2
    bid, ask = last - half, last + half
    return {
        "symbol": "AAPL",
        "venue": "yahoo_chart_public",
        "bid": round(bid, 4),
        "ask": round(ask, 4),
        "mid": round(last, 4),
        "spread_bps": spread_bps,
        "ret_short_bps": round(ret_bps, 3),
        "trade_imbalance": 0.0,
        "note": "stock TOB approximated from last + 1bp spread proxy",
    }


def build_state(crypto: dict, stock: dict) -> str:
    return json.dumps(
        {
            "mode": "paper_trading_dry_run",
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "horizon_sec": 5,
            "markets": {"crypto": crypto, "stock": stock},
            "instructions": (
                "Judge short-horizon (next few seconds) directional edge only. "
                "Prefer hold when edge is unclear or spread is wide relative to move."
            ),
        },
        separators=(",", ":"),
    )


def jev_questions(prefix: str) -> dict[str, Any]:
    return {
        f"{prefix}_direction": {
            "type": "choice",
            "instructions": f"For {prefix}, what is the best short-horizon action?",
            "criteria": {
                "buy": "Price more likely to rise over the next few seconds",
                "sell": "Price more likely to fall over the next few seconds",
                "hold": "No clear edge; stay flat or keep current stance",
            },
        },
        f"{prefix}_should_trade": {
            "type": "noul",
            "instructions": f"For {prefix}, should we place a small paper trade now?",
            "criteria": {
                "true": "Edge and liquidity justify a small trade",
                "false": "Skip; edge too weak or noisy",
            },
        },
        f"{prefix}_edge": {
            "type": "score",
            "instructions": f"Quality of short-horizon edge for {prefix}",
            "criteria": [
                "No edge / noise",
                "Very weak",
                "Modest",
                "Clear",
                "Strong",
            ],
        },
    }


def call_jev(api_key: str, state: str) -> tuple[dict[str, Any], float]:
    body = {
        "model": MODEL,
        "state": state,
        "questions": {**jev_questions("crypto"), **jev_questions("stock")},
    }
    t0 = time.perf_counter()
    try:
        resp = http_json(
            JEV_URL,
            method="POST",
            headers={"Authorization": f"Bearer {api_key}"},
            body=body,
            timeout=20.0,
        )
        latency_ms = (time.perf_counter() - t0) * 1000
        return resp, latency_ms
    except urllib.error.HTTPError as e:
        latency_ms = (time.perf_counter() - t0) * 1000
        err_body = e.read().decode("utf-8", errors="replace")[:500]
        return {"error": True, "status": e.code, "body": err_body}, latency_ms


@dataclass
class Book:
    cash: float = START_CASH
    position: float = 0.0  # units
    avg_entry: float = 0.0
    realized_pnl: float = 0.0
    fills: list[dict] = field(default_factory=list)

    def equity(self, mid: float) -> float:
        return self.cash + self.position * mid

    def mark_pnl(self, mid: float) -> float:
        return self.realized_pnl + self.position * (mid - self.avg_entry) if self.position else self.realized_pnl

    def maybe_trade(self, *, side: str, mid: float, bid: float, ask: float, meta: dict) -> dict | None:
        px = ask if side == "buy" else bid
        notional = self.equity(mid) * TRADE_FRAC
        if notional < 1 or px <= 0:
            return None
        qty = notional / px
        if side == "buy":
            self.cash -= qty * px
            new_pos = self.position + qty
            if new_pos != 0:
                self.avg_entry = ((self.avg_entry * self.position) + qty * px) / new_pos if self.position else px
            self.position = new_pos
        else:
            # sell (allow short)
            if self.position > 0:
                close_qty = min(self.position, qty)
                self.realized_pnl += close_qty * (px - self.avg_entry)
                self.position -= close_qty
                self.cash += close_qty * px
                qty_left = qty - close_qty
            else:
                qty_left = qty
            if qty_left > 0:
                # open/add short
                new_pos = self.position - qty_left
                # avg_entry for short: weighted
                if self.position >= 0:
                    self.avg_entry = px
                else:
                    old = abs(self.position)
                    self.avg_entry = ((self.avg_entry * old) + qty_left * px) / (old + qty_left)
                self.position = new_pos
                self.cash += qty_left * px
        fill = {"side": side, "px": px, "qty": qty, **meta}
        self.fills.append(fill)
        return fill


def parse_answers(answers: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for mkt in ("crypto", "stock"):
        d = answers.get(f"{mkt}_direction") or {}
        n = answers.get(f"{mkt}_should_trade") or {}
        e = answers.get(f"{mkt}_edge") or {}
        out[mkt] = {
            "direction": d.get("choice"),
            "dir_confidence": d.get("confidence"),
            "dir_probs": d.get("probabilities"),
            "should_trade": n.get("noul"),
            "edge_score": e.get("score"),
            "edge_confidence": e.get("confidence"),
        }
    return out


def main() -> int:
    api_key = os.environ.get("TYPESAFE_API_KEY") or ""
    if not api_key:
        RESULTS_PATH.write_text(json.dumps({"error": "TYPESAFE_API_KEY missing", "len": 0}, indent=2))
        SUMMARY_PATH.write_text("# Blocked\n\n`TYPESAFE_API_KEY` not set.\n")
        print("BLOCKED: TYPESAFE_API_KEY not set")
        return 2

    print(f"KEY_OK len={len(api_key)}")
    books = {"crypto": Book(), "stock": Book()}
    ticks: list[dict] = []
    latencies: list[float] = []
    errors: list[dict] = []
    t_end = time.time() + DURATION_S
    i = 0
    while time.time() < t_end:
        i += 1
        tick: dict[str, Any] = {"i": i, "ts": datetime.now(timezone.utc).isoformat()}
        try:
            crypto = fetch_crypto()
            stock = fetch_stock()
        except Exception as ex:
            errors.append({"i": i, "stage": "market", "error": str(ex)[:300]})
            time.sleep(INTERVAL_S)
            continue
        state = build_state(crypto, stock)
        resp, latency_ms = call_jev(api_key, state)
        latencies.append(latency_ms)
        tick["latency_ms"] = round(latency_ms, 1)
        tick["crypto_mid"] = crypto["mid"]
        tick["stock_mid"] = stock["mid"]
        if resp.get("error"):
            errors.append({"i": i, "stage": "jev", **{k: resp[k] for k in resp if k != "error"}})
            tick["jev_error"] = resp
            ticks.append(tick)
            time.sleep(INTERVAL_S)
            continue
        answers = resp.get("answers") or {}
        # Some gateways nest differently — tolerate top-level answer keys
        if not answers and any(k.endswith("_direction") for k in resp):
            answers = {k: v for k, v in resp.items() if isinstance(v, dict) and "type" in v}
        parsed = parse_answers(answers)
        tick["answers"] = parsed
        tick["model"] = resp.get("model")
        tick["usage"] = resp.get("usage")
        for mkt, mkt_data in (("crypto", crypto), ("stock", stock)):
            a = parsed.get(mkt) or {}
            direction = a.get("direction")
            noul = float(a.get("should_trade") or 0)
            conf = float(a.get("dir_confidence") or 0)
            fill = None
            if direction in ("buy", "sell") and noul >= NOUL_MIN and conf >= CONF_MIN:
                fill = books[mkt].maybe_trade(
                    side=direction,
                    mid=mkt_data["mid"],
                    bid=mkt_data["bid"],
                    ask=mkt_data["ask"],
                    meta={"i": i, "noul": noul, "conf": conf, "edge": a.get("edge_score")},
                )
            tick[f"{mkt}_fill"] = fill
            tick[f"{mkt}_equity"] = round(books[mkt].equity(mkt_data["mid"]), 2)
            tick[f"{mkt}_pnl"] = round(books[mkt].mark_pnl(mkt_data["mid"]), 2)
        ticks.append(tick)
        print(
            f"tick={i} lat={latency_ms:.0f}ms "
            f"c={parsed.get('crypto',{}).get('direction')} "
            f"s={parsed.get('stock',{}).get('direction')} "
            f"pnl_c={tick.get('crypto_pnl')} pnl_s={tick.get('stock_pnl')}"
        )
        time.sleep(INTERVAL_S)

    # final mids for summary
    try:
        c_final = fetch_crypto()["mid"]
        s_final = fetch_stock()["mid"]
    except Exception:
        c_final = ticks[-1]["crypto_mid"] if ticks else 0
        s_final = ticks[-1]["stock_mid"] if ticks else 0

    results = {
        "mode": "dry_run",
        "model": MODEL,
        "duration_s": DURATION_S,
        "interval_s": INTERVAL_S,
        "ticks": ticks,
        "errors": errors,
        "latency_ms": {
            "n": len(latencies),
            "min": round(min(latencies), 1) if latencies else None,
            "avg": round(statistics.mean(latencies), 1) if latencies else None,
            "max": round(max(latencies), 1) if latencies else None,
        },
        "books": {
            "crypto": {
                "cash": books["crypto"].cash,
                "position": books["crypto"].position,
                "equity": books["crypto"].equity(c_final),
                "pnl": books["crypto"].mark_pnl(c_final),
                "fills": len(books["crypto"].fills),
            },
            "stock": {
                "cash": books["stock"].cash,
                "position": books["stock"].position,
                "equity": books["stock"].equity(s_final),
                "pnl": books["stock"].mark_pnl(s_final),
                "fills": len(books["stock"].fills),
            },
        },
    }
    RESULTS_PATH.write_text(json.dumps(results, indent=2))

    def dist(mkt: str) -> dict[str, int]:
        counts = {"buy": 0, "sell": 0, "hold": 0, "other": 0}
        for t in ticks:
            d = ((t.get("answers") or {}).get(mkt) or {}).get("direction")
            if d in counts:
                counts[d] += 1
            else:
                counts["other"] += 1
        return counts

    summary = f"""# Jev dry-run HFT test

- Mode: paper trading only (no real orders)
- Model: `{MODEL}`
- Markets: BTCUSDT (Binance public), AAPL (Yahoo public)
- Duration: ~{DURATION_S}s, interval ~{INTERVAL_S}s
- Ticks: {len(ticks)}
- Jev latency ms: min={results['latency_ms']['min']} avg={results['latency_ms']['avg']} max={results['latency_ms']['max']}
- Crypto decisions: {dist('crypto')}
- Stock decisions: {dist('stock')}
- Crypto fills / PnL: {results['books']['crypto']['fills']} / {results['books']['crypto']['pnl']:.2f}
- Stock fills / PnL: {results['books']['stock']['fills']} / {results['books']['stock']['pnl']:.2f}
- Errors: {len(errors)}
"""
    SUMMARY_PATH.write_text(summary)
    print(summary)
    return 0 if not (len(ticks) == 0 and errors) else 1


if __name__ == "__main__":
    raise SystemExit(main())
