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


def questions_for_market(market_id: str, *, strategy_hint: str) -> dict[str, Any]:
    """Per-market question set — keep crypto/stock strategies independent."""
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
        resp = http_json(JEV_URL, method="POST", headers=headers, body=body, timeout=20.0)
        return resp, (time.perf_counter() - t0) * 1000
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")[:500]
        return {"error": True, "status": e.code, "body": err_body}, (time.perf_counter() - t0) * 1000
