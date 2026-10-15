"""Kalshi order book for one market.

Kalshi books only contain bids: YES bids and NO bids. Buying YES at p is the same as selling NO at
1 - p, so:

    best YES bid = highest YES bid            best YES ask = 1 - highest NO bid
    best NO bid  = highest NO bid             best NO ask  = 1 - highest YES bid

Prices are stored as integer units of 1/10000 dollar (Kalshi sends 4 decimals), quantities as floats
(Kalshi sends fixed-point contract counts with 2 decimals).
"""

from __future__ import annotations

PRICE_SCALE = 10_000
EPS = 1e-9


def to_units(price_dollars: str | float) -> int:
    return int(round(float(price_dollars) * PRICE_SCALE))


def to_dollars(units: int) -> str:
    return f"{units / PRICE_SCALE:.4f}"


def fmt_count(qty: float) -> str:
    return f"{qty:.2f}"


class OrderBook:
    __slots__ = ("ticker", "market_id", "yes", "no", "best_yes", "best_no")

    def __init__(self, ticker: str, market_id: str = "") -> None:
        self.ticker = ticker
        self.market_id = market_id
        self.yes: dict[int, float] = {}
        self.no: dict[int, float] = {}
        self.best_yes: int | None = None
        self.best_no: int | None = None

    def copy(self) -> "OrderBook":
        b = OrderBook(self.ticker, self.market_id)
        b.yes, b.no = dict(self.yes), dict(self.no)
        b.best_yes, b.best_no = self.best_yes, self.best_no
        return b

    def load(self, yes: dict[int, float], no: dict[int, float]) -> None:
        self.yes = {p: q for p, q in yes.items() if q > EPS}
        self.no = {p: q for p, q in no.items() if q > EPS}
        self.best_yes = max(self.yes) if self.yes else None
        self.best_no = max(self.no) if self.no else None

    def apply(self, side_no: bool, price: int, delta: float) -> float:
        """Apply a delta; returns the new quantity at that level."""
        levels = self.no if side_no else self.yes
        qty = levels.get(price, 0.0) + delta
        if qty > EPS:
            levels[price] = qty
        else:
            qty = 0.0
            levels.pop(price, None)
        best = self.best_no if side_no else self.best_yes
        if qty > 0 and (best is None or price > best):
            best = price
        elif price == best and qty == 0:
            best = max(levels) if levels else None
        if side_no:
            self.best_no = best
        else:
            self.best_yes = best
        return qty

    # ------------------------------------------------------------------ views

    def yes_bid(self) -> tuple[int, float] | None:
        return (self.best_yes, self.yes[self.best_yes]) if self.best_yes is not None else None

    def yes_ask(self) -> tuple[int, float] | None:
        return (PRICE_SCALE - self.best_no, self.no[self.best_no]) if self.best_no is not None else None

    def top(self) -> dict:
        """Top of book in the same shape the Replayer has always displayed."""
        yb, ya = self.yes_bid(), self.yes_ask()
        nb = (self.best_no, self.no[self.best_no]) if self.best_no is not None else None
        na = (PRICE_SCALE - self.best_yes, self.yes[self.best_yes]) if self.best_yes is not None else None

        def p(x):
            return to_dollars(x[0]) if x else None

        def q(x):
            return fmt_count(x[1]) if x else None
        return {
            "best_yes_bid_dollars": p(yb), "best_yes_bid_volume": q(yb),
            "best_yes_ask_dollars": p(ya), "best_yes_ask_volume": q(ya),
            "best_no_bid_dollars": p(nb), "best_no_bid_volume": q(nb),
            "best_no_ask_dollars": p(na), "best_no_ask_volume": q(na),
        }

    def mid_units(self) -> float | None:
        yb, ya = self.yes_bid(), self.yes_ask()
        if yb and ya:
            return (yb[0] + ya[0]) / 2
        return None

    def levels_fp(self, depth: int = 0) -> dict:
        """Kalshi `orderbook_fp` shape: ascending [price_dollars, count] pairs (best price last)."""
        def side(levels: dict[int, float]) -> list[list[str]]:
            items = sorted(levels.items())
            if depth > 0:
                items = items[-depth:]
            return [[to_dollars(p), fmt_count(q)] for p, q in items]
        return {"yes_dollars": side(self.yes), "no_dollars": side(self.no)}
