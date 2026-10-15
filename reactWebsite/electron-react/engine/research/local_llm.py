"""Option 2: a local open-source model packaged inside the project folder.

Layout (all git-ignored, under engine/runtime/):
    ollama/          portable Ollama runtime (pinned release, SHA-256 verified)
    ollama-models/   model weights (OLLAMA_MODELS), e.g. Qwen 3.5 4B (~3.3 GB)

The AI service starts its own private `ollama serve` on 127.0.0.1:<ollama_port from config.json>
(11435, not Ollama's default 11434, so it never collides with a separately installed Ollama)
and stops it on shutdown. The model is pulled from the official Ollama registry.

CLI (no UI needed):  python -m engine.research.local_llm setup | status
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

import httpx

from .installers import IS_WINDOWS, RUNTIME_DIR, Progress, download, extract, find_binary, hidden_process_flags, platform_key
from .models import CONFIG, local_model_name

OLLAMA_VERSION = "0.40.5"
_OLLAMA_BASE = f"https://github.com/ollama/ollama/releases/download/v{OLLAMA_VERSION}"
# platform -> (asset, sha256, archive kind); hashes from the release's sha256sum.txt
OLLAMA_ASSETS = {
    "windows_amd64": ("ollama-windows-amd64.zip", "5134ce7e3bc8e94d0494721c799ec293b429450d0c52461b0ee3647dd3bb4bb7", "zip"),
    "windows_arm64": ("ollama-windows-arm64.zip", "c3d469e4410ba9cfe3a8806b7c7c7799c365e77ccd24ab8efe2e9eec1fce8f4e", "zip"),
    "macos_amd64": ("ollama-darwin.tgz", "75f9907dafa2fd4c61b5967de2ebb81ccc17eb28da9172edbad0dbc717474dcf", "tar.gz"),
    "macos_arm64": ("ollama-darwin.tgz", "75f9907dafa2fd4c61b5967de2ebb81ccc17eb28da9172edbad0dbc717474dcf", "tar.gz"),
    "linux_amd64": ("ollama-linux-amd64.tar.zst", "dc5eabc292f9949546c90a97c820f924b035e05243b0de13c7f366182562169c", "tar.zst"),
    "linux_arm64": ("ollama-linux-arm64.tar.zst", "fbe71ebb1a10e59b8480c4d2839826b5f9dff1a6d5c142428b2e7db9b1a2c642", "tar.zst"),
}
OLLAMA_DIR = os.path.join(RUNTIME_DIR, "ollama")
MODELS_DIR = os.path.join(RUNTIME_DIR, "ollama-models")
PID_FILE = os.path.join(RUNTIME_DIR, "ollama.pid")
HOST = CONFIG["host"]
PORT = int(CONFIG["ollama_port"])
BASE_URL = f"http://{HOST}:{PORT}"


class LocalLLM:
    def __init__(self) -> None:
        self.progress = Progress()
        self._proc: subprocess.Popen | None = None
        self._setup_thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        self._log = os.path.join(RUNTIME_DIR, "ollama.log")

    # ------------------------------------------------------------------ queries

    @property
    def model(self) -> str:
        return local_model_name()

    def runtime_path(self) -> str | None:
        return find_binary(OLLAMA_DIR, "ollama")

    def running(self) -> bool:
        try:
            return httpx.get(f"{BASE_URL}/api/version", timeout=2).status_code == 200
        except httpx.HTTPError:
            return False

    def model_present(self) -> bool:
        try:
            tags = httpx.get(f"{BASE_URL}/api/tags", timeout=5).json().get("models", [])
        except (httpx.HTTPError, ValueError):
            return False
        want = self.model if ":" in self.model else f"{self.model}:latest"
        return any(m.get("name") == want or m.get("model") == want for m in tags)

    def capabilities(self) -> list[str]:
        try:
            return httpx.post(f"{BASE_URL}/api/show", json={"model": self.model}, timeout=10).json().get("capabilities", [])
        except (httpx.HTTPError, ValueError):
            return []

    def setup_running(self) -> bool:
        return bool(self._setup_thread and self._setup_thread.is_alive())

    def status(self) -> dict:
        installed = self.runtime_path() is not None
        running = installed and self.running()
        present = running and self.model_present()
        if self.setup_running():
            problem = self.progress.message or "Installing local model..."
        elif not installed:
            problem = "Local model not installed - click 'Install local model'"
        elif not running:
            problem = "Local model runtime is starting..."
        elif not present:
            problem = f"Model {self.model} not downloaded - click 'Install local model'"
        else:
            problem = None
        return {"runtime_installed": installed, "running": running, "model": self.model, "model_present": present,
                "ready": problem is None, "problem": problem, "base_url": BASE_URL,
                "setup": self.progress.public(), "ollama_version": OLLAMA_VERSION}

    # ------------------------------------------------------------------ lifecycle

    def install_runtime(self) -> str:
        existing = self.runtime_path()
        if existing:
            return existing
        key = platform_key()
        if key not in OLLAMA_ASSETS:
            raise RuntimeError(f"No packaged Ollama build for platform {key}")
        asset, sha, kind = OLLAMA_ASSETS[key]
        os.makedirs(RUNTIME_DIR, exist_ok=True)
        archive = download(f"{_OLLAMA_BASE}/{asset}", sha, self.progress, label=f"Ollama {OLLAMA_VERSION} runtime")
        try:
            self.progress.update(state="extracting", message="Unpacking Ollama runtime", done_bytes=0, total_bytes=0)
            extract(archive, OLLAMA_DIR, kind)
        finally:
            os.remove(archive)
        path = self.runtime_path()
        if not path:
            raise RuntimeError("Ollama archive did not contain the ollama binary")
        return path

    def start(self, wait_s: float = 60) -> bool:
        """Start the private Ollama server if installed and not already running."""
        with self._start_lock:
            if self.running():
                return True
            exe = self.runtime_path()
            if not exe:
                return False
            os.makedirs(MODELS_DIR, exist_ok=True)
            env = {k: v for k, v in os.environ.items() if not k.startswith(("ANTHROPIC_", "LANGSMITH_"))}
            env.update(OLLAMA_HOST=f"{HOST}:{PORT}", OLLAMA_MODELS=MODELS_DIR, OLLAMA_KEEP_ALIVE="30m")
            log = open(self._log, "ab")
            self._proc = subprocess.Popen([exe, "serve"], env=env, stdin=subprocess.DEVNULL, stdout=log,
                                          stderr=subprocess.STDOUT, creationflags=hidden_process_flags())
            with open(PID_FILE, "w", encoding="utf-8") as fh:
                fh.write(str(self._proc.pid))
            deadline = time.time() + wait_s
            while time.time() < deadline:
                if self.running():
                    return True
                if self._proc.poll() is not None:
                    raise RuntimeError(f"Ollama exited during startup (see {self._log})")
                time.sleep(0.5)
            raise RuntimeError("Ollama did not start in time")

    @staticmethod
    def cleanup_orphan() -> None:
        """Kill an Ollama this app started in an earlier session that outlived its engine
        (e.g. the engine was force-killed). Only a process recorded in our PID file and still
        named ollama is touched."""
        try:
            with open(PID_FILE, "r", encoding="utf-8") as fh:
                pid = int(fh.read().strip())
        except (OSError, ValueError):
            return
        try:
            if IS_WINDOWS:
                out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"], capture_output=True,
                                     text=True, creationflags=hidden_process_flags()).stdout.lower()
                if "ollama" in out:
                    subprocess.run(["taskkill", "/pid", str(pid), "/T", "/F"], capture_output=True,
                                   creationflags=hidden_process_flags())
            else:
                with open(f"/proc/{pid}/comm", "r", encoding="utf-8") as fh:
                    if "ollama" in fh.read():
                        os.kill(pid, 15)
        except OSError:
            pass
        finally:
            try:
                os.remove(PID_FILE)
            except OSError:
                pass

    def start_in_background(self) -> None:
        if self.runtime_path() and not self.running():
            threading.Thread(target=self._safe_start, daemon=True).start()

    def _safe_start(self) -> None:
        try:
            self.start()
        except Exception as exc:  # noqa: BLE001 - reported through status()
            self.progress.update(state="error", message=f"Could not start local model: {exc}")

    def stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc:
            try:
                os.remove(PID_FILE)
            except OSError:
                pass
        if proc and proc.poll() is None:
            if IS_WINDOWS:  # ollama serve spawns runner subprocesses; kill the tree
                subprocess.run(["taskkill", "/pid", str(proc.pid), "/T", "/F"], capture_output=True,
                               creationflags=hidden_process_flags())
            else:
                proc.terminate()
                try:
                    proc.wait(10)
                except subprocess.TimeoutExpired:
                    proc.kill()

    def pull_model(self) -> None:
        self.progress.update(state="pulling", message=f"Downloading model {self.model}", done_bytes=0, total_bytes=0)
        with httpx.stream("POST", f"{BASE_URL}/api/pull", json={"model": self.model, "stream": True},
                          timeout=httpx.Timeout(30, read=600)) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if not line:
                    continue
                ev = json.loads(line)
                if ev.get("error"):
                    raise RuntimeError(f"Model download failed: {ev['error']}")
                if ev.get("total"):
                    self.progress.update(done_bytes=int(ev.get("completed") or 0), total_bytes=int(ev["total"]),
                                         message=f"Downloading model {self.model} ({ev.get('status', '')})")
                else:
                    self.progress.update(message=f"{self.model}: {ev.get('status', '')}")

    def setup(self) -> None:
        """Full install: runtime -> start -> model. Safe to re-run; skips finished steps."""
        try:
            self.install_runtime()
            self.progress.update(state="starting", message="Starting local model runtime", done_bytes=0, total_bytes=0)
            self.start()
            if not self.model_present():
                self.pull_model()
            caps = self.capabilities()
            if caps and "tools" not in caps:
                raise RuntimeError(f"{self.model} does not support tool calling; choose another Qwen model")
            self.progress.update(state="done", message=f"Local model {self.model} is ready")
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            self.progress.update(state="error", message=str(exc))
            raise

    def setup_in_background(self) -> bool:
        if self.setup_running():
            return False
        self.progress.update(state="downloading", message="Preparing local model install", done_bytes=0, total_bytes=0)
        self._setup_thread = threading.Thread(target=self._safe_setup, daemon=True)
        self._setup_thread.start()
        return True

    def _safe_setup(self) -> None:
        try:
            self.setup()
        except Exception:  # noqa: BLE001 - already recorded in progress
            pass


def _cli() -> int:
    llm = LocalLLM()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "setup":
        stop = threading.Event()

        def report():
            while not stop.wait(2):
                p = llm.progress.public()
                pct = f" {p['percent']}%" if p["percent"] is not None else ""
                print(f"[{p['state']}]{pct} {p['message']}", flush=True)
        threading.Thread(target=report, daemon=True).start()
        try:
            llm.setup()
        finally:
            stop.set()
            llm.stop()
        print("Local model ready:", llm.model)
        return 0
    if cmd == "status":
        started = llm.start() if llm.runtime_path() else False
        print(json.dumps(llm.status(), indent=2))
        if started:
            llm.stop()
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(_cli())
