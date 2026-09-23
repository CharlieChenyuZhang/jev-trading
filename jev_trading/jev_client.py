from __future__ import annotations

import os
import time
import urllib.error
from typing import Any

from .httputil import http_json

JEV_URL = os.environ.get("JEV_URL", "https://openrouter.ai/api/v1/systemone")
MODEL = os.environ.get("JEV_MODEL", "~typesafe/jev-latest")


def resolve_api_key() -> str:
    return (
        os.environ.get("OPENROUTER_API_KEY")
        or os.environ.get("TYPESAFE_API_KEY")
        or ""
    )


def _move_criteria(outer_bps: float, neutral_bps: float) -> dict[str, str]:
    return {
        "large_down": f"R <= -{outer_bps:.1f} bps (large down)",
        "small_down": f"-{outer_bps:.1f} < R <= -{neutral_bps:.1f} bps (small down)",
        "flat": f"-{neutral_bps:.1f} < R < {neutral_bps:.1f} bps (narrow / flat)",
        "small_up": f"{neutral_bps:.1f} <= R < {outer_bps:.1f} bps (small up)",
        "large_up": f"R >= {outer_bps:.1f} bps (large up)",
    }


def questions_for_universe(
    market_id: str,
    symbols: list[str],
    *,
    strategy_hint: str,
    outer_bps: float = 8.0,
    neutral_bps: float = 2.0,
) -> dict[str, Any]:
    """Pick symbol + multi-horizon move forecasts + trade/size/toxicity."""
    criteria = {
        sym: f"Best opportunity in the candidate set across horizons: {sym}" for sym in symbols
    }
    criteria["none"] = "Only if every candidate is noise relative to costs; otherwise pick one"
    mc = _move_criteria(outer_bps, neutral_bps)
    # Slightly wider buckets for longer horizons
    mc_med = _move_criteria(max(outer_bps, 12.0), max(neutral_bps, 3.0))
    mc_long = _move_criteria(max(outer_bps, 20.0), max(neutral_bps, 5.0))

    return {
        "pick_symbol": {
            "type": "choice",
            "instructions": (
                f"For {market_id} ({strategy_hint}): pick ONE symbol from the candidate "
                "set. Prefer names where short and medium horizons agree. Use none only "
                "when the whole set is flat noise."
            ),
            "criteria": criteria,
        },
        "move": {
            "type": "choice",
            "instructions": (
                "SHORT horizon (~30s–1m): which return bucket is most likely for the picked "
                "symbol? If pick is none, choose flat."
            ),
            "criteria": mc,
        },
        "move_5m": {
            "type": "choice",
            "instructions": (
                "MEDIUM ~5 minutes: which return bucket is most likely for the picked symbol? "
                "If pick is none, flat."
            ),
            "criteria": mc_med,
        },
        "move_10m": {
            "type": "choice",
            "instructions": (
                "MEDIUM ~10 minutes: which return bucket is most likely for the picked symbol? "
                "If pick is none, flat."
            ),
            "criteria": mc_med,
        },
        "move_1h": {
            "type": "choice",
            "instructions": (
                "LONGER ~1 hour: which return bucket is most likely for the picked symbol? "
                "If pick is none, flat."
            ),
            "criteria": mc_long,
        },
        "trend_1d": {
            "type": "choice",
            "instructions": (
                "DAY filter (not the main trade trigger): for the picked symbol, is the "
                "broad ~1 day trend up, down, or flat/noisy? If pick is none, flat."
            ),
            "criteria": {
                "up": "Broad 1d trend up / constructive",
                "down": "Broad 1d trend down / weak",
                "flat": "No clear 1d trend / chop",
            },
        },
        "direction": {
            "type": "choice",
            "instructions": (
                "Primary action for the SHORT horizon (move). "
                "large_up/small_up → buy; large_down/small_down → sell; flat → hold. "
                "If pick is none, hold."
            ),
            "criteria": {
                "buy": "Expect net upward move on the short horizon",
                "sell": "Expect net downward move on the short horizon",
                "hold": "Flat / none / edge below cost — do not trade",
            },
        },
        "should_trade": {
            "type": "noul",
            "instructions": (
                "After fees/spread, should we place a paper trade NOW? "
                "True when short-horizon direction is buy/sell and not pure noise. "
                "False when pick is none, hold, or edge cannot cover costs."
            ),
            "criteria": {
                "true": "Short-horizon edge looks tradeable now",
                "false": "Skip this tick",
            },
        },
        "edge": {
            "type": "score",
            "instructions": "Quality of edge for the picked symbol (0 if none/flat)",
            "criteria": [
                "No edge / noise",
                "Very weak — barely above noise",
                "Modest — tradeable with small size",
                "Clear — solid edge",
                "Strong — high-conviction edge",
            ],
        },
        "toxicity": {
            "type": "score",
            "instructions": (
                "If we get filled now on the picked side, how bad is immediate adverse "
                "selection over the next few seconds?"
            ),
            "criteria": [
                "Flow and microprice do not point against us",
                "Mixed / thin book — hard to tell",
                "Some adverse flow on our side",
                "Microprice and aggressive flow both point against a fresh fill",
            ],
        },
        "size_usd": {
            "type": "choice",
            "instructions": (
                "Absolute USD notional for THIS paper trade (not a fraction of equity). "
                "If direction is buy/sell and short move is not flat, pick 50–500. "
                "Use 0 when hold, none, or flat. Prefer 50–250 unless edge is clear."
            ),
            "criteria": {
                "0": "hold / none / flat — zero size",
                "50": "$50 notional",
                "100": "$100 notional",
                "250": "$250 notional",
                "500": "$500 notional (max typical size)",
            },
        },
    }


def questions_for_market(market_id: str, *, strategy_hint: str) -> dict[str, Any]:
    return questions_for_universe(market_id, [market_id], strategy_hint=strategy_hint)


def call_jev(api_key: str, state: str, questions: dict[str, Any]) -> tuple[dict[str, Any], float]:
    body = {"model": MODEL, "state": state, "questions": questions}
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://github.com/CharlieChenyuZhang/jev-trading",
        "X-OpenRouter-Title": "jev-trading-smoke",
    }
    t0 = time.perf_counter()
    try:
        # 45s: intermittent OpenRouter SSL read stalls were hard-killing smokes at 30s
        resp = http_json(JEV_URL, method="POST", headers=headers, body=body, timeout=45.0)
        return resp, (time.perf_counter() - t0) * 1000
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:500]
        return {"error": True, "status": e.code, "body": err_body}, (time.perf_counter() - t0) * 1000
    except (TimeoutError, urllib.error.URLError, OSError) as e:
        # Do not kill the paper loop on transient network/SSL timeouts
        return {
            "error": True,
            "status": "timeout",
            "body": f"{type(e).__name__}: {e}"[:500],
        }, (time.perf_counter() - t0) * 1000
