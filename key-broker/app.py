from __future__ import annotations

import base64
import os
import secrets
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from l1_demo.assertion import AssertionError, require_claims, verify_assertion

app = FastAPI(title="L1 demo key broker", docs_url=None, redoc_url=None)
POLICY = Path(os.getenv("POLICY_FILE", "/app/config/policy.json"))
SIGNING_KEY = Path(os.getenv("MOCK_SIGNING_KEY_FILE", "/run/secrets/mock-signing.key"))
DEK_FILE = Path(os.getenv("DEK_FILE", "/run/secrets/demo-dek.hex"))
NONCES: dict[str, int] = {}


class DekRequest(BaseModel):
    nonce: str
    assertion: str


def reject(reason: str) -> HTTPException:
    # Do not log assertions, DEKs, prompts, responses, or model content.
    return HTTPException(status_code=403, detail={"reason": reason})


@app.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "live"}


@app.post("/v1/challenges")
def challenge() -> dict[str, str | int]:
    nonce, expiry = secrets.token_urlsafe(32), int(time.time()) + 60
    NONCES[nonce] = expiry
    return {"nonce": nonce, "expires_at": expiry}


@app.post("/v1/deks")
def release_dek(request: DekRequest) -> dict[str, str]:
    expiry = NONCES.pop(request.nonce, None)  # one use, including rejected attempts
    if expiry is None or expiry <= int(time.time()):
        raise reject("missing_or_replayed_nonce")
    try:
        claims = verify_assertion(request.assertion, SIGNING_KEY.read_bytes().strip())
        expected = __import__("json").loads(POLICY.read_text(encoding="utf-8"))
        require_claims(claims, expected)
        if claims.get("nonce") != request.nonce:
            raise AssertionError("claim mismatch: nonce")
        dek = bytes.fromhex(DEK_FILE.read_text(encoding="utf-8").strip())
        if len(dek) != 32:
            raise ValueError("invalid DEK")
    except AssertionError as exc:
        raise reject(str(exc)) from exc
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(503, detail={"reason": "broker_configuration_unavailable"}) from exc
    return {"dek_b64": base64.b64encode(dek).decode()}
