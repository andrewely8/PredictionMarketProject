"""Matching engine, fees and Kalshi-style position accounting."""

import pytest

from engine.marketdata.book import OrderBook, to_units
from engine.sim.exchange import Exchange, OrderRejected, fee_dollars


def make(cash=100.0, taker=0.07, maker=0.0):
    b = OrderBook("T")
    # YES bids 40c x10, 45c x5 ; NO bids 52c x3, 50c x7  -> YES asks 48c x3, 50c x7
    b.load({to_units("0.40"): 10, to_units("0.45"): 5}, {to_units("0.52"): 3, to_units("0.50"): 7})
    return Exchange({"T": b}, starting_cash=cash, taker_rate=taker, maker_rate=maker), b


def test_fee_formula_matches_kalshi():
    assert fee_dollars(0.07, 1, to_units("0.50")) == 0.02      # 0.0175 -> 2c
    assert fee_dollars(0.07, 100, to_units("0.50")) == 1.75
    assert fee_dollars(0.0, 10, to_units("0.50")) == 0.0


def test_taker_walks_levels_and_respects_limit():
    ex, _ = make(taker=0)
    o = ex.submit(ticker="T", side="bid", price=to_units("0.50"), count=5, now_ms=1,
                  time_in_force="immediate_or_cancel")
    assert [(f.price, f.count) for f in o.fills] == [(to_units("0.48"), 3), (to_units("0.50"), 2)]
    assert o.status == "executed" and ex.positions["T"].qty == 5
    assert ex.cash == pytest.approx(100 - (3 * 0.48 + 2 * 0.50))


def test_consumed_liquidity_is_not_reused_until_the_level_changes():
    ex, book = make(taker=0)
    ex.submit(ticker="T", side="bid", price=to_units("0.48"), count=3, now_ms=1, time_in_force="immediate_or_cancel")
    again = ex.submit(ticker="T", side="bid", price=to_units("0.48"), count=3, now_ms=2,
                      time_in_force="immediate_or_cancel")
    assert again.filled == 0 and again.status == "canceled"
    new_qty = book.apply(True, to_units("0.52"), 2)        # recording adds 2 more at that level
    ex.level_changed("T", True, to_units("0.52"), new_qty)
    third = ex.submit(ticker="T", side="bid", price=to_units("0.48"), count=5, now_ms=3,
                      time_in_force="immediate_or_cancel")
    assert third.filled == 2


def test_time_in_force_and_post_only():
    ex, _ = make()
    with pytest.raises(OrderRejected) as e:
        ex.submit(ticker="T", side="bid", price=to_units("0.48"), count=10, now_ms=1, time_in_force="fill_or_kill")
    assert e.value.code == "fill_or_kill_insufficient"
    with pytest.raises(OrderRejected) as e:
        ex.submit(ticker="T", side="bid", price=to_units("0.49"), count=1, now_ms=1, post_only=True)
    assert e.value.code == "post_only_cross"
    resting = ex.submit(ticker="T", side="bid", price=to_units("0.46"), count=2, now_ms=1, post_only=True)
    assert resting.status == "resting" and resting.filled == 0


def test_resting_order_fills_as_maker_when_book_crosses():
    ex, book = make(maker=0.0)
    o = ex.submit(ticker="T", side="bid", price=to_units("0.46"), count=2, now_ms=1)
    assert o.status == "resting"
    book.apply(True, to_units("0.55"), 4)       # NO bid 55c appears -> YES ask 45c <= our 46c bid
    fills = ex.match_resting(now_ms=5)
    assert len(fills) == 1 and fills[0].price == to_units("0.46") and not fills[0].is_taker
    assert o.status == "executed" and ex.positions["T"].qty == 2


def test_selling_yes_without_position_buys_no_and_round_trip_pnl():
    ex, _ = make(taker=0)
    ex.submit(ticker="T", side="ask", price=to_units("0.45"), count=2, now_ms=1, time_in_force="immediate_or_cancel")
    pos = ex.positions["T"]
    assert pos.qty == -2 and ex.cash == pytest.approx(100 - 2 * 0.55)   # bought 2 NO at 55c
    ex.submit(ticker="T", side="bid", price=to_units("0.48"), count=2, now_ms=2, time_in_force="immediate_or_cancel")
    assert pos.qty == 0 and pos.realized == pytest.approx(2 * ((1 - 0.48) - 0.55))
    assert ex.cash == pytest.approx(100 + pos.realized)


def test_balance_and_client_order_id_checks():
    ex, _ = make(cash=1.0)
    with pytest.raises(OrderRejected) as e:
        ex.submit(ticker="T", side="bid", price=to_units("0.50"), count=5, now_ms=1)
    assert e.value.code == "insufficient_balance"
    ex.submit(ticker="T", side="bid", price=to_units("0.30"), count=1, now_ms=1, client_order_id="abc")
    with pytest.raises(OrderRejected):
        ex.submit(ticker="T", side="bid", price=to_units("0.30"), count=1, now_ms=1, client_order_id="abc")
    with pytest.raises(OrderRejected):
        ex.submit(ticker="X", side="bid", price=to_units("0.30"), count=1, now_ms=1)


def test_equity_marks_positions():
    ex, _ = make(taker=0)
    ex.submit(ticker="T", side="bid", price=to_units("0.48"), count=3, now_ms=1, time_in_force="immediate_or_cancel")
    mid = (0.45 + 0.48) / 2        # our fills never change the recorded book: the ask is still 48c
    assert ex.equity() == pytest.approx(100 - 3 * 0.48 + 3 * mid)
    assert ex.equity("liquidation") == pytest.approx(100 - 3 * 0.48 + 3 * 0.45)
