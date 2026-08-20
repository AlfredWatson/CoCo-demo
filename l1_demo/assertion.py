"""Compact signed demo assertions; deliberately separate from real attestation."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any


class AssertionError(ValueError):
    """A malformed, unauthenticated, or policy-invalid demo assertion."""


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sign_assertion(claims: dict[str, Any], key: bytes) -> str:
    """Create a JWS-like HMAC token for demo-mock only (not a TEE quote)."""
    payload = _b64(_canonical(claims))
    signature = hmac.new(key, payload.encode(), hashlib.sha256).digest()
    return f"demo-mock.{payload}.{_b64(signature)}"


def verify_assertion(token: str, key: bytes, *, now: int | None = None) -> dict[str, Any]:
    try:
        scheme, payload, signature = token.split(".")
        if scheme != "demo-mock":
            raise AssertionError("unsupported assertion scheme")
        expected = hmac.new(key, payload.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _unb64(signature)):
            raise AssertionError("invalid assertion signature")
        claims = json.loads(_unb64(payload))
    except (ValueError, json.JSONDecodeError) as exc:
        raise AssertionError("malformed assertion") from exc
    if claims.get("environment") != "demo-mock":
        raise AssertionError("unexpected assertion environment")
    timestamp = int(time.time()) if now is None else now
    if not isinstance(claims.get("issued_at"), int) or not isinstance(claims.get("expires_at"), int):
        raise AssertionError("missing assertion lifetime")
    if claims["issued_at"] > timestamp or claims["expires_at"] <= timestamp:
        raise AssertionError("expired assertion")
    return claims


def require_claims(claims: dict[str, Any], expected: dict[str, Any]) -> None:
    for name, value in expected.items():
        if claims.get(name) != value:
            raise AssertionError(f"claim mismatch: {name}")
