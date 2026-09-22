#!/usr/bin/env python3
"""Separate smoke runners for crypto vs stock (dry-run only).

Jev selects a symbol from a universe each tick, then decides direction.
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
        "strategy_hint": "crypto microstructure / multi-coin Coinbase USD pairs",
        "noul_min": 0.60,
        "conf_min": 0.55,
        "default_duration_s": 45,
        "interval_s": 8.0,  # large Coinbase basket (lite parallel)
        "shadows": [
            {"id": "shadow_035_025", "noul_min": 0.35, "conf_min": 0.25},
            {"id": "shadow_040_030", "noul_min": 0.40, "conf_min": 0.30},
            {"id": "shadow_030_020", "noul_min": 0.30, "conf_min": 0.20},
        ],
    },
    "stock": {
        "fetch_universe": fetch_stock_universe,
        "universe": STOCK_UNIVERSE,
        "strategy_hint": "US equity multi-name short-horizon (session-aware)",
        "noul_min": 0.65,
        "conf_min": 0.55,
        "default_duration_s": 45,
        "interval_s": 30.0,  # large Yahoo basket — keep polite
        "shadows": [
            {"id": "shadow_035_025", "noul_min": 0.35, "conf_min": 0.25},
            {"id": "shadow_040_030", "noul_min": 0.40, "conf_min": 0.30},
            {"id": "shadow_030_020", "noul_min": 0.30, "conf_min": 0.20},
        ],
    },
}


def build_state(market_id: str, snaps: dict[str, dict], strategy_hint: str, universe: list[str]) -> str:
    compact = []
    err_n = 0
    for sym in universe:
        s = snaps.get(sym) or {}
        if s.get("error"):
            err_n += 1
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
            "universe_size": len(universe),
            "quoted": len(compact),
            "fetch_errors": err_n,
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "horizon_sec": 5,
            "snapshots": compact,
            "instructions": (
                f"Pick at most one symbol from the {market_id} universe with the best "
                "short-horizon edge. Prefer none when unclear. Do not mix asset classes. "
                "Also choose an absolute USD notional size_usd (not a fraction of equity). "
                "Use 0 when hold/none. Starting paper cash is about $10,000 per book."
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
    size_raw = s.get("choice")
    try:
        size_usd = float(size_raw) if size_raw is not None else 0.0
    except (TypeError, ValueError):
        size_usd = 0.0
    return {
        "pick_symbol": p.get("choice"),
        "pick_confidence": p.get("confidence"),
        "pick_probs": p.get("probabilities"),
        "direction": d.get("choice"),
        "dir_confidence": d.get("confidence"),
        "dir_probs": d.get("probabilities"),
        "should_trade": n.get("noul"),
        "edge_score": e.get("score"),
        "edge_confidence": e.get("confidence"),
        "size_usd": size_usd,
        "size_confidence": s.get("confidence"),
        "size_probs": s.get("probabilities"),
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
        f"SMOKE [{market_id}] universe={universe} key_ok len={len(api_key)} duration={duration}s",
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
                "ends_ts_approx": datetime.fromtimestamp(time.time() + duration, tz=timezone.utc).isoformat(),
                "strategy": cfg["strategy_hint"],
                "thresholds": {"noul_min": cfg["noul_min"], "conf_min": cfg["conf_min"], "label": "primary"},
                "shadows": shadow_cfgs,
                "paper_start_cash": 10000.0,
                "selection": "jev_pick_symbol",
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
        ok_symbols = [s for s in universe if s in mids]
        if not ok_symbols:
            errors.append({"i": i, "stage": "market", "error": "no symbols fetched"})
            time.sleep(interval)
            continue

        state = build_state(market_id, snaps, cfg["strategy_hint"], ok_symbols)
        questions = questions_for_universe(market_id, ok_symbols, strategy_hint=cfg["strategy_hint"])
        resp, latency_ms = call_jev(api_key, state, questions)
        latencies.append(latency_ms)
        tick["latency_ms"] = round(latency_ms, 1)
        tick["mids"] = mids

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
        noul = float(parsed.get("should_trade") or 0)
        conf = float(parsed.get("dir_confidence") or 0)
        fill = None
        shadow_fills: dict[str, Any] = {}

        size_usd = float(parsed.get("size_usd") or 0)
        tick["size_usd"] = size_usd
        if picked and picked != "none" and picked in snaps and snaps[picked].get("mid") is not None:
            snap = snaps[picked]
            tick["selected_symbol"] = picked
            tick["mid"] = snap["mid"]
            if (
                direction in ("buy", "sell")
                and size_usd >= 1
                and noul >= cfg["noul_min"]
                and conf >= cfg["conf_min"]
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
                        "conf": conf,
                        "edge": parsed.get("edge_score"),
                        "size_usd_jev": size_usd,
                        "book": "primary",
                    },
                )
            if direction in ("buy", "sell") and size_usd >= 1:
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
                                "conf": conf,
                                "edge": parsed.get("edge_score"),
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
            f"dir={direction} size=${size_usd:.0f} noul={noul:.2f} lat={latency_ms:.0f}ms "
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
        "thresholds": {"noul_min": cfg["noul_min"], "conf_min": cfg["conf_min"]},
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
            "thresholds": {"noul_min": cfg["noul_min"], "conf_min": cfg["conf_min"]},
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
        f"- Shadow `{sid}` (noul>={sc['noul_min']}, conf>={sc['conf_min']}): "
        f"fills={results['shadow_books'][sid]['fills']} / pnl={results['shadow_books'][sid]['pnl']:.2f}"
        for sid, sc in ((s["id"], s) for s in shadow_cfgs)
    ) or "- Shadows: none"
    summary = f"""# Smoke ({market_id})

- Mode: paper only · Jev picks symbol from universe
- Universe size: {len(universe)} (cap 254 for Jev choice incl. none)
- Strategy: {cfg['strategy_hint']}
- Duration: ~{duration}s / interval ~{interval}s
- Ticks: {len(ticks)}
- Latency ms: min={results['latency_ms']['min']} avg={results['latency_ms']['avg']} max={results['latency_ms']['max']}
- Pick dist: {picks}
- Decisions: {dist}
- Primary (noul>={cfg['noul_min']}, conf>={cfg['conf_min']}): fills={results['book']['fills']} / pnl={results['book']['pnl']:.2f}
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
