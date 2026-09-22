from __future__ import annotations

import json
import threading
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from .httputil import http_json

_DATA = Path(__file__).resolve().parent / "data"
_MID_CACHE: dict[str, float] = {}
_QUOTE_CACHE: dict[str, dict[str, Any]] = {}
_QUOTE_TS: dict[str, float] = {}
_ROT_LOCK = threading.Lock()
_ROT_IDX: dict[str, int] = {"crypto": 0, "stock": 0}

JEV_CHOICE_SYMBOL_CAP = 254  # choice options max ~255 including "none"
QUOTE_TTL_S = 180.0
CRYPTO_BATCH = 48
STOCK_BATCH = 40

_FALLBACK_CRYPTO = ["BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "DOGE-USD", "LINK-USD", "AVAX-USD"]
_FALLBACK_STOCK = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA"]


def _load_symbols(path: Path, fallback: list[str]) -> list[str]:
    if not path.exists():
        return list(fallback)
    raw = json.loads(path.read_text())
    if isinstance(raw, list):
        return [str(x) for x in raw]
    if isinstance(raw, dict) and "symbols" in raw:
        return [str(x) for x in raw["symbols"]]
    return list(fallback)


CRYPTO_UNIVERSE = _load_symbols(_DATA / "coinbase_usd_top254.json", _FALLBACK_CRYPTO)[:JEV_CHOICE_SYMBOL_CAP]
STOCK_UNIVERSE = _load_symbols(_DATA / "stock_universe.json", _FALLBACK_STOCK)[:JEV_CHOICE_SYMBOL_CAP]


def _next_batch(key: str, universe: list[str], batch: int) -> list[str]:
    if not universe:
        return []
    with _ROT_LOCK:
        i = _ROT_IDX.get(key, 0) % len(universe)
        out = []
        for k in range(batch):
            out.append(universe[(i + k) % len(universe)])
        _ROT_IDX[key] = (i + batch) % len(universe)
    # always include a few anchors so majors stay fresh
    anchors = universe[: min(8, len(universe))]
    seen = set(out)
    for a in anchors:
        if a not in seen:
            out.append(a)
            seen.add(a)
    return out


def _cache_put(sym: str, row: dict[str, Any]) -> None:
    if row.get("error"):
        return
    _QUOTE_CACHE[sym] = row
    _QUOTE_TS[sym] = time.time()


def _cache_view(universe: list[str], *, ttl: float = QUOTE_TTL_S) -> dict[str, dict[str, Any]]:
    now = time.time()
    out: dict[str, dict[str, Any]] = {}
    for sym in universe:
        row = _QUOTE_CACHE.get(sym)
        ts = _QUOTE_TS.get(sym, 0)
        if row and (now - ts) <= ttl:
            out[sym] = row
    return out


def fetch_crypto_product(symbol: str, *, lite: bool = True) -> dict[str, Any]:
    """Coinbase Exchange public REST. lite=True: ticker only (fast for large universes)."""
    base = f"https://api.exchange.coinbase.com/products/{symbol}"
    last_err: Exception | None = None
    ticker = None
    for attempt in range(3):
        try:
            ticker = http_json(f"{base}/ticker", timeout=8.0)
            break
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429 and attempt < 2:
                time.sleep(0.6 * (attempt + 1))
                continue
            raise
        except Exception as e:
            last_err = e
            if attempt < 2:
                time.sleep(0.4 * (attempt + 1))
                continue
            raise
    if ticker is None:
        raise last_err or RuntimeError(f"ticker failed for {symbol}")

    bid = float(ticker["bid"])
    ask = float(ticker["ask"])
    mid = (bid + ask) / 2.0
    spread_bps = (ask - bid) / mid * 10_000 if mid else 0.0
    imbalance = 0.0
    ret_bps = 0.0
    prev = _MID_CACHE.get(symbol)
    if prev and prev > 0:
        ret_bps = (mid - prev) / prev * 10_000
    _MID_CACHE[symbol] = mid

    if not lite:
        book = http_json(f"{base}/book?level=1", timeout=8.0)
        trades = http_json(f"{base}/trades?limit=20", timeout=8.0)
        buy_vol = sum(float(t["size"]) for t in trades if t.get("side") == "buy")
        sell_vol = sum(float(t["size"]) for t in trades if t.get("side") == "sell")
        tot = buy_vol + sell_vol
        imbalance = (buy_vol - sell_vol) / tot if tot else 0.0
        last_px = float(trades[0]["price"]) if trades else mid
        first_px = float(trades[-1]["price"]) if trades else mid
        if first_px:
            ret_bps = (last_px - first_px) / first_px * 10_000

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

    return {
        "symbol": symbol,
        "asset_class": "crypto",
        "venue": "coinbase_exchange_public",
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "spread_bps": round(spread_bps, 3),
        "ret_short_bps": round(ret_bps, 3),
        "trade_imbalance": 0.0,
        "lite": True,
    }


def fetch_crypto_universe(symbols: list[str] | None = None, *, workers: int = 10) -> dict[str, dict[str, Any]]:
    """Refresh a rotating batch; return full-universe view from TTL cache + fresh."""
    universe = list(symbols or CRYPTO_UNIVERSE)
    batch = _next_batch("crypto", universe, CRYPTO_BATCH)

    def _one(sym: str) -> tuple[str, dict[str, Any]]:
        try:
            return sym, fetch_crypto_product(sym, lite=True)
        except Exception as e:
            return sym, {"symbol": sym, "error": str(e)[:200]}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_one, s) for s in batch]
        for fut in as_completed(futs):
            sym, row = fut.result()
            _cache_put(sym, row)

    out = _cache_view(universe)
    # ensure batch errors still visible this tick if no cache
    for sym in batch:
        if sym not in out:
            # leave missing; smoke will only ask Jev about quoted ok symbols
            pass
    return out if out else {s: {"symbol": s, "error": "no_quote_yet"} for s in batch}


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


def fetch_stock_universe(symbols: list[str] | None = None, *, workers: int = 6) -> dict[str, dict[str, Any]]:
    """Refresh a rotating Yahoo batch; return TTL-cached full-universe view."""
    universe = list(symbols or STOCK_UNIVERSE)
    batch = _next_batch("stock", universe, STOCK_BATCH)

    def _one(sym: str) -> tuple[str, dict[str, Any]]:
        try:
            return sym, fetch_stock_symbol(sym)
        except Exception as e:
            return sym, {"symbol": sym, "error": str(e)[:200]}

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_one, s) for s in batch]
        for fut in as_completed(futs):
            sym, row = fut.result()
            _cache_put(sym, row)
            time.sleep(0.03)

    out = _cache_view(universe)
    return out if out else {s: {"symbol": s, "error": "no_quote_yet"} for s in batch}


def fetch_crypto_btc_usd() -> dict[str, Any]:
    return fetch_crypto_product("BTC-USD", lite=False)


def fetch_stock_aapl() -> dict[str, Any]:
    return fetch_stock_symbol("AAPL")
