"""Static checks for strategy code written by the AI, before anything runs it.

Strategies legitimately need `requests` and `websockets` to talk to the (simulated) Kalshi API, so
those are allowed. Process spawning, raw sockets, native code, file deletion and dynamic code
execution are not. Hard-coded URLs other than the local simulator and Kalshi are flagged.

These checks prevent accidents; they are not a security sandbox. Strategy runs get no API keys.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import re

FORBIDDEN_MODULES = {
    "subprocess", "socket", "shutil", "ctypes", "multiprocessing", "ftplib", "smtplib", "telnetlib", "pty",
    "webbrowser", "winreg", "asyncio.subprocess", "pickle", "marshal",
}
FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__", "breakpoint"}
FORBIDDEN_ATTR_CALLS = {
    "os.system", "os.popen", "os.remove", "os.unlink", "os.rmdir", "os.removedirs", "os.rename",
    "os.replace", "os.kill", "os.chmod", "os.startfile", "os.execv", "os.execl", "os.spawnl",
    "os.spawnv", "os.fork",
}
ALLOWED_URL = re.compile(r"^(wss?|https?)://(127\.0\.0\.1|localhost)(:\d+)?/|^(wss?|https?)://([a-z0-9-]+\.)*kalshi\.(com|co)/")


def _looks_absolute(path: str) -> bool:
    return os.path.isabs(path) or path.startswith(("/", "\\", "~")) or (len(path) > 1 and path[1] == ":")


def _dotted(node: ast.AST) -> str | None:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def validate_source(source: str, filename: str = "<artifact>") -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        tree = ast.parse(source, filename=filename)
        compile(tree, filename, "exec")
    except SyntaxError as exc:
        return {"ok": False, "errors": [f"SyntaxError line {exc.lineno}: {exc.msg}"], "warnings": [], "imports": []}

    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imports.add(node.module)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and "://" in node.value:
            if re.match(r"^[a-z]+://", node.value) and not ALLOWED_URL.match(node.value):
                warnings.append(f"line {node.lineno}: hard-coded URL {node.value[:60]!r} is not the simulator or Kalshi")
        elif isinstance(node, ast.Call):
            name = _dotted(node.func)
            if name in FORBIDDEN_CALLS or name in FORBIDDEN_ATTR_CALLS:
                errors.append(f"line {node.lineno}: call to {name}() is not allowed")
            elif name == "open" and node.args:
                mode = node.args[1] if len(node.args) > 1 else next(
                    (k.value for k in node.keywords if k.arg == "mode"), None)
                writes = isinstance(mode, ast.Constant) and isinstance(mode.value, str) and any(c in mode.value for c in "wax+")
                target = node.args[0]
                if writes and isinstance(target, ast.Constant) and isinstance(target.value, str) and (
                        _looks_absolute(target.value) or ".." in target.value):
                    errors.append(f"line {node.lineno}: writing to an absolute or parent path is not allowed")

    for mod in sorted(imports):
        root = mod.split(".")[0]
        if mod in FORBIDDEN_MODULES or root in FORBIDDEN_MODULES:
            errors.append(f"import of '{mod}' is not allowed in generated strategies")
        elif importlib.util.find_spec(root) is None:
            errors.append(f"module '{root}' is not installed in the strategy runtime")

    if "orderbook_delta" not in source:
        warnings.append("does not subscribe to the orderbook_delta channel - it will not see market data")
    if "sim_ack" not in source:
        warnings.append("does not answer sim_clock ticks with sim_ack - Max-speed backtests will not run in lockstep")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "imports": sorted(imports)}
