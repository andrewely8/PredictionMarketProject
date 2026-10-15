"""Load a recorded .jsonl file once into compact arrays, and replay it.

A 400 MB / 1.5M-line game loads in a few seconds (orjson) and takes ~40 MB in memory. Book
checkpoints every CHECKPOINT_EVERY events make seeking anywhere in the recording instant.

Snapshot lines carry no timestamp; they are stamped with the timestamp of the previous event (or of
the first delta if they open the file). A snapshot in the middle of a file (the collector reconnected)
replaces that market's book, exactly as on the live exchange.
"""

from __future__ import annotations

import os
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable, Iterator

import numpy as np
import orjson

from .book import OrderBook, to_units

KIND_DELTA, KIND_SNAPSHOT = 0, 1
CHECKPOINT_EVERY = 50_000


@dataclass
class Snapshot:
    yes: dict[int, float]
    no: dict[int, float]


class Recording:
    """Parsed recording. Events are kept in file order (the order the exchange sent them)."""

    def __init__(self, path: str, progress: Callable[[float], None] | None = None) -> None:
        self.path = os.path.abspath(path)
        self.name = os.path.basename(path)
        st = os.stat(path)
        self.size_bytes = st.st_size
        self.mtime_ns = st.st_mtime_ns
        self.tickers: list[str] = []
        self.market_ids: dict[str, str] = {}
        self.snapshots: list[Snapshot] = []
        self.lines = 0
        self.parse_errors = 0
        self.event_counts: dict[str, int] = {}
        self._parse(progress)
        self._build_checkpoints()

    # ------------------------------------------------------------------ parsing

    def _parse(self, progress) -> None:
        index: dict[str, int] = {}
        kind, ts, tick, side, price, delta, ref = [], [], [], [], [], [], []
        last_ts = -1
        read = 0
        with open(self.path, "rb") as fh:
            for raw in fh:
                read += len(raw)
                if not raw.strip():
                    continue
                self.lines += 1
                if progress and self.lines % 200_000 == 0:
                    progress(read / max(self.size_bytes, 1))
                try:
                    ev = orjson.loads(raw)
                    etype = ev.get("type", "unknown")
                except (orjson.JSONDecodeError, AttributeError):
                    self.parse_errors += 1
                    continue
                self.event_counts[etype] = self.event_counts.get(etype, 0) + 1
                msg = ev.get("msg") or {}
                ticker = msg.get("market_ticker")
                if not ticker or etype not in ("orderbook_snapshot", "orderbook_delta"):
                    continue
                t = index.get(ticker)
                if t is None:
                    t = index[ticker] = len(self.tickers)
                    self.tickers.append(ticker)
                if msg.get("market_id"):
                    self.market_ids[ticker] = msg["market_id"]
                try:
                    if etype == "orderbook_snapshot":
                        snap = Snapshot(
                            {to_units(p): float(q) for p, q in (msg.get("yes_dollars_fp") or [])},
                            {to_units(p): float(q) for p, q in (msg.get("no_dollars_fp") or [])})
                        kind.append(KIND_SNAPSHOT); ts.append(msg.get("ts_ms") or last_ts); tick.append(t)
                        side.append(0); price.append(0); delta.append(0.0); ref.append(len(self.snapshots))
                        self.snapshots.append(snap)
                    else:
                        e_ts = int(msg["ts_ms"])
                        e_side = 1 if msg["side"] == "no" else 0
                        e_price = to_units(msg["price_dollars"])
                        e_delta = float(msg["delta_fp"])
                        kind.append(KIND_DELTA); ts.append(e_ts); tick.append(t)
                        side.append(e_side); price.append(e_price); delta.append(e_delta); ref.append(-1)
                        last_ts = e_ts
                except (KeyError, TypeError, ValueError):
                    self.parse_errors += 1
        self.kind = np.array(kind, dtype=np.int8)
        self.ts = np.array(ts, dtype=np.int64)
        self.tick = np.array(tick, dtype=np.int16)
        self.side = np.array(side, dtype=np.int8)
        self.price = np.array(price, dtype=np.int32)
        self.delta = np.array(delta, dtype=np.float64)
        self.ref = np.array(ref, dtype=np.int32)
        # Opening snapshots had no timestamp yet: give them the first real timestamp.
        valid = self.ts >= 0
        if valid.any():
            first = int(self.ts[valid][0])
            self.ts[~valid] = first
        # Enforce non-decreasing time so the clock never runs backwards on a late message.
        if len(self.ts):
            np.maximum.accumulate(self.ts, out=self.ts)
        if progress:
            progress(1.0)

    def _build_checkpoints(self) -> None:
        """Book state before event i for i = 0, CHECKPOINT_EVERY, 2*CHECKPOINT_EVERY, ..."""
        self._checkpoints: list[dict[int, OrderBook]] = []
        books = self.new_books()
        for i in range(len(self.kind)):
            if i % CHECKPOINT_EVERY == 0:
                self._checkpoints.append({t: b.copy() for t, b in books.items()})
            self.apply(books, i)

    # ------------------------------------------------------------------ replay helpers

    def __len__(self) -> int:
        return len(self.kind)

    @property
    def start_ts(self) -> int:
        return int(self.ts[0]) if len(self.ts) else 0

    @property
    def end_ts(self) -> int:
        return int(self.ts[-1]) if len(self.ts) else 0

    def new_books(self) -> dict[int, OrderBook]:
        return {i: OrderBook(t, self.market_ids.get(t, "")) for i, t in enumerate(self.tickers)}

    def apply(self, books: dict[int, OrderBook], i: int) -> None:
        book = books[int(self.tick[i])]
        if self.kind[i] == KIND_SNAPSHOT:
            snap = self.snapshots[int(self.ref[i])]
            book.load(snap.yes, snap.no)
        else:
            book.apply(bool(self.side[i]), int(self.price[i]), float(self.delta[i]))

    def books_before(self, i: int) -> dict[int, OrderBook]:
        """Book state just before event i (uses the nearest checkpoint)."""
        i = max(0, min(i, len(self)))
        c = min(i // CHECKPOINT_EVERY, len(self._checkpoints) - 1) if self._checkpoints else -1
        if c < 0:
            books, start = self.new_books(), 0
        else:
            books, start = {t: b.copy() for t, b in self._checkpoints[c].items()}, c * CHECKPOINT_EVERY
        for j in range(start, i):
            self.apply(books, j)
        return books

    def index_at(self, ts_ms: float) -> int:
        """Number of events with timestamp <= ts_ms."""
        return int(np.searchsorted(self.ts, ts_ms, side="right"))

    def iter_events(self, start: int, stop: int) -> Iterator[int]:
        return iter(range(start, min(stop, len(self))))

    def summary(self) -> dict:
        return {
            "file": self.name, "size_mb": round(self.size_bytes / 1e6, 2), "lines": self.lines,
            "events": len(self), "parse_errors": self.parse_errors, "event_counts": self.event_counts,
            "tickers": self.tickers, "start_ts": self.start_ts, "end_ts": self.end_ts,
            "duration_s": (self.end_ts - self.start_ts) / 1000,
        }


# --------------------------------------------------------------------------- cache

_CACHE: "OrderedDict[tuple, Recording]" = OrderedDict()
_LOCK = threading.Lock()
_LOADING: dict[str, threading.Event] = {}
CACHE_SIZE = 3


def load_recording(path: str, progress: Callable[[float], None] | None = None) -> Recording:
    """Parse once per (path, size, mtime); concurrent callers share one parse."""
    st = os.stat(path)
    key = (os.path.realpath(path), st.st_size, st.st_mtime_ns)
    while True:
        with _LOCK:
            if key in _CACHE:
                _CACHE.move_to_end(key)
                return _CACHE[key]
            waiter = _LOADING.get(key[0])
            if waiter is None:
                _LOADING[key[0]] = threading.Event()
                break
        waiter.wait()
    try:
        rec = Recording(path, progress)
        with _LOCK:
            _CACHE[key] = rec
            while len(_CACHE) > CACHE_SIZE:
                _CACHE.popitem(last=False)
        return rec
    finally:
        with _LOCK:
            _LOADING.pop(key[0]).set()
