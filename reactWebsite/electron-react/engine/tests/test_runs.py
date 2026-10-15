"""End-to-end strategy runs: real strategy processes against a real engine server."""

import os
import shutil
import time

import httpx
import pytest

from conftest import DATA_FILE
from engine.paths import TEMPLATES_DIR

TEMPLATES = ["starter", "orderbook_imbalance", "cross_market_arbitrage", "ml_direction"]


def wait_run(base, run_id, timeout=240):
    deadline = time.time() + timeout
    while time.time() < deadline:
        run = httpx.get(f"{base}/strategy/runs/{run_id}").json()
        if run["status"] in ("completed", "failed", "stopped"):
            return run
        time.sleep(0.3)
    raise AssertionError(f"run {run_id} did not finish")


def start(base, strategy, **kw):
    r = httpx.post(f"{base}/strategy/runs", json={"strategy": strategy, "data_file": DATA_FILE, **kw}, timeout=60)
    assert r.status_code == 200, r.text
    return r.json()


def report(base, run):
    return httpx.get(f"{base}/strategy/reports/{run['report_file']}").json()


@pytest.fixture(scope="module", autouse=True)
def strategies(workspace):
    for name in TEMPLATES:
        shutil.copyfile(os.path.join(TEMPLATES_DIR, "strategies", f"{name}.py"), workspace / f"{name}.py")
    (workspace / "crashes.py").write_text("raise SystemExit('boom')\n")
    (workspace / "sleeper.py").write_text(
        (workspace / "starter.py").read_text().replace("strategy.on_book(ticker", "time.sleep(0.01); strategy.on_book(ticker"))


@pytest.mark.parametrize("template", TEMPLATES)
def test_every_template_runs_headless_to_the_end(live_server, template):
    run = wait_run(live_server, start(live_server, f"{template}.py", mode="headless")["id"])
    assert run["status"] == "completed", run
    rep = report(live_server, run)
    assert rep["replay"]["coverage"] == 1.0
    assert not any("Traceback" in line for line in rep["console_tail"]), rep["console_tail"][-20:]
    assert any("strategy started (sim)" in line for line in rep["console_tail"])


def test_headless_backtests_are_deterministic(live_server):
    a = report(live_server, wait_run(live_server, start(live_server, "orderbook_imbalance.py", mode="headless")["id"]))
    b = report(live_server, wait_run(live_server, start(live_server, "orderbook_imbalance.py", mode="headless")["id"]))
    assert a["account"]["fills"] > 0
    assert a["account"] == b["account"]


def test_replayer_run_at_speed_and_reports(live_server):
    run = wait_run(live_server, start(live_server, "orderbook_imbalance.py", mode="replayer", speed=600)["id"])
    assert run["status"] == "completed"
    reports = httpx.get(f"{live_server}/strategy/reports").json()
    assert reports[0]["run_id"] == run["id"] and reports[0]["coverage"] == 1.0


def test_stop_and_crash(live_server):
    run = start(live_server, "sleeper.py", mode="replayer", speed=1)
    time.sleep(3)
    httpx.post(f"{live_server}/strategy/runs/{run['id']}/stop", timeout=30)
    stopped = wait_run(live_server, run["id"])
    assert stopped["status"] == "stopped" and stopped["report_file"]
    crashed = wait_run(live_server, start(live_server, "crashes.py", mode="headless")["id"])
    assert crashed["status"] == "failed" and "before subscribing" in crashed["error"]
