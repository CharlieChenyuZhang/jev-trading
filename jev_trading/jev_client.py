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


def questions_for_universe(
    market_id: str,
    symbols: list[str],
    *,
    strategy_hint: str,
    outer_bps: float = 8.0,
    neutral_bps: float = 2.0,
) -> dict[str, Any]:
    """Layered Jev questions (FMZ / TypeSafe style): pick → move bucket → trade → size → toxicity."""
    criteria = {
        sym: f"Best short-horizon opportunity in the candidate set: {sym}" for sym in symbols
    }
    # Keep none, but do not encourage it as the default
    criteria["none"] = "Only if every candidate is noise relative to costs; otherwise pick one"

    large_dn = f"R <= -{outer_bps:.1f} bps (large down)"
    small_dn = f"-{outer_bps:.1f} < R <= -{neutral_bps:.1f} bps (small down)"
    flat = f"-{neutral_bps:.1f} < R < {neutral_bps:.1f} bps (narrow / flat)"
    small_up = f"{neutral_bps:.1f} <= R < {outer_bps:.1f} bps (small up)"
    large_up = f"R >= {outer_bps:.1f} bps (large up)"

    return {
        "pick_symbol": {
            "type": "choice",
            "instructions": (
                f"For {market_id} ({strategy_hint}): pick ONE symbol from the candidate "
                "set with the clearest short-horizon edge. Prefer a real symbol when "
                "any name shows directional pressure, imbalance, or abnormal short return. "
                "Use none only when the whole set is flat noise."
            ),
            "criteria": criteria,
        },
        "move": {
            "type": "choice",
            "instructions": (
                "For the picked symbol only: over the next ~30 seconds, which return "
                "interval (R = 10000 * (future_mid/mid - 1)) is most likely? "
                "If pick_symbol is none, choose flat."
            ),
            "criteria": {
                "large_down": large_dn,
                "small_down": small_dn,
                "flat": flat,
                "small_up": small_up,
                "large_up": large_up,
            },
        },
        "direction": {
            "type": "choice",
            "instructions": (
                "Translate the move into an action for the picked symbol. "
                "large_up/small_up → buy; large_down/small_down → sell; flat → hold. "
                "If pick is none, hold."
            ),
            "criteria": {
                "buy": "Expect net upward move; open/add long paper exposure",
                "sell": "Expect net downward move; open/add short or reduce long",
                "hold": "Flat / none / edge below cost — do not trade",
            },
        },
        "should_trade": {
            "type": "noul",
            "instructions": (
                "After fees/spread, should we place a paper trade NOW on the picked symbol? "
                "True when direction is buy/sell and the move is not flat noise. "
                "False when pick is none, direction is hold, or edge cannot cover costs."
            ),
            "criteria": {
                "true": "Directional move looks tradeable now on the picked symbol",
                "false": "Skip this tick",
            },
        },
        "edge": {
            "type": "score",
            "instructions": "Quality of short-horizon edge for the picked symbol (0 if none/flat)",
            "criteria": [
                "No edge / noise",
                "Very weak — barely above noise",
                "Modest — tradeable with small size",
                "Clear — solid short-horizon edge",
                "Strong — high-conviction short-horizon edge",
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
                "CRITICAL: if direction is buy or sell, you MUST pick a non-zero size "
                "(50–5000). Use 0 ONLY when direction is hold or pick_symbol is none. "
                "Scale size with edge: weak→50–100, modest→250–500, clear→1000, strong→2500–5000."
            ),
            "criteria": {
                "0": "ONLY allowed with hold or none — zero size",
                "50": "$50 notional (very weak edge)",
                "100": "$100 notional",
                "250": "$250 notional",
                "500": "$500 notional",
                "1000": "$1,000 notional",
                "2500": "$2,500 notional",
                "5000": "$5,000 notional (strong edge)",
            },
        },
    }


def questions_for_market(market_id: str, *, strategy_hint: str) -> dict[str, Any]:
    """Legacy single-symbol question set."""
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
        resp = http_json(JEV_URL, method="POST", headers=headers, body=body, timeout=30.0)
        return resp, (time.perf_counter() - t0) * 1000
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:500]
        return {"error": True, "status": e.code, "body": err_body}, (time.perf_counter() - t0) * 1000
