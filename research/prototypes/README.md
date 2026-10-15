# Prototypes

The original learning scripts from the start of the project, kept for reference. Each one has
grown into part of the desktop app:

| Prototype | What replaced it |
|---|---|
| `kalshiTutorial.py` | Kalshi API tutorials (unauthenticated and signed requests). Signing now lives in `engine/kalshi/auth.py`, market search in `engine/kalshi/markets.py` |
| `collectMarketData.py` | Websocket order-book recorder. Now the Market Tracker (`engine/collector/`), same file format |
| `backtest.py` | Order-book replay plus the moneyline/spread arbitrage check. Now `engine/marketdata/` and the simulator (`engine/sim/`); the strategy itself is the `cross_market_arbitrage` template |
| `test.py` | Live arbitrage polling against the REST order book |
| `PygameGUI.py` | First visual replayer. Now the Replayer panel |

They read `./secret/` and `./collectedData/` relative to the current directory, so run them from the
repository root if you need them.
