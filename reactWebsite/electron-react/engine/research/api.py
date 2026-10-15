"""Routes for the AI Strategy Research panel, mounted under /ai."""

from __future__ import annotations

import asyncio
import json
import os
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import iterate_in_threadpool, run_in_threadpool

from .. import settings
from ..strategies.runner import runs
from .agent import AgentService
from .artifacts import ArtifactError, ArtifactStore
from .claude_account import ClaudeAccount
from .local_llm import LocalLLM
from .models import DEFAULT_ANTHROPIC_MODEL, configure_langsmith, current_mode, provider_config, set_mode
from .tools import AgentContext, Session
from .validation import validate_source

router = APIRouter(prefix="/ai", tags=["ai"])

claude_account = ClaudeAccount()
local_llm = LocalLLM()
LANGSMITH = configure_langsmith()
artifacts = ArtifactStore()
agent_service = AgentService()
chat_sessions: dict[str, Session] = {}   # in memory only; nothing is persisted between launches
MAX_MESSAGE_CHARS = 8000


def lifespan_start() -> None:
    LocalLLM.cleanup_orphan()
    if current_mode() == "local":
        local_llm.start_in_background()   # packaged Ollama, if already installed


def lifespan_stop() -> None:
    local_llm.stop()


# --------------------------------------------------------------------------- models

class SessionRequest(BaseModel):
    data_files: list[str] = Field(default_factory=list)


class ChatRequest(BaseModel):
    message: str


class ModeRequest(BaseModel):
    mode: str


class TestRequest(BaseModel):
    data_file: str | None = None


# --------------------------------------------------------------------------- helpers

def _validated_files(names: list[str]) -> dict[str, str]:
    """Accept only existing .jsonl files directly inside the workspace directory."""
    root = os.path.realpath(settings.workspace_dir())
    out: dict[str, str] = {}
    for name in names:
        base = os.path.basename(name)
        if base != name or not base.lower().endswith(".jsonl"):
            raise HTTPException(400, f"Invalid data file name: {name}")
        path = os.path.realpath(os.path.join(root, base))
        if os.path.dirname(path) != root or not os.path.isfile(path):
            raise HTTPException(400, f"Data file not found in workspace: {name}")
        out[base] = path
    return out


def _session(session_id: str) -> Session:
    s = chat_sessions.get(session_id)
    if s is None:
        raise HTTPException(404, "Unknown session (the engine may have restarted). Start a new conversation.")
    return s


def _artifact(artifact_id: str):
    try:
        return artifacts.get(artifact_id)
    except KeyError:
        raise HTTPException(404, "Artifact not found")


def readiness() -> tuple[bool, str | None]:
    """Is the selected model option usable right now? (ready, reason-if-not)"""
    if current_mode() == "local":
        st = local_llm.status()
        return st["ready"], st["problem"]
    st = claude_account.status()
    if st["signed_in"]:
        return True, None
    if st["login_in_progress"]:
        return False, "Finish signing in with Claude in your browser"
    return False, f"{st['detail']} - click 'Sign in with Claude'"


def _session_payload(s: Session) -> dict:
    return {"session_id": s.id, "data_files": [{"name": n, "size_mb": round(os.path.getsize(p) / 1e6, 2)}
                                               for n, p in s.files.items()]}


# --------------------------------------------------------------------------- status and model choice

@router.get("/health")
def health():
    cfg = provider_config()
    ready, problem = readiness()
    return {"status": "ok", "mode": cfg.mode, "provider": cfg.provider, "model": cfg.model, "ready": ready,
            "problem": problem, "langsmith": LANGSMITH}


@router.get("/llm/status")
def llm_status():
    cfg = provider_config()
    ready, problem = readiness()
    return {"mode": cfg.mode, "model": cfg.model, "ready": ready, "problem": problem,
            "claude": {**claude_account.status(), "model": os.getenv("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL)},
            "local": local_llm.status()}


@router.post("/llm/mode")
def choose_mode(req: ModeRequest):
    try:
        set_mode(req.mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    agent_service.reset()  # new model -> fresh agent and conversation memory
    if req.mode == "local":
        local_llm.start_in_background()
    return llm_status()


@router.post("/auth/login")
def auth_login():
    try:
        return claude_account.start_login()
    except Exception as exc:  # noqa: BLE001 - download/launch problems go to the UI
        raise HTTPException(500, f"Could not start sign-in: {exc}")


@router.post("/auth/logout")
def auth_logout():
    claude_account.logout()
    agent_service.reset()
    return claude_account.status()


@router.post("/local/setup")
def local_setup():
    local_llm.setup_in_background()
    return local_llm.status()


# --------------------------------------------------------------------------- conversations

@router.post("/sessions")
def create_session(req: SessionRequest):
    s = Session(id=uuid.uuid4().hex, workspace_dir=settings.workspace_dir(), files=_validated_files(req.data_files))
    chat_sessions[s.id] = s
    return _session_payload(s)


@router.put("/sessions/{session_id}/files")
def update_files(session_id: str, req: SessionRequest):
    s = _session(session_id)
    s.workspace_dir = settings.workspace_dir()
    s.files = _validated_files(req.data_files)
    return _session_payload(s)


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str):
    chat_sessions.pop(session_id, None)
    agent_service.forget(session_id)
    return {"ok": True}


@router.post("/sessions/{session_id}/chat")
async def chat(session_id: str, req: ChatRequest):
    """Streams newline-delimited JSON events: tool_start, tool_end, final (with artifacts), error."""
    s = _session(session_id)
    message = req.message.strip()
    if not message:
        raise HTTPException(400, "Empty message")
    if len(message) > MAX_MESSAGE_CHARS:
        raise HTTPException(400, f"Message too long (max {MAX_MESSAGE_CHARS} characters)")
    ready, problem = await run_in_threadpool(readiness)
    if not ready:
        raise HTTPException(503, problem)
    ctx = AgentContext(session=s, artifacts=artifacts, loop=asyncio.get_running_loop())

    def events():
        yield {"event": "status", "text": "Thinking..."}
        for ev in agent_service.stream_turn(ctx, message):
            if ev["event"] == "final":
                ids = {x.id for x in artifacts.for_session(s.id)}
                ev["artifacts"] = [artifacts.get(a).public() for a in ev.pop("artifact_ids") if a in ids]
            yield ev

    async def ndjson():
        async for ev in iterate_in_threadpool(events()):  # the agent loop is synchronous
            yield json.dumps(ev, default=str) + "\n"

    return StreamingResponse(ndjson(), media_type="application/x-ndjson")


# --------------------------------------------------------------------------- artifacts

@router.get("/artifacts/{artifact_id}")
def get_artifact(artifact_id: str):
    art = _artifact(artifact_id)
    return {**art.public(), "content": artifacts.read(artifact_id)}


@router.get("/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: str):
    art = _artifact(artifact_id)
    return FileResponse(art.path, filename=art.filename, media_type="application/octet-stream")


@router.post("/artifacts/{artifact_id}/add-to-workspace")
def add_to_workspace(artifact_id: str):
    _artifact(artifact_id)
    try:
        target = artifacts.add_to_workspace(artifact_id, settings.workspace_dir())
    except ArtifactError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "path": target, "filename": os.path.basename(target)}


@router.delete("/artifacts/{artifact_id}")
def delete_artifact(artifact_id: str):
    _artifact(artifact_id)
    artifacts.delete(artifact_id)
    return {"ok": True}


@router.post("/artifacts/{artifact_id}/validate")
def validate_artifact(artifact_id: str):
    art = _artifact(artifact_id)
    if not art.filename.endswith(".py"):
        raise HTTPException(400, "Only Python artifacts can be validated")
    return validate_source(artifacts.read(artifact_id), art.filename)


@router.post("/artifacts/{artifact_id}/test")
async def test_artifact(artifact_id: str, req: TestRequest):
    """Headless Max-speed backtest of an artifact on a data file selected in its conversation."""
    art = _artifact(artifact_id)
    if not art.filename.endswith(".py"):
        raise HTTPException(400, "Only Python artifacts can be tested")
    check = validate_source(artifacts.read(artifact_id), art.filename)
    if not check["ok"]:
        raise HTTPException(400, "Validation failed: " + "; ".join(check["errors"]))
    s = chat_sessions.get(art.session_id)
    files = s.files if s else {}
    if req.data_file:
        if req.data_file not in files:
            raise HTTPException(400, f"{req.data_file} is not a selected data file")
        data = files[req.data_file]
    elif files:
        data = next(iter(files.values()))
    else:
        raise HTTPException(400, "Select a data file in the AI panel to test against")
    try:
        run = await runs.start(art.path, data, mode="headless")
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    return run.public()
