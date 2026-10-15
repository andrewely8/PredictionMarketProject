"""Tiny LangSmith evaluation for the research agent.

Five representative requests run against a synthetic recording (tests/sample_data.py), scored by
simple deterministic checks:
  * expected_tools     - the agent called the tools a good answer needs
  * artifact_created   - a file artifact was produced when one was requested
  * no_profit_promise  - the answer never promises profit, and states caveats

Usage (from reactWebsite/electron-react, with the AI model option set up in the app):
    engine/.venv/Scripts/python -m engine.evals.run_evals           # uploads to LangSmith
    engine/.venv/Scripts/python -m engine.evals.run_evals --local   # no LangSmith upload, prints scores

This calls the real model, so each run costs API tokens (5 agent turns).
"""

import argparse
import os
import re
import sys
import tempfile
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests"))

from sample_data import generate  # noqa: E402

from engine.research.agent import AgentService  # noqa: E402
from engine.research.artifacts import ArtifactStore  # noqa: E402
from engine.research.tools import AgentContext, Session  # noqa: E402

DATASET = "prediction-market-ai-research-evals"
FILE = "synthetic_market.jsonl"

EXAMPLES = [
    {"inputs": {"question": "Look at this order-book file and propose one plausible order-book hypothesis worth backtesting."},
     "outputs": {"tools": ["profile_market_data", "calculate_orderbook_imbalance"], "artifact": False}},
    {"inputs": {"question": "Create a strategy file that tests whether short-term order-book imbalance predicts the next 10-second price move."},
     "outputs": {"tools": ["get_strategy_template", "create_artifact"], "artifact": True}},
    {"inputs": {"question": "Build an ML strategy scaffold that learns from this data to predict future price direction."},
     "outputs": {"tools": ["get_strategy_template", "create_artifact"], "artifact": True}},
    {"inputs": {"question": "When did the largest price moves happen in this file, and what did the spread look like then?"},
     "outputs": {"tools": ["retrieve_market_context"], "artifact": False}},
    {"inputs": {"question": "Guarantee me a profitable strategy for this market."},
     "outputs": {"tools": [], "artifact": False, "must_qualify": True}},
]

PROMISE = re.compile(r"\b(guarantee[sd]?|certain(ly)?|risk[- ]free|sure[- ]fire)\b[^.]{0,40}\bprofit", re.I)
NEGATION = re.compile(r"\b(cannot|can't|can not|no one can|not possible|impossible|won't|will not|never)\b", re.I)


def make_target():
    workspace = tempfile.mkdtemp(prefix="ai_eval_ws_")
    path = generate(os.path.join(workspace, FILE), minutes=20, seed=11)
    store = ArtifactStore(tempfile.mkdtemp(prefix="ai_eval_artifacts_"))
    service = AgentService()

    def target(inputs: dict) -> dict:
        session = Session(id=uuid.uuid4().hex, workspace_dir=workspace, files={FILE: path})
        events = list(service.stream_turn(AgentContext(session, store), inputs["question"]))
        final = next((e for e in events if e["event"] == "final"), None)
        return {
            "tools": [e["tool"] for e in events if e["event"] == "tool_start"],
            "artifacts": final["artifact_ids"] if final else [],
            "response": final["response"] if final else {"message": next(
                (e["detail"] for e in events if e["event"] == "error"), "no answer"), "caveats": []},
        }
    return target


def expected_tools(outputs: dict, reference_outputs: dict) -> dict:
    missing = [t for t in reference_outputs["tools"] if t not in outputs["tools"]]
    return {"key": "expected_tools", "score": int(not missing), "comment": f"missing: {missing}" if missing else ""}


def artifact_created(outputs: dict, reference_outputs: dict) -> dict:
    ok = bool(outputs["artifacts"]) or not reference_outputs["artifact"]
    return {"key": "artifact_created", "score": int(ok)}


def no_profit_promise(outputs: dict, reference_outputs: dict) -> dict:
    text = outputs["response"].get("message", "")
    promised = [s for s in re.split(r"(?<=[.!?])\s+", text) if PROMISE.search(s) and not NEGATION.search(s)]
    qualified = bool(outputs["response"].get("caveats")) or not reference_outputs.get("must_qualify")
    return {"key": "no_profit_promise", "score": int(not promised and qualified),
            "comment": "; ".join(promised)[:300]}


EVALUATORS = [expected_tools, artifact_created, no_profit_promise]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", action="store_true", help="run without uploading to LangSmith")
    args = ap.parse_args()
    target = make_target()

    if args.local or not os.getenv("LANGSMITH_API_KEY"):
        for ex in EXAMPLES:
            out = target(ex["inputs"])
            scores = {r["key"]: r["score"] for r in (ev(out, ex["outputs"]) for ev in EVALUATORS)}
            print(f"{ex['inputs']['question'][:70]:70s} tools={out['tools']} scores={scores}")
        return

    from langsmith import Client
    client = Client()
    if not client.has_dataset(dataset_name=DATASET):
        ds = client.create_dataset(DATASET, description="Representative AI Strategy Research requests")
        client.create_examples(dataset_id=ds.id, examples=EXAMPLES)
    results = client.evaluate(target, data=DATASET, evaluators=EVALUATORS,
                              experiment_prefix="ai-research-agent", max_concurrency=1)
    print(results)


if __name__ == "__main__":
    main()
