"""Kalshi Backtester engine.

One local Python service (FastAPI on 127.0.0.1:8000, see config.json) that powers the desktop app:

    collector/   record live Kalshi order books to .jsonl files
    marketdata/  parse recordings and replay order books (shared by everything below)
    sim/         a Kalshi-compatible exchange simulator driven by the Replayer clock
    strategies/  run user strategy files against the simulator and save run reports
    research/    the AI research assistant (LangChain agent, Claude account or local Qwen)
"""
