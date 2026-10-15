"""Recording parser and order book."""

import numpy as np

from conftest import write_jsonl
from engine.marketdata.book import OrderBook, to_units
from engine.marketdata.recording import Recording, load_recording

SNAP = {"type": "orderbook_snapshot", "sid": 1, "seq": 1, "msg": {
    "market_ticker": "T", "market_id": "m",
    "yes_dollars_fp": [["0.4000", "10.00"], ["0.4500", "5.00"]],
    "no_dollars_fp": [["0.5000", "7.00"], ["0.5200", "3.00"]]}}


def delta(price, qty, side, ts, ticker="T"):
    return {"type": "orderbook_delta", "sid": 1, "seq": 2, "msg": {
        "market_ticker": ticker, "price_dollars": price, "delta_fp": qty, "side": side, "ts_ms": ts}}


def test_book_conventions():
    b = OrderBook("T")
    b.load({to_units("0.40"): 10, to_units("0.45"): 5}, {to_units("0.52"): 3})
    top = b.top()
    assert top["best_yes_bid_dollars"] == "0.4500" and top["best_yes_ask_dollars"] == "0.4800"
    assert top["best_no_bid_dollars"] == "0.5200" and top["best_no_ask_dollars"] == "0.5500"
    assert b.apply(False, to_units("0.45"), -5) == 0.0     # level removed
    assert b.yes_bid() == (to_units("0.40"), 10)
    assert b.levels_fp()["yes_dollars"] == [["0.4000", "10.00"]]


def test_recording_parses_and_stamps_snapshots(tmp_path):
    p = tmp_path / "r.jsonl"
    write_jsonl(p, [{"type": "subscribed", "id": 1, "msg": {}}, SNAP,
                    delta("0.4500", "-5.00", "yes", 1000), delta("0.4600", "8.00", "yes", 2000),
                    "not json", '"a string"', SNAP, delta("0.4100", "1.00", "yes", 3000)])
    rec = Recording(str(p))
    assert rec.tickers == ["T"] and len(rec) == 5
    assert rec.parse_errors == 2
    assert list(rec.ts) == [1000, 1000, 2000, 2000, 3000]   # snapshots take the neighbouring time
    books = rec.books_before(len(rec))
    assert books[0].yes_bid() == (to_units("0.45"), 5.0)     # 2nd snapshot replaced the book, then +0.41
    assert to_units("0.41") in books[0].yes
    assert rec.index_at(1999) == 2 and rec.index_at(2000) == 4


def test_checkpoint_seek_matches_sequential_replay(data_path, monkeypatch):
    import engine.marketdata.recording as recmod
    monkeypatch.setattr(recmod, "CHECKPOINT_EVERY", 997)
    rec = Recording(data_path)
    sequential = rec.new_books()
    for i in range(len(rec)):
        if i in (0, 500, 4321, len(rec) - 1):
            seeked = rec.books_before(i)
            for t in sequential:
                assert seeked[t].yes == sequential[t].yes and seeked[t].no == sequential[t].no
        rec.apply(sequential, i)


def test_load_recording_is_cached(data_path):
    assert load_recording(data_path) is load_recording(data_path)
    assert np.all(np.diff(load_recording(data_path).ts) >= 0)
