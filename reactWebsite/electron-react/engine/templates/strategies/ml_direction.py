"""ML direction: an online logistic regression on order-book features predicts the next move.

Every second (exchange time) it records features for each market and, HORIZON seconds later, the label
"did the midpoint go up?". It trains only on labels that are already known (no look-ahead), refits
periodically, and trades only after WARMUP samples, when the predicted probability is confident.
The first part of each recording is therefore training data, the rest is out-of-sample trading.

Written like a live Kalshi bot (orderbook_delta + fill websocket channels, orders via
POST /portfolio/events/orders). The app runs it against the simulator; to go live set KALSHI_ENV=demo
or production, KALSHI_KEY_ID, KALSHI_PRIVATE_KEY_PATH and KALSHI_TICKERS (test on demo first).
This is a research hypothesis, not a proven edge: judge it on held-out recordings, after fees.
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

import numpy as np

HORIZON = 10             # seconds ahead to predict
WARMUP = 1500            # labeled, non-flat samples before trading
REFIT_EVERY = 300        # samples between refits
MARGIN = 0.12            # trade only if |p - 0.5| > MARGIN
ORDER_SIZE = 1
L2 = 0.1


def features(book, history):
    bid, ask = book.best_bid(), book.best_ask()
    mid = (bid + ask) / 2
    depth = book.bid_size() + book.ask_size()
    imb = (book.bid_size() - book.ask_size()) / depth if depth else 0.0
    past = [h for h in history if h is not None]
    mom5 = mid - past[-5] if len(past) >= 5 else 0.0
    mom30 = mid - past[-30] if len(past) >= 30 else 0.0
    return mid, [imb, ask - bid, mom5, mom30, np.log1p(book.bid_size()), np.log1p(book.ask_size())]


def fit_logreg(X, y, iters=400, lr=0.3):
    mu, sd = X.mean(0), X.std(0) + 1e-9
    Z = (X - mu) / sd
    w, b = np.zeros(X.shape[1]), 0.0
    for _ in range(iters):
        p = 1 / (1 + np.exp(-(Z @ w + b)))
        g = p - y
        w -= lr * (Z.T @ g / len(y) + L2 * w)
        b -= lr * g.mean()
    return mu, sd, w, b


class Strategy:
    def __init__(self):
        self.next_sample = {}     # ticker -> ts_ms of next 1-second sample
        self.mids = {}            # ticker -> recent mids (1 per second)
        self.pending = []         # (label_due_ts, ticker, mid_then, features)
        self.X, self.y = [], []
        self.model = None
        self.position = {}
        self.exit_at = {}

    def on_book(self, ticker, book, ts_ms, books):
        if book.best_bid() is None or book.best_ask() is None:
            return
        if ts_ms < self.next_sample.get(ticker, 0):
            return
        self.next_sample[ticker] = ts_ms + 1000
        mids = self.mids.setdefault(ticker, [])
        mid, x = features(book, mids)
        mids.append(mid)
        del mids[:-60]
        self._label(ticker, ts_ms, mid)
        self.pending.append((ts_ms + HORIZON * 1000, ticker, mid, x))
        self._maybe_exit(ticker, book, ts_ms)
        if self.model and self.position.get(ticker, 0) == 0:
            mu, sd, w, b = self.model
            p = 1 / (1 + np.exp(-(((np.array(x) - mu) / sd) @ w + b)))
            if p > 0.5 + MARGIN and self._trade(ticker, "bid", book.best_ask(), ORDER_SIZE):
                self.exit_at[ticker] = ts_ms + HORIZON * 1000
            elif p < 0.5 - MARGIN and self._trade(ticker, "ask", book.best_bid(), ORDER_SIZE):
                self.exit_at[ticker] = ts_ms + HORIZON * 1000

    def _label(self, ticker, ts_ms, mid_now):
        """Labels become known HORIZON seconds after the features were taken - only then are they used."""
        keep = []
        for due, t, mid_then, x in self.pending:
            if t == ticker and due <= ts_ms:
                if mid_now != mid_then:
                    self.X.append(x)
                    self.y.append(1.0 if mid_now > mid_then else 0.0)
                    if len(self.y) >= WARMUP and len(self.y) % REFIT_EVERY == 0:
                        self.model = fit_logreg(np.array(self.X), np.array(self.y))
                        print(f"refit on {len(self.y)} samples, up-rate {np.mean(self.y):.2f}")
            else:
                keep.append((due, t, mid_then, x))
        self.pending = keep

    def _trade(self, ticker, side, price, count):
        """IOC order; the position is updated from the response immediately. Returns contracts filled."""
        resp = place_order(ticker, side, price, count)
        filled = float(resp["fill_count"]) if resp else 0.0
        self.position[ticker] = self.position.get(ticker, 0) + (filled if side == "bid" else -filled)
        return filled

    def _maybe_exit(self, ticker, book, ts_ms):
        pos = self.position.get(ticker, 0)
        if abs(pos) >= 0.01 and ts_ms >= self.exit_at.get(ticker, 0):
            if pos > 0:
                self._trade(ticker, "ask", book.best_bid(), abs(pos))
            else:
                self._trade(ticker, "bid", book.best_ask(), abs(pos))

    def on_fill(self, fill):
        # post_position_fp is the exchange's absolute position after the fill: always trust it.
        self.position[fill["market_ticker"]] = float(fill["post_position_fp"])

    def on_clock(self, ts_ms, books):
        pass


if __name__ == "__main__":
    asyncio.run(run(Strategy()))
