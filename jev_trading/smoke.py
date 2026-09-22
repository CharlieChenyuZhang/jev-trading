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
    """Primary first (v_best), then compare ledgers — same Jev answers, different execution."""
    variants = (EXPERIMENT.get("variants") or {})
    order = ["v_best", "v_loose", "v_strict", "v_large_only", "v_edge_size"]
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
            }
        )
    return out


VARIANTS = _variant_list()
PRIMARY = next((v for v in VARIANTS if v["id"] == "v_best"), VARIANTS[0] if VARIANTS else None)
COMPARE_VARIANTS = [v for v in VARIANTS if v["id"] != (PRIMARY or {}).get("id")]

MARKETS: dict[str, dict[str, Any]] = {
    "crypto": {
        "fetch_universe": fetch_crypto_universe,
        "universe": CRYPTO_UNIVERSE,
        "strategy_hint": "crypto microstructure / Coinbase USD — short-horizon move buckets",
        "candidate_k": 28,
        "default_duration_s": 45,
        "interval_s": 8.0,
        "max_symbol_notional_usd": 1500.0,
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


def variant_passes(
    *,
    variant: dict[str, Any],
    direction: str | None,
    move: str | None,
    noul: float,
    dir_tail: float,
    toxicity: float,
    size_usd: float,
) -> bool:
    if direction not in ("buy", "sell"):
        return False
    allowed = set(variant.get("allowed_moves") or [])
    if not move or (allowed and move not in allowed):
        return False
    if size_usd < 1:
        return False
    if noul < float(variant["noul_min"]):
        return False
    if dir_tail < float(variant["conf_min"]):
        return False
    if toxicity > float(variant.get("toxicity_max") or 9):
        return False
    return True


def symbol_exposure_ok(book: Portfolio, symbol: str, mid: float, add_notional: float, cap: float) -> bool:
    """Keep gross per-symbol paper exposure under cap."""
    pos = abs(float(book.positions.get(symbol, 0.0))) * float(mid or 0)
    return (pos + abs(add_notional)) <= cap + 1e-6



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
            "horizon_sec": 30,
            "return_buckets_bps": {"outer": outer_bps, "neutral": neutral_bps},
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "paper_cash_usd": 10000,
            "snapshots": compact,
            "instructions": (
                f"Candidates are the top movers from the {market_id} pool. "
                "Pick one symbol with edge, forecast the 30s return bucket, "
                "set buy/sell/hold, and choose an absolute USD size. "
                "If buy or sell, size_usd must be non-zero. Prefer trading when "
                "a directional bucket beats flat after spread/costs."
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
        mid = float(mids.get(sym, 0) or 0)
        avg = float(book.avg_entry.get(sym, mid) or 0)
        notional = qty * mid
        u_pnl = qty * (mid - avg) if avg else 0.0
        positions_detail.append(
            {
                "symbol": sym,
                "qty": round(qty, 8),
                "mid": round(mid, 6) if mid else None,
                "avg_entry": round(avg, 6) if avg else None,
                "notional_usd": round(notional, 2),
                "unrealized_pnl": round(u_pnl, 2),
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
            "label": "v_best",
            "noul_min": (PRIMARY or {}).get("noul_min"),
            "conf_min": (PRIMARY or {}).get("conf_min"),
            "toxicity_max": (PRIMARY or {}).get("toxicity_max"),
            "max_notional_usd": (PRIMARY or {}).get("max_notional_usd"),
            "why": (PRIMARY or {}).get("why"),
        },
        "experiment": EXPERIMENT.get("name"),
        "thresholds": {
            "noul_min": (PRIMARY or {}).get("noul_min"),
            "conf_min": (PRIMARY or {}).get("conf_min"),
            "toxicity_max": (PRIMARY or {}).get("toxicity_max"),
            "max_notional_usd": (PRIMARY or {}).get("max_notional_usd"),
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
        snap["why"] = cfg.get("why")
        live["shadows"][sid] = snap
    (out / "live.json").write_text(json.dumps(live, indent=2))
    (out / "recent_ticks.json").write_text(json.dumps(ticks[-200:], indent=2))


def run_smoke(market_id: str, *, duration_s: float | None = None, out_dir: Path | None = None) -> int:
    cfg = MARKETS[market_id]
    fetch_universe: Callable[[], dict[str, dict[str, Any]]] = cfg["fetch_universe"]
    universe: list[str] = list(cfg["universe"])
    duration = float(duration_s if duration_s is not None else cfg["default_duration_s"])
    interval = float(cfg["interval_s"])
    candidate_k = int(cfg.get("candidate_k") or 24)
    out = out_dir or Path.cwd() / "out" / market_id
    out.mkdir(parents=True, exist_ok=True)

    api_key = resolve_api_key()
    if not api_key:
        (out / "SUMMARY.md").write_text(
            f"# Blocked ({market_id})\n\nSet `OPENROUTER_API_KEY` or `TYPESAFE_API_KEY`.\n"
        )
        print(f"BLOCKED [{market_id}]: missing API key")
        return 2

    shadow_cfgs = list(cfg.get("shadows") or [])
    print(
        f"SMOKE [{market_id}] pool={len(universe)} candidate_k={candidate_k} "
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
                "variants": VARIANTS,
            },
            indent=2,
        )
    )
    book = Portfolio()
    shadow_books: dict[str, Portfolio] = {s["id"]: Portfolio() for s in shadow_cfgs}
    ticks: list[dict] = []
    latencies: list[float] = []
    errors: list[dict] = []
    t_end = time.time() + duration
    i = 0
    last_mids: dict[str, float] = {}

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
        last_mids = mids or last_mids
        candidates = rank_candidates(snaps, universe, candidate_k)
        if not candidates:
            errors.append({"i": i, "stage": "market", "error": "no symbols fetched"})
            time.sleep(interval)
            continue

        outer_bps, neutral_bps = vol_bands(snaps)
        tick["candidates"] = candidates
        tick["return_buckets_bps"] = {"outer": outer_bps, "neutral": neutral_bps}

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

        primary_variant = {
            "id": "v_best",
            "noul_min": cfg["noul_min"],
            "conf_min": cfg["conf_min"],
            "toxicity_max": cfg.get("toxicity_max", 2.0),
            "max_notional_usd": cfg.get("max_notional_usd", 250),
            "allowed_moves": cfg.get("allowed_moves") or ["large_up", "small_up", "large_down", "small_down"],
            "size_mode": cfg.get("size_mode", "jev_capped"),
        }
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

        if picked and picked != "none" and picked in snaps and snaps[picked].get("mid") is not None:
            snap = snaps[picked]
            tick["selected_symbol"] = picked
            tick["mid"] = snap["mid"]
            if variant_passes(
                variant=primary_variant,
                direction=direction,
                move=move,
                noul=noul,
                dir_tail=conf,
                toxicity=toxicity,
                size_usd=size_usd,
            ) and symbol_exposure_ok(book, picked, float(snap["mid"]), size_usd, sym_cap):
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
                        "book": "v_best",
                    },
                )
            for scfg in shadow_cfgs:
                sid = scfg["id"]
                v_size = size_for_variant(
                    variant=scfg,
                    direction=direction,
                    pick=picked,
                    move=move,
                    size_raw=size_raw,
                    size_probs=size_probs,
                    edge_score=float(edge_score) if edge_score is not None else None,
                )
                tick["variant_sizes"][sid] = v_size
                if variant_passes(
                    variant=scfg,
                    direction=direction,
                    move=move,
                    noul=noul,
                    dir_tail=conf,
                    toxicity=toxicity,
                    size_usd=v_size,
                ) and symbol_exposure_ok(shadow_books[sid], picked, float(snap["mid"]), v_size, sym_cap):
                    shadow_fills[sid] = shadow_books[sid].maybe_trade(
                        symbol=picked,
                        side=direction,
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
                            "move": move,
                            "size_usd_jev": v_size,
                            "book": sid,
                        },
                    )
        else:
            tick["selected_symbol"] = picked or "none"

        tick["fill"] = fill
        tick["shadow_fills"] = shadow_fills
        tick["equity"] = round(book.equity(mids), 2)
        tick["pnl"] = round(book.mark_pnl(mids), 2)
        tick["shadow_pnl"] = {sid: round(sb.mark_pnl(mids), 2) for sid, sb in shadow_books.items()}
        ticks.append(tick)

        shadow_bits = " ".join(
            f"{sid}={tick['shadow_pnl'][sid]:+.2f}/{len(shadow_books[sid].fills)}" for sid in shadow_books
        )
        print(
            f"[{market_id}] tick={i} pick={tick.get('selected_symbol')} "
            f"move={parsed.get('move')} dir={direction} size=${size_usd:.0f} "
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
            "label": "primary",
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
- Primary (noul>={cfg['noul_min']}, dir_tail>={cfg['conf_min']}): fills={results['book']['fills']} / pnl={results['book']['pnl']:.2f}
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
