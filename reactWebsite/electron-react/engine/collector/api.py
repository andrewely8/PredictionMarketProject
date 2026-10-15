"""HTTP routes for the Market Tracker panel."""

from __future__ import annotations

import os
import re
import time
from datetime import datetime

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .. import settings
from ..kalshi.auth import CredentialsError, credentials_status, load_credentials
from ..kalshi.markets import market_status, search_markets
from .jobs import Job, JobManager, default_filename

router = APIRouter(prefix="/collector", tags=["collector"])
manager = JobManager()
_TICKER = re.compile(r"^[A-Z0-9][A-Z0-9._-]{1,99}$")


class JobRequest(BaseModel):
    tickers: list[str]
    save_dir: str | None = None          # default: workspace
    start_at: datetime | None = None     # local or UTC ISO time; None = start now
    stop_after_minutes: float | None = Field(default=None, gt=0)
    env: str | None = None               # default: settings.kalshi_env


def _parse_tickers(raw: list[str]) -> list[str]:
    tickers: list[str] = []
    for item in raw:
        for t in re.split(r"[,\s]+", item.strip().upper()):
            if t and t not in tickers:
                tickers.append(t)
    if not tickers:
        raise HTTPException(400, "Enter at least one market ticker")
    bad = [t for t in tickers if not _TICKER.match(t)]
    if bad:
        raise HTTPException(400, f"Invalid ticker(s): {', '.join(bad)}")
    return tickers


@router.get("/credentials")
def get_credentials():
    return credentials_status(settings.get("secret_dir"))


@router.get("/markets")
async def find_markets(q: str, env: str | None = None):
    try:
        return await run_in_threadpool(search_markets, q, env or settings.get("kalshi_env"))
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Kalshi lookup failed: {exc}")


@router.get("/jobs")
def list_jobs():
    return [j.public() for j in sorted(manager.jobs.values(), key=lambda j: -j.created)]


@router.post("/jobs")
async def start_job(req: JobRequest):
    tickers = _parse_tickers(req.tickers)
    env = req.env or settings.get("kalshi_env")
    try:
        creds = load_credentials(settings.get("secret_dir"), env)
    except CredentialsError as exc:
        raise HTTPException(400, f"Kalshi {env} keys: {exc}. Set the keys folder in File → Settings.")
    try:
        statuses = await run_in_threadpool(market_status, tickers, env)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Could not reach Kalshi to check tickers: {exc}")
    missing = [t for t, s in statuses.items() if s is None]
    if missing:
        raise HTTPException(400, f"Not found on Kalshi {env}: {', '.join(missing)}")
    start_at = req.start_at.timestamp() if req.start_at else None
    begin = start_at or time.time()
    stop_at = begin + req.stop_after_minutes * 60 if req.stop_after_minutes else None
    save_dir = os.path.abspath(req.save_dir) if req.save_dir else settings.workspace_dir()
    job = Job(tickers=tickers, env=env, save_path=os.path.join(save_dir, default_filename(tickers, begin)),
              start_at=start_at, stop_at=stop_at)
    manager.start(job, creds)
    out = job.public()
    out["market_status"] = statuses
    return out


@router.post("/jobs/{job_id}/stop")
async def stop_job(job_id: str):
    if job_id not in manager.jobs:
        raise HTTPException(404, "Unknown job")
    return (await manager.stop(job_id)).public()


@router.delete("/jobs/{job_id}")
def remove_job(job_id: str):
    if job_id not in manager.jobs:
        raise HTTPException(404, "Unknown job")
    try:
        manager.remove(job_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True}
