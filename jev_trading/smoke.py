#!/usr/bin/env python3
"""Separate smoke runners for crypto vs stock (dry-run only).

Layered Jev decisions (pick → move → direction → noul → size), with
vol-adaptive return buckets and top-K candidates each tick.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .jev_client import call_jev, questions_for_universe, resolve_api_key
from .markets import (
    CRYPTO_UNIVERSE,
    STOCK_UNIVERSE,
    fetch_crypto_universe,
    fetch_stock_universe,
)
from .paper import Portfolio

def _load_experiment() -> dict[str, Any]:
    path = Path(__file__).resolve().parent / "data" / "experiment.json"
    if path.exists():
        return json.loads(path.read_text())
    return {}


EXPERIMENT = _load_experiment()


def _variant_list() -> list[dict[str, Any]]:
    """Primary first (exp_A), then compare ledgers A–H — same Jev answers, different execution."""
    variants = (EXPERIMENT.get("variants") or {})
    order = [
        "exp_A_short",
        "exp_B_short_med",
        "exp_C_multi",
        "exp_D_imbalance",
        "exp_E_exit_overlay",
        "exp_F_inv_skew",
        "exp_G_regime_mr",
        "exp_H_markout_veto",
        "v2_best",
        "v2_loose",
        "v2_strict",
    ]
    out: list[dict[str, Any]] = []
    for vid in order:
        raw = variants.get(vid)
        if not raw:
            continue
        out.append(
            {
                "id": vid,
                "role": raw.get("role", "compare"),
                "why": raw.get("why", ""),
                "noul_min": float(raw["noul_min"]),
                "conf_min": float(raw["dir_tail_min"]),  # conf_min == dir_tail gate
                "toxicity_max": float(raw.get("toxicity_max", 2.0)),
                "max_notional_usd": float(raw.get("max_notional_usd", 250)),
                "allowed_moves": list(raw.get("allowed_moves") or []),
                "size_mode": raw.get("size_mode", "jev_capped"),
                "require_agree": list(raw.get("require_agree") or ["move"]),
                "block_1d_opposite": bool(raw.get("block_1d_opposite", False)),
                # D
                "imbalance_min": float(raw.get("imbalance_min", 0.15)),
                "require_imbalance_agree": bool(raw.get("require_imbalance_agree", False)),
                # E
                "exit_overlay": bool(raw.get("exit_overlay", False)),
                "take_profit_bps": float(raw.get("take_profit_bps", 12)),
                "trail_arm_bps": float(raw.get("trail_arm_bps", 8)),
                "trail_drawdown_bps": float(raw.get("trail_drawdown_bps", 6)),
                "max_hold_sec": raw.get("max_hold_sec"),
                "max_hold_sec_crypto": float(raw.get("max_hold_sec_crypto", 900)),
                "max_hold_sec_stock": float(raw.get("max_hold_sec_stock", 1800)),
                # F
                "inv_skew": bool(raw.get("inv_skew", False)),
                "inv_skew_max_frac": float(raw.get("inv_skew_max_frac", 0.40)),
                "inv_skew_min_cash_frac": float(raw.get("inv_skew_min_cash_frac", 0.25)),
                "inv_skew_noul_boost": float(raw.get("inv_skew_noul_boost", 0.05)),
                "inv_skew_boost_sell": bool(raw.get("inv_skew_boost_sell", True)),
                # G
                "fade_in_chop": bool(raw.get("fade_in_chop", False)),
                "chop_size_cap": float(raw.get("chop_size_cap", 100)),
                "regime_median_abs_bps": float(raw.get("regime_median_abs_bps", 8.0)),
                # H
                "markout_veto": bool(raw.get("markout_veto", False)),
                "markout_adverse_bps": float(raw.get("markout_adverse_bps", -8.0)),
                "markout_window_sec": list(raw.get("markout_window_sec") or [60, 120]),
                "markout_lookback_sec": float(raw.get("markout_lookback_sec", 1800)),
                "markout_min_fills": int(raw.get("markout_min_fills", 3)),
            }
        )
    return out


VARIANTS = _variant_list()
_VARIANTS_BY_ID: dict[str, dict[str, Any]] = {v["id"]: v for v in VARIANTS}


def _resolve_primary_id(market_id: str | None = None) -> str | None:
    """Resolve primary variant id from experiment.json (per-market override supported)."""
    by_m = EXPERIMENT.get("primary_by_market") or {}
    if market_id and isinstance(by_m, dict) and by_m.get(market_id):
        return str(by_m[market_id])
    if EXPERIMENT.get("primary"):
        return str(EXPERIMENT["primary"])
    for cand in ("exp_A_short", "v2_best", "v_best"):
        if cand in _VARIANTS_BY_ID:
            return cand
    return VARIANTS[0]["id"] if VARIANTS else None


def _primary_for_market(market_id: str | None = None) -> dict[str, Any] | None:
    """Full variant dict for this market's primary (includes G/E/F/H overlay fields)."""
    pid = _resolve_primary_id(market_id)
    if not pid:
        return None
    if pid in _VARIANTS_BY_ID:
        return dict(_VARIANTS_BY_ID[pid])  # shallow copy so callers can annotate safely
    # fall back to A / first known
    for cand in ("exp_A_short", "v2_best", "v_best"):
        if cand in _VARIANTS_BY_ID:
            return dict(_VARIANTS_BY_ID[cand])
    return dict(VARIANTS[0]) if VARIANTS else None


def _compare_for_market(market_id: str | None = None) -> list[dict[str, Any]]:
    primary = _primary_for_market(market_id)
    pid = (primary or {}).get("id")
    return [dict(v) for v in VARIANTS if v["id"] != pid]


# Module-level default: experiment primary (or A). Per-market resolution happens in run_smoke.
PRIMARY = _primary_for_market(None)
COMPARE_VARIANTS = _compare_for_market(None)

MARKETS: dict[str, dict[str, Any]] = {
    "crypto": {
        "fetch_universe": fetch_crypto_universe,
        "universe": CRYPTO_UNIVERSE,
        "strategy_hint": "crypto microstructure / Coinbase USD — short-horizon move buckets",
        "candidate_k": 28,
        "default_duration_s": 45,
        "interval_s": 8.0,
        "max_symbol_notional_usd": 1500.0,
        "max_open_symbols": 8,
        "rth_only": False,
        # primary knobs live on PRIMARY; shadows = compare variants
        "noul_min": float(PRIMARY["noul_min"]) if PRIMARY else 0.45,
        "conf_min": float(PRIMARY["conf_min"]) if PRIMARY else 0.42,
        "toxicity_max": float(PRIMARY["toxicity_max"]) if PRIMARY else 2.0,
        "max_notional_usd": float(PRIMARY["max_notional_usd"]) if PRIMARY else 250.0,
        "allowed_moves": list(PRIMARY["allowed_moves"]) if PRIMARY else ["large_up", "small_up", "large_down", "small_down"],
        "size_mode": (PRIMARY or {}).get("size_mode", "jev_capped"),
        "shadows": COMPARE_VARIANTS,
    },
    "stock": {
        "fetch_universe": fetch_stock_universe,
        "universe": STOCK_UNIVERSE,
        "strategy_hint": "US equity multi-name short-horizon — session-aware move buckets",
        "candidate_k": 24,
        "default_duration_s": 45,
        "interval_s": 25.0,
        "max_symbol_notional_usd": 1500.0,
        "max_open_symbols": 8,
        "rth_only": True,
        "noul_min": float(PRIMARY["noul_min"]) if PRIMARY else 0.45,
        "conf_min": float(PRIMARY["conf_min"]) if PRIMARY else 0.42,
        "toxicity_max": float(PRIMARY["toxicity_max"]) if PRIMARY else 2.0,
        "max_notional_usd": float(PRIMARY["max_notional_usd"]) if PRIMARY else 250.0,
        "allowed_moves": list(PRIMARY["allowed_moves"]) if PRIMARY else ["large_up", "small_up", "large_down", "small_down"],
        "size_mode": (PRIMARY or {}).get("size_mode", "jev_capped"),
        "shadows": COMPARE_VARIANTS,
    },
}

MOVE_TO_DIR = {
    "large_up": "buy",
    "small_up": "buy",
    "large_down": "sell",
    "small_down": "sell",
    "flat": "hold",
}


def move_sign(move: str | None) -> str:
    """Map move bucket to buy/sell/hold."""
    if move in MOVE_TO_DIR:
        return MOVE_TO_DIR[move]
    if move in ("up",):
        return "buy"
    if move in ("down",):
        return "sell"
    return "hold"


def horizons_agree(parsed: dict[str, Any], keys: list[str]) -> bool:
    """True if all named move horizons share the same non-hold side."""
    signs = [move_sign(parsed.get(k)) for k in keys]
    sides = {s for s in signs if s in ("buy", "sell")}
    if len(sides) != 1:
        return False
    # none of the required horizons may be flat/hold
    return all(s in ("buy", "sell") for s in signs)


def blocked_by_1d(parsed: dict[str, Any], direction: str | None) -> bool:
    trend = parsed.get("trend_1d")
    if direction == "buy" and trend == "down":
        return True
    if direction == "sell" and trend == "up":
        return True
    return False


SIZE_EDGE_MAP = [
    (0.5, 0.0),
    (1.5, 50.0),
    (2.5, 100.0),
    (3.5, 250.0),
    (4.5, 500.0),
    (9.0, 1000.0),
]


def edge_size_usd(edge_score: float | None, max_notional_usd: float) -> float:
    e = float(edge_score or 0)
    mapped = 50.0
    for thr, usd in SIZE_EDGE_MAP:
        if e <= thr:
            mapped = usd
            break
    return float(min(max(mapped, 0.0), max_notional_usd))


def size_for_variant(
    *,
    variant: dict[str, Any],
    direction: str | None,
    pick: str | None,
    move: str | None,
    size_raw: float,
    size_probs: dict | None,
    edge_score: float | None,
) -> float:
    if not pick or pick == "none" or direction in (None, "hold") or move == "flat":
        return 0.0
    allowed = set(variant.get("allowed_moves") or [])
    if move and allowed and move not in allowed:
        return 0.0
    cap = float(variant.get("max_notional_usd") or 250)
    mode = variant.get("size_mode") or "jev_capped"
    if mode == "edge_only":
        return edge_size_usd(edge_score, cap)
    return resolve_size_usd(
        direction=direction,
        pick=pick,
        size_choice=float(size_raw or 0),
        size_probs=size_probs if isinstance(size_probs, dict) else None,
        edge_score=float(edge_score) if edge_score is not None else None,
        max_notional_usd=cap,
    )


def imbalance_agrees(
    direction: str | None,
    imbalance: float | None,
    imbalance_min: float = 0.15,
) -> bool:
    """D: buy only if imb > +min; sell only if imb < -min; missing/0 fails (conservative)."""
    if direction not in ("buy", "sell"):
        return False
    if imbalance is None:
        return False
    try:
        imb = float(imbalance)
    except (TypeError, ValueError):
        return False
    if imb == 0.0:
        return False
    if direction == "buy":
        return imb > float(imbalance_min)
    return imb < -float(imbalance_min)


def estimate_regime(
    snaps: dict[str, dict[str, Any]],
    candidates: list[str],
    *,
    median_abs_bps: float = 8.0,
) -> str:
    """G: trend if abs(median ret_5m) high and same-sign across candidates; else chop."""
    rets: list[float] = []
    for sym in candidates:
        s = snaps.get(sym) or {}
        if s.get("mid") is None or s.get("error"):
            continue
        try:
            rets.append(float(s.get("ret_5m_bps") or 0.0))
        except (TypeError, ValueError):
            continue
    if len(rets) < 3:
        return "chop"
    med = statistics.median(rets)
    if abs(med) < float(median_abs_bps):
        return "chop"
    signs = {1 if r > 0 else (-1 if r < 0 else 0) for r in rets if r != 0}
    if len(signs) == 1 and 0 not in signs:
        return "trend"
    # require majority same sign as median
    same = sum(1 for r in rets if (r > 0 and med > 0) or (r < 0 and med < 0))
    if same / len(rets) >= 0.7 and abs(med) >= float(median_abs_bps):
        return "trend"
    return "chop"


def apply_regime_fade(
    *,
    regime: str,
    direction: str | None,
    move: str | None,
    size_usd: float,
    variant: dict[str, Any],
) -> tuple[str | None, str | None, float, bool]:
    """G: in chop, fade large_up/large_down only; skip small; cap size. Returns (dir, move, size, ok)."""
    if not variant.get("fade_in_chop") or regime != "chop":
        return direction, move, size_usd, True
    if move in ("small_up", "small_down", "flat", None):
        return "hold", move, 0.0, False
    if move == "large_up":
        return "sell", move, min(float(size_usd), float(variant.get("chop_size_cap") or 100)), True
    if move == "large_down":
        return "buy", move, min(float(size_usd), float(variant.get("chop_size_cap") or 100)), True
    return "hold", move, 0.0, False


def inv_skew_adjust(
    *,
    book: Portfolio,
    mids: dict[str, float],
    direction: str | None,
    size_usd: float,
    variant: dict[str, Any],
    noul_min: float,
) -> tuple[bool, float, float]:
    """F: inventory skew blocks/boosts. Returns (ok, adj_size, effective_noul_min)."""
    if not variant.get("inv_skew"):
        return True, size_usd, noul_min
    eq = max(book.equity(mids), 1.0)
    long_n = book.net_long_notional(mids)
    short_n = book.net_short_notional(mids)
    cash_frac = book.cash / eq
    max_frac = float(variant.get("inv_skew_max_frac") or 0.40)
    min_cash = float(variant.get("inv_skew_min_cash_frac") or 0.25)
    boost = float(variant.get("inv_skew_noul_boost") or 0.05)
    eff_noul = float(noul_min)
    adj = float(size_usd)
    long_heavy = long_n > max_frac * eq
    short_heavy = short_n > max_frac * eq
    if direction == "buy":
        if long_heavy or cash_frac < min_cash:
            return False, 0.0, eff_noul
        if long_heavy:
            eff_noul = float(noul_min) + boost
        # soft: when long-heavy already blocked above; soft bump when long-ish (>20%)
        if long_n > 0.20 * eq:
            eff_noul = max(eff_noul, float(noul_min) + boost)
    elif direction == "sell":
        if short_heavy:
            return False, 0.0, eff_noul
        if long_heavy and variant.get("inv_skew_boost_sell"):
            adj = min(adj * 1.25, float(variant.get("max_notional_usd") or adj))
    return True, adj, eff_noul


def unrealized_bps(qty: float, mid: float, avg: float) -> float:
    if not avg or avg <= 0 or mid <= 0 or abs(qty) < 1e-12:
        return 0.0
    if qty > 0:
        return (mid - avg) / avg * 10_000.0
    return (avg - mid) / avg * 10_000.0


def trail_drawdown_bps(qty: float, mid: float, peak_mid: float) -> float:
    if peak_mid <= 0 or mid <= 0 or abs(qty) < 1e-12:
        return 0.0
    if qty > 0:
        return (peak_mid - mid) / peak_mid * 10_000.0
    return (mid - peak_mid) / peak_mid * 10_000.0


class ExitOverlayState:
    """Per-variant per-symbol entry_ts / peak_mid / trail_armed for E."""

    def __init__(self) -> None:
        self.by_variant: dict[str, dict[str, dict[str, Any]]] = {}

    def on_fill(self, variant_id: str, symbol: str, mid: float, ts: float) -> None:
        book = self.by_variant.setdefault(variant_id, {})
        st = book.get(symbol)
        if st is None:
            book[symbol] = {"entry_ts": ts, "peak_mid": float(mid), "trail_armed": False}
        else:
            # keep first entry_ts; refresh peak favorably
            st["peak_mid"] = self._favor_peak(st.get("peak_mid"), mid, None)

    def clear_if_flat(self, variant_id: str, symbol: str, qty: float) -> None:
        if abs(qty) < 1e-12:
            self.by_variant.get(variant_id, {}).pop(symbol, None)

    @staticmethod
    def _favor_peak(peak: float | None, mid: float, qty: float | None) -> float:
        if peak is None or peak <= 0:
            return float(mid)
        return float(peak)

    def update_peak(self, variant_id: str, symbol: str, qty: float, mid: float) -> None:
        st = self.by_variant.get(variant_id, {}).get(symbol)
        if not st or mid <= 0:
            return
        peak = float(st.get("peak_mid") or mid)
        if qty > 0:
            st["peak_mid"] = max(peak, mid)
        else:
            st["peak_mid"] = min(peak, mid) if peak > 0 else mid


class MarkoutTracker:
    """H: rolling adverse markout per variant/symbol after fills."""

    def __init__(self) -> None:
        # variant -> list of fill records
        self.fills: dict[str, list[dict[str, Any]]] = {}

    def record_fill(
        self,
        variant_id: str,
        *,
        symbol: str,
        side: str,
        mid: float,
        ts: float,
    ) -> None:
        self.fills.setdefault(variant_id, []).append(
            {
                "symbol": symbol,
                "side": side,
                "fill_mid": float(mid),
                "ts": float(ts),
                "markout_bps": None,
                "marked": False,
            }
        )

    def update(self, variant_id: str, mids: dict[str, float], now_ts: float, window: list[float]) -> None:
        lo, hi = float(window[0]), float(window[1]) if len(window) > 1 else float(window[0])
        for rec in self.fills.get(variant_id, []):
            if rec.get("marked"):
                continue
            age = now_ts - float(rec["ts"])
            if age < lo:
                continue
            if age > hi and rec.get("markout_bps") is None:
                # missed window — mark with whatever mid we have now once past hi
                pass
            if age > hi + 30:
                rec["marked"] = True
                continue
            mid = float(mids.get(rec["symbol"]) or 0)
            if mid <= 0:
                continue
            fill_mid = float(rec["fill_mid"])
            if fill_mid <= 0:
                continue
            move_bps = (mid - fill_mid) / fill_mid * 10_000.0
            # adverse vs fill side: buy hurt when mid down; sell hurt when mid up
            if rec["side"] == "buy":
                adverse = move_bps  # positive favorable
            else:
                adverse = -move_bps
            # store signed "against" as negative when adverse
            rec["markout_bps"] = adverse
            if age >= lo:
                rec["marked"] = True

    def avg_adverse(
        self,
        variant_id: str,
        symbol: str,
        *,
        now_ts: float,
        lookback_sec: float,
        min_fills: int,
    ) -> float | None:
        rows = [
            r
            for r in self.fills.get(variant_id, [])
            if r.get("symbol") == symbol
            and r.get("markout_bps") is not None
            and (now_ts - float(r["ts"])) <= lookback_sec
        ]
        if len(rows) < min_fills:
            return None
        return sum(float(r["markout_bps"]) for r in rows) / len(rows)

    def veto(
        self,
        variant: dict[str, Any],
        symbol: str | None,
        *,
        now_ts: float,
    ) -> bool:
        if not variant.get("markout_veto") or not symbol:
            return False
        avg = self.avg_adverse(
            variant["id"],
            symbol,
            now_ts=now_ts,
            lookback_sec=float(variant.get("markout_lookback_sec") or 1800),
            min_fills=int(variant.get("markout_min_fills") or 3),
        )
        if avg is None:
            return False
        return avg < float(variant.get("markout_adverse_bps") or -8.0)


def variant_passes(
    *,
    variant: dict[str, Any],
    direction: str | None,
    move: str | None,
    noul: float,
    dir_tail: float,
    toxicity: float,
    size_usd: float,
    parsed: dict[str, Any] | None = None,
    imbalance: float | None = None,
    effective_noul_min: float | None = None,
    markout_blocked: bool = False,
) -> bool:
    if direction not in ("buy", "sell"):
        return False
    allowed = set(variant.get("allowed_moves") or [])
    if not move or (allowed and move not in allowed):
        return False
    if size_usd < 1:
        return False
    noul_gate = float(effective_noul_min) if effective_noul_min is not None else float(variant["noul_min"])
    if noul < noul_gate:
        return False
    if dir_tail < float(variant["conf_min"]):
        return False
    if toxicity > float(variant.get("toxicity_max") or 9):
        return False
    parsed = parsed or {}
    req = list(variant.get("require_agree") or ["move"])
    if req and not horizons_agree(parsed, req):
        return False
    if variant.get("block_1d_opposite") and blocked_by_1d(parsed, direction):
        return False
    if variant.get("require_imbalance_agree"):
        if not imbalance_agrees(direction, imbalance, float(variant.get("imbalance_min") or 0.15)):
            return False
    if markout_blocked:
        return False
    return True


def symbol_exposure_ok(book: Portfolio, symbol: str, mid: float, add_notional: float, cap: float) -> bool:
    """Keep gross per-symbol paper exposure under cap."""
    pos = abs(float(book.positions.get(symbol, 0.0))) * float(mid or 0)
    return (pos + abs(add_notional)) <= cap + 1e-6


def in_us_rth(now_utc: datetime | None = None) -> bool:
    """Approx US cash equity RTH in America/Los_Angeles (no holiday calendar)."""
    from zoneinfo import ZoneInfo
    now = now_utc or datetime.now(timezone.utc)
    local = now.astimezone(ZoneInfo("America/Los_Angeles"))
    if local.weekday() >= 5:
        return False
    minutes = local.hour * 60 + local.minute
    # 06:30–13:00 PT ≈ 09:30–16:00 ET
    return 6 * 60 + 30 <= minutes <= 13 * 60


def open_symbol_count(book: Portfolio) -> int:
    return sum(1 for q in book.positions.values() if abs(q) > 1e-12)


def allow_new_symbol(book: Portfolio, symbol: str, max_open: int) -> bool:
    if symbol in book.positions and abs(book.positions.get(symbol, 0.0)) > 1e-12:
        return True
    return open_symbol_count(book) < max_open




def vol_bands(snaps: dict[str, dict[str, Any]]) -> tuple[float, float]:
    """Adaptive return bucket edges (bps), floored for fees/spread."""
    rets = [
        abs(float(s.get("ret_short_bps") or 0))
        for s in snaps.values()
        if s.get("mid") is not None and not s.get("error")
    ]
    if not rets:
        return 8.0, 2.0
    sigma = statistics.median(rets) or 2.0
    # ~30s horizon vs short window: scale up a bit; keep fee floor
    outer = max(6.0, min(40.0, 1.8 * sigma))
    neutral = max(1.5, min(outer / 3.0, 6.0))
    return round(outer, 2), round(neutral, 2)


def rank_candidates(snaps: dict[str, dict[str, Any]], universe: list[str], k: int) -> list[str]:
    scored: list[tuple[float, str]] = []
    for sym in universe:
        s = snaps.get(sym) or {}
        if s.get("mid") is None or s.get("error"):
            continue
        ret = abs(float(s.get("ret_short_bps") or 0))
        imb = abs(float(s.get("trade_imbalance") or 0))
        spr = float(s.get("spread_bps") or 0)
        # prefer movement + imbalance, lightly penalize wide spreads
        score = ret + 40.0 * imb - 0.15 * spr
        scored.append((score, sym))
    scored.sort(reverse=True)
    out = [sym for _, sym in scored[:k]]
    # always keep a few majors if present
    for anchor in ("BTC-USD", "ETH-USD", "SOL-USD", "AAPL", "MSFT", "NVDA", "SPY", "QQQ"):
        if anchor in snaps and snaps[anchor].get("mid") is not None and anchor not in out:
            out.append(anchor)
    return out[: max(k, len(out))]


def resolve_size_usd(
    *,
    direction: str | None,
    pick: str | None,
    size_choice: float,
    size_probs: dict | None,
    edge_score: float | None,
    max_notional_usd: float = 500.0,
) -> float:
    """Absolute size from Jev; buy/sell never 0; capped; no $5k lottery from weak mass."""
    if not pick or pick == "none" or direction in (None, "hold"):
        return 0.0

    def _edge_map() -> float:
        e = float(edge_score or 0)
        mapped = 50.0
        for thr, usd in SIZE_EDGE_MAP:
            if e <= thr:
                mapped = usd
                break
        return mapped

    chosen = 0.0
    if size_choice >= 1:
        chosen = float(size_choice)
    else:
        # Prefer edge-mapped size when Jev's explicit choice is 0 (common inconsistency)
        # Only use size_probs if a modest bucket clearly leads among non-zero.
        probs = size_probs or {}
        modest = []
        for k, pr in probs.items():
            try:
                usd = float(k)
                p = float(pr)
            except (TypeError, ValueError):
                continue
            if 50 <= usd <= max_notional_usd:
                modest.append((p, usd))
        if modest:
            modest.sort(reverse=True)
            if modest[0][0] >= 0.15:
                chosen = modest[0][1]
        if chosen < 1:
            chosen = _edge_map()
    if chosen < 1:
        chosen = 50.0
    return float(min(chosen, max_notional_usd))


def dir_tail(direction: str | None, dir_probs: dict | None) -> float:
    """Directional probability mass for the chosen side (open threshold uses this)."""
    probs = dir_probs or {}
    if direction == "buy":
        return float(probs.get("buy") or 0)
    if direction == "sell":
        return float(probs.get("sell") or 0)
    return 0.0


def build_state(
    market_id: str,
    snaps: dict[str, dict],
    strategy_hint: str,
    candidates: list[str],
    *,
    outer_bps: float,
    neutral_bps: float,
    pool_size: int,
) -> str:
    compact = []
    for sym in candidates:
        s = snaps.get(sym) or {}
        if s.get("error") or s.get("mid") is None:
            continue
        compact.append(
            {
                "symbol": sym,
                "mid": s.get("mid"),
                "spread_bps": s.get("spread_bps"),
                "ret_short_bps": s.get("ret_short_bps"),
                "ret_1m_bps": s.get("ret_1m_bps"),
                "ret_5m_bps": s.get("ret_5m_bps"),
                "ret_10m_bps": s.get("ret_10m_bps"),
                "ret_1h_bps": s.get("ret_1h_bps"),
                "ret_1d_bps": s.get("ret_1d_bps"),
                "trade_imbalance": s.get("trade_imbalance"),
            }
        )
    return json.dumps(
        {
            "mode": "paper_trading_dry_run_universe",
            "market": market_id,
            "strategy": strategy_hint,
            "pool_size": pool_size,
            "candidate_count": len(compact),
            "horizon_sec": {"short": 30, "m5": 300, "m10": 600, "h1": 3600, "d1": 86400},
            "return_buckets_bps": {"outer": outer_bps, "neutral": neutral_bps},
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "paper_cash_usd": 10000,
            "snapshots": compact,
            "instructions": (
                f"Candidates are the top movers from the {market_id} pool. "
                "Pick one symbol. Forecast return buckets for short (~30s-1m), "
                "5m, 10m, 1h, and a 1d trend filter. State includes realized "
                "ret_*_bps when available. Primary action follows the SHORT bucket; "
                "execution variants may require longer horizons to agree."
            ),
        },
        separators=(",", ":"),
    )


def parse_answers(answers: dict[str, Any]) -> dict[str, Any]:
    d = answers.get("direction") or {}
    n = answers.get("should_trade") or {}
    e = answers.get("edge") or {}
    p = answers.get("pick_symbol") or {}
    s = answers.get("size_usd") or {}
    m = answers.get("move") or {}
    m5 = answers.get("move_5m") or {}
    m10 = answers.get("move_10m") or {}
    m1h = answers.get("move_1h") or {}
    t1d = answers.get("trend_1d") or {}
    t = answers.get("toxicity") or {}
    size_raw = s.get("choice")
    try:
        size_choice = float(size_raw) if size_raw is not None else 0.0
    except (TypeError, ValueError):
        size_choice = 0.0

    pick = p.get("choice")
    direction = d.get("choice")
    move = m.get("choice")
    # Move bucket is the primary forecast; align action to it (FMZ-style).
    if move in MOVE_TO_DIR:
        mapped = MOVE_TO_DIR[move]
        if mapped == "hold":
            direction = "hold"
        else:
            direction = mapped

    edge_score = e.get("score")
    size_probs = s.get("probabilities")
    size_usd = resolve_size_usd(
        direction=direction,
        pick=pick,
        size_choice=size_choice,
        size_probs=size_probs if isinstance(size_probs, dict) else None,
        edge_score=float(edge_score) if edge_score is not None else None,
        max_notional_usd=500.0,
    )

    dir_probs = d.get("probabilities") if isinstance(d.get("probabilities"), dict) else {}
    return {
        "pick_symbol": pick,
        "pick_confidence": p.get("confidence"),
        "pick_probs": p.get("probabilities"),
        "move": move,
        "move_confidence": m.get("confidence"),
        "move_probs": m.get("probabilities"),
        "move_5m": m5.get("choice"),
        "move_10m": m10.get("choice"),
        "move_1h": m1h.get("choice"),
        "trend_1d": t1d.get("choice"),
        "trend_1d_probs": t1d.get("probabilities"),
        "direction": direction,
        "dir_confidence": d.get("confidence"),
        "dir_probs": dir_probs,
        "dir_tail": dir_tail(direction, dir_probs),
        "should_trade": n.get("noul"),
        "edge_score": edge_score,
        "edge_confidence": e.get("confidence"),
        "toxicity": t.get("score"),
        "toxicity_confidence": t.get("confidence"),
        "size_usd_raw": size_choice,
        "size_usd": size_usd,
        "size_confidence": s.get("confidence"),
        "size_probs": size_probs,
    }


def _portfolio_snap(book: Portfolio, mids: dict[str, float]) -> dict[str, Any]:
    positions_detail = []
    for sym, qty in book.positions.items():
        raw = mids.get(sym)
        mid = book.mark_mid(sym, raw) if hasattr(book, "mark_mid") else float(raw or 0)
        avg = float(book.avg_entry.get(sym, mid) or 0)
        mark = mid if mid > 0 else avg
        notional = qty * mark
        u_pnl = qty * (mid - avg) if (mid > 0 and avg) else 0.0
        positions_detail.append(
            {
                "symbol": sym,
                "qty": round(qty, 8),
                "mid": round(mid, 6) if mid else None,
                "avg_entry": round(avg, 6) if avg else None,
                "notional_usd": round(notional, 2),
                "unrealized_pnl": round(u_pnl, 2),
                "mark_stale": bool(mid <= 0),
                "side": "long" if qty > 0 else "short",
            }
        )
    positions_detail.sort(key=lambda x: abs(x.get("notional_usd") or 0), reverse=True)
    recent_fills = []
    for f in book.fills[-40:]:
        recent_fills.append(
            {
                "symbol": f.get("symbol"),
                "side": f.get("side"),
                "px": f.get("px"),
                "qty": f.get("qty"),
                "notional_usd": f.get("notional_usd"),
                "i": f.get("i"),
                "move": f.get("move"),
                "noul": f.get("noul"),
                "dir_tail": f.get("dir_tail"),
                "book": f.get("book"),
            }
        )
    return {
        "equity": round(book.equity(mids), 2),
        "pnl": round(book.mark_pnl(mids), 2),
        "fills": len(book.fills),
        "cash": round(book.cash, 2),
        "positions": {k: round(v, 8) for k, v in book.positions.items()},
        "positions_detail": positions_detail,
        "recent_fills": recent_fills,
        "last_fill": recent_fills[-1] if recent_fills else None,
    }



def append_decision_log(out: Path, record: dict[str, Any]) -> None:
    """Append one raw investment decision (JSONL). Survives restarts; never rewrite."""
    out.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
    with (out / "decisions.jsonl").open("a", encoding="utf-8") as f:
        f.write(line)
    archive = Path(__file__).resolve().parents[1] / "logs" / "raw_decisions"
    archive.mkdir(parents=True, exist_ok=True)
    market = str(record.get("market") or out.name)
    with (archive / f"{market}.jsonl").open("a", encoding="utf-8") as f:
        f.write(line)


def _checkpoint(
    out: Path,
    *,
    market_id: str,
    ticks: list,
    latencies: list,
    errors: list,
    book: Portfolio,
    shadow_books: dict[str, Portfolio],
    shadow_cfgs: list[dict],
    mids: dict[str, float],
    universe: list[str],
    primary_variant: dict[str, Any] | None = None,
) -> None:
    dist = {"buy": 0, "sell": 0, "hold": 0, "other": 0}
    picks: dict[str, int] = {}
    for x in ticks:
        a = x.get("answers") or {}
        d = a.get("direction")
        if d in dist:
            dist[d] += 1
        else:
            dist["other"] += 1
        ps = a.get("pick_symbol") or "unknown"
        picks[ps] = picks.get(ps, 0) + 1
    live = {
        "market": market_id,
        "universe": universe,
        "ticks_so_far": len(ticks),
        "started_ts": ticks[0]["ts"] if ticks else None,
        "last_ts": ticks[-1]["ts"] if ticks else None,
        "latency_ms": {
            "n": len(latencies),
            "min": round(min(latencies), 1) if latencies else None,
            "avg": round(sum(latencies) / len(latencies), 1) if latencies else None,
            "max": round(max(latencies), 1) if latencies else None,
        },
        "book": {
            **_portfolio_snap(book, mids),
            "label": (primary_variant or PRIMARY or {}).get("id") or "exp_A_short",
            "noul_min": (primary_variant or PRIMARY or {}).get("noul_min"),
            "conf_min": (primary_variant or PRIMARY or {}).get("conf_min"),
            "toxicity_max": (primary_variant or PRIMARY or {}).get("toxicity_max"),
            "max_notional_usd": (primary_variant or PRIMARY or {}).get("max_notional_usd"),
            "require_agree": (primary_variant or PRIMARY or {}).get("require_agree") or ["move"],
            "block_1d_opposite": bool((primary_variant or PRIMARY or {}).get("block_1d_opposite", False)),
            "why": (primary_variant or PRIMARY or {}).get("why"),
            "fade_in_chop": bool((primary_variant or PRIMARY or {}).get("fade_in_chop", False)),
            "exit_overlay": bool((primary_variant or PRIMARY or {}).get("exit_overlay", False)),
            "inv_skew": bool((primary_variant or PRIMARY or {}).get("inv_skew", False)),
            "markout_veto": bool((primary_variant or PRIMARY or {}).get("markout_veto", False)),
        },
        "experiment": EXPERIMENT.get("name"),
        "strategy_primary": (primary_variant or PRIMARY or {}).get("id"),
        "thresholds": {
            "noul_min": (primary_variant or PRIMARY or {}).get("noul_min"),
            "conf_min": (primary_variant or PRIMARY or {}).get("conf_min"),
            "toxicity_max": (primary_variant or PRIMARY or {}).get("toxicity_max"),
            "max_notional_usd": (primary_variant or PRIMARY or {}).get("max_notional_usd"),
        },
        "decision_dist": dist,
        "pick_dist": picks,
        "errors": len(errors),
        "last_answers": (ticks[-1].get("answers") if ticks else None),
        "shadows": {},
    }
    cfg_by_id = {c["id"]: c for c in shadow_cfgs}
    for sid, sb in shadow_books.items():
        snap = _portfolio_snap(sb, mids)
        cfg = cfg_by_id.get(sid) or {}
        snap["noul_min"] = cfg.get("noul_min")
        snap["conf_min"] = cfg.get("conf_min")
        snap["toxicity_max"] = cfg.get("toxicity_max")
        snap["max_notional_usd"] = cfg.get("max_notional_usd")
        snap["allowed_moves"] = cfg.get("allowed_moves")
        snap["size_mode"] = cfg.get("size_mode")
        snap["require_agree"] = cfg.get("require_agree")
        snap["block_1d_opposite"] = cfg.get("block_1d_opposite")
        snap["why"] = cfg.get("why")
        snap["require_imbalance_agree"] = cfg.get("require_imbalance_agree")
        snap["exit_overlay"] = cfg.get("exit_overlay")
        snap["inv_skew"] = cfg.get("inv_skew")
        snap["fade_in_chop"] = cfg.get("fade_in_chop")
        snap["markout_veto"] = cfg.get("markout_veto")
        live["shadows"][sid] = snap
    if ticks:
        live["regime"] = ticks[-1].get("regime")
        live["trade_imbalance"] = ticks[-1].get("trade_imbalance")
        live["variant_pass"] = ticks[-1].get("variant_pass")
    (out / "live.json").write_text(json.dumps(live, indent=2))
    (out / "recent_ticks.json").write_text(json.dumps(ticks[-200:], indent=2))


def run_smoke(market_id: str, *, duration_s: float | None = None, out_dir: Path | None = None) -> int:
    cfg = dict(MARKETS[market_id])  # shallow copy; override gates per market primary
    fetch_universe: Callable[[], dict[str, dict[str, Any]]] = cfg["fetch_universe"]
    universe: list[str] = list(cfg["universe"])
    duration = float(duration_s if duration_s is not None else cfg["default_duration_s"])
    interval = float(cfg["interval_s"])
    candidate_k = int(cfg.get("candidate_k") or 24)
    out = out_dir or Path.cwd() / "out" / market_id
    out.mkdir(parents=True, exist_ok=True)

    primary_variant = _primary_for_market(market_id)
    if not primary_variant:
        print(f"BLOCKED [{market_id}]: no primary variant in experiment.json")
        return 2
    shadow_cfgs = _compare_for_market(market_id)
    # Apply primary gates onto cfg so legacy cfg[...] reads match this market's primary
    cfg["noul_min"] = float(primary_variant["noul_min"])
    cfg["conf_min"] = float(primary_variant["conf_min"])
    cfg["toxicity_max"] = float(primary_variant.get("toxicity_max", 2.0))
    cfg["max_notional_usd"] = float(primary_variant.get("max_notional_usd", 250))
    cfg["allowed_moves"] = list(primary_variant.get("allowed_moves") or [])
    cfg["size_mode"] = primary_variant.get("size_mode", "jev_capped")
    cfg["shadows"] = shadow_cfgs

    api_key = resolve_api_key()
    if not api_key:
        (out / "SUMMARY.md").write_text(
            f"# Blocked ({market_id})\n\nSet `OPENROUTER_API_KEY` or `TYPESAFE_API_KEY`.\n"
        )
        print(f"BLOCKED [{market_id}]: missing API key")
        return 2

    print(
        f"SMOKE [{market_id}] primary={primary_variant.get('id')} "
        f"shadows={len(shadow_cfgs)} pool={len(universe)} candidate_k={candidate_k} "
        f"gates noul>={cfg['noul_min']} dir_tail>={cfg['conf_min']} "
        f"key_ok len={len(api_key)} duration={duration}s",
        flush=True,
    )
    started = datetime.now(timezone.utc).isoformat()
    (out / "run_meta.json").write_text(
        json.dumps(
            {
                "market": market_id,
                "universe": universe,
                "started_ts": started,
                "duration_s": duration,
                "interval_s": interval,
                "candidate_k": candidate_k,
                "ends_ts_approx": datetime.fromtimestamp(time.time() + duration, tz=timezone.utc).isoformat(),
                "strategy": cfg["strategy_hint"],
                "thresholds": {
                    "noul_min": cfg["noul_min"],
                    "dir_tail_min": cfg["conf_min"],
                    "toxicity_max": cfg.get("toxicity_max"),
                    "max_notional_usd": cfg.get("max_notional_usd"),
                    "label": "primary",
                },
                "shadows": shadow_cfgs,
                "paper_start_cash": 10000.0,
                "selection": "jev_pick_top_k_movers",
                "experiment": EXPERIMENT.get("name"),
                "strategy_primary": primary_variant.get("id"),
                "primary_by_market": EXPERIMENT.get("primary_by_market"),
                "variants": VARIANTS,
            },
            indent=2,
        )
    )
    book = Portfolio()
    shadow_books: dict[str, Portfolio] = {s["id"]: Portfolio() for s in shadow_cfgs}
    exit_state = ExitOverlayState()
    markout_tracker = MarkoutTracker()
    ticks: list[dict] = []
    latencies: list[float] = []
    errors: list[dict] = []
    t_end = time.time() + duration
    i = 0
    last_mids: dict[str, float] = {}
    last_regime: str = "chop"

    while time.time() < t_end:
        i += 1
        tick: dict[str, Any] = {"i": i, "ts": datetime.now(timezone.utc).isoformat(), "market": market_id}
        try:
            snaps = fetch_universe()
        except Exception as ex:
            errors.append({"i": i, "stage": "market", "error": str(ex)[:300]})
            time.sleep(interval)
            continue

        mids = {sym: float(s["mid"]) for sym, s in snaps.items() if s.get("mid") is not None}
        last_mids = {**last_mids, **mids}
        book.remember_mids(mids)
        for sb in shadow_books.values():
            sb.remember_mids(mids)
        candidates = rank_candidates(snaps, universe, candidate_k)
        if not candidates:
            errors.append({"i": i, "stage": "market", "error": "no symbols fetched"})
            time.sleep(interval)
            continue

        outer_bps, neutral_bps = vol_bands(snaps)
        tick["candidates"] = candidates
        tick["return_buckets_bps"] = {"outer": outer_bps, "neutral": neutral_bps}
        g_cfg = next((v for v in VARIANTS if v.get("fade_in_chop")), None)
        regime = estimate_regime(
            snaps,
            candidates,
            median_abs_bps=float((g_cfg or {}).get("regime_median_abs_bps") or 8.0),
        )
        last_regime = regime
        tick["regime"] = regime

        state = build_state(
            market_id,
            snaps,
            cfg["strategy_hint"],
            candidates,
            outer_bps=outer_bps,
            neutral_bps=neutral_bps,
            pool_size=len(universe),
        )
        questions = questions_for_universe(
            market_id,
            candidates,
            strategy_hint=cfg["strategy_hint"],
            outer_bps=outer_bps,
            neutral_bps=neutral_bps,
        )
        resp, latency_ms = call_jev(api_key, state, questions)
        latencies.append(latency_ms)
        tick["latency_ms"] = round(latency_ms, 1)
        tick["mids"] = {c: mids[c] for c in candidates if c in mids}

        if resp.get("error"):
            errors.append({"i": i, "stage": "jev", **{k: resp[k] for k in resp if k != "error"}})
            tick["jev_error"] = {k: resp[k] for k in resp if k != "error"}
            ticks.append(tick)
            append_decision_log(
                out,
                {
                    "ts": tick.get("ts"),
                    "market": market_id,
                    "tick": i,
                    "experiment": EXPERIMENT.get("name"),
                    "strategy_primary": primary_variant.get("id"),
                    "error": True,
                    "jev_error": tick.get("jev_error"),
                    "latency_ms": tick.get("latency_ms"),
                },
            )
            if i == 1 or i % 6 == 0:
                _checkpoint(
                    out,
                    market_id=market_id,
                    ticks=ticks,
                    latencies=latencies,
                    errors=errors,
                    book=book,
                    shadow_books=shadow_books,
                    shadow_cfgs=shadow_cfgs,
                    mids=last_mids,
                    universe=universe,
                    primary_variant=primary_variant,
                )
            time.sleep(interval)
            continue

        answers = resp.get("answers") or {}
        parsed = parse_answers(answers)
        tick["answers"] = parsed
        tick["model"] = resp.get("model")
        tick["usage"] = resp.get("usage")

        picked = parsed.get("pick_symbol")
        direction = parsed.get("direction")
        move = parsed.get("move")
        noul = float(parsed.get("should_trade") or 0)
        conf = float(parsed.get("dir_tail") or 0)  # directional tail, not concentration
        toxicity = float(parsed.get("toxicity") or 0)
        size_raw = float(parsed.get("size_usd_raw") or 0)
        edge_score = parsed.get("edge_score")
        size_probs = parsed.get("size_probs") if isinstance(parsed.get("size_probs"), dict) else None
        sym_cap = float(cfg.get("max_symbol_notional_usd") or 1500)

        # primary_variant already resolved for this market (full dict from _variant_list)
        size_usd = size_for_variant(
            variant=primary_variant,
            direction=direction,
            pick=picked,
            move=move,
            size_raw=size_raw,
            size_probs=size_probs,
            edge_score=float(edge_score) if edge_score is not None else None,
        )
        tick["size_usd"] = size_usd
        tick["toxicity"] = toxicity
        tick["variant_sizes"] = {}
        fill = None
        shadow_fills: dict[str, Any] = {}
        now_ts = time.time()
        max_open = int(cfg.get("max_open_symbols") or 8)
        session_ok = (not cfg.get("rth_only")) or in_us_rth()
        tick["session_ok"] = session_ok

        # --- E exit overlay: run before entry, E books only ---
        for scfg in shadow_cfgs:
            if not scfg.get("exit_overlay"):
                continue
            sid = scfg["id"]
            sb = shadow_books[sid]
            hold_sec = scfg.get("max_hold_sec")
            if hold_sec is None:
                hold_sec = (
                    scfg.get("max_hold_sec_crypto")
                    if market_id == "crypto"
                    else scfg.get("max_hold_sec_stock")
                )
            hold_sec = float(hold_sec or (900 if market_id == "crypto" else 1800))
            tp = float(scfg.get("take_profit_bps") or 12)
            arm = float(scfg.get("trail_arm_bps") or 8)
            dd = float(scfg.get("trail_drawdown_bps") or 6)
            for sym in list(sb.positions.keys()):
                qty = float(sb.positions.get(sym, 0.0) or 0.0)
                if abs(qty) < 1e-12:
                    continue
                snap_e = snaps.get(sym) or {}
                mid_e = float(snap_e.get("mid") or sb.mark_mid(sym) or 0)
                if mid_e <= 0:
                    continue
                avg = float(sb.avg_entry.get(sym) or mid_e)
                u_bps = unrealized_bps(qty, mid_e, avg)
                st = exit_state.by_variant.get(sid, {}).get(sym) or {
                    "entry_ts": now_ts,
                    "peak_mid": mid_e,
                    "trail_armed": False,
                }
                exit_state.by_variant.setdefault(sid, {})[sym] = st
                if u_bps >= arm:
                    st["trail_armed"] = True
                exit_state.update_peak(sid, sym, qty, mid_e)
                st = exit_state.by_variant[sid][sym]
                reason = None
                if u_bps >= tp:
                    reason = "take_profit"
                elif (now_ts - float(st.get("entry_ts") or now_ts)) >= hold_sec:
                    reason = "max_hold"
                elif st.get("trail_armed") and trail_drawdown_bps(qty, mid_e, float(st.get("peak_mid") or mid_e)) >= dd:
                    reason = "trail_stop"
                if not reason:
                    continue
                xf = sb.close_position(
                    symbol=sym,
                    mid=mid_e,
                    bid=float(snap_e.get("bid") or mid_e),
                    ask=float(snap_e.get("ask") or mid_e),
                    meta={
                        "i": i,
                        "book": sid,
                        "exit": True,
                        "exit_reason": reason,
                        "unrealized_bps": round(u_bps, 2),
                        "move": move,
                    },
                )
                if xf:
                    shadow_fills[sid] = xf
                    exit_state.clear_if_flat(sid, sym, float(sb.positions.get(sym, 0.0) or 0.0))
                    markout_tracker.record_fill(
                        sid, symbol=sym, side=xf["side"], mid=mid_e, ts=now_ts
                    )

        # H markout update each tick
        for scfg in shadow_cfgs:
            if scfg.get("markout_veto"):
                markout_tracker.update(
                    scfg["id"],
                    mids,
                    now_ts,
                    list(scfg.get("markout_window_sec") or [60, 120]),
                )

        picked_imb = None
        if picked and picked != "none" and picked in snaps and snaps[picked].get("mid") is not None:
            snap = snaps[picked]
            try:
                picked_imb = float(snap.get("trade_imbalance"))
            except (TypeError, ValueError):
                picked_imb = None
            tick["trade_imbalance"] = picked_imb
            tick["selected_symbol"] = picked
            tick["mid"] = snap["mid"]
            tick["open_symbols"] = open_symbol_count(book)
            if (
                session_ok
                and allow_new_symbol(book, picked, max_open)
                and variant_passes(
                    variant=primary_variant,
                    direction=direction,
                    move=move,
                    noul=noul,
                    dir_tail=conf,
                    toxicity=toxicity,
                    size_usd=size_usd,
                    parsed=parsed,
                    imbalance=picked_imb,
                )
                and symbol_exposure_ok(book, picked, float(snap["mid"]), size_usd, sym_cap)
            ):
                fill = book.maybe_trade(
                    symbol=picked,
                    side=direction,
                    mid=snap["mid"],
                    bid=snap["bid"],
                    ask=snap["ask"],
                    notional_usd=size_usd,
                    meta={
                        "i": i,
                        "noul": noul,
                        "dir_tail": conf,
                        "toxicity": toxicity,
                        "edge": edge_score,
                        "move": move,
                        "size_usd_jev": size_usd,
                        "size_usd_raw": size_raw,
                        "book": primary_variant["id"],
                    },
                )
            for scfg in shadow_cfgs:
                sid = scfg["id"]
                # G regime fade may invert direction / size
                v_dir, v_move, _, g_ok = apply_regime_fade(
                    regime=regime,
                    direction=direction,
                    move=move,
                    size_usd=size_usd,
                    variant=scfg,
                )
                if scfg.get("fade_in_chop") and not g_ok:
                    tick["variant_sizes"][sid] = 0.0
                    continue
                use_dir = v_dir if scfg.get("fade_in_chop") else direction
                use_move = v_move if scfg.get("fade_in_chop") else move
                v_size = size_for_variant(
                    variant=scfg,
                    direction=use_dir,
                    pick=picked,
                    move=use_move,
                    size_raw=size_raw,
                    size_probs=size_probs,
                    edge_score=float(edge_score) if edge_score is not None else None,
                )
                if scfg.get("fade_in_chop") and regime == "chop" and g_ok:
                    v_size = min(v_size, float(scfg.get("chop_size_cap") or 100))
                # F inventory skew
                skew_ok, v_size, eff_noul = inv_skew_adjust(
                    book=shadow_books[sid],
                    mids=mids,
                    direction=use_dir,
                    size_usd=v_size,
                    variant=scfg,
                    noul_min=float(scfg.get("noul_min") or 0.42),
                )
                tick["variant_sizes"][sid] = v_size
                mo_block = markout_tracker.veto(scfg, picked, now_ts=now_ts)
                # skip new entry if this sid already got an exit fill this tick
                if sid in shadow_fills and isinstance(shadow_fills[sid], dict) and shadow_fills[sid].get("exit"):
                    continue
                if (
                    session_ok
                    and skew_ok
                    and allow_new_symbol(shadow_books[sid], picked, max_open)
                    and variant_passes(
                        variant=scfg,
                        direction=use_dir,
                        move=use_move,
                        noul=noul,
                        dir_tail=conf,
                        toxicity=toxicity,
                        size_usd=v_size,
                        parsed=parsed,
                        imbalance=picked_imb,
                        effective_noul_min=eff_noul,
                        markout_blocked=mo_block,
                    )
                    and symbol_exposure_ok(shadow_books[sid], picked, float(snap["mid"]), v_size, sym_cap)
                ):
                    sf = shadow_books[sid].maybe_trade(
                        symbol=picked,
                        side=use_dir,
                        mid=snap["mid"],
                        bid=snap["bid"],
                        ask=snap["ask"],
                        notional_usd=v_size,
                        meta={
                            "i": i,
                            "noul": noul,
                            "dir_tail": conf,
                            "toxicity": toxicity,
                            "edge": edge_score,
                            "move": use_move,
                            "size_usd_jev": v_size,
                            "book": sid,
                            "regime": regime,
                            "trade_imbalance": picked_imb,
                        },
                    )
                    if sf:
                        shadow_fills[sid] = sf
                        if scfg.get("exit_overlay"):
                            exit_state.on_fill(sid, picked, float(snap["mid"]), now_ts)
                        if scfg.get("markout_veto"):
                            markout_tracker.record_fill(
                                sid,
                                symbol=picked,
                                side=use_dir,
                                mid=float(snap["mid"]),
                                ts=now_ts,
                            )
        else:
            tick["selected_symbol"] = picked or "none"

        tick["fill"] = fill
        tick["shadow_fills"] = shadow_fills
        tick["equity"] = round(book.equity(mids), 2)
        tick["pnl"] = round(book.mark_pnl(mids), 2)
        tick["shadow_pnl"] = {sid: round(sb.mark_pnl(mids), 2) for sid, sb in shadow_books.items()}
        # Whether each A–H variant would pass this tick (same Jev answers, different gates)
        variant_pass: dict[str, bool] = {}
        for v in VARIANTS:
            v_cfg = primary_variant if v["id"] == primary_variant.get("id") else v
            v_dir, v_move, _, g_ok = apply_regime_fade(
                regime=regime,
                direction=direction,
                move=move,
                size_usd=size_usd,
                variant=v_cfg,
            )
            use_dir = v_dir if v_cfg.get("fade_in_chop") else direction
            use_move = v_move if v_cfg.get("fade_in_chop") else move
            if v_cfg.get("fade_in_chop") and not g_ok:
                variant_pass[v["id"]] = False
                continue
            if v["id"] == primary_variant.get("id"):
                v_size = size_usd
            elif v["id"] in (tick.get("variant_sizes") or {}):
                v_size = float(tick["variant_sizes"][v["id"]])
            else:
                v_size = size_for_variant(
                    variant=v_cfg,
                    direction=use_dir,
                    pick=picked,
                    move=use_move,
                    size_raw=size_raw,
                    size_probs=size_probs,
                    edge_score=float(edge_score) if edge_score is not None else None,
                )
            book_for_v = book if v["id"] == primary_variant.get("id") else shadow_books.get(v["id"], book)
            skew_ok, v_size2, eff_noul = inv_skew_adjust(
                book=book_for_v,
                mids=mids,
                direction=use_dir,
                size_usd=v_size,
                variant=v_cfg,
                noul_min=float(v_cfg.get("noul_min") or 0.42),
            )
            mo_block = markout_tracker.veto(v_cfg, picked, now_ts=now_ts) if v_cfg.get("markout_veto") else False
            variant_pass[v["id"]] = bool(
                skew_ok
                and variant_passes(
                    variant=v_cfg,
                    direction=use_dir,
                    move=use_move,
                    noul=noul,
                    dir_tail=conf,
                    toxicity=toxicity,
                    size_usd=v_size2,
                    parsed=parsed,
                    imbalance=picked_imb if picked else None,
                    effective_noul_min=eff_noul,
                    markout_blocked=mo_block,
                )
            )
        tick["variant_pass"] = variant_pass
        ticks.append(tick)
        append_decision_log(
            out,
            {
                "ts": tick.get("ts"),
                "market": market_id,
                "tick": i,
                "experiment": EXPERIMENT.get("name"),
                "strategy_primary": primary_variant.get("id"),
                "strategy_hint": cfg.get("strategy_hint"),
                "gates": {
                    "noul_min": primary_variant.get("noul_min"),
                    "dir_tail_min": primary_variant.get("conf_min"),
                    "toxicity_max": primary_variant.get("toxicity_max"),
                    "max_notional_usd": primary_variant.get("max_notional_usd"),
                    "allowed_moves": primary_variant.get("allowed_moves"),
                    "size_mode": primary_variant.get("size_mode"),
                    "max_open_symbols": cfg.get("max_open_symbols"),
                    "rth_only": cfg.get("rth_only"),
                    "require_agree": primary_variant.get("require_agree"),
                    "block_1d_opposite": primary_variant.get("block_1d_opposite"),
                },
                "horizons": {
                    "move": parsed.get("move"),
                    "move_5m": parsed.get("move_5m"),
                    "move_10m": parsed.get("move_10m"),
                    "move_1h": parsed.get("move_1h"),
                    "trend_1d": parsed.get("trend_1d"),
                },
                "regime": tick.get("regime"),
                "trade_imbalance": tick.get("trade_imbalance"),
                "variant_pass": variant_pass,
                "candidates": tick.get("candidates"),
                "return_buckets_bps": tick.get("return_buckets_bps"),
                "model": tick.get("model"),
                "latency_ms": tick.get("latency_ms"),
                "usage": tick.get("usage"),
                "jev_raw_answers": answers,
                "jev_parsed": parsed,
                "execution": {
                    "selected_symbol": tick.get("selected_symbol"),
                    "session_ok": tick.get("session_ok"),
                    "open_symbols": tick.get("open_symbols"),
                    "size_usd_primary": size_usd,
                    "variant_sizes": tick.get("variant_sizes"),
                    "primary_fill": fill,
                    "shadow_fills": {k: (v if v is None or isinstance(v, dict) else str(v)) for k, v in shadow_fills.items()},
                    "equity": tick.get("equity"),
                    "pnl": tick.get("pnl"),
                    "shadow_pnl": tick.get("shadow_pnl"),
                },
            },
        )

        shadow_bits = " ".join(
            f"{sid}={tick['shadow_pnl'][sid]:+.2f}/{len(shadow_books[sid].fills)}" for sid in shadow_books
        )
        print(
            f"[{market_id}] tick={i} pick={tick.get('selected_symbol')} "
            f"move={parsed.get('move')}/{parsed.get('move_5m')}/{parsed.get('move_10m')}/{parsed.get('move_1h')} d1={parsed.get('trend_1d')} dir={direction} size=${size_usd:.0f} "
            f"noul={noul:.2f} dir_tail={conf:.2f} tox={toxicity:.2f} lat={latency_ms:.0f}ms "
            f"primary_pnl={tick['pnl']}"
            + (f" | {shadow_bits}" if shadow_bits else ""),
            flush=True,
        )
        if i == 1 or i % 6 == 0:
            _checkpoint(
                out,
                market_id=market_id,
                ticks=ticks,
                latencies=latencies,
                errors=errors,
                book=book,
                shadow_books=shadow_books,
                shadow_cfgs=shadow_cfgs,
                mids=mids,
                universe=universe,
                primary_variant=primary_variant,
            )
        time.sleep(interval)

    try:
        final_snaps = fetch_universe()
        final_mids = {sym: float(s["mid"]) for sym, s in final_snaps.items() if s.get("mid") is not None}
    except Exception:
        final_mids = last_mids

    dist = {"buy": 0, "sell": 0, "hold": 0, "other": 0}
    picks: dict[str, int] = {}
    for t in ticks:
        a = t.get("answers") or {}
        d = a.get("direction")
        if d in dist:
            dist[d] += 1
        else:
            dist["other"] += 1
        ps = a.get("pick_symbol") or "unknown"
        picks[ps] = picks.get(ps, 0) + 1

    results = {
        "mode": "dry_run_smoke_universe",
        "market": market_id,
        "universe": universe,
        "strategy": cfg["strategy_hint"],
        "model": ticks[-1].get("model") if ticks else None,
        "duration_s": duration,
        "interval_s": interval,
        "thresholds": {"noul_min": cfg["noul_min"], "dir_tail_min": cfg["conf_min"]},
        "strategy_primary": primary_variant.get("id"),
        "ticks": ticks,
        "errors": errors,
        "latency_ms": {
            "n": len(latencies),
            "min": round(min(latencies), 1) if latencies else None,
            "avg": round(statistics.mean(latencies), 1) if latencies else None,
            "max": round(max(latencies), 1) if latencies else None,
        },
        "book": {
            **_portfolio_snap(book, final_mids),
            "label": primary_variant.get("id") or "primary",
            "thresholds": {"noul_min": cfg["noul_min"], "dir_tail_min": cfg["conf_min"]},
        },
        "shadow_books": {
            sid: {
                **_portfolio_snap(sb, final_mids),
                "noul_min": next(s["noul_min"] for s in shadow_cfgs if s["id"] == sid),
                "conf_min": next(s["conf_min"] for s in shadow_cfgs if s["id"] == sid),
            }
            for sid, sb in shadow_books.items()
        },
        "decision_dist": dist,
        "pick_dist": picks,
    }
    (out / "results.json").write_text(json.dumps(results, indent=2))
    _checkpoint(
        out,
        market_id=market_id,
        ticks=ticks,
        latencies=latencies,
        errors=errors,
        book=book,
        shadow_books=shadow_books,
        shadow_cfgs=shadow_cfgs,
        mids=final_mids,
        universe=universe,
        primary_variant=primary_variant,
    )

    shadow_lines = "\n".join(
        f"- Shadow `{sid}` (noul>={sc['noul_min']}, dir_tail>={sc['conf_min']}): "
        f"fills={results['shadow_books'][sid]['fills']} / pnl={results['shadow_books'][sid]['pnl']:.2f}"
        for sid, sc in ((s["id"], s) for s in shadow_cfgs)
    ) or "- Shadows: none"
    summary = f"""# Smoke ({market_id})

- Mode: paper experiment · top-K movers → Jev layered decisions · multi-ledger variants
- Experiment: {EXPERIMENT.get('name')}
- Pool size: {len(universe)} · candidate_k={candidate_k}
- Strategy: {cfg['strategy_hint']}
- Duration: ~{duration}s / interval ~{interval}s
- Ticks: {len(ticks)}
- Latency ms: min={results['latency_ms']['min']} avg={results['latency_ms']['avg']} max={results['latency_ms']['max']}
- Pick dist: {picks}
- Decisions: {dist}
- Primary `{primary_variant.get('id')}` (noul>={cfg['noul_min']}, dir_tail>={cfg['conf_min']}): fills={results['book']['fills']} / pnl={results['book']['pnl']:.2f}
{shadow_lines}
- Errors: {len(errors)}
"""
    (out / "SUMMARY.md").write_text(summary)
    print(summary)
    return 0 if ticks or not errors else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Universe Jev paper-trading smoke (crypto | stock)")
    parser.add_argument("market", choices=sorted(MARKETS.keys()))
    parser.add_argument("--duration", type=float, default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    return run_smoke(args.market, duration_s=args.duration, out_dir=args.out)


if __name__ == "__main__":
    raise SystemExit(main())
