"""The Kalshi-compatible REST/websocket API and the Replayer controls."""

import pytest
from fastapi.testclient import TestClient

from conftest import DATA_FILE
from engine import server

API = "/trade-api/v2"


@pytest.fixture(scope="module")
def client():
    with TestClient(server.app) as c:
        st = c.post("/replay/replayer/load", json={"file": DATA_FILE}).json()
        assert st["state"] == "ready" and len(st["books"]) == 2
        yield c


def tickers(client):
    return [m["ticker"] for m in client.get(f"{API}/markets").json()["markets"]]


def test_market_data_endpoints(client):
    ts = tickers(client)
    assert len(ts) == 2
    m = client.get(f"{API}/markets/{ts[0]}").json()["market"]
    assert m["status"] == "active" and m["event_ticker"] == ts[0].rsplit("-", 1)[0]
    ob = client.get(f"{API}/markets/{ts[0]}/orderbook", params={"depth": 3}).json()["orderbook_fp"]
    assert len(ob["yes_dollars"]) == 3
    prices = [float(p) for p, _ in ob["yes_dollars"]]
    assert prices == sorted(prices)                      # ascending, best last (as recorded by Kalshi)
    assert client.get(f"{API}/markets/NOPE").status_code == 404
    assert client.get(f"{API}/exchange/status").json()["trading_active"] is True


def test_orders_positions_fills_balance(client):
    client.post("/replay/replayer/reset")
    t = tickers(client)[0]
    ask = client.get(f"{API}/markets/{t}").json()["market"]["yes_ask_dollars"]
    r = client.post(f"{API}/portfolio/events/orders", json={
        "ticker": t, "side": "bid", "count": "2.00", "price": ask, "time_in_force": "immediate_or_cancel",
        "self_trade_prevention_type": "taker_at_cross", "client_order_id": "c1"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["fill_count"] == "2.00" and body["average_fill_price"] == ask
    pos = client.get(f"{API}/portfolio/positions").json()["market_positions"]
    assert pos[0]["ticker"] == t and pos[0]["position_fp"] == "2.00"
    fills = client.get(f"{API}/portfolio/fills").json()["fills"]
    assert fills[0]["action"] == "buy" and fills[0]["post_position_fp"] == "2.00"
    bal = client.get(f"{API}/portfolio/balance").json()
    assert bal["balance"] < 100_000                      # cents, started at $1000

    # Classic endpoint: buy NO at a low price -> rests; then cancel it.
    r = client.post(f"{API}/portfolio/orders", json={"ticker": t, "side": "no", "action": "buy", "count": 1,
                                                     "type": "limit", "no_price": 1})
    assert r.status_code == 201
    order = r.json()["order"]
    assert order["status"] == "resting" and order["side"] == "ask"
    assert client.get(f"{API}/portfolio/orders", params={"status": "resting"}).json()["orders"][0]["order_id"] == order["order_id"]
    assert client.delete(f"{API}/portfolio/orders/{order['order_id']}").json()["order"]["status"] == "canceled"

    bad = client.post(f"{API}/portfolio/events/orders", json={"ticker": t, "side": "bid", "count": "1", "price": "1.50",
                                                              "time_in_force": "good_till_canceled",
                                                              "self_trade_prevention_type": "taker_at_cross"})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "invalid_parameters"
    dup = client.post(f"{API}/portfolio/events/orders", json={"ticker": t, "side": "bid", "count": "1", "price": "0.01",
                                                              "time_in_force": "good_till_canceled",
                                                              "self_trade_prevention_type": "taker_at_cross",
                                                              "client_order_id": "c1"})
    assert dup.json()["error"]["code"] == "duplicate_client_order_id"


def test_websocket_subscribe_snapshot_and_errors(client):
    client.post("/replay/replayer/reset")
    t = tickers(client)
    with client.websocket_connect("/trade-api/ws/v2") as ws:
        ws.send_json({"id": 1, "cmd": "subscribe", "params": {"channels": ["orderbook_delta"], "market_ticker": t[0]}})
        sub = ws.receive_json()
        assert sub["type"] == "subscribed" and sub["msg"]["channel"] == "orderbook_delta"
        snap = ws.receive_json()
        assert snap["type"] == "orderbook_snapshot" and snap["msg"]["market_ticker"] == t[0]
        assert snap["msg"]["yes_dollars_fp"] and snap["seq"] == 1
        ws.send_json({"id": 2, "cmd": "subscribe", "params": {"channels": ["orderbook_delta"], "market_ticker": "BAD"}})
        assert ws.receive_json()["type"] == "error"
        ws.send_json({"id": 3, "cmd": "subscribe", "params": {"channels": ["trade"]}})
        assert "not simulated" in ws.receive_json()["msg"]["msg"]
        # While a strategy is connected the replay cannot be rewound under it.
        assert client.post("/replay/replayer/seek", json={"fraction": 0.5}).status_code == 409


def test_replay_controls(client):
    client.post("/replay/replayer/reset")
    st = client.post("/replay/replayer/seek", json={"fraction": 0.5}).json()
    assert abs(st["progress"] - 0.5) < 0.01 and st["state"] == "ready"
    st = client.post("/replay/replayer/seek", json={"fraction": 1.0}).json()
    assert st["state"] == "ended"
    st = client.post("/replay/replayer/reset").json()
    assert st["progress"] == 0 and st["account"]["fills"] == 0
    assert client.post("/replay/replayer/load", json={"file": "missing.jsonl"}).status_code == 400
    assert client.post("/replay/replayer/load", json={"file": "../secret.jsonl"}).status_code == 400


def test_workspace_settings_and_host_check(client, workspace):
    ws = client.get("/workspace").json()
    assert ws["dir"] == str(workspace) and ws["data_files"][0]["name"] == DATA_FILE
    names = [t["template"] for t in client.get("/workspace/templates").json()]
    assert {"starter", "orderbook_imbalance", "cross_market_arbitrage", "ml_direction"} <= set(names)
    made = client.post("/workspace/strategies", json={"name": "my strat", "template": "starter"})
    assert made.status_code == 200 and made.json()["name"] == "my strat.py"
    assert client.post("/workspace/strategies", json={"name": "my strat", "template": "starter"}).status_code == 409
    assert client.post("/workspace/strategies", json={"name": "../x", "template": "starter"}).status_code == 400
    s = client.put("/settings", json={"changes": {"sim_starting_balance": 500}}).json()
    assert s["sim_starting_balance"] == 500 and "credentials" in s
    assert client.put("/settings", json={"changes": {"kalshi_env": "moon"}}).status_code == 400
    client.put("/settings", json={"changes": {"sim_starting_balance": 1000}})
    assert client.get("/health", headers={"host": "evil.example.com"}).status_code == 400
