from __future__ import annotations

import time
import urllib.error
from typing import Any

from .httputil import http_json

CRYPTO_UNIVERSE = [
    "BTC-USD",
    "ETH-USD",
    "SOL-USD",
    "XRP-USD",
    "DOGE-USD",
    "LINK-USD",
    "AVAX-USD",
]

STOCK_UNIVERSE = [
    "AAPL",
    "MSFT",
    "NVDA",
    "GOOGL",
    "AMZN",
    "META",
    "TSLA",
]


def fetch_crypto_product(symbol: str) -> dict[str, Any]:
    """Coinbase Exchange public REST — top-of-book + recent trades for one product."""
    base = f"https://api.exchange.coinbase.com/products/{symbol}"
    ticker = http_json(f"{base}/ticker")
    book = http_json(f"{base}/book?level=1")
    trades = http_json(f"{base}/trades?limit=20")
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
            out.append([float(row[0]), float(row[1])])
        return out

    return {
        "symbol": symbol,
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


def fetch_crypto_universe(symbols: list[str] | None = None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for sym in symbols or CRYPTO_UNIVERSE:
        try:
            out[sym] = fetch_crypto_product(sym)
        except Exception as e:
            out[sym] = {"symbol": sym, "error": str(e)[:200]}
    return out


def fetch_stock_symbol(symbol: str) -> dict[str, Any]:
    """Yahoo public chart — one equity; TOB approximated from last + 1bp spread."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1m&range=1d"
    raw = None
    last_err: Exception | None = None
    for attempt in range(4):
        try:
            raw = http_json(url, timeout=12.0)
            break
        except urllib.error.HTTPError as e:
            last_err = e
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
        raise last_err or RuntimeError(f"Yahoo chart fetch failed for {symbol}")
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
        "symbol": symbol,
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


def fetch_stock_universe(symbols: list[str] | None = None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for i, sym in enumerate(symbols or STOCK_UNIVERSE):
        try:
            out[sym] = fetch_stock_symbol(sym)
        except Exception as e:
            out[sym] = {"symbol": sym, "error": str(e)[:200]}
        # polite gap to reduce Yahoo 429s when polling a basket
        if i + 1 < len(symbols or STOCK_UNIVERSE):
            time.sleep(0.35)
    return out


# Back-compat aliases used by older scripts
def fetch_crypto_btc_usd() -> dict[str, Any]:
    return fetch_crypto_product("BTC-USD")


def fetch_stock_aapl() -> dict[str, Any]:
    return fetch_stock_symbol("AAPL")
