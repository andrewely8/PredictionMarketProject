# Prediction Market Project — Kalshi Backtester

A research workbench for trading strategies on Kalshi prediction markets. It runs this loop:

```text
 record live Kalshi order books  ->  write a strategy like a live Kalshi bot  ->  test it in the
 Replayer against the recording  ->  ask the AI to improve / redesign it      ->  retest
```

Everything runs locally in one desktop app (Electron + React). A Python engine records data,
simulates the exchange, runs strategies and hosts the AI assistant.

The project's goals and research notes are in [`notes/`](notes/), the papers in
[`references/`](references/), and the original learning prototypes in
[`research/prototypes/`](research/prototypes/).

---

## The pipeline

### 1. Record live market data (Market Tracker)

- Search an event, series or market ticker (e.g. `KXMLBGAME`, or `KXMLBGAME-26OCT152000MILLAD`).
- Tick the markets you want and press **TRACK**.
- Optionally **schedule ahead** (start at e.g. 7:30 PM) and **stop after** N minutes.

Each recording subscribes to Kalshi's `orderbook_delta` websocket channel and writes every message
to `<workspace>/<event>_<date-time>.jsonl`. That format is identical to the original
`collectMarketData.py` files, so your existing recordings keep working.

Recordings reconnect automatically if the connection drops. The panel shows status, update counts,
file size and time since the last update, and has a Stop button.

### 2. Write a strategy (Workspace)

**New strategy** copies a template into your workspace and opens it in your editor. Strategies are
standalone Python files written **exactly like a live Kalshi bot**:

- market data from the `orderbook_delta` websocket channel, fills from the `fill` channel;
- orders via `POST /portfolio/events/orders` (`side: "bid"` buys YES, `"ask"` sells YES);
- connection details from environment variables (`KALSHI_API_BASE`, `KALSHI_WS_URL`,
  `KALSHI_TICKERS`, `KALSHI_ENV`).

When the app runs a strategy, those variables point at the simulator. Set them to Kalshi's demo or
production URLs, plus `KALSHI_KEY_ID` and `KALSHI_PRIVATE_KEY_PATH`, and the same file trades live.
Always test on demo first.

| Template | Idea |
|---|---|
| `starter` | The plumbing (connection, local books, `place_order`) and a print-only strategy |
| `orderbook_imbalance` | Buy the heavy side of a one-sided top of book; exit after a hold time |
| `cross_market_arbitrage` | Moneyline YES + spread NO bought together for less than $1 (the original `backtest.py` idea) |
| `ml_direction` | Online logistic regression on order-book features, trained only on already-known labels |

### 3. Test it (Replayer)

1. Pick a recording (**replay**) and a strategy (**test**).
2. Press **Run Strategy TEST**.

The simulator replays the order book on the Replayer clock (1×–500×, or **Max**). Your strategy
connects to it as if it were Kalshi; its orders are matched against the recorded book, with
Kalshi's fees.

While it runs, the panel shows the top of book for every market, live P&L, cash, fees, positions,
an equity curve, recent fills and the strategy's console output. Each run saves a report to
`<workspace>/runs/`, listed in the Workspace.

### 4. Improve it (AI Strategy Research)

**Ask AI to improve** (in the Replayer, a report, or a strategy's **AI** button) hands the strategy
and its latest report to the research assistant. The assistant then:

1. reads both;
2. checks the data with deterministic statistics tools;
3. writes an improved version;
4. backtests it in the same simulator (headless, Max speed);
5. compares the result with the original.

The assistant runs on either:

- **your Claude account** (Sign in with Claude, browser OAuth), or
- **a local Qwen model** packaged in the project folder (Ollama + Qwen 3.5 4B, about 5 GB).

### 5. Retest

On the assistant's result card, click **Add to Workspace**, then **Use in Replayer**, then
**Run Strategy TEST** again. Compare the two reports.

---

## Getting started

Requirements: Node 24+, Python 3.12+ (3.13 used here), Windows/macOS/Linux.

```bash
cd reactWebsite/electron-react
npm install                                        # app dependencies
python -m venv engine/.venv                        # engine environment
engine/.venv/Scripts/python -m pip install -r engine/requirements.txt   # macOS/Linux: engine/.venv/bin/python
npm start                                          # starts the app and the engine
```

Then, in the app:

1. **File → Settings**: choose the folder with your Kalshi API keys. It uses the same layout this
   project always used: `keys.json` + `kalshiProductionKey.txt` / `kalshiDemoKey.txt`. Keys are only
   used to record data; they are never sent to strategies or the AI.
2. **File → Choose workspace folder** if you want something other than the default
   `PredictionMarketProject/workspace/`. To reuse your earlier recordings, point it at the folder
   that holds them.
3. **Help → Getting started** has the same walkthrough inside the app.

## Architecture

```text
reactWebsite/electron-react/
├── src/main/            Electron: window, native dialogs, starts/stops the engine (engine.ts)
├── src/renderer/        React UI: MarketTracker, Workspace, Replayer, AI Strategy Research
│   ├── api/engine.ts    the only way the UI talks to the engine (HTTP + websocket, 127.0.0.1:8000)
│   └── contexts/        shared state: settings, workspace listing, selected files, AI requests
└── engine/              Python service (FastAPI), see engine/README.md
    ├── collector/       live recording jobs (Kalshi websocket)
    ├── kalshi/          request signing + public market search
    ├── marketdata/      one fast recording parser + order book, shared by everything
    ├── sim/             Kalshi-compatible simulator: REST /trade-api/v2, websocket /trade-api/ws/v2
    ├── strategies/      runs strategy files against the simulator, writes run reports
    ├── research/        AI assistant (LangChain agent; Claude account or local Qwen)
    ├── templates/       strategy templates
    └── tests/           pytest suite
```

The Electron main process keeps no trading logic. The renderer has no access to keys or the file
system beyond native folder pickers and "open in editor".

## Testing

```bash
cd reactWebsite/electron-react
engine/.venv/Scripts/python -m pytest engine/tests -c engine/tests/pytest.ini   # engine: 48 tests
npm test                                                                      # UI (Jest)
npm run lint                                                                  # ESLint + Prettier
npx tsc --noEmit                                                              # TypeScript
```

## Honest limits

- **Simulated fills are optimistic about queues.** Taker fills use recorded prices and sizes; maker
  orders fill when the book crosses them, ignoring queue position. Your orders do not move the
  recorded book.
- **P&L marks open positions at the midpoint.** Markets are not settled, because outcomes are not
  in the recordings.
- **A good backtest on one recording is weak evidence.** Test across several games before trusting
  a strategy.
