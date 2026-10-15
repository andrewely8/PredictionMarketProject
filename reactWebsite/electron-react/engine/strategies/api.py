"""Routes for the Workspace panel (files, templates, settings) and strategy runs."""

from __future__ import annotations

import os
import re
import shutil

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import settings
from ..kalshi.auth import credentials_status
from ..paths import TEMPLATES_DIR
from .runner import runs

router = APIRouter(tags=["workspace"])
STRATEGY_TEMPLATES = os.path.join(TEMPLATES_DIR, "strategies")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,80}$")


def _workspace_file(name: str, ext: str) -> str:
    base = os.path.basename(name)
    if base != name or not base.lower().endswith(ext):
        raise HTTPException(400, f"Expected a {ext} file name in the workspace, got {name!r}")
    root = os.path.realpath(settings.workspace_dir())
    path = os.path.realpath(os.path.join(root, base))
    if os.path.dirname(path) != root or not os.path.isfile(path):
        raise HTTPException(404, f"{name} is not in the workspace")
    return path


def template_list() -> list[dict]:
    out = []
    for name in sorted(os.listdir(STRATEGY_TEMPLATES)):
        if name.endswith(".py"):
            with open(os.path.join(STRATEGY_TEMPLATES, name), "r", encoding="utf-8") as fh:
                doc = fh.read().split('"""')
            summary = doc[1].strip().splitlines()[0] if len(doc) > 2 else ""
            out.append({"template": name[:-3], "summary": summary})
    return out


# --------------------------------------------------------------------------- settings

class SettingsUpdate(BaseModel):
    changes: dict


@router.get("/settings")
def get_settings():
    s = settings.load()
    return {**s, "credentials": credentials_status(s["secret_dir"])}


@router.put("/settings")
def put_settings(req: SettingsUpdate):
    try:
        settings.update(req.changes)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return get_settings()


# --------------------------------------------------------------------------- workspace

@router.get("/workspace")
def workspace():
    root = settings.workspace_dir()
    data, strategies = [], []
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        st = os.stat(path)
        item = {"name": name, "size_bytes": st.st_size, "modified": st.st_mtime}
        if name.lower().endswith(".jsonl"):
            data.append(item)
        elif name.lower().endswith(".py"):
            strategies.append(item)
    return {"dir": root, "data_files": data, "strategy_files": strategies, "reports": runs.list_reports(50)}


@router.get("/workspace/templates")
def templates():
    return template_list()


class NewStrategy(BaseModel):
    name: str
    template: str = "starter"


@router.post("/workspace/strategies")
def new_strategy(req: NewStrategy):
    name = req.name.strip()
    if not name.endswith(".py"):
        name += ".py"
    if not _NAME.match(name):
        raise HTTPException(400, "Use letters, numbers, spaces, '.', '-' or '_' for the file name")
    src = os.path.join(STRATEGY_TEMPLATES, f"{req.template}.py")
    if not os.path.isfile(src):
        raise HTTPException(400, f"Unknown template {req.template!r}")
    dest = os.path.join(settings.workspace_dir(), name)
    if os.path.exists(dest):
        raise HTTPException(409, f"{name} already exists in the workspace")
    shutil.copyfile(src, dest)
    return {"name": name, "path": dest}


@router.get("/workspace/strategies/{name}")
def read_strategy(name: str):
    path = _workspace_file(name, ".py")
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return {"name": name, "path": path, "content": fh.read()}


# --------------------------------------------------------------------------- runs

class RunRequest(BaseModel):
    strategy: str
    data_file: str
    speed: float | None = 10.0     # None = Max
    mode: str = "replayer"         # replayer | headless


@router.post("/strategy/runs")
async def start_run(req: RunRequest):
    if req.mode not in ("replayer", "headless"):
        raise HTTPException(400, "mode must be 'replayer' or 'headless'")
    strategy = _workspace_file(req.strategy, ".py")
    data = _workspace_file(req.data_file, ".jsonl")
    try:
        run = await runs.start(strategy, data, mode=req.mode, speed=req.speed)
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return run.public()


@router.get("/strategy/runs")
def list_runs():
    return [r.public() for r in sorted(runs.runs.values(), key=lambda r: -r.started)][:20]


@router.get("/strategy/runs/{run_id}")
def get_run(run_id: str):
    if run_id not in runs.runs:
        raise HTTPException(404, "Unknown run")
    return runs.runs[run_id].public()


@router.post("/strategy/runs/{run_id}/stop")
async def stop_run(run_id: str):
    if run_id not in runs.runs:
        raise HTTPException(404, "Unknown run")
    return (await runs.stop(run_id)).public()


@router.get("/strategy/reports")
def list_reports():
    return runs.list_reports()


@router.get("/strategy/reports/{name}")
def get_report(name: str):
    base = os.path.basename(name)
    path = os.path.join(settings.workspace_dir(), "runs", base)
    if base != name or not base.endswith(".json") or not os.path.isfile(path):
        raise HTTPException(404, "Report not found")
    return runs.load_report(path)
