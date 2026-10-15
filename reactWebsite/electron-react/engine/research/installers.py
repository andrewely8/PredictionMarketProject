"""Download-and-unpack helpers for the runtimes this feature keeps inside the project folder.

Everything lands under engine/runtime/ (git-ignored). Versions are pinned
and every archive is checked against a hard-coded SHA-256 from the official release before it is
unpacked. Nothing is installed system-wide.
"""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import threading
import urllib.request
import zipfile
from dataclasses import dataclass, field

from ..paths import RUNTIME_DIR
IS_WINDOWS = os.name == "nt"


def platform_key() -> str:
    """'windows_amd64', 'macos_arm64', 'linux_amd64', ..."""
    system = {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}.get(platform.system(), "unknown")
    machine = platform.machine().lower()
    arch = "arm64" if machine in ("arm64", "aarch64") else "amd64" if machine in ("amd64", "x86_64") else machine
    return f"{system}_{arch}"


@dataclass
class Progress:
    """Thread-safe progress record polled by the UI."""
    state: str = "idle"  # idle | downloading | verifying | extracting | pulling | done | error
    message: str = ""
    done_bytes: int = 0
    total_bytes: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def update(self, **kw) -> None:
        with self._lock:
            for k, v in kw.items():
                setattr(self, k, v)

    def public(self) -> dict:
        with self._lock:
            pct = round(100 * self.done_bytes / self.total_bytes, 1) if self.total_bytes else None
            return {"state": self.state, "message": self.message, "done_bytes": self.done_bytes,
                    "total_bytes": self.total_bytes, "percent": pct}


def download(url: str, sha256: str, progress: Progress | None = None, label: str = "") -> str:
    """Stream `url` to a temp file, verify its SHA-256, return the path. Raises on mismatch."""
    progress = progress or Progress()
    fd, path = tempfile.mkstemp(prefix="ai_research_dl_", dir=RUNTIME_DIR if os.path.isdir(RUNTIME_DIR) else None)
    digest = hashlib.sha256()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "prediction-market-ai-research"})
        with urllib.request.urlopen(req, timeout=60) as resp, os.fdopen(fd, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            progress.update(state="downloading", message=f"Downloading {label}", done_bytes=0, total_bytes=total)
            done = 0
            while chunk := resp.read(1 << 20):
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                progress.update(done_bytes=done)
        progress.update(state="verifying", message=f"Verifying {label}")
        if digest.hexdigest() != sha256.lower():
            raise RuntimeError(f"Checksum mismatch for {label}: refusing to install it")
        return path
    except BaseException:
        if os.path.exists(path):
            os.remove(path)
        raise


def _check_member(dest: str, name: str) -> None:
    target = os.path.realpath(os.path.join(dest, name))
    if os.path.commonpath([target, os.path.realpath(dest)]) != os.path.realpath(dest):
        raise RuntimeError(f"Archive entry escapes the install folder: {name}")


def extract(archive: str, dest: str, kind: str) -> None:
    """Unpack zip / tar.gz / tar.zst into dest, rejecting path-traversal entries."""
    os.makedirs(dest, exist_ok=True)
    if kind == "zip":
        with zipfile.ZipFile(archive) as zf:
            for name in zf.namelist():
                _check_member(dest, name)
            zf.extractall(dest)
    elif kind == "tar.gz":
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(dest, filter="data")  # "data" filter blocks traversal, links outside, devices
    elif kind == "tar.zst":
        tar = shutil.which("tar")
        if not tar:
            raise RuntimeError("Extracting .tar.zst needs a 'tar' with zstd support")
        listing = subprocess.run([tar, "--zstd", "-tf", archive], capture_output=True, text=True, check=True)
        for name in listing.stdout.splitlines():
            _check_member(dest, name)
        subprocess.run([tar, "--zstd", "-xf", archive, "-C", dest], check=True)
    else:
        raise ValueError(kind)
    if not IS_WINDOWS:  # make the main binaries executable
        for root, _, files in os.walk(dest):
            for f in files:
                if f in ("ant", "ollama"):
                    p = os.path.join(root, f)
                    os.chmod(p, os.stat(p).st_mode | 0o111)


def find_binary(root: str, name: str) -> str | None:
    exe = name + (".exe" if IS_WINDOWS else "")
    if not os.path.isdir(root):
        return None
    for dirpath, _, files in os.walk(root):
        if exe in files:
            return os.path.join(dirpath, exe)
    return None


def hidden_process_flags() -> int:
    """Avoid flashing console windows for helper processes on Windows."""
    return subprocess.CREATE_NO_WINDOW if IS_WINDOWS else 0
