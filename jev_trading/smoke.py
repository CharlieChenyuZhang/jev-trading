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

MARKETS: dict[str, dict[str, Any]] = {
    "crypto": {
        "fetch_universe": fetch_crypto_universe,
        "universe": CRYPTO_UNIVERSE,
        "strategy_hint": "crypto microstructure / Coinbase USD — short-horizon move buckets",
        # Open thresholds calibrated to observed Jev noul/dir tails (FMZ: open vs wait)
        "noul_min": 0.38,
        "conf_min": 0.35,  # uses directional tail P(buy)|P(sell), not concentration
        "toxicity_max": 2.2,  # skip when adverse-selection score too high
        "max_notional_usd": 500.0,
        "candidate_k": 32,
        "default_duration_s": 45,
        "interval_s": 8.0,
        "shadows": [
            {"id": "shadow_030_020", "noul_min": 0.30, "conf_min": 0.20},
            {"id": "shadow_040_030", "noul_min": 0.40, "conf_min": 0.30},
            {"id": "shadow_strict_060_055", "noul_min": 0.60, "conf_min": 0.55},
        ],
    },
    "stock": {
        "fetch_universe": fetch_stock_universe,
        "universe": STOCK_UNIVERSE,
        "strategy_hint": "US equity multi-name short-horizon — session-aware move buckets",
        "noul_min": 0.40,
        "conf_min": 0.35,
        "toxicity_max": 2.2,
        "max_notional_usd": 500.0,
        "candidate_k": 24,
        "default_duration_s": 45,
        "interval_s": 25.0,
        "shadows": [
            {"id": "shadow_030_020", "noul_min": 0.30, "conf_min": 0.20},
            {"id": "shadow_040_030", "noul_min": 0.40, "conf_min": 0.30},
            {"id": "shadow_strict_060_055", "noul_min": 0.60, "conf_min": 0.55},
        ],
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
    return {
        "equity": round(book.equity(mids), 2),
        "pnl": round(book.mark_pnl(mids), 2),
        "fills": len(book.fills),
        "cash": round(book.cash, 2),
        "positions": {k: round(v, 8) for k, v in book.positions.items()},
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
        "book": {**_portfolio_snap(book, mids), "label": "primary"},
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
        max_notion = float(cfg.get("max_notional_usd") or 500)
        tox_max = float(cfg.get("toxicity_max") or 2.2)
        # Re-clamp with market cap; skip flat / toxic
        size_usd = float(parsed.get("size_usd") or 0)
        size_usd = min(size_usd, max_notion) if size_usd >= 1 else 0.0
        if move == "flat" or direction == "hold":
            size_usd = 0.0
            direction = "hold"
        tick["size_usd"] = size_usd
        tick["toxicity"] = toxicity
        fill = None
        shadow_fills: dict[str, Any] = {}

        if picked and picked != "none" and picked in snaps and snaps[picked].get("mid") is not None:
            snap = snaps[picked]
            tick["selected_symbol"] = picked
            tick["mid"] = snap["mid"]
            if (
                direction in ("buy", "sell")
                and move in ("large_up", "small_up", "large_down", "small_down")
                and size_usd >= 1
                and noul >= cfg["noul_min"]
                and conf >= cfg["conf_min"]
                and toxicity <= tox_max
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
                        "edge": parsed.get("edge_score"),
                        "move": parsed.get("move"),
                        "size_usd_jev": size_usd,
                        "size_usd_raw": parsed.get("size_usd_raw"),
                        "book": "primary",
                    },
                )
            if (
                direction in ("buy", "sell")
                and move in ("large_up", "small_up", "large_down", "small_down")
                and size_usd >= 1
                and toxicity <= tox_max
            ):
                for scfg in shadow_cfgs:
                    if noul >= scfg["noul_min"] and conf >= scfg["conf_min"]:
                        sid = scfg["id"]
                        shadow_fills[sid] = shadow_books[sid].maybe_trade(
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
                                "edge": parsed.get("edge_score"),
                                "move": parsed.get("move"),
                                "size_usd_jev": size_usd,
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

- Mode: paper only · top-K movers → Jev layered decisions
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
