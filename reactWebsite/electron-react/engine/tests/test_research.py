"""AI research assistant: statistics, retrieval, artifacts, validation, model options, and the
agent loop driving real tools (including a real backtest) through the live engine.

A scripted fake chat model stands in for the LLM, so the real LangChain create_agent graph, ToolNode,
context injection, checkpointer and structured-output handling run without network access or keys.
"""

import hashlib
import io
import json
import os
import zipfile

import httpx
import httpx2
import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from conftest import DATA_FILE, write_jsonl
from engine import settings
from engine.paths import TEMPLATES_DIR
from engine.research import agent as agent_mod
from engine.research import api as ai_api
from engine.research import claude_account as ca
from engine.research import installers
from engine.research import local_llm as ll
from engine.research import market_data as mdmod
from engine.research import models
from engine.research.artifacts import ArtifactError, ArtifactStore, sanitize_filename
from engine.research.rag import SessionIndex
from engine.research.tools import AgentContext, Session
from engine.research.validation import validate_source

STARTER = open(os.path.join(TEMPLATES_DIR, "strategies", "starter.py"), encoding="utf-8").read()


class ScriptedToolModel(GenericFakeChatModel):
    """Fake model that replays scripted AIMessages (including tool calls) and accepts bind_tools."""

    def bind_tools(self, tools, **kwargs):
        return self


def call(name, args, i):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{i}", "type": "tool_call"}])


def final(i, **fields):
    return call("ResearchResponse", {"message": "done", **fields}, i)


def run_turn(tmp_path, workspace, files, script, message="x", loop=None):
    service = agent_mod.AgentService(model=ScriptedToolModel(messages=iter(script)))
    session = Session(id="t1", workspace_dir=str(workspace), files=files)
    store = ArtifactStore(str(tmp_path / "generated"))
    events = list(service.stream_turn(AgentContext(session, store, loop), message))
    msgs = service.agent.get_state({"configurable": {"thread_id": "t1"}}).values["messages"]
    tool_out = {m.name: m.content for m in msgs if type(m).__name__ == "ToolMessage"}
    return events, tool_out, store


# --------------------------------------------------------------------------- statistics + retrieval

def test_market_data_conventions_and_stats(tmp_path, data_path):
    p = tmp_path / "tiny.jsonl"
    write_jsonl(p, [
        {"type": "subscribed", "id": 1, "msg": {}},
        {"type": "orderbook_snapshot", "msg": {"market_ticker": "T", "yes_dollars_fp": [["0.4000", "10.00"], ["0.4500", "5.00"]],
                                               "no_dollars_fp": [["0.5000", "7.00"], ["0.5200", "3.00"]]}},
        {"type": "orderbook_delta", "msg": {"market_ticker": "T", "price_dollars": "0.4500", "delta_fp": "-5.00", "side": "yes", "ts_ms": 1000}},
        {"type": "orderbook_delta", "msg": {"market_ticker": "T", "price_dollars": "0.4600", "delta_fp": "8.00", "side": "yes", "ts_ms": 2000}},
        "not json",
    ])
    a = mdmod.MarketData(str(p)).tickers["T"].arrays()
    assert list(a["bid"]) == [45.0, 40.0, 46.0] and list(a["ask"]) == [48.0, 48.0, 48.0]
    md = mdmod.load_market_data(data_path)
    prof = mdmod.profile(md)
    assert prof["parse_errors"] == 0 and len(prof["tickers"]) == 2
    assert mdmod.spread_statistics(md)["spread_statistics"][0]["time_weighted_mean_cents"] > 0
    assert mdmod.imbalance_analysis(md, None, 10)["imbalance_analysis"][0]["samples"] > 100
    assert len(mdmod.sample_windows(md, None, 3, "largest_move", 60)["windows"]) == 3


def test_retrieval_returns_summaries(data_path):
    idx = SessionIndex([data_path])
    docs = idx.retrieve("large move bid heavy", k=5)
    assert docs and all(d.metadata["file"] == DATA_FILE for d in docs)
    assert all("BBB" in d.metadata.get("ticker", "") for d in idx.retrieve("window", k=5, ticker="BBB"))


# --------------------------------------------------------------------------- artifacts + validation

def test_artifact_store_is_sandboxed(tmp_path):
    assert sanitize_filename("../../etc/evil.py", "python_strategy") == "evil.py"
    with pytest.raises(ArtifactError):
        sanitize_filename("a.py", "shell_script")
    store = ArtifactStore(str(tmp_path / "generated"))
    a = store.create("s1", "../strat.py", "print(1)", "python_strategy", "d")
    b = store.create("s1", "strat.py", "print(2)", "python_strategy", "d")
    assert (a.filename, b.filename) == ("strat.py", "strat_2.py")
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "strat.py").write_text("ORIGINAL")
    assert os.path.basename(store.add_to_workspace(a.id, str(ws))) == "strat_2.py"
    assert (ws / "strat.py").read_text() == "ORIGINAL"


@pytest.mark.parametrize("src, needle", [
    ("import subprocess\n", "subprocess"),
    ("import socket\n", "socket"),
    ("import os\nos.system('dir')\n", "os.system"),
    ("eval('1')\n", "eval"),
    ("open('/etc/passwd', 'w')\n", "absolute"),
    ("import definitely_not_installed_pkg\n", "not installed"),
    ("def f(:\n", "SyntaxError"),
])
def test_validation_rejects_dangerous_code(src, needle):
    res = validate_source(src)
    assert not res["ok"] and any(needle in e for e in res["errors"])


def test_validation_accepts_strategy_libraries_and_flags_foreign_urls():
    ok = validate_source(STARTER)
    assert ok["ok"] and not ok["warnings"]
    res = validate_source("import requests, websockets\nURL = 'https://evil.example.com/x'\n")
    assert res["ok"] and any("evil.example.com" in w for w in res["warnings"])


# --------------------------------------------------------------------------- model options

@pytest.fixture
def signed_in_profile(tmp_path, monkeypatch):
    cfg = tmp_path / "anthropic"
    (cfg / "configs").mkdir(parents=True)
    (cfg / "credentials").mkdir()
    (cfg / "configs" / "default.json").write_text(json.dumps({"authentication": {"type": "user_oauth"}}))
    (cfg / "credentials" / "default.json").write_text(json.dumps({"access_token": "sk-ant-oat-TEST", "expires_at": 9_999_999_999}))
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(cfg))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)


def capture_transport(monkeypatch, body):
    captured = []

    def handle(self, request):
        captured.append(request)
        return httpx2.Response(200, json=body)
    monkeypatch.setattr(httpx2.HTTPTransport, "handle_request", handle)
    return captured


def test_mode_is_a_setting():
    models.set_mode("local")
    assert models.current_mode() == "local" and settings.get("ai_mode") == "local"
    assert type(models.build_chat_model()).__name__ == "ChatOllama"
    models.set_mode("claude")
    assert isinstance(models.build_chat_model(), models.AccountChatAnthropic)
    with pytest.raises(ValueError):
        models.set_mode("gpt")


def test_signed_in_profile_is_used_as_bearer_token(signed_in_profile, monkeypatch):
    captured = capture_transport(monkeypatch, {"id": "m", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
                                               "content": [{"type": "text", "text": "hi"}], "stop_reason": "end_turn",
                                               "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}})
    model = models.build_chat_model(models.ProviderConfig("claude", "anthropic", "claude-opus-5-5"))
    assert model.invoke("hello").content == "hi"
    h = captured[-1].headers
    assert h["authorization"] == "Bearer sk-ant-oat-TEST" and "x-api-key" not in h
    assert "oauth-2025-04-20" in h["anthropic-beta"]


def test_account_status(signed_in_profile, monkeypatch, tmp_path):
    capture_transport(monkeypatch, {"data": [], "has_more": False, "first_id": None, "last_id": None})
    acct = ca.ClaudeAccount()
    assert acct.status()["signed_in"] is True
    monkeypatch.setenv("ANTHROPIC_CONFIG_DIR", str(tmp_path / "empty"))
    acct.invalidate()
    st = acct.status()
    assert st["signed_in"] is False and st["detail"] == "Not signed in"


def zip_bytes(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_cli_download_is_checksum_verified_and_login_gets_no_static_keys(tmp_path, monkeypatch):
    exe = "ant.exe" if installers.IS_WINDOWS else "ant"
    payload = zip_bytes({f"ant/{exe}": b"binary"})

    class Resp(io.BytesIO):
        headers = {"Content-Length": str(len(payload))}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    key = installers.platform_key()
    monkeypatch.setattr(ca, "ANT_DIR", str(tmp_path / "ant"))
    monkeypatch.setattr(ca, "RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(installers, "RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(ca.shutil, "which", lambda name: None)
    monkeypatch.setattr(installers.urllib.request, "urlopen", lambda req, timeout=None: Resp(payload))
    monkeypatch.setitem(ca.ANT_ASSETS, key, ("ant.zip", "0" * 64, "zip"))
    with pytest.raises(RuntimeError, match="Checksum mismatch"):
        ca.ClaudeAccount().install_cli()
    monkeypatch.setitem(ca.ANT_ASSETS, key, ("ant.zip", hashlib.sha256(payload).hexdigest(), "zip"))
    launched = {}

    class FakePopen:
        def __init__(self, args, env=None, **kw):
            launched.update(args=args, env=env)

        def poll(self):
            return None
    monkeypatch.setattr(ca.subprocess, "Popen", FakePopen)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-stale")
    assert ca.ClaudeAccount().start_login()["started"] is True
    assert launched["args"][1:] == ["auth", "login"] and "ANTHROPIC_API_KEY" not in launched["env"]


def test_archive_traversal_rejected_and_local_status(tmp_path, monkeypatch):
    bad = tmp_path / "bad.zip"
    bad.write_bytes(zip_bytes({"../escape.txt": b"x"}))
    with pytest.raises(RuntimeError, match="escapes"):
        installers.extract(str(bad), str(tmp_path / "dest"), "zip")
    monkeypatch.setattr(ll, "OLLAMA_DIR", str(tmp_path / "ollama"))
    st = ll.LocalLLM().status()
    assert st["ready"] is False and "not installed" in st["problem"] and st["base_url"].endswith(":11435")
    assert installers.platform_key() in ll.OLLAMA_ASSETS


# --------------------------------------------------------------------------- agent loop (in process)

def test_agent_turn_and_workspace_tools(tmp_path, workspace, data_path):
    (workspace / "mine.py").write_text("print('my strategy')\n")
    script = [
        call("profile_market_data", {"file_name": DATA_FILE}, 1),
        call("retrieve_market_context", {"query": "large move", "k": 3}, 2),
        call("read_workspace_strategy_file", {"file_name": "mine.py"}, 3),
        call("read_workspace_strategy_file", {"file_name": "../secret.py"}, 4),
        call("get_strategy_template", {"template": "orderbook_imbalance"}, 5),
        call("create_artifact", {"filename": "../better.py", "content": STARTER, "artifact_type": "python_strategy",
                                 "description": "v2"}, 6),
        final(7, hypotheses=["imbalance leads mid"]),
    ]
    events, out, store = run_turn(tmp_path, workspace, {DATA_FILE: data_path}, script)
    assert events[-1]["event"] == "final", events
    assert events[-1]["response"]["hypotheses"] == ["imbalance leads mid"]
    assert out["read_workspace_strategy_file"]  # last call (traversal) must be an error
    assert "error" in out["read_workspace_strategy_file"]
    art = store.get(events[-1]["artifact_ids"][0])
    assert art.filename == "better.py"
    assert json.loads(out["create_artifact"])["validation"]["ok"]
    assert "class Strategy" in out["get_strategy_template"]


def test_nothing_ticked_names_available_files(tmp_path, workspace):
    events, out, _ = run_turn(tmp_path, workspace, {}, [call("profile_market_data", {"file_name": DATA_FILE}, 1), final(2)])
    err = json.loads(out["profile_market_data"])["error"]
    assert "tick" in err and DATA_FILE in err


# --------------------------------------------------------------------------- the improve-and-retest loop (live engine)

def test_ai_improves_and_backtests_through_the_live_engine(live_server, workspace, monkeypatch):
    """Scripted model: read the user's strategy + its report, write v2, backtest v2 in the simulator."""
    (workspace / "orig.py").write_text(STARTER)
    r = httpx.post(f"{live_server}/strategy/runs", json={"strategy": "orig.py", "data_file": DATA_FILE, "mode": "headless"}).json()
    for _ in range(300):
        run = httpx.get(f"{live_server}/strategy/runs/{r['id']}").json()
        if run["status"] not in ("starting", "waiting", "running"):
            break
        import time
        time.sleep(0.3)
    assert run["status"] == "completed"
    improved = STARTER.replace("self.last_print = 0", "self.last_print = 0  # v2")
    script = [
        call("read_workspace_strategy_file", {"file_name": "orig.py"}, 1),
        call("list_run_reports", {"strategy": "orig.py"}, 2),
        call("read_run_report", {"report_file": run["report_file"]}, 3),
        call("create_artifact", {"filename": "orig_v2.py", "content": improved, "artifact_type": "python_strategy",
                                 "description": "v2"}, 4),
    ]
    model = ScriptedToolModel(messages=iter(script + [final(9, backtest_results=["v2 tested"])]))
    monkeypatch.setattr(ai_api, "agent_service", agent_mod.AgentService(model=model))
    monkeypatch.setattr(ai_api, "readiness", lambda: (True, None))
    store = ArtifactStore(str(workspace.parent / "gen"))
    monkeypatch.setattr(ai_api, "artifacts", store)

    sid = httpx.post(f"{live_server}/ai/sessions", json={"data_files": [DATA_FILE]}).json()["session_id"]

    # The artifact id is only known after create_artifact runs, so the test call is appended lazily.
    def events_for(message):
        with httpx.stream("POST", f"{live_server}/ai/sessions/{sid}/chat", json={"message": message}, timeout=300) as resp:
            return [json.loads(line) for line in resp.iter_lines() if line]
    script_iter = model.messages

    def with_test():
        for m in script_iter:
            if m.tool_calls and m.tool_calls[0]["name"] == "ResearchResponse":
                art_id = next(a.id for a in store.for_session(sid))
                yield call("run_strategy_test", {"strategy": art_id, "file_name": DATA_FILE, "timeout_seconds": 120}, 8)
            yield m
    model.messages = with_test()
    events = events_for("Improve orig.py")
    assert events[-1]["event"] == "final", events[-3:]
    tools = [e["tool"] for e in events if e["event"] == "tool_start"]
    assert tools == ["read_workspace_strategy_file", "list_run_reports", "read_run_report", "create_artifact",
                     "run_strategy_test"]
    assert all(e["status"] == "complete" for e in events if e["event"] == "tool_end"), events
    reports = httpx.get(f"{live_server}/strategy/reports").json()
    assert reports[0]["strategy"] == "orig_v2.py" and reports[0]["status"] == "completed"

    # Add to Workspace, then the user can retest it in the Replayer.
    art = events[-1]["artifacts"][0]
    added = httpx.post(f"{live_server}/ai/artifacts/{art['id']}/add-to-workspace").json()
    assert (workspace / added["filename"]).exists()
