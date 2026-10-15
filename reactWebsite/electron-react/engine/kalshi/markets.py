"""Public (unauthenticated) Kalshi market lookups used by the Market Tracker's search box."""

from __future__ import annotations

import httpx

from .auth import ENVIRONMENTS


def _client() -> httpx.Client:
    return httpx.Client(timeout=15, headers={"User-Agent": "kalshi-backtester"})


def _summary(m: dict) -> dict:
    return {
        "ticker": m.get("ticker"),
        "event_ticker": m.get("event_ticker"),
        "title": m.get("title") or m.get("subtitle") or "",
        "subtitle": m.get("yes_sub_title") or m.get("subtitle") or "",
        "status": m.get("status"),
        "close_time": m.get("close_time"),
        "yes_bid_dollars": m.get("yes_bid_dollars"),
        "yes_ask_dollars": m.get("yes_ask_dollars"),
        "volume": m.get("volume_fp", m.get("volume")),
    }


def search_markets(query: str, env: str = "production", limit: int = 200) -> dict:
    """Resolve a market, event or series ticker into a list of markets.

    Tries, in order: exact market ticker, event ticker (all markets in the event), series ticker
    (open markets in the series).
    """
    q = query.strip().upper()
    if not q:
        return {"query": query, "kind": None, "markets": []}
    base = ENVIRONMENTS[env]["rest"]
    with _client() as c:
        r = c.get(f"{base}/markets/{q}")
        if r.status_code == 200 and r.json().get("market"):
            return {"query": q, "kind": "market", "markets": [_summary(r.json()["market"])]}
        r = c.get(f"{base}/markets", params={"event_ticker": q, "limit": limit})
        if r.status_code == 200 and r.json().get("markets"):
            return {"query": q, "kind": "event", "markets": [_summary(m) for m in r.json()["markets"]]}
        r = c.get(f"{base}/markets", params={"series_ticker": q, "status": "open", "limit": limit})
        if r.status_code == 200 and r.json().get("markets"):
            return {"query": q, "kind": "series", "markets": [_summary(m) for m in r.json()["markets"]]}
        r.raise_for_status()
    return {"query": q, "kind": None, "markets": []}


def market_status(tickers: list[str], env: str = "production") -> dict[str, str | None]:
    """ticker -> status ('active', 'closed', ... or None if not found)."""
    base = ENVIRONMENTS[env]["rest"]
    out: dict[str, str | None] = {}
    with _client() as c:
        for t in tickers:
            r = c.get(f"{base}/markets/{t}")
            out[t] = r.json().get("market", {}).get("status") if r.status_code == 200 else None
    return out
