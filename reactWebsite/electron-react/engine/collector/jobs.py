"""Recording jobs.

Each job subscribes to the `orderbook_delta` channel for a set of market tickers and appends every
raw websocket message, one JSON object per line, to its own file. That is exactly the format the
Replayer, the simulator and the AI tools read:

    {"type": "subscribed", ...}
    {"type": "orderbook_snapshot", "msg": {...}}     # one per market, again after any reconnect
    {"type": "orderbook_delta", "msg": {..., "ts_ms": ...}}

Jobs can start at a scheduled time, stop at a scheduled time, and reconnect automatically
(with exponential backoff) if the connection drops.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field

import websockets

from ..kalshi.auth import ENVIRONMENTS, WS_SIGN_PATH, Credentials

FLUSH_EVERY_S = 1.0
MAX_BACKOFF_S = 30.0


def default_filename(tickers: list[str], started: float) -> str:
    """'<event ticker>_<YYYYMMDD-HHMMSS>.jsonl' (event = longest common '-' prefix of the tickers)."""
    parts = [t.split("-") for t in tickers]
    common = []
    for segs in zip(*parts):
        if len(set(segs)) != 1:
            break
        common.append(segs[0])
    label = "-".join(common) if common else tickers[0]
    if len(tickers) == 1:
        label = tickers[0]
    label = re.sub(r"[^A-Za-z0-9._-]+", "_", label) or "recording"
    return f"{label}_{time.strftime('%Y%m%d-%H%M%S', time.localtime(started))}.jsonl"


@dataclass
class Job:
    tickers: list[str]
    env: str
    save_path: str
    start_at: float | None = None      # epoch seconds; None = now
    stop_at: float | None = None       # epoch seconds; None = until stopped
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])
    status: str = "scheduled"          # scheduled | connecting | recording | reconnecting | stopped | finished | error
    created: float = field(default_factory=time.time)
    messages: int = 0
    deltas: int = 0
    bytes_written: int = 0
    reconnects: int = 0
    last_message_at: float | None = None
    error: str | None = None
    _stop: asyncio.Event = field(default_factory=asyncio.Event, repr=False)
    _task: asyncio.Task | None = field(default=None, repr=False)

    def public(self) -> dict:
        return {
            "id": self.id, "tickers": self.tickers, "env": self.env, "file": os.path.basename(self.save_path),
            "save_path": self.save_path, "status": self.status, "start_at": self.start_at, "stop_at": self.stop_at,
            "created": self.created, "messages": self.messages, "deltas": self.deltas,
            "bytes_written": self.bytes_written, "reconnects": self.reconnects,
            "last_message_at": self.last_message_at, "error": self.error,
        }


def subscribe_command(tickers: list[str]) -> dict:
    # Kalshi accepts "market_ticker" for one market and "market_tickers" for several.
    params: dict = {"channels": ["orderbook_delta"]}
    if len(tickers) == 1:
        params["market_ticker"] = tickers[0]
    else:
        params["market_tickers"] = tickers
    return {"id": 1, "cmd": "subscribe", "params": params}


async def _wait_or_stop(job: Job, seconds: float) -> bool:
    """Sleep up to `seconds`; return True if the job was asked to stop."""
    try:
        await asyncio.wait_for(job._stop.wait(), timeout=max(0.0, seconds))
        return True
    except asyncio.TimeoutError:
        return False


async def run_job(job: Job, creds: Credentials, connect=websockets.connect) -> None:
    ws_url = ENVIRONMENTS[job.env]["ws"]
    try:
        if job.start_at and job.start_at > time.time():
            job.status = "scheduled"
            if await _wait_or_stop(job, job.start_at - time.time()):
                job.status = "stopped"
                return
        os.makedirs(os.path.dirname(job.save_path), exist_ok=True)
        backoff = 1.0
        with open(job.save_path, "a", encoding="utf-8") as out:
            while not job._stop.is_set():
                if job.stop_at and time.time() >= job.stop_at:
                    job.status = "finished"
                    return
                job.status = "connecting" if job.reconnects == 0 else "reconnecting"
                try:
                    async with connect(ws_url, additional_headers=creds.headers("GET", WS_SIGN_PATH),
                                       ping_interval=20, ping_timeout=20, max_size=None) as ws:
                        await ws.send(json.dumps(subscribe_command(job.tickers)))
                        backoff = 1.0
                        last_flush = time.time()
                        while not job._stop.is_set():
                            timeout = 1.0
                            if job.stop_at:
                                timeout = min(timeout, max(0.0, job.stop_at - time.time()))
                                if timeout == 0:
                                    job.status = "finished"
                                    return
                            try:
                                raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                            except asyncio.TimeoutError:
                                if time.time() - last_flush >= FLUSH_EVERY_S:
                                    out.flush()
                                    last_flush = time.time()
                                continue
                            text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                            msg = json.loads(text)
                            if msg.get("type") == "error":
                                job.error = (msg.get("msg") or {}).get("msg") or text[:200]
                                job.status = "error"
                                return
                            out.write(text.rstrip("\n") + "\n")
                            job.messages += 1
                            job.bytes_written += len(text) + 1
                            job.last_message_at = time.time()
                            if msg.get("type") == "orderbook_delta":
                                job.deltas += 1
                            job.status = "recording"
                            if time.time() - last_flush >= FLUSH_EVERY_S:
                                out.flush()
                                last_flush = time.time()
                except (OSError, websockets.WebSocketException, asyncio.TimeoutError) as exc:
                    job.error = f"connection lost: {exc}"
                finally:
                    out.flush()
                if job._stop.is_set():
                    break
                job.reconnects += 1
                job.status = "reconnecting"
                if await _wait_or_stop(job, backoff):
                    break
                backoff = min(backoff * 2, MAX_BACKOFF_S)
        job.status = "stopped"
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI
        job.status, job.error = "error", f"{type(exc).__name__}: {exc}"


class JobManager:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}

    def start(self, job: Job, creds: Credentials) -> Job:
        self.jobs[job.id] = job
        job._task = asyncio.get_running_loop().create_task(run_job(job, creds))
        return job

    async def stop(self, job_id: str) -> Job:
        job = self.jobs[job_id]
        job._stop.set()
        if job._task:
            try:
                await asyncio.wait_for(job._task, timeout=10)
            except asyncio.TimeoutError:
                job._task.cancel()
        return job

    async def stop_all(self) -> None:
        for job_id in list(self.jobs):
            if self.jobs[job_id]._task and not self.jobs[job_id]._task.done():
                await self.stop(job_id)

    def remove(self, job_id: str) -> None:
        job = self.jobs[job_id]
        if job._task and not job._task.done():
            raise ValueError("Stop the job before removing it")
        del self.jobs[job_id]
