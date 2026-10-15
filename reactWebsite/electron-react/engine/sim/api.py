"""HTTP + websocket routes of the simulator.

Kalshi-compatible API (what strategies talk to), for the Replayer's session:
    REST       http://127.0.0.1:8000/trade-api/v2/...
    websocket  ws://127.0.0.1:8000/trade-api/ws/v2
and for any other session (headless backtests):
    http://127.0.0.1:8000/sims/{session_id}/trade-api/v2/...   ws://.../sims/{session_id}/trade-api/ws/v2

Replay control used by the Replayer panel:
    /replay/{session_id}/load | play | pause | seek | reset | state     and websocket /replay/{session_id}/stream
"""

from __future__ import annotations

import asyncio
import os

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .. import settings
from ..marketdata.book import PRICE_SCALE, to_units
from .exchange import OrderRejected
from .session import SessionManager, SimSession, sessions

kalshi = APIRouter(tags=["kalshi-sim"])
control = APIRouter(prefix="/replay", tags=["replay"])

PREFIXES = ["/trade-api", "/sims/{session_id}/trade-api"]


def _session(session_id: str | None) -> SimSession:
    sid = session_id or SessionManager.REPLAYER
    try:
        s = sessions.get(sid)
    except KeyError:
        raise HTTPException(404, f"Unknown simulator session {sid}")
    if s.recording is None or s.exchange is None:
        raise HTTPException(409, "No data file is loaded in the Replayer")
    return s


def _kalshi_error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def _check_signed(request: Request, s: SimSession) -> None:
    if "kalshi-access-key" not in {k.lower() for k in request.headers.keys()}:
        s.note_unsigned()


def _event_ticker(ticker: str) -> str:
    return ticker.rsplit("-", 1)[0] if "-" in ticker else ticker


def _market(s: SimSession, ticker: str) -> dict:
    top = s.books[ticker].top()
    return {
        "ticker": ticker, "event_ticker": _event_ticker(ticker), "status": "active" if s.state != "ended" else "closed",
        "yes_bid_dollars": top["best_yes_bid_dollars"], "yes_ask_dollars": top["best_yes_ask_dollars"],
        "no_bid_dollars": top["best_no_bid_dollars"], "no_ask_dollars": top["best_no_ask_dollars"],
        "title": ticker, "market_type": "binary",
    }


# --------------------------------------------------------------------------- Kalshi REST

def _add(path: str, methods: list[str], endpoint, status_code: int = 200) -> None:
    for prefix in PREFIXES:
        kalshi.add_api_route(prefix + path, endpoint, methods=methods, status_code=status_code)


async def exchange_status(session_id: str | None = None):
    s = sessions.sessions.get(session_id or SessionManager.REPLAYER)
    active = bool(s and s.recording and s.state != "ended")
    return {"exchange_active": active, "trading_active": active}


async def get_markets(request: Request, session_id: str | None = None, tickers: str | None = None,
                      event_ticker: str | None = None, status: str | None = None, limit: int = 100):
    s = _session(session_id)
    _check_signed(request, s)
    names = list(s.books)
    if tickers:
        wanted = set(tickers.split(","))
        names = [t for t in names if t in wanted]
    if event_ticker:
        names = [t for t in names if _event_ticker(t) == event_ticker]
    markets = [_market(s, t) for t in names]
    if status in ("open", "active"):
        markets = [m for m in markets if m["status"] == "active"]
    return {"markets": markets[:limit], "cursor": ""}


async def get_market(ticker: str, request: Request, session_id: str | None = None):
    s = _session(session_id)
    _check_signed(request, s)
    if ticker not in s.books:
        return _kalshi_error(404, "not_found", f"Market {ticker} is not in the replayed recording")
    return {"market": _market(s, ticker)}


async def get_orderbook(ticker: str, request: Request, session_id: str | None = None, depth: int = 0):
    s = _session(session_id)
    _check_signed(request, s)
    if ticker not in s.books:
        return _kalshi_error(404, "not_found", f"Market {ticker} is not in the replayed recording")
    return {"orderbook_fp": s.books[ticker].levels_fp(depth)}


async def get_balance(request: Request, session_id: str | None = None):
    s = _session(session_id)
    _check_signed(request, s)
    ex = s.exchange
    return {"balance": int(round(ex.cash * 100)), "portfolio_value": int(round(ex.equity() * 100)),
            "updated_ts": s.clock_ts // 1000}


async def get_positions(request: Request, session_id: str | None = None, ticker: str | None = None):
    s = _session(session_id)
    _check_signed(request, s)
    positions = [p for p in s.exchange.kalshi_positions() if not ticker or p["ticker"] == ticker]
    return {"market_positions": positions, "event_positions": [], "cursor": ""}


async def get_fills(request: Request, session_id: str | None = None, ticker: str | None = None,
                    order_id: str | None = None, limit: int = 100):
    s = _session(session_id)
    _check_signed(request, s)
    fills = [f.kalshi() for f in reversed(s.exchange.fills)
             if (not ticker or f.ticker == ticker) and (not order_id or f.order_id == order_id)]
    return {"fills": fills[:limit], "cursor": ""}


async def get_orders(request: Request, session_id: str | None = None, ticker: str | None = None,
                     status: str | None = None, limit: int = 100):
    s = _session(session_id)
    _check_signed(request, s)
    orders = [o.kalshi() for o in reversed(list(s.exchange.orders.values()))
              if (not ticker or o.ticker == ticker) and (not status or o.status == status)]
    return {"orders": orders[:limit], "cursor": ""}


async def get_order(order_id: str, request: Request, session_id: str | None = None):
    s = _session(session_id)
    _check_signed(request, s)
    order = s.exchange.orders.get(order_id)
    if order is None:
        return _kalshi_error(404, "not_found", "Order not found")
    return {"order": order.kalshi()}


def _submit(s: SimSession, **kw):
    try:
        order = s.exchange.submit(now_ms=s.clock_ts, **kw)
    except OrderRejected as exc:
        s.log(f"[sim] order rejected ({exc.code}): {exc}")
        return None, _kalshi_error(400, exc.code, str(exc))
    filled = order.filled
    s.log(f"[sim] {order.side} {order.ticker} {order.count:g} @ {order.price / PRICE_SCALE:.4f} "
          f"-> {order.status}, filled {filled:g}")
    return order, None


async def _flush_after_order(s: SimSession) -> None:
    await s._flush_all()  # deliver fill messages right away


async def create_order_v2(request: Request, session_id: str | None = None):
    """POST /portfolio/events/orders - Kalshi Create Order (V2): side bid/ask on the YES book."""
    s = _session(session_id)
    _check_signed(request, s)
    body = await request.json()
    try:
        price = to_units(body["price"])
        count = float(body["count"])
        side = str(body["side"])
    except (KeyError, TypeError, ValueError):
        return _kalshi_error(400, "invalid_parameters", "ticker, side, count and price are required")
    order, err = _submit(s, ticker=str(body.get("ticker")), side=side, price=price, count=count,
                         time_in_force=body.get("time_in_force", "good_till_canceled"),
                         post_only=bool(body.get("post_only", False)), client_order_id=body.get("client_order_id"))
    if err:
        return err
    await _flush_after_order(s)
    out = {"order_id": order.order_id, "client_order_id": order.client_order_id,
           "fill_count": f"{order.filled:.2f}", "remaining_count": f"{order.remaining:.2f}", "ts_ms": s.clock_ts}
    if order.fills:
        k = order.kalshi()
        out["average_fill_price"] = k["average_fill_price"]
        out["average_fee_paid"] = f"{sum(f.fee for f in order.fills) / order.filled:.6f}"
    return JSONResponse(status_code=201, content=out)


async def create_order_classic(request: Request, session_id: str | None = None):
    """POST /portfolio/orders - classic Kalshi order: side yes/no + action buy/sell, prices in cents."""
    s = _session(session_id)
    _check_signed(request, s)
    body = await request.json()
    try:
        side, action = str(body["side"]), str(body.get("action", "buy"))
        count = float(body["count"])
        if body.get("type") == "market":
            yes_limit = PRICE_SCALE - 100 if (side, action) in (("yes", "buy"), ("no", "sell")) else 100
        elif "yes_price" in body or "yes_price_dollars" in body:
            yes_limit = int(body["yes_price"]) * 100 if "yes_price" in body else to_units(body["yes_price_dollars"])
        else:
            no = int(body["no_price"]) * 100 if "no_price" in body else to_units(body["no_price_dollars"])
            yes_limit = PRICE_SCALE - no
    except (KeyError, TypeError, ValueError):
        return _kalshi_error(400, "invalid_parameters", "side, action, count and a yes/no price are required")
    book_side = "bid" if (side, action) in (("yes", "buy"), ("no", "sell")) else "ask"
    tif = body.get("time_in_force") or ("immediate_or_cancel" if body.get("type") == "market" else "good_till_canceled")
    order, err = _submit(s, ticker=str(body.get("ticker")), side=book_side, price=yes_limit, count=count,
                         time_in_force=tif, post_only=bool(body.get("post_only", False)),
                         client_order_id=body.get("client_order_id"))
    if err:
        return err
    await _flush_after_order(s)
    return JSONResponse(status_code=201, content={"order": order.kalshi()})


async def cancel_order(order_id: str, request: Request, session_id: str | None = None):
    s = _session(session_id)
    _check_signed(request, s)
    try:
        order = s.exchange.cancel(order_id)
    except OrderRejected as exc:
        return _kalshi_error(404, exc.code, str(exc))
    return {"order": order.kalshi(), "order_id": order.order_id, "reduced_by_fp": f"{order.remaining:.2f}"}


_add("/v2/exchange/status", ["GET"], exchange_status)
_add("/v2/markets", ["GET"], get_markets)
_add("/v2/markets/{ticker}", ["GET"], get_market)
_add("/v2/markets/{ticker}/orderbook", ["GET"], get_orderbook)
_add("/v2/portfolio/balance", ["GET"], get_balance)
_add("/v2/portfolio/positions", ["GET"], get_positions)
_add("/v2/portfolio/fills", ["GET"], get_fills)
_add("/v2/portfolio/orders", ["GET"], get_orders)
_add("/v2/portfolio/orders", ["POST"], create_order_classic)
_add("/v2/portfolio/orders/{order_id}", ["GET"], get_order)
_add("/v2/portfolio/orders/{order_id}", ["DELETE"], cancel_order)
_add("/v2/portfolio/events/orders", ["POST"], create_order_v2)
_add("/v2/portfolio/events/orders/{order_id}", ["DELETE"], cancel_order)


# --------------------------------------------------------------------------- Kalshi websocket

async def _feed(ws: WebSocket, session_id: str | None) -> None:
    sid = session_id or SessionManager.REPLAYER
    s = sessions.sessions.get(sid)
    await ws.accept()
    if s is None or s.recording is None:
        await ws.send_json({"type": "error", "msg": {"code": 9, "msg": "No data file is loaded in the Replayer"}})
        await ws.close()
        return
    if "kalshi-access-key" not in {k.lower() for k in ws.headers.keys()}:
        s.note_unsigned()
    client = s.connect(ws.send_json)
    s.log("[sim] strategy connected to the market data feed")
    try:
        while True:
            await s.handle_command(client, await ws.receive_text())
    except WebSocketDisconnect:
        pass
    finally:
        s.disconnect(client)
        s.log("[sim] strategy disconnected")


@kalshi.websocket("/trade-api/ws/v2")
async def feed_default(ws: WebSocket):
    await _feed(ws, None)


@kalshi.websocket("/sims/{session_id}/trade-api/ws/v2")
async def feed_session(ws: WebSocket, session_id: str):
    await _feed(ws, session_id)


# --------------------------------------------------------------------------- Replayer control

class LoadRequest(BaseModel):
    file: str        # file name in the workspace, or an absolute path


class PlayRequest(BaseModel):
    speed: float | None = 1.0    # None = Max


class SeekRequest(BaseModel):
    ts_ms: int | None = None
    fraction: float | None = None


def _resolve_data_file(name: str) -> str:
    path = name if os.path.isabs(name) else os.path.join(settings.workspace_dir(), name)
    path = os.path.abspath(path)
    if not path.lower().endswith(".jsonl") or not os.path.isfile(path):
        raise HTTPException(400, f"Data file not found: {name}")
    return path


def _control_session(session_id: str) -> SimSession:
    try:
        return sessions.get(session_id)
    except KeyError:
        raise HTTPException(404, "Unknown session")


@control.post("/{session_id}/load")
async def load(session_id: str, req: LoadRequest):
    s = _control_session(session_id)
    if s.clients:
        raise HTTPException(409, "Stop the running strategy first")
    path = _resolve_data_file(req.file)
    try:
        await s.load(path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, str(exc))
    return s.state_payload()


@control.post("/{session_id}/play")
async def play(session_id: str, req: PlayRequest):
    s = _control_session(session_id)
    if req.speed is not None and req.speed <= 0:
        raise HTTPException(400, "speed must be positive (or null for Max)")
    try:
        await s.play(req.speed)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return s.state_payload()


@control.post("/{session_id}/pause")
async def pause(session_id: str):
    s = _control_session(session_id)
    await s.pause()
    return s.state_payload()


@control.post("/{session_id}/seek")
async def seek(session_id: str, req: SeekRequest):
    s = _control_session(session_id)
    if s.recording is None:
        raise HTTPException(400, "Load a data file first")
    rec = s.recording
    ts = req.ts_ms if req.ts_ms is not None else rec.start_ts + (req.fraction or 0) * (rec.end_ts - rec.start_ts)
    was_playing = s.state == "playing"
    await s.pause()
    try:
        s.seek(int(ts))
    except ValueError as exc:
        raise HTTPException(409, str(exc))
    if was_playing:
        await s.play(s.speed)
    return s.state_payload()


@control.post("/{session_id}/reset")
async def reset(session_id: str):
    s = _control_session(session_id)
    if s.clients:
        raise HTTPException(409, "Stop the running strategy first")
    await s.pause()
    s.reset()
    return s.state_payload()


@control.get("/{session_id}/state")
async def state(session_id: str):
    return _control_session(session_id).state_payload()


@control.websocket("/{session_id}/stream")
async def stream(ws: WebSocket, session_id: str):
    """Pushes the session state ~5 times a second for the Replayer panel."""
    from ..strategies.runner import runs  # local import: the runner depends on this module's sessions
    await ws.accept()
    try:
        while True:
            s = sessions.sessions.get(session_id)
            payload = s.state_payload() if s else {"session": session_id, "state": "empty"}
            run = next((r for r in sorted(runs.runs.values(), key=lambda r: -r.started) if r.session_id == session_id), None)
            payload["run"] = run.public() if run else None
            await ws.send_json(payload)
            await asyncio.sleep(0.2)
    except (WebSocketDisconnect, RuntimeError):
        pass
