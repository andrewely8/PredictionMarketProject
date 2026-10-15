"""Kalshi API-key request signing (RSA-PSS over timestamp + method + path).

Credentials stay in the user's secret folder (Settings → Kalshi keys folder), using the layout this
project has always used:

    keys.json               {"Kalshi_production_Api_key": "...", "Kalshi_demo_Api_key": "..."}
    kalshiProductionKey.txt PEM private key for production
    kalshiDemoKey.txt       PEM private key for demo

Nothing is copied out of that folder and keys are never sent to the UI.
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

ENVIRONMENTS = {
    "production": {
        "rest": "https://external-api.kalshi.com/trade-api/v2",
        "ws": "wss://external-api-ws.kalshi.com/trade-api/ws/v2",
        "key_field": "Kalshi_production_Api_key",
        "key_file": "kalshiProductionKey.txt",
    },
    "demo": {
        "rest": "https://external-api.demo.kalshi.co/trade-api/v2",
        "ws": "wss://external-api-ws.demo.kalshi.co/trade-api/ws/v2",
        "key_field": "Kalshi_demo_Api_key",
        "key_file": "kalshiDemoKey.txt",
    },
}
WS_SIGN_PATH = "/trade-api/ws/v2"


class CredentialsError(RuntimeError):
    pass


@dataclass
class Credentials:
    env: str
    key_id: str
    private_key: object

    def headers(self, method: str, path: str) -> dict[str, str]:
        """Signed headers for a request to `path` (full path from root, query string ignored)."""
        timestamp = str(int(time.time() * 1000))
        message = f"{timestamp}{method.upper()}{path.split('?')[0]}".encode("utf-8")
        signature = self.private_key.sign(  # type: ignore[attr-defined]
            message,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY": self.key_id,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("utf-8"),
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
        }


def load_credentials(secret_dir: str, env: str) -> Credentials:
    if env not in ENVIRONMENTS:
        raise CredentialsError(f"Unknown Kalshi environment '{env}'")
    spec = ENVIRONMENTS[env]
    keys_path = os.path.join(secret_dir, "keys.json")
    pem_path = os.path.join(secret_dir, spec["key_file"])
    try:
        with open(keys_path, "r", encoding="utf-8") as fh:
            key_id = json.load(fh).get(spec["key_field"])
    except FileNotFoundError:
        raise CredentialsError(f"keys.json not found in {secret_dir}") from None
    except ValueError:
        raise CredentialsError(f"{keys_path} is not valid JSON") from None
    if not key_id:
        raise CredentialsError(f"keys.json has no '{spec['key_field']}' entry")
    try:
        with open(pem_path, "rb") as fh:
            private_key = serialization.load_pem_private_key(fh.read(), password=None)
    except FileNotFoundError:
        raise CredentialsError(f"{spec['key_file']} not found in {secret_dir}") from None
    except ValueError:
        raise CredentialsError(f"{spec['key_file']} is not a valid PEM private key") from None
    return Credentials(env=env, key_id=str(key_id), private_key=private_key)


def credentials_status(secret_dir: str) -> dict:
    """Which environments have usable keys (never returns the keys themselves)."""
    out = {"secret_dir": secret_dir}
    for env in ENVIRONMENTS:
        try:
            load_credentials(secret_dir, env)
            out[env] = {"ok": True, "problem": None}
        except CredentialsError as exc:
            out[env] = {"ok": False, "problem": str(exc)}
    return out
