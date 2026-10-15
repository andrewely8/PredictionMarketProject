"""Starter strategy: connects, keeps live order books, prints the market every minute. No orders.

This file is written exactly like a bot for the real Kalshi exchange:
  * market data comes from the `orderbook_delta` websocket channel,
  * fills come from the `fill` channel,
  * orders go to POST /portfolio/events/orders (side "bid" = buy YES, "ask" = sell YES).

When the app runs it (Workspace -> test, then Run strategy in the Replayer) it points the file at the
simulator through environment variables, so it trades against a recording on the Replayer's clock.
To run the same file live: set KALSHI_ENV=demo (try demo first!) or production, plus KALSHI_KEY_ID and
KALSHI_PRIVATE_KEY_PATH, and list your markets in KALSHI_TICKERS.

Edit the Strategy class at the bottom; the plumbing above it rarely needs changes.
"""

import asyncio
import base64
import json
import os
import time
import uuid
from urllib.parse import urlparse

import requests
import websockets

# --------------------------------------------------------------------------- connection
ENV = os.environ.get("KALSHI_ENV", "sim")
_LIVE = {
    "demo": ("https://external-api.demo.kalshi.co/trade-api/v2", "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2"),
    "production": ("https://external-api.kalshi.com/trade-api/v2", "wss://external-api-ws.kalshi.com/trade-api/ws/v2"),
}
_SIM = ("http://127.0.0.1:8000/trade-api/v2", "ws://127.0.0.1:8000/trade-api/ws/v2")
API_BASE = os.environ.get("KALSHI_API_BASE") or _LIVE.get(ENV, _SIM)[0]
WS_URL = os.environ.get("KALSHI_WS_URL") or _LIVE.get(ENV, _SIM)[1]
TICKERS = [t for t in os.environ.get("KALSHI_TICKERS", "").split(",") if t]
_private_key = None


def signed_headers(method, url):
    """Kalshi API-key signature. The simulator accepts unsigned requests, so nothing is needed there."""
    global _private_key
    if ENV == "sim":
        return {}
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    if _private_key is None:
        with open(os.environ["KALSHI_PRIVATE_KEY_PATH"], "rb") as fh:
            _private_key = serialization.load_pem_private_key(fh.read(), password=None)
    ts = str(int(time.time() * 1000))
    sig = _private_key.sign(f"{ts}{method}{urlparse(url).path}".encode(),
                            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
                            hashes.SHA256())
    return {"KALSHI-ACCESS-KEY": os.environ["KALSHI_KEY_ID"], "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
            "KALSHI-ACCESS-TIMESTAMP": ts}


class Book:
    """One market's order book in cents. Kalshi books hold bids only: YES ask = 100 - best NO bid."""

    def __init__(self):
        self.yes, self.no = {}, {}

    def snapshot(self, msg):
        self.yes = {round(float(p) * 100, 2): float(q) for p, q in msg.get("yes_dollars_fp") or []}
        self.no = {round(float(p) * 100, 2): float(q) for p, q in msg.get("no_dollars_fp") or []}

    def delta(self, msg):
        levels = self.yes if msg["side"] == "yes" else self.no
        price = round(float(msg["price_dollars"]) * 100, 2)
        qty = levels.get(price, 0.0) + float(msg["delta_fp"])
        if qty > 1e-9:
            levels[price] = qty
        else:
            levels.pop(price, None)

    def best_bid(self):
        return max(self.yes) if self.yes else None

    def best_ask(self):
        return round(100 - max(self.no), 2) if self.no else None

    def bid_size(self):
        return self.yes[max(self.yes)] if self.yes else 0.0

    def ask_size(self):
        return self.no[max(self.no)] if self.no else 0.0


def place_order(ticker, side, price_cents, count, time_in_force="immediate_or_cancel"):
    """side 'bid' buys YES, 'ask' sells YES (= buys NO). Returns Kalshi's response, or None if rejected."""
    url = API_BASE + "/portfolio/events/orders"
    body = {"ticker": ticker, "side": side, "count": f"{count:.2f}", "price": f"{price_cents / 100:.4f}",
            "time_in_force": time_in_force, "self_trade_prevention_type": "taker_at_cross",
            "client_order_id": str(uuid.uuid4())}
    r = requests.post(url, json=body, headers=signed_headers("POST", url), timeout=10)
    if r.status_code != 201:
        print(f"order rejected {r.status_code}: {r.text[:200]}")
        return None
    return r.json()


def list_markets():
    url = API_BASE + "/markets"
    r = requests.get(url, params={"status": "open"}, headers=signed_headers("GET", url), timeout=10)
    r.raise_for_status()
    return [m["ticker"] for m in r.json()["markets"]]


async def run(strategy):
    tickers = TICKERS or list_markets()
    books = {t: Book() for t in tickers}
    print(f"strategy started ({ENV}): {len(tickers)} markets: {', '.join(tickers)}")
    async with websockets.connect(WS_URL, additional_headers=signed_headers("GET", WS_URL), max_size=None) as ws:
        await ws.send(json.dumps({"id": 1, "cmd": "subscribe",
                                  "params": {"channels": ["orderbook_delta"], "market_tickers": tickers}}))
        await ws.send(json.dumps({"id": 2, "cmd": "subscribe", "params": {"channels": ["fill"]}}))
        if ENV == "sim":
            # Simulator-only channel: lets "Max" speed backtests run in lockstep with this strategy.
            await ws.send(json.dumps({"id": 3, "cmd": "subscribe", "params": {"channels": ["sim_clock"]}}))
        async for raw in ws:
            msg = json.loads(raw)
            kind, body = msg.get("type"), msg.get("msg") or {}
            if kind == "orderbook_snapshot":
                books[body["market_ticker"]].snapshot(body)
            elif kind == "orderbook_delta":
                ticker = body["market_ticker"]
                books[ticker].delta(body)
                strategy.on_book(ticker, books[ticker], body["ts_ms"], books)
            elif kind == "fill":
                strategy.on_fill(body)
            elif kind == "sim_clock":
                strategy.on_clock(body["ts_ms"], books)
                await ws.send(json.dumps({"id": 0, "cmd": "sim_ack", "params": {"tick": body["tick"]}}))
            elif kind == "error":
                print("exchange error:", body)


# --------------------------------------------------------------------------- your strategy

class Strategy:
    def __init__(self):
        self.last_print = 0

    def on_book(self, ticker, book, ts_ms, books):
        """Called on every order-book change. Place orders with place_order(...)."""
        if ts_ms - self.last_print >= 60_000:
            self.last_print = ts_ms
            clock = time.strftime("%H:%M:%S", time.gmtime(ts_ms / 1000))
            for t, b in books.items():
                print(f"{clock} {t}: YES bid {b.best_bid()} / ask {b.best_ask()}")

    def on_fill(self, fill):
        print(f"fill: {fill['action']} {fill['count_fp']} {fill['market_ticker']} @ {fill['yes_price_dollars']}")

    def on_clock(self, ts_ms, books):
        """Simulator time tick (only in the simulator). Good place for time-based decisions."""


if __name__ == "__main__":
    asyncio.run(run(Strategy()))
