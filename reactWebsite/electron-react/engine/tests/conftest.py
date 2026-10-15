"""Shared fixtures. Every test runs against an isolated settings file and workspace."""

import json
import os
import socket
import sys
import threading
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from sample_data import generate  # noqa: E402

from engine import settings  # noqa: E402

DATA_FILE = "synthetic_market.jsonl"


@pytest.fixture(scope="session")
def workspace(tmp_path_factory):
    """A workspace holding one synthetic recording (~20 minutes, 2 markets)."""
    ws = tmp_path_factory.mktemp("workspace")
    generate(str(ws / DATA_FILE), minutes=20, seed=3)
    return ws


@pytest.fixture(scope="session")
def data_path(workspace):
    return str(workspace / DATA_FILE)


@pytest.fixture(scope="session", autouse=True)
def isolated_settings(tmp_path_factory, workspace):
    path = tmp_path_factory.mktemp("settings") / "settings.local.json"
    path.write_text(json.dumps({"workspace_dir": str(workspace), "secret_dir": str(path.parent / "no-secret")}))
    settings.set_path(str(path))
    return path


def write_jsonl(path, lines):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for obj in lines:
            fh.write((obj if isinstance(obj, str) else json.dumps(obj)) + "\n")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def live_server():
    """The real engine app served by uvicorn on a free port; strategy processes connect to it."""
    import uvicorn

    from engine import server
    from engine.strategies import runner

    port = _free_port()
    runner.BASE_URL, runner.HOST, runner.PORT = f"http://127.0.0.1:{port}", "127.0.0.1", port
    config = uvicorn.Config(server.app, host="127.0.0.1", port=port, log_level="warning", lifespan="off")
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    thread.join(10)
