"""Strategy runs.

A run = one strategy file + one recording + one simulator session:

1. the session is reset to the start of the recording with a fresh simulated account;
2. the strategy is started as its own Python process with these environment variables
       KALSHI_ENV=sim
       KALSHI_API_BASE=http://127.0.0.1:8000/[sims/<id>/]trade-api/v2
       KALSHI_WS_URL=ws://127.0.0.1:8000/[sims/<id>/]trade-api/ws/v2
       KALSHI_TICKERS=<markets in the recording, comma separated>
   (no API keys or other secrets are passed);
3. replay starts once the strategy has subscribed (or after SUBSCRIBE_TIMEOUT_S);
4. at the end of the data the strategy gets a short grace period, then is stopped;
5. a report is written to <workspace>/runs/<timestamp>__<strategy>__<data>.json.

"replayer" runs use the Replayer's session at the chosen speed so you can watch them; "headless"
runs use a private session at Max speed (used by the AI tools and "Backtest to end").
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
import uuid
from dataclasses import dataclass, field

from .. import settings
from ..paths import BASE_URL, HOST, PORT
from ..sim.session import SessionManager, SimSession, sessions

SUBSCRIBE_TIMEOUT_S = 20.0
END_GRACE_S = 2.0
MAX_REPORT_FILLS = 2000
MAX_CURVE_POINTS = 600


def strategy_env(session_id: str, tickers: list[str]) -> dict[str, str]:
    keep = ("PATH", "SYSTEMROOT", "SystemRoot", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE", "LANG", "LC_ALL")
    env = {k: v for k, v in os.environ.items() if k in keep}
    prefix = "" if session_id == SessionManager.REPLAYER else f"/sims/{session_id}"
    env.update({
        "KALSHI_ENV": "sim",
        "KALSHI_API_BASE": f"{BASE_URL}{prefix}/trade-api/v2",
        "KALSHI_WS_URL": f"ws://{HOST}:{PORT}{prefix}/trade-api/ws/v2",
        "KALSHI_TICKERS": ",".join(tickers),
        "PYTHONUNBUFFERED": "1",
        "PYTHONIOENCODING": "utf-8",
    })
    return env


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text)[:60]


def max_drawdown(curve: list[tuple[int, float]]) -> float:
    peak, worst = float("-inf"), 0.0
    for _, eq in curve:
        peak = max(peak, eq)
        worst = max(worst, peak - eq)
    return worst


def _downsample(curve: list[tuple[int, float]], n: int) -> list[list[float]]:
    if len(curve) <= n:
        return [[t, round(v, 4)] for t, v in curve]
    step = len(curve) / n
    return [[curve[int(i * step)][0], round(curve[int(i * step)][1], 4)] for i in range(n)] + \
           [[curve[-1][0], round(curve[-1][1], 4)]]


@dataclass
class Run:
    strategy_path: str
    data_path: str
    mode: str                          # "replayer" | "headless"
    speed: float | None
    id: str = field(default_factory=lambda: time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4])
    status: str = "starting"           # starting | waiting | running | completed | stopped | failed
    error: str | None = None
    started: float = field(default_factory=time.time)
    finished: float | None = None
    report_path: str | None = None
    returncode: int | None = None
    session_id: str = SessionManager.REPLAYER
    _proc: asyncio.subprocess.Process | None = None
    _stop: asyncio.Event = field(default_factory=asyncio.Event)
    _task: asyncio.Task | None = None

    def public(self) -> dict:
        return {"id": self.id, "strategy": os.path.basename(self.strategy_path),
                "data_file": os.path.basename(self.data_path), "mode": self.mode, "speed": self.speed,
                "status": self.status, "error": self.error, "started": self.started, "finished": self.finished,
                "report_file": os.path.basename(self.report_path) if self.report_path else None,
                "session": self.session_id, "returncode": self.returncode}


class RunManager:
    def __init__(self) -> None:
        self.runs: dict[str, Run] = {}

    def active_replayer_run(self) -> Run | None:
        return next((r for r in self.runs.values()
                     if r.mode == "replayer" and r.status in ("starting", "waiting", "running")), None)

    async def start(self, strategy_path: str, data_path: str, mode: str = "replayer",
                    speed: float | None = 10.0) -> Run:
        if not os.path.isfile(strategy_path) or not strategy_path.endswith(".py"):
            raise ValueError(f"Strategy file not found: {strategy_path}")
        if mode == "replayer" and self.active_replayer_run():
            raise ValueError("A strategy is already running in the Replayer - stop it first")
        run = Run(strategy_path=strategy_path, data_path=data_path, mode=mode,
                  speed=None if mode == "headless" else speed)
        if mode == "headless":
            run.session_id = f"run-{run.id}"
            sessions.create(run.session_id)
        session = sessions.get(run.session_id)
        if session.recording is None or session.recording.path != os.path.abspath(data_path):
            await session.load(data_path)
        else:
            await session.pause()
            session.reset()
        self.runs[run.id] = run
        run._task = asyncio.get_running_loop().create_task(self._execute(run, session))
        return run

    async def run_to_completion(self, strategy_path: str, data_path: str, timeout_s: float) -> dict:
        """Headless run that returns the report (used by the AI tools)."""
        run = await self.start(strategy_path, data_path, mode="headless")
        try:
            await asyncio.wait_for(asyncio.shield(run._task), timeout_s)
        except asyncio.TimeoutError:
            await self.stop(run.id)
            run.error = f"Timed out after {timeout_s:.0f}s"
        return self.load_report(run.report_path) if run.report_path else {"status": run.status, "error": run.error}

    async def stop(self, run_id: str) -> Run:
        run = self.runs[run_id]
        run._stop.set()
        if run._task:
            try:
                await asyncio.wait_for(asyncio.shield(run._task), 15)
            except asyncio.TimeoutError:
                pass
        return run

    async def stop_all(self) -> None:
        for run in list(self.runs.values()):
            if run.status in ("starting", "waiting", "running"):
                await self.stop(run.id)

    # ------------------------------------------------------------------ execution

    async def _pump(self, stream, session: SimSession, prefix: str) -> None:
        while True:
            line = await stream.readline()
            if not line:
                return
            session.log(prefix + line.decode("utf-8", errors="replace").rstrip())

    async def _execute(self, run: Run, session: SimSession) -> None:
        outcome = await self._drive(run, session)
        run.finished = time.time()
        run.status = outcome
        session.log(f"[run] {run.status}" + (f": {run.error}" if run.error else ""))
        try:
            run.report_path = self._write_report(run, session)
        except Exception as exc:  # noqa: BLE001
            session.log(f"[run] could not write report: {exc}")
        run.status = outcome  # published only now, so a finished run always has its report
        if run.mode == "headless":
            await sessions.close(run.session_id)

    async def _drive(self, run: Run, session: SimSession) -> str:
        """Start the process, play the replay, return the outcome (completed | stopped | failed)."""
        rec = session.recording
        outcome = "failed"
        session.console.clear()
        session.log(f"[run] {os.path.basename(run.strategy_path)} on {rec.name} "
                    f"({'Max' if run.speed is None else f'{run.speed:g}x'} speed)")
        pumps = []
        try:
            run._proc = await asyncio.create_subprocess_exec(
                sys.executable, "-u", run.strategy_path, cwd=os.path.dirname(run.strategy_path),
                env=strategy_env(run.session_id, rec.tickers), stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            pumps = [asyncio.create_task(self._pump(run._proc.stdout, session, "")),
                     asyncio.create_task(self._pump(run._proc.stderr, session, "[stderr] "))]
            run.status = "waiting"
            exited = asyncio.create_task(run._proc.wait())
            subscribed = asyncio.create_task(session.wait_subscribed(SUBSCRIBE_TIMEOUT_S))
            stop = asyncio.create_task(run._stop.wait())
            await asyncio.wait({exited, subscribed, stop}, return_when=asyncio.FIRST_COMPLETED)
            if stop.done():
                outcome = "stopped"
            elif exited.done():
                run.error = "The strategy exited before subscribing to market data"
            else:
                if not subscribed.result():
                    session.log(f"[run] strategy did not subscribe within {SUBSCRIBE_TIMEOUT_S:.0f}s; starting replay anyway")
                run.status = "running"
                await session.play(run.speed)
                ended = asyncio.create_task(session.wait_ended())
                await asyncio.wait({ended, exited, stop}, return_when=asyncio.FIRST_COMPLETED)
                if stop.done():
                    outcome = "stopped"
                elif ended.done():
                    outcome = "completed" if session.state == "ended" else "failed"
                    run.error = session.error
                    await asyncio.sleep(END_GRACE_S)
                else:
                    run.error = f"The strategy process exited (code {run._proc.returncode}) before the data ended"
                ended.cancel()
            for t in (exited, subscribed, stop):
                t.cancel()
        except Exception as exc:  # noqa: BLE001
            outcome, run.error = "failed", f"{type(exc).__name__}: {exc}"
        finally:
            await session.pause()
            await self._terminate(run)
            for p in pumps:
                try:
                    await asyncio.wait_for(p, 2)
                except asyncio.TimeoutError:
                    p.cancel()
        return outcome

    async def _terminate(self, run: Run) -> None:
        proc = run._proc
        if proc is None:
            return
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 5)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        run.returncode = proc.returncode

    # ------------------------------------------------------------------ reports

    def _write_report(self, run: Run, session: SimSession) -> str:
        """Write the report; `run.status` already holds the outcome at this point."""
        ex, rec = session.exchange, session.recording
        curve = session.equity_curve + [(session.clock_ts, ex.equity())]
        per_ticker = {}
        for t, p in ex.positions.items():
            per_ticker[t] = {"position": round(p.qty, 2), "realized_pnl": round(p.realized, 4),
                             "fees": round(p.fees, 4), "traded_dollars": round(p.traded, 4),
                             "fills": sum(1 for f in ex.fills if f.ticker == t)}
        span = max(rec.end_ts - rec.start_ts, 1)
        report = {
            "run_id": run.id, "strategy": os.path.basename(run.strategy_path), "strategy_path": run.strategy_path,
            "data_file": rec.name, "mode": run.mode, "speed": "max" if run.speed is None else run.speed,
            "status": run.status, "error": run.error,
            "started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(run.started)),
            "wall_seconds": round((run.finished or time.time()) - run.started, 1),
            "replay": {"start_ts": rec.start_ts, "end_ts": rec.end_ts, "reached_ts": session.clock_ts,
                       "coverage": round((session.clock_ts - rec.start_ts) / span, 4), "markets": rec.tickers},
            "account": ex.summary(),
            "starting_balance": ex.starting_cash,
            "max_drawdown": round(max_drawdown(curve), 4),
            "per_market": per_ticker,
            "fills": [f.kalshi() for f in ex.fills[:MAX_REPORT_FILLS]],
            "orders_rejected": sum(1 for line in session.console if "order rejected" in line),
            "equity_curve": _downsample(curve, MAX_CURVE_POINTS),
            "console_tail": session.console[-200:],
            "assumptions": [
                "Taker fills at recorded best prices; liquidity you take is not available again until the level changes.",
                "Resting orders fill at their limit when the recorded book crosses them (queue position ignored).",
                "Fees: Kalshi formula with the rates in Settings. P&L marks open positions at the midpoint; "
                "markets are not settled because outcomes are not in the recording.",
            ],
        }
        out_dir = os.path.join(settings.workspace_dir(), "runs")
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"{run.id}__{_slug(report['strategy'][:-3])}__{_slug(rec.name[:-6])}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=1)
        return path

    @staticmethod
    def load_report(path: str) -> dict:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    @staticmethod
    def list_reports(limit: int = 100) -> list[dict]:
        out_dir = os.path.join(settings.workspace_dir(), "runs")
        if not os.path.isdir(out_dir):
            return []
        items = []
        for name in sorted(os.listdir(out_dir), reverse=True)[:limit]:
            if not name.endswith(".json"):
                continue
            try:
                r = RunManager.load_report(os.path.join(out_dir, name))
            except (OSError, ValueError):
                continue
            acct = r.get("account", {})
            items.append({"report_file": name, "run_id": r.get("run_id"), "strategy": r.get("strategy"),
                          "data_file": r.get("data_file"), "status": r.get("status"), "started": r.get("started"),
                          "pnl": acct.get("pnl"), "fees": acct.get("fees"), "fills": acct.get("fills"),
                          "max_drawdown": r.get("max_drawdown"), "coverage": r.get("replay", {}).get("coverage")})
        return items


runs = RunManager()
