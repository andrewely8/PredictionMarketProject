"""Option 1: "Sign in with Claude".

Sign-in uses Anthropic's own OAuth flow through the Anthropic CLI (`ant auth login`), which opens
the browser, lets the user pick their Claude Console organization/workspace, and stores a profile
in the user's standard Anthropic config folder (%APPDATA%\\Anthropic on Windows,
~/.config/anthropic elsewhere). The Anthropic Python SDK reads that profile automatically and
refreshes its short-lived tokens, so this app never sees or stores the token itself.

This is a Claude Console (API) account: usage is billed to the API organization chosen at
sign-in. Consumer claude.ai Pro/Max subscriptions cannot be used by third-party apps.

If `ant` is not on PATH, a pinned, checksum-verified copy is downloaded into
engine/runtime/ant/ (git-ignored).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time

import anthropic

from .installers import RUNTIME_DIR, Progress, download, extract, find_binary, hidden_process_flags, platform_key

ANT_VERSION = "1.41.0"
_ANT_BASE = f"https://github.com/anthropics/anthropic-cli/releases/download/v{ANT_VERSION}"
# platform -> (asset, sha256, archive kind); hashes from ant_<version>_checksums.txt
ANT_ASSETS = {
    "windows_amd64": ("ant_1.41.0_windows_amd64.zip", "b4e166258ead21b16f67724a1a8625c803b5b0f758d79bfc0c5246df74c1dd21", "zip"),
    "windows_arm64": ("ant_1.41.0_windows_arm64.zip", "39bb7171613e23708582f9faa0e7d1a420fcd940d455573ebd2bc78453f77f1f", "zip"),
    "macos_amd64": ("ant_1.41.0_macos_amd64.zip", "369f5f407a4effcb1371404bb7909660a89183738f6e1b9db17bb03be2a731d8", "zip"),
    "macos_arm64": ("ant_1.41.0_macos_arm64.zip", "c9258b594fa6d25e3fef639a15c3f1a0f726e9811845aba148c56d2f14536a5c", "zip"),
    "linux_amd64": ("ant_1.41.0_linux_amd64.tar.gz", "464df887f9371df822637ccd949e0f82553c53d25994b75207124870891b3931", "tar.gz"),
    "linux_arm64": ("ant_1.41.0_linux_arm64.tar.gz", "ad48ba9216bb7dd4860e84772f1e99153ba319c56bdc4d1aabb28433b7ec24ce", "tar.gz"),
}
ANT_DIR = os.path.join(RUNTIME_DIR, "ant")
STATUS_TTL_S = 30


def _env_without_static_keys() -> dict:
    # A stale ANTHROPIC_API_KEY would silently shadow the signed-in profile for `ant`.
    return {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}


class ClaudeAccount:
    def __init__(self) -> None:
        self.install_progress = Progress()
        self._login_proc: subprocess.Popen | None = None
        self._status: dict | None = None
        self._status_time = 0.0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ CLI

    def ant_path(self) -> str | None:
        return find_binary(ANT_DIR, "ant") or shutil.which("ant")

    def install_cli(self) -> str:
        existing = self.ant_path()
        if existing:
            return existing
        key = platform_key()
        if key not in ANT_ASSETS:
            raise RuntimeError(f"No Anthropic CLI build for platform {key}")
        asset, sha, kind = ANT_ASSETS[key]
        os.makedirs(RUNTIME_DIR, exist_ok=True)
        archive = download(f"{_ANT_BASE}/{asset}", sha, self.install_progress, label="Anthropic CLI")
        try:
            self.install_progress.update(state="extracting", message="Unpacking Anthropic CLI")
            extract(archive, ANT_DIR, kind)
        finally:
            os.remove(archive)
        path = find_binary(ANT_DIR, "ant")
        if not path:
            raise RuntimeError("Anthropic CLI archive did not contain the 'ant' binary")
        self.install_progress.update(state="done", message="Anthropic CLI installed")
        return path

    # ------------------------------------------------------------------ sign-in

    def start_login(self) -> dict:
        """Install the CLI if needed, then launch `ant auth login` (opens the browser)."""
        if self._login_proc and self._login_proc.poll() is None:
            return {"started": False, "message": "Sign-in already in progress - finish it in your browser."}
        ant = self.install_cli()
        self._login_proc = subprocess.Popen(
            [ant, "auth", "login"], env=_env_without_static_keys(), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=hidden_process_flags())
        self.invalidate()
        return {"started": True, "message": "Complete the sign-in in the browser window that opened."}

    def logout(self) -> None:
        ant = self.ant_path()
        if ant:
            subprocess.run([ant, "auth", "logout"], env=_env_without_static_keys(), capture_output=True,
                           timeout=30, creationflags=hidden_process_flags())
        self.invalidate()

    def login_in_progress(self) -> bool:
        return bool(self._login_proc and self._login_proc.poll() is None)

    # ------------------------------------------------------------------ status

    def invalidate(self) -> None:
        with self._lock:
            self._status = None

    def credential_source(self) -> str:
        if os.getenv("ANTHROPIC_API_KEY"):
            return "api_key_env"
        if os.getenv("ANTHROPIC_AUTH_TOKEN"):
            return "auth_token_env"
        return "claude_account"

    def status(self) -> dict:
        """Signed-in status, verified with a real (free) authenticated call, cached briefly."""
        with self._lock:
            if self._status is not None and time.time() - self._status_time < STATUS_TTL_S \
                    and not self.login_in_progress():
                return self._status
        status = {"cli_installed": self.ant_path() is not None, "login_in_progress": self.login_in_progress(),
                  "source": self.credential_source(), "install": self.install_progress.public()}
        try:
            client = anthropic.Anthropic(max_retries=0, timeout=15)  # SDK credential chain: env key or profile
            client.models.list(limit=1)
            status.update(signed_in=True, detail="Signed in")
        except TypeError as exc:  # "Could not resolve authentication method"
            status.update(signed_in=False, detail="Not signed in" if "authentication" in str(exc) else str(exc))
        except anthropic.CredentialsError:  # profile missing/incomplete, e.g. after `ant auth logout`
            status.update(signed_in=False, detail="Not signed in")
        except anthropic.AuthenticationError:
            status.update(signed_in=False, detail="Sign-in expired or was revoked - sign in again")
        except anthropic.PermissionDeniedError:
            status.update(signed_in=False, detail="This account/workspace is not allowed to use the API")
        except anthropic.APIConnectionError:
            status.update(signed_in=False, detail="Cannot reach api.anthropic.com - check your connection")
        except anthropic.AnthropicError as exc:
            status.update(signed_in=False, detail=f"Not signed in ({type(exc).__name__})")
        with self._lock:
            self._status, self._status_time = status, time.time()
        return status
