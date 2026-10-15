"""A simulation session: one recording, one replay clock, one simulated exchange account.

The Replayer panel drives the "replayer" session; headless backtests (AI tests, "Run to end")
get their own sessions so they never disturb what is on screen.

Clock modes
-----------
* speed = 1, 2, 5, ... : replay time advances at `speed` x real time. Strategies run live against it,
  so their processing and network latency matter, as on the real exchange.
* speed = None ("Max") : replay as fast as possible. Strategies that subscribe to the simulator-only
  `sim_clock` channel are run in lockstep: after every LOCKSTEP_STEP_MS of replay time the simulator
  sends `sim_clock` and waits for `{"cmd": "sim_ack"}` before moving on, so results are deterministic
  and independent of machine speed. Orders sent before the ack are matched at that instant.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from starlette.concurrency import run_in_threadpool

from .. import settings
from ..marketdata.book import OrderBook, fmt_count, to_dollars
from ..marketdata.recording import KIND_SNAPSHOT, Recording, load_recording
from .exchange import Exchange, Fill

TICK_REAL_S = 0.025          # timed modes: clock update interval
LOCKSTEP_STEP_MS = 250       # Max mode: replay-time step between sim_clock ticks
MAX_CHUNK_EVENTS = 5_000     # Max mode without lockstep: events per batch
ACK_TIMEOUT_S = 10.0
CONSOLE_LINES = 400


def iso_ms(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass
class Client:
    """One websocket connection to the simulated Kalshi feed."""
    send: Any                                   # async callable(dict)
    subs: dict[int, dict] = field(default_factory=dict)   # sid -> {"channel", "tickers", "seq"}
    lockstep: bool = False
    acked_tick: int = -1
    ack_event: asyncio.Event = field(default_factory=asyncio.Event)
    next_sid: int = 1
    outbox: list = field(default_factory=list)

    def next_seq(self, sid: int) -> int:
        self.subs[sid]["seq"] += 1
        return self.subs[sid]["seq"]


class SimSession:
    def __init__(self, session_id: str) -> None:
        self.id = session_id
        self.recording: Recording | None = None
        self.books: dict[str, OrderBook] = {}
        self.exchange: Exchange | None = None
        self.index = 0                 # next event to apply
        self.clock_ts = 0              # current replay time (ms since epoch)
        self.state = "empty"           # empty | loading | ready | playing | paused | ended | error
        self.speed: float | None = 1.0
        self.load_progress = 0.0
        self.error: str | None = None
        self.clients: list[Client] = []
        self.console: list[str] = []
        self.equity_curve: list[tuple[int, float]] = []
        self._task: asyncio.Task | None = None
        self._tick = 0
        self._ended = asyncio.Event()
        self._subscribed = asyncio.Event()
        self._warned_unsigned = False

    # ------------------------------------------------------------------ loading / reset

    async def load(self, path: str) -> None:
        await self.pause()
        self.state, self.load_progress, self.error = "loading", 0.0, None

        def progress(f: float) -> None:
            self.load_progress = f
        try:
            self.recording = await run_in_threadpool(load_recording, path, progress)
        except Exception as exc:  # noqa: BLE001
            self.state, self.error = "error", f"Could not load {path}: {exc}"
            raise
        self.reset()

    def reset(self) -> None:
        """Back to the start of the recording with a fresh simulated account."""
        if self.recording is None:
            return
        rec = self.recording
        idx_books = rec.books_before(0)
        self.books = {rec.tickers[i]: b for i, b in idx_books.items()}
        self.index = 0
        self.clock_ts = rec.start_ts
        s = settings.load()
        self.exchange = Exchange(self.books, starting_cash=float(s["sim_starting_balance"]),
                                 taker_rate=float(s["sim_taker_fee_rate"]), maker_rate=float(s["sim_maker_fee_rate"]))
        self.exchange.listeners.append(self._on_fill)
        self.equity_curve = [(self.clock_ts, self.exchange.equity())]
        self._tick = 0
        self._ended = asyncio.Event()
        self._subscribed = asyncio.Event()
        self.error = None
        self.state = "ready"
        # Apply the opening snapshots so the book is populated at t0.
        self._advance_to(self.clock_ts, broadcast=False)

    def seek(self, ts_ms: int) -> None:
        """Jump to a time. Only allowed without connected strategies (it rewrites history)."""
        if self.recording is None:
            return
        if self.clients:
            raise ValueError("Stop the running strategy before seeking")
        rec = self.recording
        ts_ms = max(rec.start_ts, min(int(ts_ms), rec.end_ts))
        i = rec.index_at(ts_ms)
        idx_books = rec.books_before(i)
        for t, b in idx_books.items():   # keep the same OrderBook objects (the exchange holds them)
            live = self.books[rec.tickers[t]]
            live.load(b.yes, b.no)
        for t in self.books:
            self.exchange.book_replaced(t)
        self.index, self.clock_ts = i, ts_ms
        self.state = "ended" if i >= len(rec) else ("paused" if self.state in ("playing", "paused", "ended") else "ready")

    # ------------------------------------------------------------------ clock

    async def play(self, speed: float | None) -> None:
        if self.recording is None:
            raise ValueError("Load a data file first")
        self.speed = speed
        if self.state == "ended":
            return
        if self._task and not self._task.done():
            return
        self.state = "playing"
        self._task = asyncio.get_running_loop().create_task(self._run())

    async def pause(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        if self.state == "playing":
            self.state = "paused"

    async def wait_ended(self) -> None:
        await self._ended.wait()

    async def wait_subscribed(self, timeout: float) -> bool:
        try:
            await asyncio.wait_for(self._subscribed.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def _run(self) -> None:
        rec = self.recording
        assert rec is not None
        try:
            last = time.monotonic()
            while self.index < len(rec):
                if self.speed is None:
                    if any(c.lockstep for c in self.clients):
                        # Step LOCKSTEP_STEP_MS at a time, but jump straight over quiet stretches
                        # (nothing can happen between events: resting orders only fill on book changes).
                        target = max(self.clock_ts + LOCKSTEP_STEP_MS, int(rec.ts[self.index]))
                    else:
                        j = min(self.index + MAX_CHUNK_EVENTS, len(rec)) - 1
                        target = int(rec.ts[j])
                    await self._step(target)
                    await asyncio.sleep(0)
                else:
                    await asyncio.sleep(TICK_REAL_S)
                    now = time.monotonic()
                    target = self.clock_ts + int((now - last) * 1000 * self.speed)
                    last = now
                    await self._step(target)
            self.clock_ts = rec.end_ts
            self.state = "ended"
            await self._flush_all()
            self._ended.set()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self.state, self.error = "error", f"{type(exc).__name__}: {exc}"
            self._ended.set()

    async def _step(self, target_ts: int) -> None:
        self._advance_to(target_ts, broadcast=True)
        fills = self.exchange.match_resting(self.clock_ts)
        if self.equity_curve and self.clock_ts - self.equity_curve[-1][0] >= 1000:
            self.equity_curve.append((self.clock_ts, self.exchange.equity()))
        await self._send_clock()
        await self._flush_all()
        if self.speed is None:
            await self._await_acks()
        del fills

    def _advance_to(self, target_ts: int, broadcast: bool) -> None:
        rec = self.recording
        stop = rec.index_at(target_ts)
        ex = self.exchange
        for i in range(self.index, stop):
            ticker = rec.tickers[int(rec.tick[i])]
            book = self.books[ticker]
            if rec.kind[i] == KIND_SNAPSHOT:
                snap = rec.snapshots[int(rec.ref[i])]
                book.load(snap.yes, snap.no)
                ex.book_replaced(ticker)
                if broadcast:
                    self._queue_book_message(ticker, None)
            else:
                side_no = bool(rec.side[i])
                price = int(rec.price[i])
                new_qty = book.apply(side_no, price, float(rec.delta[i]))
                ex.level_changed(ticker, side_no, price, new_qty)
                if broadcast:
                    self._queue_book_message(ticker, i)
        self.index = max(self.index, stop)
        self.clock_ts = max(self.clock_ts, min(target_ts, rec.end_ts))

    # ------------------------------------------------------------------ websocket feed

    def _queue_book_message(self, ticker: str, i: int | None) -> None:
        rec = self.recording
        for c in self.clients:
            for sid, sub in c.subs.items():
                if sub["channel"] != "orderbook_delta" or ticker not in sub["tickers"]:
                    continue
                if i is None:
                    c.outbox.append(self.snapshot_message(ticker, sid, c.next_seq(sid)))
                else:
                    ts = int(rec.ts[i])
                    c.outbox.append({"type": "orderbook_delta", "sid": sid, "seq": c.next_seq(sid), "msg": {
                        "market_ticker": ticker, "market_id": self.books[ticker].market_id,
                        "price_dollars": to_dollars(int(rec.price[i])), "delta_fp": fmt_count(float(rec.delta[i])),
                        "side": "no" if rec.side[i] else "yes", "ts": iso_ms(ts), "ts_ms": ts}})

    def snapshot_message(self, ticker: str, sid: int, seq: int) -> dict:
        book = self.books[ticker]
        levels = book.levels_fp()
        return {"type": "orderbook_snapshot", "sid": sid, "seq": seq, "msg": {
            "market_ticker": ticker, "market_id": book.market_id,
            "yes_dollars_fp": levels["yes_dollars"], "no_dollars_fp": levels["no_dollars"]}}

    def _on_fill(self, fill: Fill) -> None:
        for c in self.clients:
            for sid, sub in c.subs.items():
                if sub["channel"] == "fill":
                    c.outbox.append({"type": "fill", "sid": sid, "seq": c.next_seq(sid),
                                     "sending_ts_ms": self.clock_ts, "msg": fill.kalshi()})

    async def _send_clock(self) -> None:
        self._tick += 1
        for c in self.clients:
            for sid, sub in c.subs.items():
                if sub["channel"] == "sim_clock":
                    c.outbox.append({"type": "sim_clock", "sid": sid, "seq": c.next_seq(sid), "msg": {
                        "tick": self._tick, "ts_ms": self.clock_ts, "lockstep": self.speed is None and c.lockstep}})

    async def _flush_all(self) -> None:
        for c in list(self.clients):
            if c.outbox:
                batch, c.outbox = c.outbox, []
                try:
                    for msg in batch:
                        await c.send(msg)
                except Exception:  # noqa: BLE001 - client went away
                    self.disconnect(c)

    async def _await_acks(self) -> None:
        for c in [c for c in self.clients if c.lockstep]:
            while c.acked_tick < self._tick:
                c.ack_event.clear()
                try:
                    await asyncio.wait_for(c.ack_event.wait(), ACK_TIMEOUT_S)
                except asyncio.TimeoutError:
                    c.lockstep = False
                    self.log(f"[sim] strategy did not sim_ack tick {self._tick} within {ACK_TIMEOUT_S:.0f}s; "
                             "continuing without lockstep")
                    break

    def connect(self, send) -> Client:
        c = Client(send=send)
        self.clients.append(c)
        return c

    def disconnect(self, c: Client) -> None:
        if c in self.clients:
            self.clients.remove(c)
            c.ack_event.set()

    async def handle_command(self, c: Client, raw: str) -> None:
        """Kalshi websocket commands: subscribe / unsubscribe, plus the simulator's sim_ack."""
        try:
            cmd = json.loads(raw)
        except ValueError:
            await c.send({"type": "error", "msg": {"code": 1, "msg": "Unable to parse message"}})
            return
        cid = cmd.get("id")
        name = cmd.get("cmd")
        params = cmd.get("params") or {}
        if name == "sim_ack":
            c.acked_tick = max(c.acked_tick, int(params.get("tick", c.acked_tick)))
            c.ack_event.set()
            return
        if name == "unsubscribe":
            for sid in params.get("sids") or []:
                c.subs.pop(int(sid), None)
            await c.send({"id": cid, "type": "unsubscribed", "msg": {"sids": params.get("sids") or []}})
            return
        if name != "subscribe":
            await c.send({"id": cid, "type": "error", "msg": {"code": 5, "msg": f"Unknown command {name!r}"}})
            return
        channels = params.get("channels") or []
        tickers = list(params.get("market_tickers") or [])
        if params.get("market_ticker"):
            tickers.append(params["market_ticker"])
        if not channels:
            await c.send({"id": cid, "type": "error", "msg": {"code": 2, "msg": "Params required"}})
            return
        unknown = [t for t in tickers if t not in self.books]
        if unknown:
            await c.send({"id": cid, "type": "error", "msg": {
                "code": 6, "msg": f"Unknown market ticker(s) {unknown}; this recording has {list(self.books)}"}})
            return
        for channel in channels:
            if channel not in ("orderbook_delta", "fill", "sim_clock"):
                await c.send({"id": cid, "type": "error", "msg": {
                    "code": 7, "msg": f"Channel {channel!r} is not simulated (supported: orderbook_delta, fill, sim_clock)"}})
                continue
            if channel == "orderbook_delta" and not tickers:
                await c.send({"id": cid, "type": "error", "msg": {"code": 2, "msg": "Params required: market_ticker(s)"}})
                continue
            sid = c.next_sid
            c.next_sid += 1
            c.subs[sid] = {"channel": channel, "tickers": set(tickers), "seq": 0}
            await c.send({"id": cid, "type": "subscribed", "msg": {"channel": channel, "sid": sid}})
            if channel == "orderbook_delta":
                for t in tickers:
                    await c.send(self.snapshot_message(t, sid, c.next_seq(sid)))
            if channel == "sim_clock":
                c.lockstep = True
                c.acked_tick = self._tick
            self._subscribed.set()

    # ------------------------------------------------------------------ misc

    def log(self, line: str) -> None:
        self.console.append(line)
        if len(self.console) > CONSOLE_LINES:
            del self.console[: len(self.console) - CONSOLE_LINES]

    def note_unsigned(self) -> None:
        if not self._warned_unsigned:
            self._warned_unsigned = True
            self.log("[sim] requests are not signed with KALSHI-ACCESS-* headers - fine for the simulator, "
                     "required on the real exchange")

    def state_payload(self) -> dict:
        rec = self.recording
        out: dict[str, Any] = {"session": self.id, "state": self.state, "speed": self.speed, "error": self.error,
                               "load_progress": round(self.load_progress, 3)}
        if rec is None:
            return out
        span = max(rec.end_ts - rec.start_ts, 1)
        out.update({
            "file": rec.name, "path": rec.path, "start_ts": rec.start_ts, "end_ts": rec.end_ts, "clock_ts": self.clock_ts,
            "progress": round((self.clock_ts - rec.start_ts) / span, 5), "events": len(rec), "index": self.index,
            "books": {t: b.top() for t, b in self.books.items()},
            "connected_strategies": len(self.clients),
        })
        if self.exchange:
            out["account"] = self.exchange.summary()
            out["recent_fills"] = [f.kalshi() for f in self.exchange.fills[-25:]][::-1]
            out["open_orders"] = [o.kalshi() for o in self.exchange.orders.values() if o.status == "resting"][:50]
            curve = self.equity_curve + [(self.clock_ts, self.exchange.equity())]
            step = max(1, len(curve) // 200)
            out["equity_curve"] = [[t, round(v, 4)] for t, v in curve[::step]] + [[curve[-1][0], round(curve[-1][1], 4)]]
        out["console"] = self.console[-150:]
        return out


class SessionManager:
    REPLAYER = "replayer"

    def __init__(self) -> None:
        self.sessions: dict[str, SimSession] = {self.REPLAYER: SimSession(self.REPLAYER)}

    def get(self, session_id: str) -> SimSession:
        return self.sessions[session_id]

    def create(self, session_id: str) -> SimSession:
        s = SimSession(session_id)
        self.sessions[session_id] = s
        return s

    async def close(self, session_id: str) -> None:
        s = self.sessions.pop(session_id, None)
        if s:
            await s.pause()

    async def shutdown(self) -> None:
        for s in self.sessions.values():
            await s.pause()


sessions = SessionManager()
