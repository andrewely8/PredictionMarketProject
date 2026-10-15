"""The LangChain agent: model + system instructions + tools + memory + structured output.

Built with `langchain.agents.create_agent` (LangChain v1), which runs a LangGraph tool-calling
loop: the model decides which tools to call, ToolNode executes them, and the loop repeats until
the model returns a final `ResearchResponse`.

  * conversation state: LangGraph InMemorySaver checkpointer, one thread per panel session
  * per-session data (selected files, index, artifacts): AgentContext via `context=`
  * system prompt: static research rules + the selected file names (dynamic_prompt middleware)
  * guard rails: ModelCallLimitMiddleware bounds the loop, ContextEditingMiddleware clears old
    tool outputs when the context grows
  * tracing: every run is traced to LangSmith when LANGSMITH_TRACING=true (see README)
"""

from __future__ import annotations

import threading
import warnings
from typing import Iterator

from langchain.agents import create_agent
from langchain.agents.middleware import (
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    ModelCallLimitMiddleware,
    ModelRequest,
    ModelRetryMiddleware,
    dynamic_prompt,
)
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from .models import ResearchResponse, build_chat_model, provider_config
from .tools import ALL_TOOLS, TOOL_LABELS, AgentContext

# LangGraph serializes the runtime context for tracing; our context holds live objects
# (stores, runner), which only produces noisy pydantic warnings.
warnings.filterwarnings("ignore", message="Pydantic serializer warnings")

STRUCTURE_PROMPT = """Rewrite the research answer below into the response schema. Do not add any fact, number or claim that is not in the answer. `message` keeps the main answer in Markdown. Copy measured facts into observations, untested ideas into hypotheses, results of strategy test runs into backtest_results, assumptions/risks into caveats, and suggested follow-ups into next_steps. Leave a list empty if the answer has nothing for it."""

SYSTEM_PROMPT = """You are a quantitative research copilot inside a Kalshi backtesting app. The user records live Kalshi order books (orderbook_snapshot / orderbook_delta .jsonl files), writes strategy files that trade like live Kalshi bots, tests them in the app's simulator/Replayer, and asks you to analyze data and to improve or redesign strategies. You are not a tipster.

What you can access (through tools only):
- The .jsonl recordings the user ticked in the panel: statistics, window summaries and retrieval via the data tools (never raw lines). If none are ticked, ask the user to tick them.
- The user's strategy files (.py) in the workspace: list_workspace_strategy_files, read_workspace_strategy_file.
- Saved run reports of strategy tests (Replayer runs and your own backtests): list_run_reports, read_run_report.
- Files you generate with create_artifact, which you can validate and backtest with run_strategy_test.
Do not tell the user you cannot read their files; use these tools, or say which file to tick.

How to work:
- Never invent statistics: every number you report must come from a tool result in this conversation.
- Start with profile_market_data for unfamiliar recordings. Use the calculate_* tools for numeric facts and retrieve_market_context / sample_market_windows to locate interesting periods.
- Prices are cents (0-100) of the YES contract. YES ask = 100 - best NO bid.
- Keep tool calls purposeful; do not repeat a call with the same arguments.

Improving a strategy (the usual request):
1. read_workspace_strategy_file for the strategy, and list_run_reports + read_run_report for its latest results.
2. Diagnose from the evidence: fees vs. gross edge, spread paid, number of trades, drawdown, rejected orders, errors in the console. Check the data (spreads, imbalance) when it matters.
3. Write the improved version with create_artifact (new file name, e.g. <name>_v2.py). Keep the file's plumbing (connection, Book, place_order, run) and change the Strategy class and parameters.
4. run_strategy_test on the new version AND, if no recent report exists, on the original, on the same data file; compare the two reports honestly. If the change does not help, say so.

Writing strategies:
- Start from get_strategy_template (starter, orderbook_imbalance, cross_market_arbitrage, ml_direction) or the user's file. Strategies are standalone Python files that talk to Kalshi's API: websocket channels orderbook_delta and fill, orders via POST /portfolio/events/orders (side "bid" = buy YES, "ask" = sell YES, price in dollars). They must read KALSHI_API_BASE / KALSHI_WS_URL / KALSHI_TICKERS from the environment, subscribe to the simulator's sim_clock channel when KALSHI_ENV == "sim" and answer each tick with {"cmd": "sim_ack", "params": {"tick": n}} (the templates already do this).
- Allowed libraries: standard library, numpy, requests, websockets, cryptography. No subprocess, raw sockets, file deletion, eval/exec, or writing outside the working directory.
- Save every file with create_artifact (plain file name). The user decides whether to add it to the workspace, where they can watch it trade in the Replayer.

Research standards (always apply):
- Never claim a strategy is or will be profitable. Backtests are evidence on one recording, not proof; prefer testing on several recordings. If asked for a guaranteed profitable strategy, explain why that cannot be promised and offer a testable alternative.
- Separate observed facts (tool output), hypotheses (untested ideas), and actual backtest results (only from run reports / run_strategy_test).
- Avoid look-ahead bias: decisions at time t may only use information available at t. For ML: learn only from labels that are already known, evaluate on later data, compare against a naive baseline, and prefer simple models first.
- State assumptions about fees, fills, queue position, latency, liquidity and slippage. The simulator fills takers at recorded prices, maker orders when the book crosses them (queue ignored), and charges Kalshi fees.

Final answer: fill the structured response. `message` is concise Markdown. Put measured facts in observations, untested ideas in hypotheses, backtest numbers in backtest_results, and assumptions/risks in caveats."""


@dynamic_prompt
def _session_prompt(request: ModelRequest) -> str:
    ctx: AgentContext = request.runtime.context
    files = ", ".join(ctx.session.files) or "(none selected - ask the user to select .jsonl files in the panel)"
    return f"{SYSTEM_PROMPT}\n\nSelected data files for this conversation: {files}"


def build_agent(model: BaseChatModel | None = None, checkpointer=None):
    cfg = provider_config()
    model_is_default = model is None
    model = model or build_chat_model(cfg)
    local = cfg.mode == "local"
    middleware = [
        _session_prompt,
        # Local models run on the user's CPU/GPU with a smaller context window: fewer loop
        # iterations and earlier clearing of old tool outputs.
        ModelCallLimitMiddleware(run_limit=12 if local else 25, exit_behavior="end"),
        ContextEditingMiddleware(edits=[ClearToolUsesEdit(trigger=9_000 if local else 60_000, keep=3 if local else 4)]),
    ]
    if cfg.mode == "claude" and isinstance(model, ChatAnthropic):
        from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
        middleware.append(AnthropicPromptCachingMiddleware(ttl="5m"))
    if local:
        # Small local models occasionally emit a malformed tool call that Ollama rejects; retry.
        from ollama import ResponseError
        middleware.append(ModelRetryMiddleware(max_retries=2, retry_on=(ResponseError,), on_failure="error",
                                               initial_delay=0.5))
    return create_agent(
        model=model,
        tools=ALL_TOOLS,
        middleware=middleware,
        # Claude returns the schema natively. Local models end with plain text, which
        # AgentService._structure_text maps onto the schema afterwards (more reliable than a
        # large final schema tool call from a small model).
        response_format=None if local and model_is_default else ResearchResponse,
        context_schema=AgentContext,
        checkpointer=checkpointer or InMemorySaver(),
        name="prediction_market_research_agent",
    )


class AgentService:
    """Owns the compiled agent and runs one turn at a time per session."""

    def __init__(self, model: BaseChatModel | None = None) -> None:
        self._model = model
        self._agent = None
        self._build_lock = threading.Lock()
        self._busy: set[str] = set()

    @property
    def agent(self):
        with self._build_lock:
            if self._agent is None:
                self._agent = build_agent(self._model)
            return self._agent

    def reset(self) -> None:
        with self._build_lock:
            self._agent = None

    def _structure_text(self, text: str, config: dict) -> ResearchResponse | None:
        """Local models often end with plain Markdown instead of the schema tool call (Ollama
        ignores forced tool choice). One extra call with Ollama's native JSON-schema output maps
        that answer onto ResearchResponse without adding facts."""
        try:
            model = build_chat_model(provider_config())
            if "reasoning" in type(model).model_fields:  # no "thinking" needed to reformat text
                model = model.model_copy(update={"reasoning": False})
            structurer = model.with_structured_output(ResearchResponse, method="json_schema")
            out = structurer.invoke([SystemMessage(STRUCTURE_PROMPT), HumanMessage(text)],
                                    config={**config, "run_name": "structure_final_answer"})
            if isinstance(out, ResearchResponse) and out.message.strip():
                return out
        except Exception:  # noqa: BLE001 - fall back to the plain answer
            pass
        return None

    def forget(self, session_id: str) -> None:
        if self._agent is not None:
            self._agent.checkpointer.delete_thread(session_id)

    def stream_turn(self, ctx: AgentContext, user_message: str) -> Iterator[dict]:
        """Run one user turn, yielding UI events:
        tool_start / tool_end / final / error."""
        sid = ctx.session.id
        if sid in self._busy:
            yield {"event": "error", "detail": "This session is already processing a message."}
            return
        self._busy.add(sid)
        ctx.session.turn_artifacts = []
        cfg = provider_config()
        config = {
            "configurable": {"thread_id": sid},
            "run_name": "ai_research_turn",
            "tags": ["ai-research-panel", cfg.mode, cfg.provider],
            "metadata": {"session_id": sid, "mode": cfg.mode, "provider": cfg.provider, "model": cfg.model,
                         "selected_files": list(ctx.session.files)},
            "recursion_limit": 80,
        }
        structured: ResearchResponse | dict | None = None
        last_text = ""
        try:
            for update in self.agent.stream({"messages": [HumanMessage(user_message)]}, config=config,
                                            context=ctx, stream_mode="updates"):
                for node_update in update.values():
                    if not isinstance(node_update, dict):
                        continue
                    if node_update.get("structured_response") is not None:
                        structured = node_update["structured_response"]
                    for msg in node_update.get("messages", []) or []:
                        if isinstance(msg, AIMessage):
                            for call in msg.tool_calls:
                                if call["name"] == ResearchResponse.__name__:
                                    continue  # the final-answer schema, not a user-visible tool
                                yield {"event": "tool_start", "tool": call["name"], "id": call["id"],
                                       "label": TOOL_LABELS.get(call["name"], f"Running {call['name']}...")}
                            if isinstance(msg.content, str) and msg.content.strip():
                                last_text = msg.content
                            elif isinstance(msg.content, list):
                                texts = [b.get("text", "") for b in msg.content if isinstance(b, dict) and b.get("type") == "text"]
                                last_text = "\n".join(t for t in texts if t) or last_text
                        elif isinstance(msg, ToolMessage) and msg.name != ResearchResponse.__name__:
                            failed = msg.status == "error" or str(msg.content).startswith('{"error"')
                            yield {"event": "tool_end", "tool": msg.name, "id": msg.tool_call_id,
                                   "status": "error" if failed else "complete"}
            if isinstance(structured, ResearchResponse):
                response = structured.model_dump()
            elif isinstance(structured, dict):
                response = ResearchResponse(**structured).model_dump()
            else:  # a local model answered in plain text, or the call limit ended the loop
                fallback = None
                if last_text and self._model is None and cfg.mode == "local":
                    yield {"event": "tool_start", "tool": "structure_answer", "id": "structure",
                           "label": "Organizing the answer..."}
                    fallback = self._structure_text(last_text, config)
                    yield {"event": "tool_end", "tool": "structure_answer", "id": "structure",
                           "status": "complete" if fallback else "error"}
                response = (fallback or ResearchResponse(
                    message=last_text or "The agent stopped without a final answer.")).model_dump()
            yield {"event": "final", "response": response, "artifact_ids": list(ctx.session.turn_artifacts)}
        except Exception as exc:  # noqa: BLE001 - surface provider/agent errors to the UI
            yield {"event": "error", "detail": f"{type(exc).__name__}: {exc}"}
        finally:
            self._busy.discard(sid)
