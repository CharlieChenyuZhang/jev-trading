#!/usr/bin/env python3
"""Separate smoke runners for crypto vs stock (dry-run only)."""
from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .jev_client import call_jev, questions_for_market, resolve_api_key
from .markets import fetch_crypto_btc_usd, fetch_stock_aapl
from .paper import Book

MARKETS: dict[str, dict[str, Any]] = {
    "crypto": {
        "fetch": fetch_crypto_btc_usd,
        "strategy_hint": "crypto microstructure / 24-7 BTC-USD",
        "noul_min": 0.60,
        "conf_min": 0.55,
        "default_duration_s": 45,
        "interval_s": 2.5,
        # Parallel paper books for parameter comparison (same signals, different gates)
        "shadows": [
            {"id": "shadow_035_025", "noul_min": 0.35, "conf_min": 0.25},
            {"id": "shadow_040_030", "noul_min": 0.40, "conf_min": 0.30},
            {"id": "shadow_030_020", "noul_min": 0.30, "conf_min": 0.20},
        ],
    },
    "stock": {
        "fetch": fetch_stock_aapl,
        "strategy_hint": "US equity AAPL short-horizon (session-aware)",
        "noul_min": 0.65,  # slightly stricter for thinner TOB proxy
        "conf_min": 0.55,
        "default_duration_s": 45,
        # Slower than crypto: Yahoo public chart rate-limits hard (HTTP 429)
        "interval_s": 8.0,
        "shadows": [],  # overnight mostly hold; add shadows later in RTH if needed
    },
}


def build_state(market_id: str, snap: dict[str, Any], strategy_hint: str) -> str:
    return json.dumps(
        {
            "mode": "paper_trading_dry_run",
            "market": market_id,
            "strategy": strategy_hint,
            "ts_utc": datetime.now(timezone.utc).isoformat(),
            "horizon_sec": 5,
            "snapshot": snap,
            "instructions": (
                f"Judge short-horizon edge for {market_id} only. "
                "Do not consider other asset classes. Prefer hold when unclear."
            ),
        },
        separators=(",", ":"),
    )


def parse_answers(answers: dict[str, Any]) -> dict[str, Any]:
    d = answers.get("direction") or {}
    n = answers.get("should_trade") or {}
    e = answers.get("edge") or {}
    return {
        "direction": d.get("choice"),
        "dir_confidence": d.get("confidence"),
        "dir_probs": d.get("probabilities"),
        "should_trade": n.get("noul"),
        "edge_score": e.get("score"),
        "edge_confidence": e.get("confidence"),
    }




def _book_snap(book: Book, mid: float | None = None) -> dict[str, Any]:
    m = mid if mid is not None else 0.0
    return {
        "equity": round(book.equity(m), 2) if mid is not None else round(book.cash, 2),
        "pnl": round(book.mark_pnl(m), 2) if mid is not None else round(book.realized_pnl, 2),
        "fills": len(book.fills),
        "position": book.position,
        "cash": round(book.cash, 2),
    }


def _checkpoint(
    out: Path,
    *,
    market_id: str,
    ticks: list,
    latencies: list,
    errors: list,
    book: Book,
    shadow_books: dict[str, Book] | None = None,
    shadow_cfgs: list[dict] | None = None,
    extra: dict | None = None,
) -> None:
    dist = {"buy": 0, "sell": 0, "hold": 0, "other": 0}
    for x in ticks:
        d = ((x.get("answers") or {}).get("direction"))
        if d in dist:
            dist[d] += 1
        else:
            dist["other"] += 1
    mid = ticks[-1].get("mid") if ticks else None
    live = {
        "market": market_id,
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
            "equity": ticks[-1].get("equity") if ticks else book.cash,
            "pnl": ticks[-1].get("pnl") if ticks else 0.0,
            "fills": len(book.fills),
            "position": book.position,
            "cash": book.cash,
            "label": "primary",
        },
        "decision_dist": dist,
        "errors": len(errors),
        "last_answers": (ticks[-1].get("answers") if ticks else None),
        "shadows": {},
    }
    if shadow_books:
        cfg_by_id = {c["id"]: c for c in (shadow_cfgs or [])}
        for sid, sb in shadow_books.items():
            snap = _book_snap(sb, float(mid) if mid is not None else None)
            cfg = cfg_by_id.get(sid) or {}
            snap["noul_min"] = cfg.get("noul_min")
            snap["conf_min"] = cfg.get("conf_min")
            live["shadows"][sid] = snap
    if extra:
        live.update(extra)
    (out / "live.json").write_text(json.dumps(live, indent=2))
    (out / "recent_ticks.json").write_text(json.dumps(ticks[-200:], indent=2))


def run_smoke(market_id: str, *, duration_s: float | None = None, out_dir: Path | None = None) -> int:
    cfg = MARKETS[market_id]
    fetch: Callable[[], dict[str, Any]] = cfg["fetch"]
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

    print(f"SMOKE [{market_id}] key_ok len={len(api_key)} duration={duration}s", flush=True)
    started = datetime.now(timezone.utc).isoformat()
    shadow_cfgs = list(cfg.get("shadows") or [])
    (out / "run_meta.json").write_text(json.dumps({
        "market": market_id,
        "started_ts": started,
        "duration_s": duration,
        "interval_s": interval,
        "ends_ts_approx": datetime.fromtimestamp(time.time() + duration, tz=timezone.utc).isoformat(),
        "strategy": cfg["strategy_hint"],
        "thresholds": {"noul_min": cfg["noul_min"], "conf_min": cfg["conf_min"], "label": "primary"},
        "shadows": shadow_cfgs,
        "paper_start_cash": 10000.0,
    }, indent=2))
    book = Book()
    shadow_books: dict[str, Book] = {s["id"]: Book() for s in shadow_cfgs}
    ticks: list[dict] = []
    latencies: list[float] = []
    errors: list[dict] = []
    t_end = time.time() + duration
    i = 0
    while time.time() < t_end:
        i += 1
        tick: dict[str, Any] = {"i": i, "ts": datetime.now(timezone.utc).isoformat(), "market": market_id}
        try:
            snap = fetch()
        except Exception as ex:
            errors.append({"i": i, "stage": "market", "error": str(ex)[:300]})
            time.sleep(interval)
            continue
        state = build_state(market_id, snap, cfg["strategy_hint"])
        questions = questions_for_market(market_id, strategy_hint=cfg["strategy_hint"])
        resp, latency_ms = call_jev(api_key, state, questions)
        latencies.append(latency_ms)
        tick["latency_ms"] = round(latency_ms, 1)
        tick["mid"] = snap["mid"]
        if resp.get("error"):
            errors.append({"i": i, "stage": "jev", **{k: resp[k] for k in resp if k != "error"}})
            tick["jev_error"] = {k: resp[k] for k in resp if k != "error"}
            ticks.append(tick)
            if i == 1 or i % 12 == 0:
                _checkpoint(
                    out,
                    market_id=market_id,
                    ticks=ticks,
                    latencies=latencies,
                    errors=errors,
                    book=book,
                    shadow_books=shadow_books,
                    shadow_cfgs=shadow_cfgs,
                )
            time.sleep(interval)
            continue
        answers = resp.get("answers") or {}
        parsed = parse_answers(answers)
        tick["answers"] = parsed
        tick["model"] = resp.get("model")
        tick["usage"] = resp.get("usage")
        direction = parsed.get("direction")
        noul = float(parsed.get("should_trade") or 0)
        conf = float(parsed.get("dir_confidence") or 0)
        fill = None
        if (
            direction in ("buy", "sell")
            and noul >= cfg["noul_min"]
            and conf >= cfg["conf_min"]
        ):
            fill = book.maybe_trade(
                side=direction,
                mid=snap["mid"],
                bid=snap["bid"],
                ask=snap["ask"],
                meta={"i": i, "noul": noul, "conf": conf, "edge": parsed.get("edge_score"), "book": "primary"},
            )
        shadow_fills: dict[str, Any] = {}
        if direction in ("buy", "sell"):
            for scfg in shadow_cfgs:
                if noul >= scfg["noul_min"] and conf >= scfg["conf_min"]:
                    sid = scfg["id"]
                    shadow_fills[sid] = shadow_books[sid].maybe_trade(
                        side=direction,
                        mid=snap["mid"],
                        bid=snap["bid"],
                        ask=snap["ask"],
                        meta={"i": i, "noul": noul, "conf": conf, "edge": parsed.get("edge_score"), "book": sid},
                    )
        tick["fill"] = fill
        tick["shadow_fills"] = shadow_fills
        tick["equity"] = round(book.equity(snap["mid"]), 2)
        tick["pnl"] = round(book.mark_pnl(snap["mid"]), 2)
        tick["shadow_pnl"] = {
            sid: round(sb.mark_pnl(snap["mid"]), 2) for sid, sb in shadow_books.items()
        }
        ticks.append(tick)
        shadow_bits = " ".join(
            f"{sid}={tick['shadow_pnl'][sid]:+.2f}/{len(shadow_books[sid].fills)}"
            for sid in shadow_books
        )
        print(
            f"[{market_id}] tick={i} lat={latency_ms:.0f}ms "
            f"dir={direction} noul={noul:.2f} primary_pnl={tick['pnl']}"
            + (f" | {shadow_bits}" if shadow_bits else ""),
            flush=True,
        )
        if i == 1 or i % 12 == 0:
            _checkpoint(
                out,
                market_id=market_id,
                ticks=ticks,
                latencies=latencies,
                errors=errors,
                book=book,
                shadow_books=shadow_books,
                shadow_cfgs=shadow_cfgs,
            )
        time.sleep(interval)

    try:
        final_mid = fetch()["mid"]
    except Exception:
        final_mid = ticks[-1]["mid"] if ticks else 0

    dist = {"buy": 0, "sell": 0, "hold": 0, "other": 0}
    for t in ticks:
        d = ((t.get("answers") or {}).get("direction"))
        if d in dist:
            dist[d] += 1
        else:
            dist["other"] += 1

    results = {
        "mode": "dry_run_smoke",
        "market": market_id,
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
            "cash": book.cash,
            "position": book.position,
            "equity": book.equity(final_mid),
            "pnl": book.mark_pnl(final_mid),
            "fills": len(book.fills),
            "label": "primary",
            "thresholds": {"noul_min": cfg["noul_min"], "conf_min": cfg["conf_min"]},
        },
        "shadow_books": {
            sid: {
                **_book_snap(sb, final_mid),
                "noul_min": next(s["noul_min"] for s in shadow_cfgs if s["id"] == sid),
                "conf_min": next(s["conf_min"] for s in shadow_cfgs if s["id"] == sid),
            }
            for sid, sb in shadow_books.items()
        },
        "decision_dist": dist,
    }
    (out / "results.json").write_text(json.dumps(results, indent=2))
    shadow_lines = "\n".join(
        f"- Shadow `{sid}` (noul>={sc['noul_min']}, conf>={sc['conf_min']}): "
        f"fills={results['shadow_books'][sid]['fills']} / pnl={results['shadow_books'][sid]['pnl']:.2f}"
        for sid, sc in ((s['id'], s) for s in shadow_cfgs)
    ) or "- Shadows: none"
    summary = f"""# Smoke ({market_id})

- Mode: paper only
- Strategy: {cfg['strategy_hint']}
- Duration: ~{duration}s / interval ~{interval}s
- Ticks: {len(ticks)}
- Latency ms: min={results['latency_ms']['min']} avg={results['latency_ms']['avg']} max={results['latency_ms']['max']}
- Decisions: {dist}
- Primary (noul>={cfg['noul_min']}, conf>={cfg['conf_min']}): fills={results['book']['fills']} / pnl={results['book']['pnl']:.2f}
{shadow_lines}
- Errors: {len(errors)}
"""
    (out / "SUMMARY.md").write_text(summary)
    print(summary)
    return 0 if ticks or not errors else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Separate Jev paper-trading smoke (crypto | stock)")
    parser.add_argument("market", choices=sorted(MARKETS.keys()), help="Which market smoke to run")
    parser.add_argument("--duration", type=float, default=None, help="Seconds (default 45)")
    parser.add_argument("--out", type=Path, default=None, help="Output directory")
    args = parser.parse_args()
    return run_smoke(args.market, duration_s=args.duration, out_dir=args.out)


if __name__ == "__main__":
    raise SystemExit(main())
