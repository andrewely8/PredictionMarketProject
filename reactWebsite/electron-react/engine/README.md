# Engine

The Python service behind the desktop app: FastAPI on `127.0.0.1:8000` (`config.json`). Electron
starts it automatically (`src/main/engine.ts`, using `engine/.venv`). To run it by itself:

```bash
cd reactWebsite/electron-react
engine/.venv/Scripts/python -m uvicorn engine.server:app --host 127.0.0.1 --port 8000
```

It only listens on localhost, rejects non-local `Host` headers, and only the app's own renderer may
call it from a browser context (CORS).

## Modules

| Module | What it does |
|---|---|
| `settings.py` | User settings in `settings.local.json` (git-ignored): workspace, Kalshi keys folder, environment, simulator balance and fees, AI mode |
| `kalshi/` | Kalshi API-key signing (your existing `secret/` layout) and public market search |
| `collector/` | Recording jobs: subscribe to `orderbook_delta`, append raw messages to `.jsonl`, schedule, auto-stop, reconnect with backoff |
| `marketdata/` | `Recording` parses a file once with orjson into numpy arrays (1.46M lines in ~3 s), with book checkpoints for instant seeking. `OrderBook` handles Kalshi's bids-only books (YES ask = 1 − best NO bid) |
| `sim/` | `Exchange` matching engine and account; `SimSession` replay clock plus the websocket feed; `api.py` Kalshi-compatible routes and Replayer controls |
| `strategies/` | Starts strategy processes against a session, waits for them to subscribe, plays, stops, writes reports |
| `research/` | AI assistant: LangChain agent, data/strategy/report tools, BM25 retrieval, sandboxed artifacts, Claude sign-in, packaged Ollama + Qwen |
| `templates/strategies/` | Strategy templates (each is a complete Kalshi-style bot) |

## The simulator (kalshiApiSim)

Strategies talk to it exactly as they would to Kalshi.

| | Replayer session | Any other session (headless backtests) |
|---|---|---|
| REST | `http://127.0.0.1:8000/trade-api/v2` | `http://127.0.0.1:8000/sims/<id>/trade-api/v2` |
| Websocket | `ws://127.0.0.1:8000/trade-api/ws/v2` | `ws://127.0.0.1:8000/sims/<id>/trade-api/ws/v2` |

**REST:**

- `GET /exchange/status`
- `GET /markets`, `GET /markets/{ticker}`, `GET /markets/{ticker}/orderbook?depth=`
- `GET /portfolio/balance` (cents), `GET /portfolio/positions`, `GET /portfolio/fills`
- `GET /portfolio/orders`, `GET /portfolio/orders/{id}`
- `POST /portfolio/events/orders`: Create Order V2. `side` is `bid`/`ask`; `price` and `count` are
  fixed-point strings; `time_in_force` is `good_till_canceled` | `immediate_or_cancel` |
  `fill_or_kill`; also `post_only` and `client_order_id`. Returns `201`.
- `POST /portfolio/orders`: classic orders. `side` is `yes`/`no`, `action` is `buy`/`sell`,
  `yes_price`/`no_price` are in cents, and `type: market` is supported.
- `DELETE /portfolio/events/orders/{id}` and `DELETE /portfolio/orders/{id}`: cancel.
- Errors use Kalshi's shape: `{"error": {"code", "message"}}`.

**Websocket commands:** `subscribe` with `channels` and `market_ticker` / `market_tickers`, and
`unsubscribe`.

| Channel | What you receive |
|---|---|
| `orderbook_delta` | `subscribed`, an `orderbook_snapshot` per market, then `orderbook_delta` messages with the recorded `ts_ms` |
| `fill` | Kalshi-shaped fill messages, including `post_position_fp` |
| `sim_clock` (simulator only) | See lockstep below |

Unsigned requests are accepted. The console notes once that real Kalshi requires the
`KALSHI-ACCESS-*` headers.

**Clock and lockstep.** At a speed of 1×–500×, replay time advances at that multiple of real time
and strategies react live, so their latency matters. At **Max**:

1. A strategy subscribed to `sim_clock` receives `{"type": "sim_clock", "msg": {"tick", "ts_ms"}}`
   after every 250 ms of replay time.
2. Quiet stretches are skipped.
3. The simulator waits for `{"cmd": "sim_ack", "params": {"tick": n}}` before moving on.
4. Orders sent before the ack are matched at that instant.

Backtests are therefore deterministic. A 20-minute recording runs in about 6 s; a 3.5-hour, 1.4M-event
game runs in about 30 s. All templates implement the ack.

**Fill model:**

- **Takers** walk recorded price levels best-first, never past the limit price.
- **Consumed liquidity:** liquidity you have taken is remembered per level, until the recording
  changes that level.
- **Makers:** resting orders fill at their limit when the recorded book crosses them. Queue
  position is ignored, so maker fills are optimistic.
- **Fees:** `ceil(rate × count × P × (1−P))` to the cent, per fill. The rates are in Settings
  (taker 0.07, maker 0).
- **Positions:** YES (+) / NO (−) contracts, as on Kalshi. Selling YES with no YES position buys
  NO at 1 − P.
- **Balance:** checked at submit, and again for resting fills.
- **P&L:** equity marks positions at the midpoint (liquidation value at the bid is also reported).
  There is no settlement, because outcomes are not in the recordings.

## Strategy runs and reports

`POST /strategy/runs {strategy, data_file, speed, mode}` (`mode` is `replayer` or `headless`)
starts a run:

1. The session resets.
2. The strategy starts as `python -u <file>` in the workspace, with `KALSHI_ENV=sim`,
   `KALSHI_API_BASE`, `KALSHI_WS_URL` and `KALSHI_TICKERS`. No API keys are passed.
3. Playback begins once the strategy subscribes.
4. At the end of the data the strategy gets a 2 s grace period, then is stopped.

Reports go to `<workspace>/runs/<run>__<strategy>__<data>.json`. They contain the account
summary, max drawdown, per-market results, fills, an equity curve, the console tail, and the
simulator's assumptions.

## AI research assistant (`/ai/...`)

A LangChain `create_agent` agent with InMemorySaver conversation memory and a structured
`ResearchResponse`. Its tools:

| Area | Tools |
|---|---|
| Data (ticked recordings only, never raw lines) | `profile_market_data`, `calculate_spread_statistics`, `calculate_orderbook_imbalance`, `sample_market_windows`, `compare_files`, `retrieve_market_context` (BM25 over window summaries) |
| Your files (read-only) | `list_workspace_strategy_files`, `read_workspace_strategy_file`, `list_run_reports`, `read_run_report` |
| Building | `get_strategy_template`, `create_artifact` (sandboxed in `engine/generated/`), `validate_python_artifact` |
| Testing | `run_strategy_test`: a real headless backtest in the simulator; the report also appears in the Workspace |

It has no shell, no arbitrary file access and no network tools. Generated code is statically
checked before running: no subprocess, sockets, file deletion or eval, and hard-coded foreign URLs
are flagged.

**Models:**

- **Claude account:** "Sign in with Claude" runs Anthropic's browser OAuth (`ant auth login`,
  CLI 1.41.0, downloaded and SHA-256 verified into `runtime/ant/` if needed). The Anthropic SDK
  reads the profile itself.
- **Local Qwen:** a pinned Ollama 0.40.5 plus `qwen3.5:4b`, installed into `runtime/` from the
  panel, or with `python -m engine.research.local_llm setup`. It is served privately on
  127.0.0.1:11435. Stale processes from a crashed session are cleaned up on startup.
- **Tracing:** optional LangSmith tracing via `LANGSMITH_TRACING` / `LANGSMITH_API_KEY` in
  `engine/.env`.
- **Evals:** `python -m engine.evals.run_evals [--local]`.

## Tests

```bash
engine/.venv/Scripts/python -m pytest engine/tests -c engine/tests/pytest.ini
```

The suite covers the recording parser and checkpoint seeking, matching/fees/accounting, the REST
and websocket API, collector jobs (fake Kalshi socket), every template as a real process against a
live server, determinism, stop/crash handling, and the AI tools. It also includes the full
"read strategy + report → write v2 → backtest v2" loop through the live engine, with a scripted
model.
