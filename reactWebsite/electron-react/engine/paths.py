"""Filesystem locations used by the engine. Nothing here is machine-specific."""

from __future__ import annotations

import json
import os

ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(ENGINE_DIR)                      # reactWebsite/electron-react
REPO_ROOT = os.path.dirname(os.path.dirname(APP_DIR))      # PredictionMarketProject

RUNTIME_DIR = os.path.join(ENGINE_DIR, "runtime")          # git-ignored: Ollama, models, Anthropic CLI
TEMPLATES_DIR = os.path.join(ENGINE_DIR, "templates")      # strategy templates
GENERATED_DIR = os.path.join(ENGINE_DIR, "generated")      # AI artifacts before "Add to Workspace"
SETTINGS_PATH = os.path.join(APP_DIR, "settings.local.json")  # git-ignored user settings

DEFAULT_WORKSPACE = os.path.join(REPO_ROOT, "workspace")   # git-ignored
DEFAULT_SECRET_DIR = os.path.join(REPO_ROOT, "secret")     # git-ignored

with open(os.path.join(ENGINE_DIR, "config.json"), "r", encoding="utf-8") as _fh:
    CONFIG = json.load(_fh)

HOST: str = CONFIG["host"]
PORT: int = int(CONFIG["port"])
BASE_URL = f"http://{HOST}:{PORT}"
