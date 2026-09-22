from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Book:
    """Single-symbol paper book (legacy / simple smoke)."""

    cash: float = 10_000.0
    position: float = 0.0
    avg_entry: float = 0.0
    realized_pnl: float = 0.0
    fills: list[dict] = field(default_factory=list)
    trade_frac: float = 0.01  # unused when notional_usd is provided
    last_good_mid: float | None = None

    def _mid(self, mid: float) -> float:
        if mid and mid > 0:
            self.last_good_mid = float(mid)
            return float(mid)
        if self.last_good_mid and self.last_good_mid > 0:
            return float(self.last_good_mid)
        return 0.0

    def equity(self, mid: float) -> float:
        m = self._mid(mid)
        return self.cash + self.position * m

    def mark_pnl(self, mid: float) -> float:
        m = self._mid(mid)
        if self.position and m > 0:
            return self.realized_pnl + self.position * (m - self.avg_entry)
        return self.realized_pnl

    def maybe_trade(
        self,
        *,
        side: str,
        mid: float,
        bid: float,
        ask: float,
        meta: dict,
        notional_usd: float | None = None,
    ) -> dict | None:
        px = ask if side == "buy" else bid
        if mid and mid > 0:
            self.last_good_mid = float(mid)
        if notional_usd is None:
            notional = self.equity(mid) * self.trade_frac
        else:
            notional = float(notional_usd)
        if notional < 1 or px <= 0:
            return None
        if side == "buy":
            notional = min(notional, max(0.0, self.cash * 0.99))
        if notional < 1:
            return None
        qty = notional / px
        if side == "buy":
            self.cash -= qty * px
            new_pos = self.position + qty
            if new_pos != 0:
                self.avg_entry = (
                    ((self.avg_entry * self.position) + qty * px) / new_pos if self.position else px
                )
            self.position = new_pos
        else:
            if self.position > 0:
                close_qty = min(self.position, qty)
                self.realized_pnl += close_qty * (px - self.avg_entry)
                self.position -= close_qty
                self.cash += close_qty * px
                qty_left = qty - close_qty
            else:
                qty_left = qty
            if qty_left > 0:
                new_pos = self.position - qty_left
                if self.position >= 0:
                    self.avg_entry = px
                else:
                    old = abs(self.position)
                    self.avg_entry = ((self.avg_entry * old) + qty_left * px) / (old + qty_left)
                self.position = new_pos
                self.cash += qty_left * px
        fill = {"side": side, "px": px, "qty": qty, "notional_usd": round(qty * px, 2), **meta}
        self.fills.append(fill)
        return fill


@dataclass
class Portfolio:
    """Multi-symbol paper book sharing one cash pool ($10k default)."""

    cash: float = 10_000.0
    positions: dict[str, float] = field(default_factory=dict)
    avg_entry: dict[str, float] = field(default_factory=dict)
    realized_pnl: float = 0.0
    fills: list[dict] = field(default_factory=list)
    trade_frac: float = 0.01  # unused when notional_usd is provided
    last_good_mids: dict[str, float] = field(default_factory=dict)

    def remember_mids(self, mids: dict[str, float]) -> None:
        for sym, mid in mids.items():
            try:
                m = float(mid)
            except (TypeError, ValueError):
                continue
            if m > 0:
                self.last_good_mids[sym] = m

    def mark_mid(self, symbol: str, mid: float | None = None) -> float:
        try:
            m = float(mid) if mid is not None else 0.0
        except (TypeError, ValueError):
            m = 0.0
        if m > 0:
            self.last_good_mids[symbol] = m
            return m
        return float(self.last_good_mids.get(symbol) or 0.0)

    def equity(self, mids: dict[str, float]) -> float:
        self.remember_mids(mids)
        total = self.cash
        for sym, qty in self.positions.items():
            m = self.mark_mid(sym, mids.get(sym))
            if m > 0:
                total += qty * m
            else:
                # no usable mark — keep cost basis so equity does not fake-wipe
                total += qty * float(self.avg_entry.get(sym) or 0.0)
        return total

    def mark_pnl(self, mids: dict[str, float]) -> float:
        self.remember_mids(mids)
        unreal = 0.0
        for sym, qty in self.positions.items():
            m = self.mark_mid(sym, mids.get(sym))
            avg = self.avg_entry.get(sym, m)
            if m > 0 and avg is not None:
                unreal += qty * (m - avg)
            # if still no mid, contribute 0 unrealized (hold at cost)
        return self.realized_pnl + unreal

    def net_long_notional(self, mids: dict[str, float]) -> float:
        self.remember_mids(mids)
        total = 0.0
        for sym, qty in self.positions.items():
            if qty <= 0:
                continue
            m = self.mark_mid(sym, mids.get(sym))
            if m <= 0:
                m = float(self.avg_entry.get(sym) or 0.0)
            total += qty * m
        return total

    def net_short_notional(self, mids: dict[str, float]) -> float:
        """Absolute short notional (positive number)."""
        self.remember_mids(mids)
        total = 0.0
        for sym, qty in self.positions.items():
            if qty >= 0:
                continue
            m = self.mark_mid(sym, mids.get(sym))
            if m <= 0:
                m = float(self.avg_entry.get(sym) or 0.0)
            total += abs(qty) * m
        return total

    def maybe_trade(
        self,
        *,
        symbol: str,
        side: str,
        mid: float,
        bid: float,
        ask: float,
        meta: dict,
        notional_usd: float | None = None,
    ) -> dict | None:
        px = ask if side == "buy" else bid
        if mid and mid > 0:
            self.last_good_mids[symbol] = float(mid)
        mids = {symbol: mid}
        for s in self.positions:
            mids.setdefault(s, self.last_good_mids.get(s) or self.avg_entry.get(s, 0.0))
        if notional_usd is None:
            notional = self.equity(mids) * self.trade_frac
        else:
            notional = float(notional_usd)
        if notional < 1 or px <= 0:
            return None
        if side == "buy":
            notional = min(notional, max(0.0, self.cash * 0.99))
        if notional < 1:
            return None
        qty = notional / px
        pos = self.positions.get(symbol, 0.0)
        avg = self.avg_entry.get(symbol, 0.0)
        if side == "buy":
            self.cash -= qty * px
            new_pos = pos + qty
            if new_pos != 0:
                self.avg_entry[symbol] = ((avg * pos) + qty * px) / new_pos if pos else px
            self.positions[symbol] = new_pos
        else:
            if pos > 0:
                close_qty = min(pos, qty)
                self.realized_pnl += close_qty * (px - avg)
                pos -= close_qty
                self.cash += close_qty * px
                qty_left = qty - close_qty
            else:
                qty_left = qty
            if qty_left > 0:
                if pos >= 0:
                    self.avg_entry[symbol] = px
                else:
                    old = abs(pos)
                    self.avg_entry[symbol] = ((avg * old) + qty_left * px) / (old + qty_left)
                pos -= qty_left
                self.cash += qty_left * px
            self.positions[symbol] = pos
            if abs(self.positions[symbol]) < 1e-12:
                self.positions.pop(symbol, None)
                self.avg_entry.pop(symbol, None)
        fill = {
            "symbol": symbol,
            "side": side,
            "px": px,
            "qty": qty,
            "notional_usd": round(qty * px, 2),
            **meta,
        }
        self.fills.append(fill)
        return fill

    def close_position(
        self,
        *,
        symbol: str,
        mid: float,
        bid: float,
        ask: float,
        meta: dict | None = None,
    ) -> dict | None:
        """Flatten a symbol by trading opposite side for full position notional."""
        pos = float(self.positions.get(symbol, 0.0) or 0.0)
        if abs(pos) < 1e-12:
            return None
        m = self.mark_mid(symbol, mid)
        if pos > 0:
            side = "sell"
            px = float(bid or m or 0)
            notional = abs(pos) * px
        else:
            side = "buy"
            px = float(ask or m or 0)
            notional = abs(pos) * px
        if notional < 1 or px <= 0:
            return None
        meta = dict(meta or {})
        meta.setdefault("exit", True)
        meta.setdefault("flatten", True)
        return self.maybe_trade(
            symbol=symbol,
            side=side,
            mid=m if m > 0 else px,
            bid=bid,
            ask=ask,
            notional_usd=notional,
            meta=meta,
        )
