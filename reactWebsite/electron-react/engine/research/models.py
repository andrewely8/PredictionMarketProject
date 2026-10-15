"""Model selection, provider construction, and the structured response schema.

The user picks one of two modes in the AI panel (persisted as `ai_mode` in the engine settings):

  "claude" - their own Claude account, signed in with `ant auth login` (see claude_account.py).
             The Anthropic SDK resolves the signed-in profile itself; an ANTHROPIC_API_KEY in the
             environment also works as a developer fallback.
  "local"  - the packaged Ollama + Qwen model (see local_llm.py).

Both are created through LangChain chat-model classes, so the agent code is identical.

Optional environment overrides (engine/.env, git-ignored):
    ANTHROPIC_MODEL=claude-opus-5-5   ANTHROPIC_EFFORT=high   ANTHROPIC_SERVER_FALLBACK=true
    LOCAL_LLM_MODEL=qwen3.5:4b        LOCAL_LLM_NUM_CTX=16384
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import cached_property
from typing import Any

from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_ollama import ChatOllama
from pydantic import BaseModel, Field

from .. import settings
from ..paths import CONFIG, ENGINE_DIR

load_dotenv(os.path.join(ENGINE_DIR, ".env"))

MODES = ("claude", "local")
DEFAULT_ANTHROPIC_MODEL = "claude-opus-5-5"
DEFAULT_LOCAL_MODEL = "qwen3.5:4b"
DEFAULT_LANGSMITH_PROJECT = "prediction-market-ai-research"


# --------------------------------------------------------------------------- mode

def current_mode() -> str:
    return settings.get("ai_mode")


def set_mode(mode: str) -> None:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    settings.update({"ai_mode": mode})


def local_model_name() -> str:
    return os.getenv("LOCAL_LLM_MODEL", DEFAULT_LOCAL_MODEL)


@dataclass(frozen=True)
class ProviderConfig:
    mode: str      # "claude" | "local"
    provider: str  # "anthropic" | "ollama"
    model: str


def provider_config() -> ProviderConfig:
    if current_mode() == "local":
        return ProviderConfig("local", "ollama", local_model_name())
    return ProviderConfig("claude", "anthropic", os.getenv("ANTHROPIC_MODEL", DEFAULT_ANTHROPIC_MODEL))


# --------------------------------------------------------------------------- chat models

class AccountChatAnthropic(ChatAnthropic):
    """ChatAnthropic that lets the Anthropic SDK resolve credentials itself.

    Stock ChatAnthropic always passes api_key (an empty string when unset), which disables the
    SDK's credential chain. Dropping an empty key lets the SDK use, in order: ANTHROPIC_API_KEY,
    ANTHROPIC_AUTH_TOKEN, then the profile written by `ant auth login`, refreshing OAuth tokens
    and sending the OAuth headers automatically.
    """

    @cached_property
    def _client_params(self) -> dict[str, Any]:
        params = dict(ChatAnthropic._client_params.func(self))
        if not params.get("api_key"):
            params.pop("api_key", None)
        return params


def build_chat_model(cfg: ProviderConfig | None = None, local_base_url: str | None = None) -> BaseChatModel:
    cfg = cfg or provider_config()
    if cfg.mode == "claude":
        kwargs: dict = {
            "model": cfg.model,
            "max_tokens": 16000,
            "reasoning_effort": os.getenv("ANTHROPIC_EFFORT", "high"),
            "max_retries": 2,
        }
        # Server-side refusal fallback: if the model declines, the API retries on a fallback
        # model inside the same call. Set ANTHROPIC_SERVER_FALLBACK=false to disable.
        if os.getenv("ANTHROPIC_SERVER_FALLBACK", "true").lower() != "false":
            kwargs["betas"] = ["server-side-fallback-2026-07-01"]
            kwargs["model_kwargs"] = {"fallbacks": "default"}
        return AccountChatAnthropic(**kwargs)
    return ChatOllama(
        model=cfg.model,
        base_url=local_base_url or f"http://{CONFIG['host']}:{CONFIG['ollama_port']}",
        temperature=0,
        num_ctx=int(os.getenv("LOCAL_LLM_NUM_CTX", "16384")),
    )


def configure_langsmith() -> dict:
    """LangSmith tracing is driven by standard env vars; we only fill in a default project name."""
    enabled = os.getenv("LANGSMITH_TRACING", "").lower() == "true"
    if enabled:
        os.environ.setdefault("LANGSMITH_PROJECT", DEFAULT_LANGSMITH_PROJECT)
    return {
        "tracing": enabled and bool(os.getenv("LANGSMITH_API_KEY")),
        "project": os.getenv("LANGSMITH_PROJECT") if enabled else None,
    }


class ResearchResponse(BaseModel):
    """Final answer of one agent turn, rendered by the React panel."""

    message: str = Field(description="Main answer in Markdown. Concise; reference tool results for any numbers.")
    observations: list[str] = Field(default_factory=list,
                                    description="Facts measured by tools in this conversation (include the numbers).")
    hypotheses: list[str] = Field(default_factory=list,
                                  description="Untested ideas that could be backtested. Never stated as facts.")
    backtest_results: list[str] = Field(default_factory=list,
                                        description="Results of run_strategy_test runs, if any were executed.")
    caveats: list[str] = Field(default_factory=list,
                               description="Assumptions and risks: costs, fills, latency, look-ahead, overfitting.")
    next_steps: list[str] = Field(default_factory=list, description="Suggested follow-up experiments.")
