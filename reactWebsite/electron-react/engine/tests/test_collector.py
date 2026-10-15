"""Recording jobs against a fake Kalshi websocket."""

import asyncio
import json
import time

from engine.collector.jobs import Job, default_filename, run_job, subscribe_command


class FakeCreds:
    def headers(self, method, path):
        assert method == "GET" and path == "/trade-api/ws/v2"
        return {"KALSHI-ACCESS-KEY": "k"}


class FakeWS:
    def __init__(self, messages, fail_after=None):
        self.messages = list(messages)
        self.sent = []
        self.fail_after = fail_after

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def send(self, text):
        self.sent.append(json.loads(text))

    async def recv(self):
        if self.fail_after is not None and not self.messages:
            raise OSError("socket closed")
        if not self.messages:
            await asyncio.sleep(10)
        return self.messages.pop(0)


def msgs(n):
    out = [json.dumps({"type": "subscribed", "id": 1, "msg": {"channel": "orderbook_delta", "sid": 1}})]
    out += [json.dumps({"type": "orderbook_delta", "sid": 1, "seq": i, "msg": {
        "market_ticker": "A-B", "price_dollars": "0.5000", "delta_fp": "1.00", "side": "yes", "ts_ms": i}})
        for i in range(n)]
    return out


def test_filename_and_subscribe_command():
    assert default_filename(["KXA-EV-X", "KXA-EV-Y"], 0).startswith("KXA-EV_")
    assert default_filename(["ONE-T"], 0).startswith("ONE-T_")
    assert subscribe_command(["A"])["params"] == {"channels": ["orderbook_delta"], "market_ticker": "A"}
    assert subscribe_command(["A", "B"])["params"]["market_tickers"] == ["A", "B"]


def test_job_records_until_stop_time(tmp_path):
    ws = FakeWS(msgs(5))
    job = Job(tickers=["A-B"], env="demo", save_path=str(tmp_path / "out.jsonl"), stop_at=time.time() + 1.5)
    asyncio.run(run_job(job, FakeCreds(), connect=lambda *a, **k: ws))
    lines = (tmp_path / "out.jsonl").read_text().splitlines()
    assert job.status == "finished" and job.messages == 6 and job.deltas == 5 and len(lines) == 6
    assert ws.sent[0]["cmd"] == "subscribe"


def test_job_reconnects_and_appends(tmp_path):
    sockets = [FakeWS(msgs(2), fail_after=True), FakeWS(msgs(3))]
    job = Job(tickers=["A-B"], env="demo", save_path=str(tmp_path / "out.jsonl"), stop_at=time.time() + 3)
    asyncio.run(run_job(job, FakeCreds(), connect=lambda *a, **k: sockets.pop(0)))
    assert job.reconnects == 1 and job.deltas == 5
    assert len((tmp_path / "out.jsonl").read_text().splitlines()) == 7


def test_exchange_error_stops_the_job(tmp_path):
    err = json.dumps({"type": "error", "id": 1, "msg": {"code": 6, "msg": "Unknown market ticker"}})
    job = Job(tickers=["A-B"], env="demo", save_path=str(tmp_path / "out.jsonl"))
    asyncio.run(run_job(job, FakeCreds(), connect=lambda *a, **k: FakeWS([err])))
    assert job.status == "error" and "Unknown market" in job.error


def test_scheduled_job_can_be_cancelled_before_start(tmp_path):
    async def go():
        job = Job(tickers=["A-B"], env="demo", save_path=str(tmp_path / "x.jsonl"), start_at=time.time() + 60)
        task = asyncio.create_task(run_job(job, FakeCreds(), connect=lambda *a, **k: FakeWS([])))
        await asyncio.sleep(0.1)
        assert job.status == "scheduled"
        job._stop.set()
        await task
        return job
    job = asyncio.run(go())
    assert job.status == "stopped" and not (tmp_path / "x.jsonl").exists()
