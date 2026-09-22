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


def questions_for_universe(market_id: str, symbols: list[str], *, strategy_hint: str) -> dict[str, Any]:
    """Jev picks a symbol from the universe, then direction / trade gate / edge."""
    criteria = {sym: f"Best short-horizon opportunity among the universe: {sym}" for sym in symbols}
    criteria["none"] = "No symbol has a clear short-horizon edge; stay flat"
    return {
        "pick_symbol": {
            "type": "choice",
            "instructions": (
                f"For {market_id} ({strategy_hint}): pick ONE symbol from the universe "
                "with the best short-horizon edge right now, or none."
            ),
            "criteria": criteria,
        },
        "direction": {
            "type": "choice",
            "instructions": (
                "For the symbol you picked (ignore others): best short-horizon action "
                "over the next few seconds? If pick_symbol is none, prefer hold."
            ),
            "criteria": {
                "buy": "Price more likely to rise over the next few seconds",
                "sell": "Price more likely to fall over the next few seconds",
                "hold": "No clear edge; stay flat or keep current stance",
            },
        },
        "should_trade": {
            "type": "noul",
            "instructions": (
                "Should we place a small paper trade now in the picked symbol? "
                "False if pick_symbol is none or edge is weak."
            ),
            "criteria": {
                "true": "Edge and liquidity justify a small trade in the picked symbol",
                "false": "Skip; no pick or edge too weak",
            },
        },
        "edge": {
            "type": "score",
            "instructions": "Quality of short-horizon edge for the picked symbol (0 if none)",
            "criteria": [
                "No edge / noise",
                "Very weak",
                "Modest",
                "Clear",
                "Strong",
            ],
        },

        "size_usd": {
            "type": "choice",
            "instructions": (
                "Absolute paper trade size in USD notional for this tick "
                "(not a fraction of equity). Use 0 if hold / none / no trade. "
                "Pick a concrete dollar amount."
            ),
            "criteria": {
                "0": "No trade / zero size",
                "50": "About $50 notional",
                "100": "About $100 notional",
                "250": "About $250 notional",
                "500": "About $500 notional",
                "1000": "About $1,000 notional",
                "2500": "About $2,500 notional",
                "5000": "About $5,000 notional",
            },
        },
    }


def questions_for_market(market_id: str, *, strategy_hint: str) -> dict[str, Any]:
    """Legacy single-symbol question set."""
    return {
        "direction": {
            "type": "choice",
            "instructions": (
                f"For {market_id} only ({strategy_hint}): "
                "best short-horizon action over the next few seconds?"
            ),
            "criteria": {
                "buy": "Price more likely to rise over the next few seconds",
                "sell": "Price more likely to fall over the next few seconds",
                "hold": "No clear edge; stay flat or keep current stance",
            },
        },
        "should_trade": {
            "type": "noul",
            "instructions": f"For {market_id} only: should we place a small paper trade now?",
            "criteria": {
                "true": "Edge and liquidity justify a small trade under this market's strategy",
                "false": "Skip; edge too weak or noisy for this strategy",
            },
        },
        "edge": {
            "type": "score",
            "instructions": f"Quality of short-horizon edge for {market_id} under its own strategy",
            "criteria": [
                "No edge / noise",
                "Very weak",
                "Modest",
                "Clear",
                "Strong",
            ],
        },

        "size_usd": {
            "type": "choice",
            "instructions": (
                "Absolute paper trade size in USD notional for this tick "
                "(not a fraction of equity). Use 0 if hold / none / no trade. "
                "Pick a concrete dollar amount."
            ),
            "criteria": {
                "0": "No trade / zero size",
                "50": "About $50 notional",
                "100": "About $100 notional",
                "250": "About $250 notional",
                "500": "About $500 notional",
                "1000": "About $1,000 notional",
                "2500": "About $2,500 notional",
                "5000": "About $5,000 notional",
            },
        },
    }


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
