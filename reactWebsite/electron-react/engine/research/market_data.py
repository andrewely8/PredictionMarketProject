"""Deterministic statistics over recorded order books, used by the AI research tools.

Recordings are loaded with the shared parser (engine.marketdata.recording) and replayed into a
compact top-of-book series per market, recorded only when the top of book changes. Every number the
LLM sees is computed here; raw file lines never go into a prompt.

Conventions (same as the simulator): best YES ask = 1 - best NO bid; prices reported in cents (0-100)
of the YES contract; imbalance = (bid_qty - ask_qty) / (bid_qty + ask_qty) at the top of book.
"""

from __future__ import annotations

import math
import os
import threading
from array import array
from collections import OrderedDict
from datetime import datetime, timezone

import numpy as np
from langsmith import traceable

from ..marketdata.book import PRICE_SCALE
from ..marketdata.recording import load_recording

UNITS_PER_CENT = PRICE_SCALE // 100
MAX_GRID_POINTS = 200_000


def iso(ts_ms: float | None) -> str | None:
    if ts_ms is None or (isinstance(ts_ms, float) and math.isnan(ts_ms)):
        return None
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat(timespec="seconds")


def _r(x, digits: int = 4):
    """Round for JSON output; NaN/inf become None."""
    if x is None:
        return None
    x = float(x)
    if math.isnan(x) or math.isinf(x):
        return None
    return round(x, digits)


class TickerSeries:
    """Top-of-book series recorded only when the top of book changes."""

    def __init__(self, ticker: str) -> None:
        self.ticker = ticker
        self.ts = array("q")
        self.bid = array("q")
        self.ask = array("q")
        self.bidq = array("d")
        self.askq = array("d")
        self.deltas = 0
        self.snapshots = 0
        self.volume_added = 0.0
        self.volume_removed = 0.0
        self._last_top: tuple | None = None
        self._np: dict | None = None

    def record(self, ts_ms: int, top: tuple) -> None:
        if top == self._last_top:
            return
        self._last_top = top
        self.ts.append(ts_ms)
        self.bid.append(top[0])
        self.bidq.append(top[1])
        self.ask.append(top[2])
        self.askq.append(top[3])

    def arrays(self) -> dict:
        """Numpy view with derived fields (cents). Rows with a missing side are dropped."""
        if self._np is None:
            ts = np.frombuffer(self.ts, dtype=np.int64).astype(np.float64)
            bid = np.frombuffer(self.bid, dtype=np.int64).astype(np.float64)
            ask = np.frombuffer(self.ask, dtype=np.int64).astype(np.float64)
            bidq = np.frombuffer(self.bidq, dtype=np.float64)
            askq = np.frombuffer(self.askq, dtype=np.float64)
            ok = (bid >= 0) & (ask >= 0)
            bid, ask, bidq, askq, ts = bid[ok], ask[ok], bidq[ok], askq[ok], ts[ok]
            depth = bidq + askq
            with np.errstate(invalid="ignore", divide="ignore"):
                imb = np.where(depth > 0, (bidq - askq) / depth, 0.0)
            self._np = {
                "ts": ts,
                "bid": bid / UNITS_PER_CENT,
                "ask": ask / UNITS_PER_CENT,
                "mid": (bid + ask) / 2 / UNITS_PER_CENT,
                "spread": (ask - bid) / UNITS_PER_CENT,
                "bidq": bidq,
                "askq": askq,
                "imbalance": imb,
            }
        return self._np


class MarketData:
    """Top-of-book series per market for one recording."""

    def __init__(self, path: str) -> None:
        rec = load_recording(path)
        self.path = rec.path
        self.name = rec.name
        self.size_bytes = rec.size_bytes
        self.lines = rec.lines
        self.parse_errors = rec.parse_errors
        self.event_counts = dict(rec.event_counts)
        self.first_ts: int | None = rec.start_ts if len(rec) else None
        self.last_ts: int | None = rec.end_ts if len(rec) else None
        self.tickers: dict[str, TickerSeries] = {t: TickerSeries(t) for t in rec.tickers}
        books = rec.new_books()
        for i in range(len(rec)):
            t = int(rec.tick[i])
            rec.apply(books, i)
            series = self.tickers[rec.tickers[t]]
            if rec.kind[i] == 0:
                series.deltas += 1
                d = float(rec.delta[i])
                if d >= 0:
                    series.volume_added += d
                else:
                    series.volume_removed -= d
            else:
                series.snapshots += 1
            b = books[t]
            top = (b.best_yes if b.best_yes is not None else -1,
                   b.yes.get(b.best_yes, 0.0) if b.best_yes is not None else 0.0,
                   PRICE_SCALE - b.best_no if b.best_no is not None else -1,
                   b.no.get(b.best_no, 0.0) if b.best_no is not None else 0.0)
            series.record(int(rec.ts[i]), top)

    @property
    def duration_s(self) -> float:
        if self.first_ts is None or self.last_ts is None:
            return 0.0
        return (self.last_ts - self.first_ts) / 1000


# --------------------------------------------------------------------------- cache

_CACHE: "OrderedDict[tuple, MarketData]" = OrderedDict()
_CACHE_LOCK = threading.Lock()
_CACHE_SIZE = 4


@traceable(run_type="chain", name="load_market_data")
def load_market_data(path: str) -> MarketData:
    """Build once per (path, size, mtime); keeps the 4 most recent files in memory."""
    st = os.stat(path)
    key = (os.path.realpath(path), st.st_size, st.st_mtime_ns)
    with _CACHE_LOCK:
        if key in _CACHE:
            _CACHE.move_to_end(key)
            return _CACHE[key]
    md = MarketData(path)
    with _CACHE_LOCK:
        _CACHE[key] = md
        while len(_CACHE) > _CACHE_SIZE:
            _CACHE.popitem(last=False)
    return md


# --------------------------------------------------------------------------- helpers

def resolve_tickers(md: MarketData, ticker: str | None) -> list[str]:
    if not ticker:
        return list(md.tickers)
    if ticker in md.tickers:
        return [ticker]
    matches = [t for t in md.tickers if ticker.lower() in t.lower()]
    if not matches:
        raise ValueError(f"Ticker '{ticker}' not found in {md.name}. Available: {list(md.tickers)}")
    return matches


def _durations(ts: np.ndarray, end_ts: float) -> np.ndarray:
    """How long each top-of-book state lasted (ms); used for time weighting."""
    if len(ts) == 0:
        return ts
    return np.diff(ts, append=max(end_ts, ts[-1]))


def _weighted_mean(x: np.ndarray, w: np.ndarray) -> float:
    total = w.sum()
    return float((x * w).sum() / total) if total > 0 else float(np.mean(x)) if len(x) else float("nan")


def grid_step_ms(md: MarketData) -> int:
    span = (md.last_ts or 0) - (md.first_ts or 0)
    return max(1000, int(math.ceil(span / MAX_GRID_POINTS / 1000)) * 1000)


def as_of_grid(arr: dict, start_ts: float, end_ts: float, step_ms: int) -> dict:
    """Sample the series on a regular clock using only information known at each grid time.

    Uses the last state with ts <= grid time (no look-ahead).
    """
    grid = np.arange(start_ts, end_ts + 1, step_ms, dtype=np.float64)
    idx = np.searchsorted(arr["ts"], grid, side="right") - 1
    valid = idx >= 0
    out = {"ts": grid[valid]}
    for key in ("mid", "spread", "imbalance", "bidq", "askq"):
        out[key] = arr[key][idx[valid]]
    return out


def _ticker_headline(md: MarketData, ticker: str) -> dict:
    s = md.tickers[ticker]
    a = s.arrays()
    if len(a["ts"]) == 0:
        return {"ticker": ticker, "deltas": s.deltas, "note": "no two-sided top of book observed"}
    w = _durations(a["ts"], md.last_ts or a["ts"][-1])
    return {
        "ticker": ticker,
        "deltas": s.deltas,
        "snapshots": s.snapshots,
        "top_of_book_updates": int(len(a["ts"])),
        "first_mid_cents": _r(a["mid"][0], 2),
        "last_mid_cents": _r(a["mid"][-1], 2),
        "min_mid_cents": _r(a["mid"].min(), 2),
        "max_mid_cents": _r(a["mid"].max(), 2),
        "time_weighted_mean_spread_cents": _r(_weighted_mean(a["spread"], w), 3),
        "time_weighted_mean_imbalance": _r(_weighted_mean(a["imbalance"], w), 3),
        "volume_added": _r(s.volume_added, 2),
        "volume_removed": _r(s.volume_removed, 2),
    }


# --------------------------------------------------------------------------- public statistics

@traceable(run_type="tool", name="stats.profile")
def profile(md: MarketData) -> dict:
    return {
        "file": md.name,
        "size_mb": _r(md.size_bytes / 1e6, 2),
        "lines": md.lines,
        "parse_errors": md.parse_errors,
        "event_counts": md.event_counts,
        "start_utc": iso(md.first_ts),
        "end_utc": iso(md.last_ts),
        "duration_minutes": _r(md.duration_s / 60, 1),
        "tickers": [_ticker_headline(md, t) for t in md.tickers],
        "units": "prices in cents of the YES contract (0-100); imbalance = (bid_qty - ask_qty)/(bid_qty + ask_qty) at top of book",
    }


@traceable(run_type="tool", name="stats.spread")
def spread_statistics(md: MarketData, ticker: str | None = None) -> dict:
    results = []
    for t in resolve_tickers(md, ticker):
        a = md.tickers[t].arrays()
        if len(a["ts"]) == 0:
            results.append({"ticker": t, "note": "no two-sided top of book observed"})
            continue
        sp = a["spread"]
        w = _durations(a["ts"], md.last_ts or a["ts"][-1])
        total = w.sum() or 1.0
        buckets = {"<=1c": sp <= 1.0001, "1-2c": (sp > 1.0001) & (sp <= 2.0001),
                   "2-5c": (sp > 2.0001) & (sp <= 5.0001), ">5c": sp > 5.0001}
        results.append({
            "ticker": t,
            "observations": int(len(sp)),
            "time_weighted_mean_cents": _r(_weighted_mean(sp, w), 3),
            "median_cents": _r(np.median(sp), 3),
            "p10_cents": _r(np.percentile(sp, 10), 3),
            "p90_cents": _r(np.percentile(sp, 90), 3),
            "max_cents": _r(sp.max(), 3),
            "pct_time_locked_or_crossed": _r(100 * w[sp <= 0].sum() / total, 2),
            "pct_time_by_spread_bucket": {k: _r(100 * w[m].sum() / total, 2) for k, m in buckets.items()},
        })
    return {"file": md.name, "spread_statistics": results}


@traceable(run_type="tool", name="stats.imbalance")
def imbalance_analysis(md: MarketData, ticker: str | None = None, horizon_s: int = 10) -> dict:
    """Does top-of-book imbalance at time t relate to the midpoint change over (t, t+h]?

    Sampled on a regular clock so each point uses only information available at t.
    Includes a chronological first-70% / last-30% split to show whether the relation is stable.
    """
    horizon_s = int(min(max(horizon_s, 1), 3600))
    step = grid_step_ms(md)
    h = max(1, int(round(horizon_s * 1000 / step)))
    results = []
    for t in resolve_tickers(md, ticker):
        a = md.tickers[t].arrays()
        if len(a["ts"]) < 3:
            results.append({"ticker": t, "note": "not enough top-of-book observations"})
            continue
        g = as_of_grid(a, a["ts"][0], md.last_ts or a["ts"][-1], step)
        if len(g["ts"]) <= h + 10:
            results.append({"ticker": t, "note": "recording too short for this horizon"})
            continue
        imb = g["imbalance"][:-h]
        fut = g["mid"][h:] - g["mid"][:-h]
        n = len(imb)

        def corr(x, y):
            if len(x) < 3 or np.std(x) == 0 or np.std(y) == 0:
                return None
            return _r(np.corrcoef(x, y)[0, 1], 4)

        split = int(n * 0.7)
        edges = np.unique(np.quantile(imb, [0, 0.2, 0.4, 0.6, 0.8, 1.0]))
        buckets = []
        for lo, hi in zip(edges[:-1], edges[1:]):
            m = (imb >= lo) & ((imb <= hi) if hi == edges[-1] else (imb < hi))
            if m.sum() == 0:
                continue
            f = fut[m]
            buckets.append({
                "imbalance_range": [_r(lo, 3), _r(hi, 3)],
                "samples": int(m.sum()),
                "mean_future_mid_change_cents": _r(f.mean(), 4),
                "pct_up": _r(100 * (f > 0).mean(), 1),
                "pct_down": _r(100 * (f < 0).mean(), 1),
                "pct_flat": _r(100 * (f == 0).mean(), 1),
            })
        results.append({
            "ticker": t,
            "samples": int(n),
            "sample_step_seconds": step / 1000,
            "horizon_seconds": h * step / 1000,
            "pct_samples_with_mid_change": _r(100 * (fut != 0).mean(), 2),
            "correlation_full": corr(imb, fut),
            "correlation_first_70pct": corr(imb[:split], fut[:split]),
            "correlation_last_30pct": corr(imb[split:], fut[split:]),
            "by_imbalance_quintile": buckets,
        })
    return {
        "file": md.name,
        "imbalance_analysis": results,
        "caveats": [
            "Overlapping horizons make samples autocorrelated; effective sample size is much smaller than 'samples'.",
            "Mid changes are not tradeable P&L: crossing the spread, fees, queue position and latency are ignored.",
            "A correlation in one recording is a hypothesis, not evidence of a durable edge.",
        ],
    }


def window_stats(md: MarketData, ticker: str, window_s: int) -> list[dict]:
    """Fixed, non-overlapping clock windows with summary statistics (used by sampling and RAG)."""
    a = md.tickers[ticker].arrays()
    if len(a["ts"]) == 0:
        return []
    end = md.last_ts or a["ts"][-1]
    win_ms = max(1, int(window_s)) * 1000
    step = min(grid_step_ms(md), win_ms)
    g = as_of_grid(a, a["ts"][0], end, step)
    out = []
    start = a["ts"][0]
    while start < end:
        stop = start + win_ms
        m = (g["ts"] >= start) & (g["ts"] < stop)
        if m.sum() >= 2:
            mid = g["mid"][m]
            n_updates = int(((a["ts"] >= start) & (a["ts"] < stop)).sum())
            out.append({
                "ticker": ticker,
                "start_ms": float(start),
                "start_utc": iso(start),
                "end_utc": iso(min(stop, end)),
                "mid_open_cents": _r(mid[0], 2),
                "mid_close_cents": _r(mid[-1], 2),
                "mid_high_cents": _r(mid.max(), 2),
                "mid_low_cents": _r(mid.min(), 2),
                "mid_change_cents": _r(mid[-1] - mid[0], 2),
                "mean_spread_cents": _r(g["spread"][m].mean(), 3),
                "mean_imbalance": _r(g["imbalance"][m].mean(), 3),
                "top_of_book_updates": n_updates,
            })
        start = stop
    return out


@traceable(run_type="tool", name="stats.sample_windows")
def sample_windows(md: MarketData, ticker: str | None = None, count: int = 5,
                   criteria: str = "largest_move", window_s: int = 60) -> dict:
    count = int(min(max(count, 1), 20))
    window_s = int(min(max(window_s, 5), 3600))
    tickers = resolve_tickers(md, ticker)
    windows = [w for t in tickers for w in window_stats(md, t, window_s)]
    if not windows:
        return {"file": md.name, "windows": [], "note": "no windows available"}
    keys = {
        "largest_move": lambda w: abs(w["mid_change_cents"] or 0),
        "widest_spread": lambda w: w["mean_spread_cents"] or 0,
        "most_active": lambda w: w["top_of_book_updates"],
        "strongest_imbalance": lambda w: abs(w["mean_imbalance"] or 0),
    }
    if criteria in keys:
        chosen = sorted(windows, key=keys[criteria], reverse=True)[:count]
    elif criteria == "random":
        rng = np.random.default_rng(0)  # fixed seed so repeated calls are reproducible
        chosen = [windows[i] for i in sorted(rng.choice(len(windows), size=min(count, len(windows)), replace=False))]
    else:  # evenly_spaced
        idx = np.linspace(0, len(windows) - 1, num=min(count, len(windows))).astype(int)
        chosen = [windows[i] for i in idx]
    for w in chosen:
        w.pop("start_ms", None)
    return {"file": md.name, "criteria": criteria, "window_seconds": window_s,
            "total_windows": len(windows), "windows": chosen}


@traceable(run_type="tool", name="stats.compare")
def compare(mds: list[MarketData]) -> dict:
    rows = []
    for md in mds:
        for t in md.tickers:
            row = _ticker_headline(md, t)
            row["file"] = md.name
            row["duration_minutes"] = _r(md.duration_s / 60, 1)
            rows.append(row)
    return {"comparison": rows}
