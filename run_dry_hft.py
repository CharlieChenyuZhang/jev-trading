#!/usr/bin/env python3
"""Deprecated combined runner.

Crypto and stock strategies are separate — use:
  python smoke_crypto.py
  python smoke_stock.py
  python -m jev_trading.smoke crypto
  python -m jev_trading.smoke stock
"""
from __future__ import annotations

import sys

print(
    "run_dry_hft.py is deprecated: crypto and stock smokes are separate.\n"
    "  python smoke_crypto.py\n"
    "  python smoke_stock.py\n"
    "  python -m jev_trading.smoke crypto|stock\n",
    file=sys.stderr,
)
raise SystemExit(2)
