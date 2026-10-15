"""User settings, persisted in settings.local.json (git-ignored). The engine owns them; the UI
reads and updates them through GET/PUT /settings."""

from __future__ import annotations

import json
import os
import threading
from typing import Any

from .paths import DEFAULT_SECRET_DIR, DEFAULT_WORKSPACE, SETTINGS_PATH

DEFAULTS: dict[str, Any] = {
    "workspace_dir": DEFAULT_WORKSPACE,
    "secret_dir": DEFAULT_SECRET_DIR,     # holds keys.json + kalshiDemoKey.txt / kalshiProductionKey.txt
    "kalshi_env": "production",           # "production" | "demo"
    "ai_mode": "claude",                  # "claude" | "local"
    "sim_starting_balance": 1000.0,       # dollars
    "sim_maker_fee_rate": 0.0,            # Kalshi maker fee multiplier (taker is 0.07)
    "sim_taker_fee_rate": 0.07,
}
_ALLOWED = {
    "kalshi_env": {"production", "demo"},
    "ai_mode": {"claude", "local"},
}
_lock = threading.Lock()
_path = SETTINGS_PATH  # tests may repoint this


def set_path(path: str) -> None:
    global _path
    _path = path


def load() -> dict[str, Any]:
    data: dict[str, Any] = {}
    try:
        with open(_path, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        if isinstance(raw, dict):
            data = raw
    except (OSError, ValueError):
        pass
    return {**DEFAULTS, **{k: v for k, v in data.items() if k in DEFAULTS}}


def get(key: str) -> Any:
    return load()[key]


def update(changes: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        current = load()
        for key, value in changes.items():
            if key not in DEFAULTS:
                raise ValueError(f"Unknown setting: {key}")
            if key in _ALLOWED and value not in _ALLOWED[key]:
                raise ValueError(f"{key} must be one of {sorted(_ALLOWED[key])}")
            if key in ("workspace_dir", "secret_dir"):
                value = os.path.abspath(str(value))
            if key.startswith("sim_"):
                value = float(value)
                if value < 0:
                    raise ValueError(f"{key} must be >= 0")
            current[key] = value
        os.makedirs(os.path.dirname(_path), exist_ok=True)
        with open(_path, "w", encoding="utf-8") as fh:
            json.dump(current, fh, indent=2)
        return current


def workspace_dir(create: bool = True) -> str:
    path = load()["workspace_dir"]
    if create:
        os.makedirs(path, exist_ok=True)
    return path
