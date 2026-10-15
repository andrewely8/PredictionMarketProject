"""Cross-market arbitrage: moneyline YES + spread NO, bought together for less than $1.

For a game market "<EVENT>-TEAM" (TEAM wins) and a spread market "<EVENT>-TEAM<N>" (TEAM wins by more
than N - 0.5 runs), owning YES on the moneyline and NO on the spread pays at least $1 in every outcome:
  * TEAM loses           -> spread NO pays $1
  * TEAM wins by < N     -> moneyline YES and spread NO both pay ($2)
  * TEAM wins by >= N    -> moneyline YES pays $1
So if YES ask(moneyline) + NO ask(spread) + fees < $1, buying both locks in a profit at settlement.
(This is the idea from the original backtest.py, generalized to every team / spread pair in the data.)

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

import math
import re

MIN_EDGE_CENTS = 1.0     # required profit per pair after fees
ORDER_SIZE = 1           # pairs per trade
MAX_PAIRS = 20           # total pairs per market pair
TAKER_FEE_RATE = 0.07


def fee_cents(price_cents, count=1):
    p = price_cents / 100
    return math.ceil(TAKER_FEE_RATE * count * p * (1 - p) * 100)


def find_pairs(tickers):
    """(moneyline, spread) pairs, e.g. KXMLBGAME-26SEP012138NYYLAA-NYY with KXMLBSPREAD-26SEP012138NYYLAA-NYY2."""
    pairs = []
    games = [t for t in tickers if t.split("-")[0].endswith("GAME")]
    for game in games:
        event, team = game.split("-")[1], game.split("-")[-1]
        for t in tickers:
            parts = t.split("-")
            if parts[0].endswith("SPREAD") and len(parts) >= 3 and parts[1] == event \
                    and re.fullmatch(re.escape(team) + r"\d+", parts[-1]):
                pairs.append((game, t))
    return pairs


class Strategy:
    def __init__(self):
        self.pairs = None
        self.bought = {}      # pair -> pairs bought

    def on_book(self, ticker, book, ts_ms, books):
        if self.pairs is None:
            self.pairs = find_pairs(list(books))
            print(f"watching {len(self.pairs)} moneyline/spread pairs: {self.pairs}")
        for game, spread in self.pairs:
            if ticker not in (game, spread) or self.bought.get((game, spread), 0) >= MAX_PAIRS:
                continue
            yes_ask = books[game].best_ask()                  # buy YES on the moneyline
            spread_bid = books[spread].best_bid()              # NO ask on the spread = 100 - YES bid
            if yes_ask is None or spread_bid is None:
                continue
            no_ask = 100 - spread_bid
            cost = yes_ask + no_ask + fee_cents(yes_ask) + fee_cents(no_ask)
            if 100 - cost >= MIN_EDGE_CENTS:
                print(f"arb: {game} YES {yes_ask}c + {spread} NO {no_ask}c = {cost}c incl. fees")
                first = place_order(game, "bid", yes_ask, ORDER_SIZE, "fill_or_kill")
                if first and float(first["fill_count"]) >= ORDER_SIZE:
                    second = place_order(spread, "ask", spread_bid, ORDER_SIZE, "fill_or_kill")  # sell YES = buy NO
                    if not second:
                        print(f"warning: second leg {spread} did not fill - holding an unhedged {game} YES position")
                    self.bought[(game, spread)] = self.bought.get((game, spread), 0) + ORDER_SIZE

    def on_fill(self, fill):
        print(f"fill: {fill['action']} {fill['count_fp']} {fill['market_ticker']} @ {fill['yes_price_dollars']}")

    def on_clock(self, ts_ms, books):
        pass


if __name__ == "__main__":
    asyncio.run(run(Strategy()))
