"""Engine entry point.

    cd reactWebsite/electron-react
    engine/.venv/Scripts/python -m uvicorn engine.server:app --host 127.0.0.1 --port 8000

The Electron app starts this automatically (src/main/engine.ts).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware

from . import settings
from .collector.api import manager as collector_jobs
from .collector.api import router as collector_router
from .research.api import lifespan_start as research_start
from .research.api import lifespan_stop as research_stop
from .research.api import router as research_router
from .sim.api import control as replay_router
from .sim.api import kalshi as kalshi_router
from .sim.session import sessions
from .strategies.api import router as workspace_router
from .strategies.runner import runs

log = logging.getLogger("engine")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.workspace_dir()  # create the default workspace on first launch
    research_start()
    yield
    await runs.stop_all()
    await collector_jobs.stop_all()
    await sessions.shutdown()
    research_stop()


app = FastAPI(title="Kalshi Backtester engine", lifespan=lifespan)
# Browser pages may only call the engine from the app's own renderer (dev server or file://).
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:1212", "null"],
                   allow_methods=["*"], allow_headers=["*"])
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

app.include_router(workspace_router)
app.include_router(collector_router)
app.include_router(replay_router)
app.include_router(kalshi_router)
app.include_router(research_router)


@app.get("/health")
def health():
    return {"status": "ok", "workspace": settings.workspace_dir(create=False)}
