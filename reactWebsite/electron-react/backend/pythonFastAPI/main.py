from fastapi import FastAPI, WebSocket
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import json
import requests
from config.config import ENVIRONMENTS

app = FastAPI()
SCHEDULE_FILE = Path("../scheduler/scheduler.json")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Item(BaseModel):
    name: str
    price: float
    is_offer: bool = None

class ScheduledEvent(BaseModel):
    market_tickers: str
    scheduled_ahead: str
    date_input: str
    time_input: str
    time_ampm: str
    save_dir: str
    iso_time: str
    status: str

class SearchQuerry(BaseModel):
    query: str


@app.get("/")
async def root():
    return {"message": "Hello from python fastAPI "}



@app.get("/health")
async def health():
    return {"message": "Hello from python fastAPI "}



@app.get("/items/{item_id}")
def read_item(item_id: int, q: str = None):
    return {"item_id": item_id,"q":q}



@app.put("items/{item_id}")
def save_item(item_id: int, item: Item):
    return {"item_name": item_id,"item_info":item}



@app.get("/scheduledEvents")
def get_events():
    with open(SCHEDULE_FILE, "r") as f:
        d = json.load(f)
    return d



@app.post("/scheduledEvents")
def create_event(event: ScheduledEvent):
    if SCHEDULE_FILE.exists():
        with open(SCHEDULE_FILE, "r") as f:
            events = json.load(f)
    else:
        events = {}

    event_id = str(max(map(int, events.keys()), default=0) + 1)

    events[event_id] = event.model_dump()

    with open(SCHEDULE_FILE, "w") as f:
        json.dump(events, f, indent=2)

    return {"success": True, "id": event_id}


def _summary(m: dict) -> dict:
    bid = m.get("yes_bid_dollars")
    ask = m.get("yes_ask_dollars")

    if bid is None and m.get("yes_bid_cents") is not None:
        bid = f"{m['yes_bid_cents'] / 100:.4f}"

    if ask is None and m.get("yes_ask_cents") is not None:
        ask = f"{m['yes_ask_cents'] / 100:.4f}"

    return {
        "ticker": m.get("ticker"),
        "event_ticker": m.get("event_ticker"),
        "title": m.get("title") or m.get("subtitle") or "",
        "subtitle": m.get("yes_sub_title") or m.get("subtitle") or "",
        "status": m.get("status"),
        "close_time": m.get("close_time") or m.get("close_ts"),
        "yes_bid_dollars": bid,
        "yes_ask_dollars": ask,
        "volume": m.get("volume_fp", m.get("volume")),
    }

@app.post("/kalshiMarketSearch")
def search_markets(query: SearchQuerry):
    base = ENVIRONMENTS["production"]["rest"]
    limit = 25

    q = query.query.strip().upper()
    if not q:
        return {"query": query, "kind": None, "markets": []}
    r = requests.get(f"{base}/markets/{q}", timeout=15)
    if r.status_code == 200 and r.json().get("market"):
        print(r.json())
        return {"query": q, "kind": "market", "markets": [_summary(r.json()["market"])]}
    
    r = requests.get(f"{base}/markets", params={"event_ticker": q, "limit": limit}, timeout=15)
    if r.status_code == 200 and r.json().get("markets"):
        print(r.json())
        return {"query": q, "kind": "event", "markets": [_summary(m) for m in r.json()["markets"]]}
        
    r = requests.get(f"{base}/markets", params={"series_ticker": q, "status": "open", "limit": limit}, timeout=15)
    if r.status_code == 200 and r.json().get("markets"):
        print(r.json())
        return {"query": q, "kind": "series", "markets": [_summary(m) for m in r.json()["markets"]]}
    
    ## PUBLIC URL, NOT KALSHI'S DOCUMENTATION
    ## SEARCHES BY KEYWORD / GENERAL TYPING SEARCHES
    ## REQUIRES COOKIE AUTHENTICATION FOR RESPONSES 
    # r = requests.get("https://pro.kalshi.com/api/markets/search",params={"q": q, "page_size": limit},timeout=15)
    # if r.status_code == 200 and r.json().get("groups"):
    #     groups = r.json().get("groups", [])
    #     markets = [_summary(m) for group in groups for m in group.get("markets", [])]
    #     return { "query": q, "kind": "keyword", "markets": markets}
    
    r.raise_for_status()
    return {"query": q, "kind": None, "markets": []}