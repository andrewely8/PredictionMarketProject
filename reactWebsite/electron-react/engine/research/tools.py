"""The narrow, application-specific tools the research agent may call.

Permissions, by design:
  * data tools read ONLY the .jsonl files the user ticked in the panel, addressed by file name,
    and return compact statistics - never raw lines;
  * the user's strategy files (.py) and run reports (runs/*.json) in the workspace can be read by
    name, read-only;
  * create_artifact writes ONLY into engine/generated/<session>/; nothing reaches the workspace
    until the user clicks "Add to Workspace";
  * run_strategy_test runs a strategy against the simulator (headless, Max speed, no API keys);
  * there is no shell tool, no arbitrary file read/write, no network tool.

Per-session state (selected files, retrieval index, artifacts) is injected through LangChain's
ToolRuntime context, so the model cannot address another session's data.
"""

from __future__ import annotations

import asyncio
import functools
import json
import os
from dataclasses import dataclass, field
from typing import Literal

from langchain.tools import ToolRuntime, tool

from ..paths import TEMPLATES_DIR
from ..strategies.runner import runs
from . import market_data as mdmod
from .artifacts import ArtifactError, ArtifactStore
from .rag import SessionIndex
from .validation import validate_source

STRATEGY_TEMPLATES = os.path.join(TEMPLATES_DIR, "strategies")
TEMPLATE_NAMES = ("starter", "orderbook_imbalance", "cross_market_arbitrage", "ml_direction")
MAX_TOOL_CHARS = 12_000
MAX_STRATEGY_FILE_BYTES = 100_000
MAX_TEST_SECONDS = 600


@dataclass
class Session:
    id: str
    workspace_dir: str
    files: dict[str, str] = field(default_factory=dict)  # data file name -> validated absolute path
    index: SessionIndex | None = None
    turn_artifacts: list[str] = field(default_factory=list)

    def get_index(self) -> SessionIndex:
        if self.index is None or self.index.paths != list(self.files.values()):
            self.index = SessionIndex(list(self.files.values()))
        return self.index


@dataclass
class AgentContext:
    """Runtime context passed to every tool call (not visible to or settable by the model)."""
    session: Session
    artifacts: ArtifactStore
    loop: asyncio.AbstractEventLoop | None = None   # the engine's event loop, for strategy runs


def _json(obj) -> str:
    text = json.dumps(obj, default=str)
    if len(text) > MAX_TOOL_CHARS:
        text = text[:MAX_TOOL_CHARS] + '..."[truncated: ask for a narrower ticker/window]"'
    return text


def _workspace_files(session: Session, ext: str, sub: str = "") -> list[str]:
    folder = os.path.join(session.workspace_dir, sub)
    try:
        return sorted(f for f in os.listdir(folder)
                      if f.lower().endswith(ext) and os.path.isfile(os.path.join(folder, f)))
    except OSError:
        return []


def _workspace_path(session: Session, name: str, ext: str, sub: str = "") -> str:
    base = os.path.basename(str(name).replace("\\", "/"))
    if base != name or not base.lower().endswith(ext):
        raise ValueError(f"Pass only a {ext} file name, one of {_workspace_files(session, ext, sub)[:30]}")
    root = os.path.realpath(os.path.join(session.workspace_dir, sub))
    path = os.path.realpath(os.path.join(root, base))
    if os.path.dirname(path) != root or not os.path.isfile(path):
        raise ValueError(f"'{base}' was not found. Available: {_workspace_files(session, ext, sub)[:30]}")
    return path


def _resolve(session: Session, file_name: str | None) -> str:
    if not session.files:
        raise ValueError("No data files are selected, so they cannot be analyzed yet. Ask the user to tick "
                         f"the files in the panel's 'Data files' list. Available: {_workspace_files(session, '.jsonl')}")
    if not file_name:
        if len(session.files) == 1:
            return next(iter(session.files.values()))
        raise ValueError(f"Several files are selected; pass file_name, one of {list(session.files)}")
    name = os.path.basename(file_name)
    if name not in session.files:
        raise ValueError(f"'{file_name}' is not a selected file. Selected: {list(session.files)}")
    return session.files[name]


def _ctx(runtime: ToolRuntime) -> AgentContext:
    return runtime.context


def _safe(fn):
    """Return errors to the model as JSON instead of crashing the agent loop."""
    @functools.wraps(fn)  # keeps the signature so @tool builds the right schema
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (ValueError, KeyError, ArtifactError, FileNotFoundError, TimeoutError) as exc:
            return _json({"error": str(exc)})
    return wrapper


def condense_report(report: dict) -> dict:
    """The parts of a run report an LLM needs (fills and the equity curve are summarized)."""
    acct = report.get("account", {})
    curve = report.get("equity_curve") or []
    return {
        "report_file": report.get("report_file"), "strategy": report.get("strategy"), "data_file": report.get("data_file"),
        "status": report.get("status"), "error": report.get("error"), "speed": report.get("speed"),
        "coverage_of_recording": report.get("replay", {}).get("coverage"), "account": acct,
        "starting_balance": report.get("starting_balance"), "max_drawdown": report.get("max_drawdown"),
        "per_market": report.get("per_market"), "orders_rejected": report.get("orders_rejected"),
        "equity_first_last": [curve[0], curve[-1]] if curve else None,
        "first_fills": report.get("fills", [])[:12],
        "console_tail": (report.get("console_tail") or [])[-30:],
        "assumptions": report.get("assumptions"),
    }


# --------------------------------------------------------------------------- market data

@tool
@_safe
def list_selected_data_files(runtime: ToolRuntime) -> str:
    """List the market-data files the user selected for this conversation (name and size)."""
    s = _ctx(runtime).session
    return _json([{"file_name": n, "size_mb": round(os.path.getsize(p) / 1e6, 2)} for n, p in s.files.items()])


@tool
@_safe
def profile_market_data(runtime: ToolRuntime, file_name: str | None = None) -> str:
    """Profile one selected file: line/event counts, time range, tickers, and per-ticker headline
    stats (mid range, time-weighted spread and imbalance, volume added/removed). Start here."""
    return _json(mdmod.profile(mdmod.load_market_data(_resolve(_ctx(runtime).session, file_name))))


@tool
@_safe
def calculate_spread_statistics(runtime: ToolRuntime, file_name: str | None = None, ticker: str | None = None) -> str:
    """Bid/ask spread statistics in cents (time-weighted mean, percentiles, % time per spread bucket)
    for one selected file, optionally a single ticker."""
    md = mdmod.load_market_data(_resolve(_ctx(runtime).session, file_name))
    return _json(mdmod.spread_statistics(md, ticker))


@tool
@_safe
def calculate_orderbook_imbalance(runtime: ToolRuntime, file_name: str | None = None, ticker: str | None = None,
                                  horizon_seconds: int = 10) -> str:
    """Measure whether top-of-book imbalance at time t relates to the midpoint change over the next
    horizon_seconds. Returns correlations (full, first 70%, last 30%) and per-quintile future moves.
    Sampled without look-ahead."""
    md = mdmod.load_market_data(_resolve(_ctx(runtime).session, file_name))
    return _json(mdmod.imbalance_analysis(md, ticker, horizon_seconds))


@tool
@_safe
def sample_market_windows(runtime: ToolRuntime, file_name: str | None = None, ticker: str | None = None,
                          count: int = 5,
                          criteria: Literal["largest_move", "widest_spread", "most_active",
                                            "strongest_imbalance", "evenly_spaced", "random"] = "largest_move",
                          window_seconds: int = 60) -> str:
    """Return summaries of up to 20 fixed time windows (mid open/close/high/low, spread, imbalance,
    activity) chosen by a criterion. Use to inspect representative or extreme periods."""
    md = mdmod.load_market_data(_resolve(_ctx(runtime).session, file_name))
    return _json(mdmod.sample_windows(md, ticker, count, criteria, window_seconds))


@tool
@_safe
def compare_files(runtime: ToolRuntime, file_names: list[str]) -> str:
    """Side-by-side headline statistics for two or more selected files."""
    s = _ctx(runtime).session
    return _json(mdmod.compare([mdmod.load_market_data(_resolve(s, n)) for n in file_names]))


@tool
@_safe
def retrieve_market_context(runtime: ToolRuntime, query: str, k: int = 6, file_name: str | None = None,
                            ticker: str | None = None) -> str:
    """Search the session's retrieval index of text summaries (file overviews, ticker summaries and
    ~5-minute window summaries tagged e.g. 'large move', 'wide spread', 'bid heavy', 'most active').
    Use it to find WHERE something happened; use the calculate_* tools for exact numbers."""
    s = _ctx(runtime).session
    if file_name:
        _resolve(s, file_name)
    docs = s.get_index().retrieve(query, k=k, file=os.path.basename(file_name) if file_name else None, ticker=ticker)
    return _json([{"text": d.page_content, "metadata": d.metadata} for d in docs])


# --------------------------------------------------------------------------- the user's strategies and results

@tool
@_safe
def list_workspace_strategy_files(runtime: ToolRuntime) -> str:
    """List the user's own Python strategy files (.py) in their workspace folder (name and size).
    Use read_workspace_strategy_file to read one."""
    s = _ctx(runtime).session
    return _json([{"file_name": f, "size_bytes": os.path.getsize(os.path.join(s.workspace_dir, f))}
                  for f in _workspace_files(s, ".py")])


@tool
@_safe
def read_workspace_strategy_file(runtime: ToolRuntime, file_name: str) -> str:
    """Read one of the user's own Python strategy files (.py) from their workspace folder, by file
    name, e.g. to review or improve it. Read-only. To propose changes, save an improved version with
    create_artifact (the original is never modified)."""
    path = _workspace_path(_ctx(runtime).session, file_name, ".py")
    if os.path.getsize(path) > MAX_STRATEGY_FILE_BYTES:
        raise ValueError(f"'{file_name}' is too large to read (> {MAX_STRATEGY_FILE_BYTES} bytes)")
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        return fh.read()


@tool
@_safe
def list_run_reports(runtime: ToolRuntime, strategy: str | None = None) -> str:
    """List saved strategy run reports (newest first): strategy, data file, status, P&L, fees, fills,
    max drawdown. Optionally filter by strategy file name. Read one with read_run_report."""
    items = runs.list_reports(200)
    if strategy:
        items = [r for r in items if r.get("strategy") == os.path.basename(strategy)]
    return _json(items[:40])


@tool
@_safe
def read_run_report(runtime: ToolRuntime, report_file: str) -> str:
    """Read one run report (from list_run_reports): account summary, P&L, fees, drawdown, per-market
    results, first fills, the strategy's console output and the simulator's fill assumptions."""
    path = _workspace_path(_ctx(runtime).session, report_file, ".json", "runs")
    report = runs.load_report(path)
    report["report_file"] = os.path.basename(path)
    return _json(condense_report(report))


# --------------------------------------------------------------------------- building and testing

@tool
@_safe
def get_strategy_template(template: Literal["starter", "orderbook_imbalance", "cross_market_arbitrage",
                                            "ml_direction"]) -> str:
    """Return a tested strategy file to adapt. All templates are written like live Kalshi bots
    (orderbook_delta + fill websocket channels, POST /portfolio/events/orders) and run against the
    simulator unchanged: 'starter' (plumbing only), 'orderbook_imbalance' (momentum on one-sided books),
    'cross_market_arbitrage' (moneyline YES + spread NO < $1), 'ml_direction' (online logistic regression,
    no look-ahead). Keep the plumbing above the Strategy class; change the Strategy class."""
    if template not in TEMPLATE_NAMES:
        raise ValueError(f"template must be one of {TEMPLATE_NAMES}")
    with open(os.path.join(STRATEGY_TEMPLATES, f"{template}.py"), "r", encoding="utf-8") as fh:
        return fh.read()


@tool
@_safe
def create_artifact(runtime: ToolRuntime, filename: str, content: str,
                    artifact_type: Literal["python_strategy", "ml_strategy", "analysis_report",
                                           "experiment_plan", "data_report"],
                    description: str) -> str:
    """Save a generated file (strategy script, report, plan) to the sandboxed generated-artifacts
    folder and show it to the user as an artifact card. Only a plain file name is accepted; it is
    sanitized and never overwrites an existing file. The user decides whether to add it to their
    workspace."""
    c = _ctx(runtime)
    art = c.artifacts.create(c.session.id, filename, content, artifact_type, description)
    c.session.turn_artifacts.append(art.id)
    out = {"artifact_id": art.id, "filename": art.filename, "type": art.type, "size_bytes": art.size_bytes}
    if art.filename.endswith(".py"):
        out["validation"] = validate_source(content, art.filename)
    return _json(out)


@tool
@_safe
def validate_python_artifact(runtime: ToolRuntime, artifact_id: str) -> str:
    """Static checks on a generated Python artifact: syntax, compile, forbidden imports/calls, and
    whether imports are installed. Does not execute the code."""
    c = _ctx(runtime)
    art = c.artifacts.get(artifact_id)
    if art.session_id != c.session.id or not art.filename.endswith(".py"):
        raise ValueError("artifact_id must be a Python artifact from this session")
    return _json(validate_source(c.artifacts.read(artifact_id), art.filename))


@tool
@_safe
def run_strategy_test(runtime: ToolRuntime, strategy: str, file_name: str | None = None,
                      timeout_seconds: int = 300) -> str:
    """Backtest a strategy on one selected data file with the simulator (headless, Max speed, lockstep).
    `strategy` is either an artifact_id from this session or the name of a .py file in the user's
    workspace. Returns the run report summary (P&L, fees, drawdown, fills, console); the full report is
    saved in the workspace's runs/ folder so the user sees it too."""
    c = _ctx(runtime)
    if c.loop is None:
        raise ValueError("Strategy tests are not available in this context")
    if strategy.endswith(".py"):
        path = _workspace_path(c.session, strategy, ".py")
    else:
        art = c.artifacts.get(strategy)
        if art.session_id != c.session.id or not art.filename.endswith(".py"):
            raise ValueError("strategy must be a Python artifact_id from this session or a workspace .py file")
        check = validate_source(c.artifacts.read(art.id), art.filename)
        if not check["ok"]:
            return _json({"status": "rejected", "validation": check})
        path = art.path
    data = _resolve(c.session, file_name)
    timeout = max(30, min(int(timeout_seconds), MAX_TEST_SECONDS))
    future = asyncio.run_coroutine_threadsafe(runs.run_to_completion(path, data, timeout), c.loop)
    report = future.result(timeout + 30)
    if "run_id" in report:
        report["report_file"] = next((r["report_file"] for r in runs.list_reports(20)
                                      if r.get("run_id") == report["run_id"]), None)
        return _json(condense_report(report))
    return _json(report)


ALL_TOOLS = [
    list_selected_data_files,
    profile_market_data,
    calculate_spread_statistics,
    calculate_orderbook_imbalance,
    sample_market_windows,
    compare_files,
    retrieve_market_context,
    list_workspace_strategy_files,
    read_workspace_strategy_file,
    list_run_reports,
    read_run_report,
    get_strategy_template,
    create_artifact,
    validate_python_artifact,
    run_strategy_test,
]

# Short, human-readable activity labels shown in the panel while a tool runs.
TOOL_LABELS = {
    "list_selected_data_files": "Listing selected data files...",
    "profile_market_data": "Profiling selected file...",
    "calculate_spread_statistics": "Calculating spread statistics...",
    "calculate_orderbook_imbalance": "Measuring order-book imbalance vs. future moves...",
    "sample_market_windows": "Sampling market windows...",
    "compare_files": "Comparing files...",
    "retrieve_market_context": "Retrieving relevant market windows...",
    "list_workspace_strategy_files": "Listing your strategy files...",
    "read_workspace_strategy_file": "Reading your strategy file...",
    "list_run_reports": "Listing run reports...",
    "read_run_report": "Reading run report...",
    "get_strategy_template": "Loading strategy template...",
    "create_artifact": "Generating artifact...",
    "validate_python_artifact": "Validating Python artifact...",
    "run_strategy_test": "Backtesting strategy in the simulator...",
}
