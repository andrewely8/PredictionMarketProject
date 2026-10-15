"""Matching engine and portfolio for the simulator.

Fill model (what a strategy can and cannot expect):

* Taker orders fill immediately against the recorded book at the moment the order arrives,
  walking price levels best-first, never better than the limit price.
* Liquidity you take is remembered per price level, so the same resting size cannot be bought
  twice. It is released when the recording changes that level (that level's queue was replaced).
  Your orders never move the recorded book itself: the market data you receive is what happened.
* Resting (maker) orders fill at their own limit price when the recorded book crosses them
  (e.g. a resting YES bid at 45c fills once someone offers YES at <= 45c). Queue position is
  ignored, so maker fills are optimistic.
* Fees: Kalshi's formula, ceil(rate * count * P * (1 - P)) rounded up to the cent, per fill.
  Taker rate 0.07 and maker rate 0 by default (File → Settings).
* Positions follow Kalshi: a market position is YES contracts (positive) or NO contracts
  (negative). Buying costs the price of the side you buy; selling returns it.
"""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass, field

from ..marketdata.book import PRICE_SCALE, OrderBook, fmt_count, to_dollars

TIFS = ("good_till_canceled", "immediate_or_cancel", "fill_or_kill")
EPS = 1e-9


class OrderRejected(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def fee_dollars(rate: float, count: float, price_units: int) -> float:
    p = price_units / PRICE_SCALE
    raw = rate * count * p * (1 - p)
    return math.ceil(round(raw * 100, 6)) / 100 if raw > 0 else 0.0


@dataclass
class Fill:
    trade_id: str
    order_id: str
    client_order_id: str | None
    ticker: str
    book_side: str          # "bid" (bought YES) | "ask" (sold YES)
    price: int              # YES price units
    count: float
    fee: float
    is_taker: bool
    ts_ms: int
    post_position: float

    def kalshi(self) -> dict:
        """Shape of a Kalshi `fill` websocket message / GET /portfolio/fills entry."""
        buy = self.book_side == "bid"
        return {
            "trade_id": self.trade_id, "order_id": self.order_id, "client_order_id": self.client_order_id,
            "market_ticker": self.ticker, "ticker": self.ticker, "is_taker": self.is_taker,
            "side": "yes", "action": "buy" if buy else "sell", "book_side": self.book_side,
            "purchased_side": "yes" if buy else "no",
            "yes_price_dollars": to_dollars(self.price), "no_price_dollars": to_dollars(PRICE_SCALE - self.price),
            "count_fp": fmt_count(self.count), "fee_cost": f"{self.fee:.6f}",
            "ts": self.ts_ms // 1000, "ts_ms": self.ts_ms, "post_position_fp": fmt_count(self.post_position),
        }


@dataclass
class Order:
    order_id: str
    client_order_id: str | None
    ticker: str
    side: str               # "bid" = buy YES, "ask" = sell YES
    price: int
    count: float
    time_in_force: str
    post_only: bool
    created_ts: int
    remaining: float = 0.0
    status: str = "resting"  # resting | executed | canceled
    fills: list[Fill] = field(default_factory=list)

    @property
    def filled(self) -> float:
        return self.count - self.remaining

    def avg_price(self) -> float | None:
        n = sum(f.count for f in self.fills)
        return sum(f.price * f.count for f in self.fills) / n if n else None

    def kalshi(self) -> dict:
        avg = self.avg_price()
        fees = sum(f.fee for f in self.fills)
        return {
            "order_id": self.order_id, "client_order_id": self.client_order_id, "ticker": self.ticker,
            "side": self.side, "action": "buy" if self.side == "bid" else "sell", "status": self.status,
            "price": to_dollars(self.price), "yes_price_dollars": to_dollars(self.price),
            "time_in_force": self.time_in_force, "post_only": self.post_only,
            "initial_count_fp": fmt_count(self.count), "fill_count_fp": fmt_count(self.filled),
            "remaining_count_fp": fmt_count(self.remaining),
            "average_fill_price": to_dollars(round(avg)) if avg is not None else None,
            "fees_paid_dollars": f"{fees:.4f}", "created_ts_ms": self.created_ts,
        }


@dataclass
class Position:
    qty: float = 0.0          # + YES contracts, - NO contracts
    yes_cost: float = 0.0     # dollars paid for the YES contracts currently held
    no_cost: float = 0.0      # dollars paid for the NO contracts currently held
    realized: float = 0.0
    fees: float = 0.0
    traded: float = 0.0       # dollars traded


class Exchange:
    def __init__(self, books: dict[str, OrderBook], starting_cash: float,
                 taker_rate: float = 0.07, maker_rate: float = 0.0) -> None:
        self.books = books                      # ticker -> live OrderBook (owned by the session)
        self.starting_cash = starting_cash
        self.cash = starting_cash
        self.taker_rate, self.maker_rate = taker_rate, maker_rate
        self.orders: dict[str, Order] = {}
        self.fills: list[Fill] = []
        self.positions: dict[str, Position] = {}
        self._consumed: dict[tuple[str, bool, int], float] = {}   # (ticker, no_side, price) -> qty taken
        self._client_ids: set[str] = set()
        self.listeners: list = []               # callables(fill) for websocket `fill` subscribers

    # ------------------------------------------------------------------ market data hooks

    def level_changed(self, ticker: str, side_no: bool, price: int, new_qty: float) -> None:
        key = (ticker, side_no, price)
        if key in self._consumed:
            self._consumed[key] = min(self._consumed[key], new_qty)
            if self._consumed[key] <= EPS:
                del self._consumed[key]

    def book_replaced(self, ticker: str) -> None:
        for key in [k for k in self._consumed if k[0] == ticker]:
            del self._consumed[key]

    # ------------------------------------------------------------------ matching

    def _available(self, ticker: str, side_no: bool, price: int, qty: float) -> float:
        return max(0.0, qty - self._consumed.get((ticker, side_no, price), 0.0))

    def _crossing_levels(self, book: OrderBook, side: str, limit: int):
        """Yield (yes_price, book_no_side, raw_book_price, available) best-first for a taker order."""
        if side == "bid":   # buy YES: consume NO bids; YES ask = 1 - NO bid
            for no_price in sorted(book.no, reverse=True):
                yes_price = PRICE_SCALE - no_price
                if yes_price > limit:
                    break
                yield yes_price, True, no_price, self._available(book.ticker, True, no_price, book.no[no_price])
        else:               # sell YES: consume YES bids
            for yes_price in sorted(book.yes, reverse=True):
                if yes_price < limit:
                    break
                yield yes_price, False, yes_price, self._available(book.ticker, False, yes_price, book.yes[yes_price])

    def _collateral(self, ticker: str, side: str, price: int, count: float) -> float:
        """Cash needed: buying YES costs P; selling YES beyond a long position buys NO at 1-P."""
        pos = self.positions.get(ticker, Position()).qty
        if side == "bid":
            closing = min(count, max(0.0, -pos))
            return (count - closing) * price / PRICE_SCALE
        closing = min(count, max(0.0, pos))
        return (count - closing) * (PRICE_SCALE - price) / PRICE_SCALE

    def submit(self, *, ticker: str, side: str, price: int, count: float, now_ms: int,
               time_in_force: str = "good_till_canceled", post_only: bool = False,
               client_order_id: str | None = None) -> Order:
        if ticker not in self.books:
            raise OrderRejected("market_not_found", f"Market {ticker} is not in the replayed recording")
        if side not in ("bid", "ask"):
            raise OrderRejected("invalid_parameters", "side must be 'bid' (buy YES) or 'ask' (sell YES)")
        if not (0 < price < PRICE_SCALE):
            raise OrderRejected("invalid_parameters", "price must be between 0.0001 and 0.9999 dollars")
        if count <= 0 or round(count, 2) != round(count, 6):
            raise OrderRejected("invalid_parameters", "count must be positive with at most 2 decimals")
        if time_in_force not in TIFS:
            raise OrderRejected("invalid_parameters", f"time_in_force must be one of {TIFS}")
        if client_order_id:
            if client_order_id in self._client_ids:
                raise OrderRejected("duplicate_client_order_id", "client_order_id was already used")
            self._client_ids.add(client_order_id)
        needed = self._collateral(ticker, side, price, count)
        fee_reserve = fee_dollars(self.taker_rate, count, price)
        if needed + fee_reserve > self.cash + EPS:
            raise OrderRejected("insufficient_balance",
                                f"Order needs ${needed + fee_reserve:.2f}, balance is ${self.cash:.2f}")
        book = self.books[ticker]
        levels = list(self._crossing_levels(book, side, price))
        crosses = any(avail > EPS for *_, avail in levels)
        if post_only and crosses:
            raise OrderRejected("post_only_cross", "post_only order would cross the book")
        if time_in_force == "fill_or_kill" and sum(a for *_, a in levels) + EPS < count:
            raise OrderRejected("fill_or_kill_insufficient", "Not enough liquidity to fill the whole order")

        order = Order(order_id=str(uuid.uuid4()), client_order_id=client_order_id, ticker=ticker, side=side,
                      price=price, count=count, time_in_force=time_in_force, post_only=post_only,
                      created_ts=now_ms, remaining=count)
        self.orders[order.order_id] = order
        for yes_price, no_side, raw_price, avail in levels:
            if order.remaining <= EPS:
                break
            take = min(order.remaining, avail)
            if take <= EPS:
                continue
            key = (ticker, no_side, raw_price)
            self._consumed[key] = self._consumed.get(key, 0.0) + take
            self._fill(order, yes_price, take, is_taker=True, now_ms=now_ms)
        if order.remaining <= EPS:
            order.remaining, order.status = 0.0, "executed"
        elif time_in_force != "good_till_canceled":
            order.status = "canceled"
        return order

    def cancel(self, order_id: str) -> Order:
        order = self.orders.get(order_id)
        if order is None:
            raise OrderRejected("not_found", "Order not found")
        if order.status == "resting":
            order.status = "canceled"
        return order

    def match_resting(self, now_ms: int) -> list[Fill]:
        """After new market data: fill resting orders the book has crossed (maker fills at our price)."""
        new: list[Fill] = []
        for order in [o for o in self.orders.values() if o.status == "resting"]:
            book = self.books[order.ticker]
            for _yes_price, no_side, raw_price, avail in self._crossing_levels(book, order.side, order.price):
                if order.remaining <= EPS:
                    break
                take = min(order.remaining, avail)
                if take <= EPS:
                    continue
                need = self._collateral(order.ticker, order.side, order.price, take)
                if need > self.cash + EPS:
                    order.status = "canceled"   # Kalshi would cancel for insufficient balance
                    break
                key = (order.ticker, no_side, raw_price)
                self._consumed[key] = self._consumed.get(key, 0.0) + take
                new.append(self._fill(order, order.price, take, is_taker=False, now_ms=now_ms))
            if order.remaining <= EPS and order.status == "resting":
                order.remaining, order.status = 0.0, "executed"
        return new

    # ------------------------------------------------------------------ accounting

    def _fill(self, order: Order, price: int, count: float, *, is_taker: bool, now_ms: int) -> Fill:
        pos = self.positions.setdefault(order.ticker, Position())
        p = price / PRICE_SCALE
        fee = fee_dollars(self.taker_rate if is_taker else self.maker_rate, count, price)
        if order.side == "bid":                      # buy YES (first closes any NO position)
            close = min(count, max(0.0, -pos.qty))
            if close > 0:
                avg_no = pos.no_cost / -pos.qty
                proceeds = close * (1 - p)
                pos.realized += proceeds - close * avg_no
                pos.no_cost -= close * avg_no
                self.cash += proceeds
                pos.qty += close
            opened = count - close
            if opened > 0:
                self.cash -= opened * p
                pos.yes_cost += opened * p
                pos.qty += opened
        else:                                        # sell YES (first closes any YES position)
            close = min(count, max(0.0, pos.qty))
            if close > 0:
                avg_yes = pos.yes_cost / pos.qty
                proceeds = close * p
                pos.realized += proceeds - close * avg_yes
                pos.yes_cost -= close * avg_yes
                self.cash += proceeds
                pos.qty -= close
            opened = count - close
            if opened > 0:
                self.cash -= opened * (1 - p)
                pos.no_cost += opened * (1 - p)
                pos.qty -= opened
        self.cash -= fee
        pos.fees += fee
        pos.realized -= fee
        pos.traded += count * p
        if abs(pos.qty) < EPS:
            pos.qty, pos.yes_cost, pos.no_cost = 0.0, 0.0, 0.0
        order.remaining -= count
        fill = Fill(trade_id=str(uuid.uuid4()), order_id=order.order_id, client_order_id=order.client_order_id,
                    ticker=order.ticker, book_side=order.side, price=price, count=count, fee=fee,
                    is_taker=is_taker, ts_ms=now_ms, post_position=pos.qty)
        order.fills.append(fill)
        self.fills.append(fill)
        for listener in self.listeners:
            listener(fill)
        return fill

    def position_value(self, ticker: str, pos: Position, how: str = "mid") -> float:
        """Value of a position: 'mid' marks at the midpoint, 'liquidation' at the price you could sell."""
        book = self.books[ticker]
        yb, ya = book.yes_bid(), book.yes_ask()
        if pos.qty > 0:
            if how == "liquidation":
                px = yb[0] if yb else 0
            else:
                px = book.mid_units() or (yb[0] if yb else 0)
            return pos.qty * px / PRICE_SCALE
        if pos.qty < 0:
            if how == "liquidation":
                px = ya[0] if ya else PRICE_SCALE    # NO bid = 1 - YES ask
            else:
                px = book.mid_units() or (ya[0] if ya else PRICE_SCALE)
            return -pos.qty * (PRICE_SCALE - px) / PRICE_SCALE
        return 0.0

    def equity(self, how: str = "mid") -> float:
        return self.cash + sum(self.position_value(t, p, how) for t, p in self.positions.items())

    def summary(self) -> dict:
        eq = self.equity()
        return {
            "cash": round(self.cash, 4), "equity": round(eq, 4),
            "liquidation_equity": round(self.equity("liquidation"), 4),
            "pnl": round(eq - self.starting_cash, 4),
            "realized_pnl": round(sum(p.realized for p in self.positions.values()), 4),
            "fees": round(sum(p.fees for p in self.positions.values()), 4),
            "fills": len(self.fills), "orders": len(self.orders),
            "open_orders": sum(1 for o in self.orders.values() if o.status == "resting"),
            "contracts_traded": round(sum(f.count for f in self.fills), 2),
            "positions": {t: round(p.qty, 2) for t, p in self.positions.items() if abs(p.qty) > EPS},
        }

    def kalshi_positions(self) -> list[dict]:
        out = []
        for t, p in self.positions.items():
            out.append({
                "ticker": t, "exchange_index": 0, "position_fp": fmt_count(p.qty),
                "total_traded_dollars": f"{p.traded:.4f}",
                "market_exposure_dollars": f"{(p.yes_cost + p.no_cost):.4f}",
                "realized_pnl_dollars": f"{p.realized:.4f}", "fees_paid_dollars": f"{p.fees:.4f}",
                "last_updated_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
        return out
