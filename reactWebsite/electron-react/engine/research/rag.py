"""Lightweight retrieval over the selected market-data files.

Each selected JSONL file is reduced (by market_data.py) to a set of short text Documents:

  * one file-overview document
  * one summary document per ticker
  * one document per fixed clock window per ticker (mid open/close/high/low, spread,
    imbalance, activity) with plain-language tags such as "large move", "wide spread",
    "bid heavy" so keyword queries can find them

Those documents go into a LangChain BM25Retriever. BM25 is lexical, so there is no embedding
model, no external call and no vector database; it works the same with the cloud and the
local provider. Raw JSONL lines are never indexed or returned.

Numeric questions should be answered by the deterministic tools in tools.py; retrieval is for
locating *where* in the data something interesting happened.
"""

from __future__ import annotations

import re
import threading

import numpy as np
from langchain_community.retrievers import BM25Retriever
from langchain_core.documents import Document

from . import market_data as mdmod

MAX_WINDOWS_PER_TICKER = 240


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def _choose_window_seconds(md: mdmod.MarketData) -> int:
    """~5 minute windows, coarser for long recordings so a ticker yields <= 240 windows."""
    span = max(md.duration_s, 1)
    return int(max(300, np.ceil(span / MAX_WINDOWS_PER_TICKER / 60) * 60))


def _window_tags(w: dict, move_hi: float, spread_hi: float | None, active_hi: float) -> list[str]:
    tags = []
    change = w["mid_change_cents"] or 0
    if abs(change) >= move_hi and abs(change) > 0:
        tags.append("large move big price change volatile")
    tags.append("price rising up" if change > 0 else "price falling down" if change < 0 else "price flat unchanged")
    if spread_hi is not None and (w["mean_spread_cents"] or 0) >= spread_hi:
        tags.append("wide spread illiquid")
    if w["top_of_book_updates"] >= active_hi:
        tags.append("most active busy high activity")
    imb = w["mean_imbalance"] or 0
    if imb > 0.3:
        tags.append("bid heavy buy pressure positive imbalance")
    elif imb < -0.3:
        tags.append("ask heavy sell pressure negative imbalance")
    return tags


def build_documents(md: mdmod.MarketData) -> list[Document]:
    prof = mdmod.profile(md)
    docs = [Document(
        page_content=(
            f"File overview {md.name}: {md.lines} lines, {prof['size_mb']} MB, "
            f"from {prof['start_utc']} to {prof['end_utc']} ({prof['duration_minutes']} minutes). "
            f"Tickers: {', '.join(md.tickers) or 'none'}. Event counts: {md.event_counts}."
        ),
        metadata={"file": md.name, "kind": "file_overview"},
    )]
    for head in prof["tickers"]:
        docs.append(Document(
            page_content=f"Ticker summary {head['ticker']} in {md.name}: "
                         + ", ".join(f"{k}={v}" for k, v in head.items() if k != "ticker"),
            metadata={"file": md.name, "ticker": head["ticker"], "kind": "ticker_summary"},
        ))

    window_s = _choose_window_seconds(md)
    for ticker in md.tickers:
        windows = mdmod.window_stats(md, ticker, window_s)
        if not windows:
            continue
        moves = np.array([abs(w["mid_change_cents"] or 0) for w in windows])
        spreads = np.array([w["mean_spread_cents"] or 0 for w in windows])
        active = np.array([w["top_of_book_updates"] for w in windows])
        move_hi, active_hi = np.percentile(moves, 90), np.percentile(active, 90)
        spread_hi = np.percentile(spreads, 90)
        if spread_hi <= np.median(spreads):  # constant spread: no window is "wide"
            spread_hi = None
        for w in windows:
            tags = _window_tags(w, move_hi, spread_hi, active_hi)
            text = (
                f"Window {w['start_utc']} to {w['end_utc']} | {ticker} | {md.name} | "
                f"mid {w['mid_open_cents']}c -> {w['mid_close_cents']}c (change {w['mid_change_cents']}c, "
                f"high {w['mid_high_cents']}c, low {w['mid_low_cents']}c) | mean spread {w['mean_spread_cents']}c | "
                f"mean imbalance {w['mean_imbalance']} | {w['top_of_book_updates']} top-of-book updates | "
                f"tags: {'; '.join(tags)}"
            )
            docs.append(Document(page_content=text, metadata={
                "file": md.name, "ticker": ticker, "kind": "window", "start_utc": w["start_utc"],
                "window_seconds": window_s,
            }))
    return docs


class SessionIndex:
    """BM25 index for one set of selected files, built lazily and cached per session."""

    def __init__(self, paths: list[str]) -> None:
        self.paths = list(paths)
        self._retriever: BM25Retriever | None = None
        self._doc_count = 0
        self._lock = threading.Lock()

    def _build(self) -> BM25Retriever | None:
        docs: list[Document] = []
        for path in self.paths:
            docs.extend(build_documents(mdmod.load_market_data(path)))
        self._doc_count = len(docs)
        if not docs:
            return None
        return BM25Retriever.from_documents(docs, preprocess_func=_tokenize, k=40)

    def retrieve(self, query: str, k: int = 6, file: str | None = None, ticker: str | None = None) -> list[Document]:
        with self._lock:
            if self._retriever is None:
                self._retriever = self._build()
        if self._retriever is None:
            return []
        # BM25Retriever.invoke is a LangChain retriever run, so it shows up in LangSmith traces.
        docs = self._retriever.invoke(query)
        if file:
            docs = [d for d in docs if d.metadata.get("file") == file]
        if ticker:
            docs = [d for d in docs if ticker.lower() in (d.metadata.get("ticker") or "").lower()]
        return docs[: max(1, min(k, 12))]

    @property
    def doc_count(self) -> int:
        return self._doc_count
