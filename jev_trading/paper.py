from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Book:
    cash: float = 10_000.0
    position: float = 0.0
    avg_entry: float = 0.0
    realized_pnl: float = 0.0
    fills: list[dict] = field(default_factory=list)
    trade_frac: float = 0.01

    def equity(self, mid: float) -> float:
        return self.cash + self.position * mid

    def mark_pnl(self, mid: float) -> float:
        if self.position:
            return self.realized_pnl + self.position * (mid - self.avg_entry)
        return self.realized_pnl

    def maybe_trade(self, *, side: str, mid: float, bid: float, ask: float, meta: dict) -> dict | None:
        px = ask if side == "buy" else bid
        notional = self.equity(mid) * self.trade_frac
        if notional < 1 or px <= 0:
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
        fill = {"side": side, "px": px, "qty": qty, **meta}
        self.fills.append(fill)
        return fill
