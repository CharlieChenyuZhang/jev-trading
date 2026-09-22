from __future__ import annotations

from typing import Any

from .httputil import http_json


def fetch_crypto_btc_usd() -> dict[str, Any]:
    """Coinbase Exchange public REST — BTC-USD top-of-book + recent trades."""
    ticker = http_json("https://api.exchange.coinbase.com/products/BTC-USD/ticker")
    book = http_json("https://api.exchange.coinbase.com/products/BTC-USD/book?level=1")
    trades = http_json("https://api.exchange.coinbase.com/products/BTC-USD/trades?limit=20")
    bid = float(ticker["bid"])
    ask = float(ticker["ask"])
    mid = (bid + ask) / 2.0
    spread_bps = (ask - bid) / mid * 10_000 if mid else 0.0
    buy_vol = sum(float(t["size"]) for t in trades if t.get("side") == "buy")
    sell_vol = sum(float(t["size"]) for t in trades if t.get("side") == "sell")
    tot = buy_vol + sell_vol
    imbalance = (buy_vol - sell_vol) / tot if tot else 0.0
    last_px = float(trades[0]["price"]) if trades else mid
    first_px = float(trades[-1]["price"]) if trades else mid
    ret_bps = (last_px - first_px) / first_px * 10_000 if first_px else 0.0
    def _lvl(rows):
        out = []
        for row in rows[:1]:
            # Coinbase level rows are [price, size, num_orders]
            out.append([float(row[0]), float(row[1])])
        return out

    return {
        "symbol": "BTC-USD",
        "asset_class": "crypto",
        "venue": "coinbase_exchange_public",
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "spread_bps": round(spread_bps, 3),
        "ret_short_bps": round(ret_bps, 3),
        "trade_imbalance": round(imbalance, 4),
        "bids": _lvl(book.get("bids", [])),
        "asks": _lvl(book.get("asks", [])),
    }


def fetch_stock_aapl() -> dict[str, Any]:
    """Yahoo public chart — AAPL; TOB approximated from last + 1bp spread."""
    import time
    import urllib.error

    url = "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?interval=1m&range=1d"
    raw = None
    last_err: Exception | None = None
    for attempt in range(4):
        try:
            raw = http_json(url, timeout=12.0)
            break
        except urllib.error.HTTPError as e:
            last_err = e
            # Yahoo often 429s under tight polling — back off and retry
            if e.code == 429 and attempt < 3:
                time.sleep(1.5 * (attempt + 1))
                continue
            raise
        except Exception as e:
            last_err = e
            if attempt < 3:
                time.sleep(0.8 * (attempt + 1))
                continue
            raise
    if raw is None:
        raise last_err or RuntimeError("Yahoo chart fetch failed")
    result = raw["chart"]["result"][0]
    meta = result["meta"]
    quotes = result["indicators"]["quote"][0]
    closes = [c for c in (quotes.get("close") or []) if c is not None]
    last = float(meta.get("regularMarketPrice") or (closes[-1] if closes else 0))
    prev = float(closes[-6]) if len(closes) >= 6 else float(closes[0] if closes else last)
    ret_bps = (last - prev) / prev * 10_000 if prev else 0.0
    spread_bps = 1.0
    half = last * spread_bps / 10_000 / 2
    bid, ask = last - half, last + half
    return {
        "symbol": "AAPL",
        "asset_class": "stock",
        "venue": "yahoo_chart_public",
        "bid": round(bid, 4),
        "ask": round(ask, 4),
        "mid": round(last, 4),
        "spread_bps": spread_bps,
        "ret_short_bps": round(ret_bps, 3),
        "trade_imbalance": 0.0,
        "note": "stock TOB approximated from last + 1bp spread proxy",
    }
